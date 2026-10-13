"""Lynceus inspection pipeline — AI client orchestration.

Two interchangeable AI client implementations with the same contract:

* :class:`VLLMClient` — talks to live vLLM OpenAI-compatible servers
  (``VLLM_VLM_URL`` for the vision-language model, ``VLLM_LLM_URL`` for the
  text-only model) over ``httpx``, sending the truck photo as a base64
  data-URI image and asking for structured JSON back.  Robust JSON parsing
  with exactly one retry on malformed output.
* :class:`StubAIClients` — fully deterministic, offline implementation for
  tests and demos without a GPU.  The ``demo_case`` flag in the inspection
  payload selects one of three scripted outcomes (green / amber / red).

Provenance is stated, never inferred: every result carries a ``provenance``
field (``"live"`` or ``"stub"``) and live failures fall back to the stub
with an *honest* ``"stub_fallback_live_error"`` marker — the stub never
masquerades as a live model.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any, Dict, Optional, Protocol

import httpx

from lynceus import gas_ingest
from lynceus import gas_twin
from lynceus.config import Settings, get_settings


class LiveAIUnavailableError(RuntimeError):
    """Live AI failed and stub fallback is disabled (fail-closed mode)."""


class _RateLimitedError(Exception):
    """HTTP 429 from the shared endpoint; carries the Retry-After hint."""

    def __init__(self, retry_after: float) -> None:
        super().__init__(f"rate limited; retry after {retry_after}s")
        self.retry_after = retry_after

__all__ = [
    "AIClients",
    "VLLMClient",
    "StubAIClients",
    "resolve_clients",
    "run_inspection",
]


# ---------------------------------------------------------------------------
# Client contract
# ---------------------------------------------------------------------------


class AIClients(Protocol):
    """The duck-typed contract both implementations satisfy."""

    provenance: str

    def vlm(self, photo: Optional[str]) -> Dict[str, Any]:
        """Analyse the truck-load photo; returns ``detected`` + ``confidence``."""
        ...

    def llm(self, manifest_text: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Cross-check the waybill text; returns ``reasoning`` + ``confidence``."""
        ...


# ---------------------------------------------------------------------------
# Shared JSON plumbing
# ---------------------------------------------------------------------------

_VLM_PROMPT = (
    "You are the gate inspector for an alternative-fuel (RDF) facility. "
    "Analyse the truck-load photo and reply with ONLY a JSON object, no prose, "
    "with exactly these keys: "
    '"contamination" (string description of any contamination found, or '
    '"none detected"), '
    '"moisture" (number, visual wet-basis moisture estimate as a fraction 0..1), '
    '"hard_contaminants" (list of strings among metal/rock/concrete/tire/e-waste), '
    '"light_contaminants" (list of strings among plastic_film/glass/textile/'
    "organic_residue/wet_mix), and "
    '"confidence" (number 0..1, your confidence in the analysis). '
    "Be conservative: report contamination only when visible."
)

_LLM_PROMPT = (
    "You are auditing a waste-transfer waybill for a gate inspector. "
    "Given the waybill text and the inspection context, reply with ONLY a JSON "
    "object, no prose, with exactly these keys: "
    '"reasoning" (string, one or two sentences in English), '
    '"declared_weight_kg" (number or null), '
    '"declared_moisture_fraction" (number or null), '
    '"crosscheck_notes" (string, discrepancies between waybill and context, '
    'or "consistent"), '
    '"crosscheck_failed" (boolean, true when the waybill contradicts the '
    "measured context), and "
    '"confidence" (number 0..1).'
)


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    """Best-effort extraction of the first JSON object from model output.

    Handles the common vLLM failure modes: markdown fences, leading prose,
    and trailing commentary.  Returns ``None`` when nothing parseable is
    found.
    """
    if not text:
        return None
    candidate = re.sub(r"```(?:json)?", "", text).strip()
    try:
        parsed = json.loads(candidate)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    depth = 0
    start = -1
    for idx, char in enumerate(text):
        if char == "{":
            if depth == 0:
                start = idx
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                try:
                    parsed = json.loads(text[start : idx + 1])
                    if isinstance(parsed, dict):
                        return parsed
                except json.JSONDecodeError:
                    start = -1
    return None


def _clamp01(value: Any, default: float = 0.0) -> float:
    """Coerce a model-supplied number into the closed 0..1 range."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number != number or number in (float("inf"), float("-inf")):
        return default
    return max(0.0, min(1.0, number))


# ---------------------------------------------------------------------------
# Live client (vLLM, OpenAI chat-completions format)
# ---------------------------------------------------------------------------


class VLLMClient:
    """Live AI client against two vLLM OpenAI-compatible endpoints."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        timeout_s: float = 90.0,
    ) -> None:
        self._settings = settings or get_settings()
        self._timeout_s = timeout_s
        self.provenance = "live"

    def _auth_headers(self) -> Dict[str, str]:
        """Bearer header when an API key is configured, else nothing."""
        if self._settings.vllm_api_key:
            return {"Authorization": f"Bearer {self._settings.vllm_api_key}"}
        return {}

    @staticmethod
    def _read_sse(r: httpx.Response) -> str:
        """Consume an SSE chat-completions stream and join delta contents.

        Some OpenAI-compatible endpoints always answer with ``text/event-stream``
        (even without ``stream: true``), so the reader collects
        ``choices[0].delta.content`` fragments until ``data: [DONE]``.
        """
        parts: list = []
        for line in r.iter_lines():
            line = line.strip()
            if not line or not line.startswith("data:"):
                continue
            data = line[len("data:") :].strip()
            if data == "[DONE]":
                break
            try:
                chunk = json.loads(data)
            except json.JSONDecodeError:
                continue
            try:
                delta = chunk["choices"][0]["delta"].get("content")
            except (KeyError, IndexError, TypeError, AttributeError):
                continue
            if delta:
                parts.append(delta)
        return "".join(parts)

    def _chat_once(self, base_url: str, model: str, messages: list) -> str:
        """Single chat-completions attempt; raises on transport/HTTP errors."""
        with httpx.stream(
            "POST",
            f"{base_url.rstrip('/')}/chat/completions",
            json={
                "model": model,
                "messages": messages,
                "max_tokens": 512,
                "temperature": 0.1,
            },
            headers=self._auth_headers(),
            timeout=self._timeout_s,
        ) as response:
            if response.status_code == 429:
                retry_after = float(response.headers.get("retry-after", "1"))
                raise _RateLimitedError(retry_after)
            response.raise_for_status()
            content_type = response.headers.get("content-type", "")
            if "text/event-stream" in content_type:
                return self._read_sse(response)
            # Fallback: a full non-streaming JSON body (application/json).
            payload = json.loads(response.read().decode("utf-8"))
            return str(payload["choices"][0]["message"]["content"])

    def _chat(self, base_url: str, model: str, messages: list) -> str:
        """One chat-completions round trip; raises on transport/HTTP errors.

        The response is read through two paths: SSE when the endpoint streams
        (``text/event-stream``), plain JSON otherwise.  Shared endpoints
        (AMD Token Factory) rate-limit per key, so a 429 is retried after
        its ``Retry-After`` hint — up to two waits, then the error surfaces
        (and the honest stub-fallback / fail-closed path takes over).
        """
        for attempt in range(3):
            try:
                return self._chat_once(base_url, model, messages)
            except _RateLimitedError as exc:
                if attempt == 2:
                    raise ValueError(
                        f"endpoint rate-limited after 3 attempts ({base_url})"
                    ) from exc
                time.sleep(exc.retry_after + 0.25 * (attempt + 1))
        raise AssertionError("unreachable")

    def _chat_json(self, base_url: str, model: str, messages: list) -> Dict[str, Any]:
        """Chat round trip with robust JSON parsing and exactly one retry."""
        content = self._chat(base_url, model, messages)
        parsed = _extract_json(content)
        if parsed is not None:
            return parsed
        retry_messages = messages + [
            {"role": "assistant", "content": content},
            {
                "role": "user",
                "content": "Your previous reply was not valid JSON. "
                "Reply again with ONLY the JSON object — no prose, no code fences.",
            },
        ]
        content = self._chat(base_url, model, retry_messages)
        parsed = _extract_json(content)
        if parsed is None:
            raise ValueError(
                "model did not return parseable JSON after one retry: " + content[:200]
            )
        return parsed

    def vlm(self, photo: Optional[str]) -> Dict[str, Any]:
        if not photo:
            raise ValueError("VLMClient.vlm requires a base64 photo")
        data_uri = (
            photo if photo.startswith("data:") else f"data:image/jpeg;base64,{photo}"
        )
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": _VLM_PROMPT},
                    {"type": "image_url", "image_url": {"url": data_uri}},
                ],
            }
        ]
        parsed = self._chat_json(
            self._settings.vllm_vlm_url, self._settings.vlm_model, messages
        )
        return {
            "detected": {
                "contamination": parsed.get("contamination", "unknown"),
                "moisture": parsed.get("moisture"),
                "hard_contaminants": parsed.get("hard_contaminants", []),
                "light_contaminants": parsed.get("light_contaminants", []),
            },
            "confidence": _clamp01(parsed.get("confidence")),
            "model": self._settings.vlm_model,
            "model_version": self._settings.vlm_model,
            "raw_output": json.dumps(parsed, sort_keys=True),
            "provenance": self.provenance,
        }

    def llm(self, manifest_text: str, context: Dict[str, Any]) -> Dict[str, Any]:
        context_block = json.dumps(context, sort_keys=True, default=str)
        messages = [
            {
                "role": "user",
                "content": (
                    f"{_LLM_PROMPT}\n\n--- WAYBILL TEXT ---\n{manifest_text}\n\n"
                    f"--- INSPECTION CONTEXT (JSON) ---\n{context_block}"
                ),
            }
        ]
        parsed = self._chat_json(
            self._settings.vllm_llm_url, self._settings.llm_model, messages
        )
        return {
            "reasoning": str(parsed.get("reasoning", "")),
            "confidence": _clamp01(parsed.get("confidence")),
            "declared_weight_kg": parsed.get("declared_weight_kg"),
            "declared_moisture_fraction": parsed.get("declared_moisture_fraction"),
            "crosscheck_notes": str(parsed.get("crosscheck_notes", "consistent")),
            "crosscheck_failed": bool(parsed.get("crosscheck_failed", False)),
            "model": self._settings.llm_model,
            "model_version": self._settings.llm_model,
            "raw_output": json.dumps(parsed, sort_keys=True),
            "provenance": self.provenance,
        }


# ---------------------------------------------------------------------------
# Deterministic offline stub (tests / demo without GPU)
# ---------------------------------------------------------------------------

#: Scripted VLM outcomes per demo case, mirroring the demo-UI waybill stories
#: (green: clean & dry, amber: wet organic mix, red: metal on top of bales).
_STUB_VLM: Dict[str, Dict[str, Any]] = {
    "green": {
        "detected": {
            "contamination": "none detected",
            "moisture": 0.10,
            "hard_contaminants": [],
            "light_contaminants": [],
        },
        "confidence": 0.87,
    },
    "amber": {
        "detected": {
            "contamination": "wet organic mix, visible free liquid",
            "moisture": 0.55,
            "hard_contaminants": [],
            "light_contaminants": ["wet_mix", "organic_residue"],
        },
        "confidence": 0.72,
    },
    "red": {
        "detected": {
            "contamination": "metal drum and concrete rubble on top of the bales",
            "moisture": 0.14,
            "hard_contaminants": ["metal", "concrete"],
            "light_contaminants": [],
        },
        "confidence": 0.83,
    },
}

_STUB_LLM: Dict[str, Dict[str, Any]] = {
    "green": {
        "reasoning": "Waybill is consistent with the inspection: declared dry "
        "RDF fluff, weight within tolerance.",
        "confidence": 0.90,
        "crosscheck_notes": "consistent",
        "crosscheck_failed": False,
    },
    "amber": {
        "reasoning": "Waybill claims 30% moisture but the visual analysis shows "
        "a visibly wet organic mix — moisture claim is optimistic.",
        "confidence": 0.74,
        "crosscheck_notes": "moisture claim below visual estimate",
        "crosscheck_failed": False,
    },
    "red": {
        "reasoning": "Waybill claims clean dry RDF but the driver note admits "
        "scrap metal and concrete rubble loaded on top; weighbridge weight is "
        "far above the declared weight.",
        "confidence": 0.88,
        "crosscheck_notes": "declared weight and contamination contradict the "
        "waybill's 'clean, no contamination' claim",
        "crosscheck_failed": True,
    },
}


class StubAIClients:
    """Deterministic offline stand-in for the live vLLM pair.

    The ``demo_case`` key of the inspection payload selects the scripted
    outcome; anything unrecognised degrades to the green (clean) script so
    the stub never invents a random verdict.
    """

    def __init__(self, demo_case: Optional[str] = None, provenance: str = "stub") -> None:
        self._demo_case = (demo_case or "green").strip().lower()
        if self._demo_case not in _STUB_VLM:
            self._demo_case = "green"
        self.provenance = provenance

    def vlm(self, photo: Optional[str]) -> Dict[str, Any]:
        script = _STUB_VLM[self._demo_case]
        return {
            "detected": dict(script["detected"]),
            "confidence": script["confidence"],
            "model": "stub-vlm",
            "model_version": "stub-1",
            "raw_output": json.dumps(script, sort_keys=True),
            "provenance": self.provenance,
        }

    def llm(self, manifest_text: str, context: Dict[str, Any]) -> Dict[str, Any]:
        script = _STUB_LLM[self._demo_case]
        return {
            "reasoning": script["reasoning"],
            "confidence": script["confidence"],
            "declared_weight_kg": None,
            "declared_moisture_fraction": None,
            "crosscheck_notes": script["crosscheck_notes"],
            "crosscheck_failed": script["crosscheck_failed"],
            "model": "stub-llm",
            "model_version": "stub-1",
            "raw_output": json.dumps(script, sort_keys=True),
            "provenance": self.provenance,
        }


# ---------------------------------------------------------------------------
# Client resolution + pipeline
# ---------------------------------------------------------------------------


def _vlm_reachable(settings: Settings, timeout_s: float = 2.0) -> bool:
    """Cheap liveness probe of the vLLM VLM endpoint (``GET /models``)."""
    try:
        response = httpx.get(
            f"{settings.vllm_vlm_url.rstrip('/')}/models", timeout=timeout_s
        )
        return response.status_code < 500
    except httpx.HTTPError:
        return False


def resolve_clients(
    payload: Dict[str, Any], settings: Optional[Settings] = None
) -> AIClients:
    """Choose the live client or the honest stub for this inspection.

    The stub wins when the payload sets ``demo_case`` (scripted demo) or when
    the vLLM VLM endpoint is unreachable.  A live failure *during* the
    pipeline is handled by :func:`run_inspection`, which then falls back to
    the stub with the explicit ``stub_fallback_live_error`` provenance.
    """
    settings = settings or get_settings()
    demo_case = payload.get("demo_case")
    if demo_case:
        return StubAIClients(demo_case=demo_case)
    if _vlm_reachable(settings):
        return VLLMClient(settings=settings)
    return StubAIClients(demo_case=demo_case, provenance="stub")


def _gate_gas_readings(
    payload: Dict[str, Any], record_id: Optional[str]
) -> Optional[Dict[str, Any]]:
    """Gas readings for this inspection: live instrument first, twin second.

    A configured, reachable sensor gateway (:mod:`lynceus.gas_ingest`,
    env ``LYNCEUS_GAS_SENSOR_URL`` — e.g. a TDLAS gate
    monitor) provides *measured* values and is stamped
    ``sentinel_gate_sensor``.  Otherwise the physics digital twin runs
    and is stamped ``digital_twin``.  Either way the audit record states
    which it was; a measurement never masquerades as a simulation and
    vice versa.
    """
    live = gas_ingest.fetch_live_readings()
    if live is not None:
        return live
    return _simulate_gas_readings(payload, record_id)


def _simulate_gas_readings(
    payload: Dict[str, Any], record_id: Optional[str]
) -> Optional[Dict[str, Any]]:
    """Run the gas digital twin for this load, or ``None`` when it cannot.

    The twin needs the full batch description (waste stream, tonnage,
    moisture, age) and the Lynceus decision engine.  Anything missing or
    off-domain means "no gas data for this inspection" — the gas channel
    is a *supporting* signal and must never fail the inspection itself.
    """
    waste_stream = payload.get("waste_stream") or payload.get("stream")
    weight_kg = payload.get("weight_kg")
    moisture = payload.get("moisture")
    age_h = payload.get("age_h")
    if not waste_stream or weight_kg is None or moisture is None or age_h is None:
        return None
    try:
        return gas_twin.simulate_gate_readings(
            str(waste_stream),
            float(weight_kg) / 1000.0,
            float(moisture),
            float(age_h),
            truck_id=str(payload.get("truck_id") or ""),
            record_id=str(record_id or ""),
        )
    except (gas_twin.GasTwinUnavailableError, ValueError, TypeError):
        return None


def run_inspection(
    payload: Dict[str, Any],
    ai_clients: AIClients,
    record_id: Optional[str] = None,
    allow_stub_fallback: bool = True,
) -> Dict[str, Any]:
    """Run the VLM + LLM + gas-twin stages for one inspection payload.

    Args:
        payload: The raw ``/inspect`` request payload (``truck_id``,
            ``demo_case``, ``photo_base64``, ``manifest_text``, weights, ...).
        ai_clients: A live :class:`VLLMClient` or a :class:`StubAIClients`.
        record_id: The audit record identity — part of the deterministic
            noise seed of the gas twin, so the same truck + record always
            reproduce the same readings.

    Returns:
        ``{"vlm": ..., "llm": ..., "gas": ..., "provenance": "live"|"stub"}``.
        ``gas`` carries the digital-twin gate readings (see
        :mod:`lynceus.gas_twin`) or ``None`` when the twin could not run
        (incomplete batch description or engine unavailable).  When the
        live client raises, the call falls back to the stub for the *same*
        payload and reports ``provenance: "stub_fallback_live_error"`` with
        the original error message — the stub result is marked honestly,
        never passed off as live output.
    """
    payload = dict(payload or {})
    gas_result = _gate_gas_readings(payload, record_id)
    context = {
        "truck_id": payload.get("truck_id"),
        "weight_kg": payload.get("weight_kg"),
        "declared_weight_kg": payload.get("declared_weight_kg"),
        "waste_stream": payload.get("waste_stream") or payload.get("stream"),
        "moisture": payload.get("moisture"),
        "age_h": payload.get("age_h"),
    }
    manifest_text = str(payload.get("manifest_text") or "")
    photo = payload.get("photo_base64") or payload.get("photo")

    try:
        vlm_result = ai_clients.vlm(photo)
        llm_result = ai_clients.llm(manifest_text, context)
    except Exception as exc:  # noqa: BLE001 — any live failure falls back
        if ai_clients.provenance == "live":
            if not allow_stub_fallback:
                raise LiveAIUnavailableError(
                    f"live AI failed ({type(exc).__name__}: {exc}); "
                    "stub fallback disabled"
                ) from exc
            fallback = StubAIClients(demo_case=payload.get("demo_case"))
            vlm_result = fallback.vlm(photo)
            llm_result = fallback.llm(manifest_text, context)
            return {
                "vlm": vlm_result,
                "llm": llm_result,
                "gas": gas_result,
                "provenance": "stub_fallback_live_error",
                "fallback_reason": f"{type(exc).__name__}: {exc}",
            }
        raise

    return {
        "vlm": vlm_result,
        "llm": llm_result,
        "gas": gas_result,
        "provenance": ai_clients.provenance,
    }

