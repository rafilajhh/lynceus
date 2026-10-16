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
masquerades as a live model.  With stub fallback disabled, a live failure
on a photo the CPU detector could read is answered in
``"detector_only_degraded"`` mode (always held for a human) instead of 503.
"""

from __future__ import annotations

import base64
import binascii
import copy
import json
import logging
import math
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timezone
from email.utils import parsedate_to_datetime
from typing import Any, Dict, List, Optional, Protocol

import httpx

from lynceus import detector
from lynceus import gas_ingest
from lynceus import gas_twin
from lynceus.config import Settings, get_settings, provider_for_url
from lynceus.vision_boxes import parse_locations


#: Per-call read budgets (seconds).  The VLM is the slow, image-bearing call;
#: the text-only LLM cross-check and the assist answer must not hold the gate
#: (or the page) for a full VLM budget when a shared endpoint stalls.
VLM_TIMEOUT_S = 90.0
LLM_TIMEOUT_S = 45.0
ASSIST_TIMEOUT_S = 30.0
EXPLAIN_TIMEOUT_S = ASSIST_TIMEOUT_S


class LiveAIUnavailableError(RuntimeError):
    """Live AI failed and stub fallback is disabled (fail-closed mode)."""


class VisionModelsFailedError(RuntimeError):
    """The VLM and its fallbacks all failed; the message lists every attempt
    (the primary's first) and the last failure is chained as the cause."""


def _model_specific_failure(exc: BaseException) -> bool:
    """True when the next vision model may still answer: the endpoint replied
    with an error status (400 "model not supported", 503 "no available
    workers", 429 retries spent) or the model's reply was not usable JSON.
    Connection failures and timeouts are not: the endpoint is down or the
    budget is spent."""
    if isinstance(exc, httpx.HTTPStatusError):
        return True
    return isinstance(exc, (ValueError, KeyError, TypeError)) and not isinstance(
        exc, httpx.HTTPError
    )


#: Bound each retry wait so a shared-key 429 cannot stall a request indefinitely.
MAX_RETRY_AFTER_S = 10.0
_DEFAULT_RETRY_AFTER_S = 1.0

#: One process-wide budget across VLM, LLM, assist and shift calls. Four leaves
#: headroom for teammates under Token Factory's eight-concurrent shared-key cap.
_OUTBOUND_SLOTS = threading.BoundedSemaphore(4)
#: Floor for the per-request httpx timeout passed as the budget left.
_MIN_REQUEST_TIMEOUT_S = 0.05


def _parse_retry_after(value: Any) -> float:
    """Parse numeric seconds or an HTTP-date, bounded to a 0..10 s wait."""
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        try:
            retry_at = parsedate_to_datetime(value)
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=timezone.utc)
            seconds = retry_at.timestamp() - time.time()
        except (TypeError, ValueError, OverflowError, AttributeError):
            return _DEFAULT_RETRY_AFTER_S
    if math.isnan(seconds):
        return _DEFAULT_RETRY_AFTER_S
    return min(MAX_RETRY_AFTER_S, max(seconds, 0.0))


class _RateLimitedError(Exception):
    """HTTP 429 from the shared endpoint; carries the Retry-After hint."""

    def __init__(self, retry_after: float) -> None:
        super().__init__(f"rate limited; retry after {retry_after}s")
        self.retry_after = retry_after


def _deadline_error(budget_s: float) -> httpx.ReadTimeout:
    """The timeout a call past its wall-clock budget raises.

    A :class:`httpx.ReadTimeout`, i.e. the same error a stalled read raises,
    so every caller's existing timeout handling applies unchanged.
    """
    return httpx.ReadTimeout(f"no complete reply within {budget_s:g} s")


def _check_deadline(deadline: Optional[float], budget_s: float) -> None:
    if deadline is not None and time.monotonic() > deadline:
        raise _deadline_error(budget_s)

__all__ = [
    "AIClients",
    "VLLMClient",
    "StubAIClients",
    "UnavailableAIClients",
    "VisionModelsFailedError",
    "DEGRADED_PROVENANCE",
    "resolve_clients",
    "resolve_assist_client",
    "resolve_explain_client",
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
    # Same wording as the validated probe (scripts/probe_token_factory.py).
    ' Also include the key "locations" (list of objects {"label": one of the '
    'contaminant strings, "box": [x0,y0,x1,y1] normalised 0..1 from the '
    'top-left, "zone": one of '
    "top-left|top|top-right|left|center|right|bottom-left|bottom|bottom-right"
    "}); use an empty list when nothing is found."
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


def _fold_system_messages(messages: list) -> list:
    """Merge every ``system`` message into the first ``user`` message.

    Order is kept: system text comes first, separated by a blank line. A
    conversation without a user turn gets one built from the system text.
    """
    system = [str(m.get("content", "")) for m in messages if m.get("role") == "system"]
    if not system:
        return list(messages)
    rest = [dict(m) for m in messages if m.get("role") != "system"]
    preamble = "\n\n".join(system)
    for message in rest:
        if message.get("role") == "user":
            message["content"] = f"{preamble}\n\n{message.get('content', '')}"
            return rest
    return [{"role": "user", "content": preamble}] + rest


class VLLMClient:
    """Live AI client against two vLLM OpenAI-compatible endpoints."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        timeout_s: float = VLM_TIMEOUT_S,
    ) -> None:
        self._settings = settings or get_settings()
        self._timeout_s = timeout_s
        self.provenance = "live"

    def _scoped(self, budget_s: float) -> "VLLMClient":
        """A shallow copy whose calls time out after ``budget_s`` at most.

        A copy rather than a mutation: the VLM and LLM calls run concurrently
        on one client, so a shared timeout attribute would race.
        """
        scoped = copy.copy(self)
        scoped._timeout_s = min(self._timeout_s, budget_s)
        return scoped

    def _auth_headers(self) -> Dict[str, str]:
        """Bearer header when an API key is configured, else nothing."""
        if self._settings.vllm_api_key:
            return {"Authorization": f"Bearer {self._settings.vllm_api_key}"}
        return {}

    @staticmethod
    def _read_sse(
        r: httpx.Response, deadline: Optional[float] = None, budget_s: float = 0.0
    ) -> str:
        """Consume an SSE chat-completions stream and join delta contents.

        Some OpenAI-compatible endpoints always answer with ``text/event-stream``
        (even without ``stream: true``), so the reader collects
        ``choices[0].delta.content`` fragments until ``data: [DONE]``.
        ``deadline`` (a ``time.monotonic()`` value) is checked per received
        chunk, not per line, so bytes trickling without a newline stop too.
        """
        parts: list = []
        pending = ""
        for text in r.iter_text():
            _check_deadline(deadline, budget_s)
            pending += text
            *lines, pending = pending.split("\n")
            for line in lines:
                if VLLMClient._sse_line(line, parts):
                    return "".join(parts)
        VLLMClient._sse_line(pending, parts)
        return "".join(parts)

    @staticmethod
    def _sse_line(line: str, parts: list) -> bool:
        """Append one SSE line's delta content to ``parts``; True on ``[DONE]``."""
        line = line.strip()
        if not line.startswith("data:"):
            return False
        data = line[len("data:") :].strip()
        if data == "[DONE]":
            return True
        try:
            chunk = json.loads(data)
        except json.JSONDecodeError:
            return False
        try:
            delta = chunk["choices"][0]["delta"].get("content")
        except (KeyError, IndexError, TypeError, AttributeError):
            return False
        if delta:
            parts.append(delta)
        return False

    def _chat_once(
        self, base_url: str, model: str, messages: list, max_tokens: int = 512
    ) -> str:
        """Single chat-completions attempt; raises on transport/HTTP errors.

        httpx timeouts apply per read, so an endpoint trickling SSE bytes
        never trips them.  The attempt therefore runs on a daemon thread and
        the caller waits at most ``self._timeout_s`` wall-clock (slot wait,
        connect, SSE or JSON read) before :func:`_deadline_error` is raised:
        the ``ReadTimeout`` a stalled read raises, so stub fallback,
        fail-closed and Pythia's CANNOT_ANSWER behave as for any timeout.
        The worker checks the same deadline per chunk, so an abandoned
        stream closes and frees its outbound slot at its next chunk or
        per-read timeout.
        """
        deadline = time.monotonic() + self._timeout_s
        outcome: Dict[str, Any] = {}
        finished = threading.Event()

        def _attempt() -> None:
            try:
                outcome["text"] = self._chat_attempt(
                    base_url, model, messages, max_tokens, deadline
                )
            except BaseException as exc:  # noqa: BLE001 — re-raised below
                outcome["error"] = exc
            finally:
                finished.set()

        threading.Thread(target=_attempt, name="lynceus-chat", daemon=True).start()
        if not finished.wait(self._timeout_s):
            raise _deadline_error(self._timeout_s)
        if "error" in outcome:
            raise outcome["error"]
        return outcome["text"]

    def _chat_attempt(
        self, base_url: str, model: str, messages: list, max_tokens: int, deadline: float
    ) -> str:
        """The HTTP round trip behind :meth:`_chat_once`, bounded by ``deadline``."""
        budget_s = self._timeout_s
        if not _OUTBOUND_SLOTS.acquire(timeout=max(deadline - time.monotonic(), 0.0)):
            raise _deadline_error(budget_s)
        try:
            # The slot may arrive just as the caller gave up: never send then,
            # and give httpx only what is left of the budget, so an abandoned
            # worker cannot hold the slot for another full budget.
            _check_deadline(deadline, budget_s)
            remaining_s = max(deadline - time.monotonic(), _MIN_REQUEST_TIMEOUT_S)
            with httpx.stream(
                "POST",
                f"{base_url.rstrip('/')}/chat/completions",
                json={
                    "model": model,
                    "messages": messages,
                    "max_tokens": max_tokens,
                    "temperature": 0.1,
                },
                headers=self._auth_headers(),
                timeout=remaining_s,
            ) as response:
                if response.status_code == 429:
                    raise _RateLimitedError(
                        _parse_retry_after(response.headers.get("retry-after", "1"))
                    )
                response.raise_for_status()
                content_type = response.headers.get("content-type", "")
                if "text/event-stream" in content_type:
                    return self._read_sse(response, deadline, budget_s)
                # Fallback: a full non-streaming JSON body (application/json).
                body = bytearray()
                for chunk in response.iter_bytes():
                    _check_deadline(deadline, budget_s)
                    body.extend(chunk)
                payload = json.loads(body.decode("utf-8"))
                return str(payload["choices"][0]["message"]["content"])
        finally:
            _OUTBOUND_SLOTS.release()

    def _chat(
        self, base_url: str, model: str, messages: list, max_tokens: int = 512
    ) -> str:
        """One chat-completions round trip; raises on transport/HTTP errors.

        The response is read through two paths: SSE when the endpoint streams
        (``text/event-stream``), plain JSON otherwise.  Shared endpoints
        (AMD Token Factory) rate-limit per key, so a 429 is retried after
        its ``Retry-After`` hint (capped at 10 s including jitter), with
        up to two waits before the error surfaces
        (and the honest stub-fallback / fail-closed path takes over).
        """
        # One wall-clock budget for the attempts and the waits between them.
        deadline = time.monotonic() + self._timeout_s
        client = self
        for attempt in range(3):
            try:
                return client._chat_once(base_url, model, messages, max_tokens)
            except _RateLimitedError as exc:
                if attempt == 2:
                    raise ValueError(
                        f"endpoint rate-limited after 3 attempts ({base_url})"
                    ) from exc
                time.sleep(min(MAX_RETRY_AFTER_S, exc.retry_after + 0.25 * (attempt + 1)))
                client = self._remaining(deadline)
        raise AssertionError("unreachable")

    def _remaining(self, deadline: float) -> "VLLMClient":
        """A copy scoped to what is left before ``deadline``; raises the
        deadline ``ReadTimeout`` when nothing is left."""
        remaining_s = deadline - time.monotonic()
        if remaining_s <= 0:
            raise _deadline_error(self._timeout_s)
        return self._scoped(remaining_s)

    def _chat_json(
        self, base_url: str, model: str, messages: list, max_tokens: int = 512
    ) -> Dict[str, Any]:
        """Chat round trip with robust JSON parsing and exactly one retry.

        The retry gets only what is left of ``self._timeout_s``: one budget
        covers both round trips.
        """
        deadline = time.monotonic() + self._timeout_s
        content = self._chat(base_url, model, messages, max_tokens)
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
        content = self._remaining(deadline)._chat(base_url, model, retry_messages, max_tokens)
        parsed = _extract_json(content)
        if parsed is None:
            raise ValueError(
                "model did not return parseable JSON after one retry: " + content[:200]
            )
        return parsed

    def vlm(self, photo: Optional[str]) -> Dict[str, Any]:
        if not photo:
            raise ValueError("VLMClient.vlm requires a base64 photo")
        # PNG base64 always starts "iVBOR" (the 0x89 'PNG' signature); the
        # API has already admitted only JPEG and PNG.
        mime = "image/png" if photo.startswith("iVBOR") else "image/jpeg"
        data_uri = photo if photo.startswith("data:") else f"data:{mime};base64,{photo}"
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": _VLM_PROMPT},
                    {"type": "image_url", "image_url": {"url": data_uri}},
                ],
            }
        ]
        # VLM_MODEL first, then VLM_FALLBACK_MODELS in order: a shared endpoint
        # can drop one model ("no available workers") while others still serve.
        # One wall-clock budget covers the whole chain.  Only a failure of the
        # model itself (an HTTP error status, an unparseable reply) moves on;
        # an unreachable endpoint or a spent budget ends the chain.  The model
        # that answered is reported; the ones that failed are named in
        # ``fallback_from`` so the audit never hides the switch.
        models = (self._settings.vlm_model, *self._settings.vlm_fallback_models)
        deadline = time.monotonic() + self._timeout_s
        failed: List[str] = []
        details: List[str] = []
        for model in models:
            started = time.perf_counter()
            try:
                parsed = self._remaining(deadline)._chat_json(
                    self._settings.vllm_vlm_url, model, messages
                )
                break
            except Exception as exc:  # noqa: BLE001 — next model, else re-raise
                took = f"{type(exc).__name__} after {time.perf_counter() - started:.1f} s"
                failed.append(f"{model}: {took}")
                details.append(f"{model}: {took} ({str(exc)[:160]})")
                if model != models[-1] and _model_specific_failure(exc):
                    continue
                if len(failed) == 1:
                    raise
                raise VisionModelsFailedError(
                    "every vision model tried failed: " + "; ".join(details)
                ) from exc
        latency_ms = (time.perf_counter() - started) * 1000.0
        mode = self._settings.localisation_mode
        result = self._vlm_result(parsed, model, latency_ms, mode)
        if failed:
            result["fallback_from"] = failed
        return result

    def _vlm_result(
        self, parsed: Dict[str, Any], model: str, latency_ms: float, mode: str
    ) -> Dict[str, Any]:
        return {
            "detected": {
                "contamination": parsed.get("contamination", "unknown"),
                "moisture": parsed.get("moisture"),
                "hard_contaminants": parsed.get("hard_contaminants", []),
                "light_contaminants": parsed.get("light_contaminants", []),
            },
            "confidence": _clamp01(parsed.get("confidence")),
            "boxes": parse_locations(parsed.get("locations"), mode),
            "localisation": mode,
            "model": model,
            "model_version": model,
            "raw_output": json.dumps(parsed, sort_keys=True),
            "provenance": self.provenance,
            "provider": provider_for_url(self._settings.vllm_vlm_url),
            "latency_ms": latency_ms,
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
        started = time.perf_counter()
        parsed = self._scoped(LLM_TIMEOUT_S)._chat_json(
            self._settings.vllm_llm_url, self._settings.llm_model, messages
        )
        latency_ms = (time.perf_counter() - started) * 1000.0
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
            "provider": provider_for_url(self._settings.vllm_llm_url),
            "latency_ms": latency_ms,
        }

    def assist(
        self, messages: list, max_tokens: int = 700
    ) -> tuple[Dict[str, Any], float]:
        """JSON chat against the assist endpoint/model.

        Returns ``(parsed_json, latency_ms)``; raises like :meth:`_chat_json`
        on transport errors, rate limiting, or unparseable output.
        """
        started = time.perf_counter()
        parsed = self._scoped(ASSIST_TIMEOUT_S)._chat_json(
            self._settings.assist_url,
            self._settings.assist_model,
            messages,
            max_tokens,
        )
        return parsed, (time.perf_counter() - started) * 1000.0

    def explain(
        self, messages: list, max_tokens: int = 700
    ) -> tuple[Dict[str, Any], float]:
        """JSON chat against the explain endpoint/model (shift-report prose).

        Same contract as :meth:`assist`; the role defaults to the assist
        endpoint and model unless ``EXPLAIN_URL`` / ``EXPLAIN_MODEL`` are set.
        System messages are folded into the first user turn: Gemma chat
        templates have no system role, and the Token Factory probe recorded
        unusable Gemma replies whenever a system message was sent.
        """
        started = time.perf_counter()
        parsed = self._scoped(EXPLAIN_TIMEOUT_S)._chat_json(
            self._settings.explain_url,
            self._settings.explain_model,
            _fold_system_messages(messages),
            max_tokens,
        )
        return parsed, (time.perf_counter() - started) * 1000.0


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
            # Matches what the red demo photos show (aluminium trays, a
            # bolt): metal only, nothing the camera did not see.
            "contamination": "crumpled metal containers on top of the load",
            "moisture": 0.14,
            "hard_contaminants": ["metal"],
            "light_contaminants": [],
        },
        "confidence": 0.83,
        "locations": [{"label": "metal", "zone": "center"}],
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
        "scrap metal loaded on top; weighbridge weight is "
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

    def __init__(
        self,
        demo_case: Optional[str] = None,
        provenance: str = "stub",
        fallback_reason: Optional[str] = None,
    ) -> None:
        self.fallback_reason = fallback_reason
        self._demo_case = (demo_case or "green").strip().lower()
        if self._demo_case not in _STUB_VLM:
            self._demo_case = "green"
        self.provenance = provenance

    def vlm(self, photo: Optional[str]) -> Dict[str, Any]:
        script = _STUB_VLM[self._demo_case]
        return {
            "detected": dict(script["detected"]),
            "confidence": script["confidence"],
            "boxes": parse_locations(script.get("locations", []), "zone"),
            "localisation": "zone",
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
    """Cheap liveness probe of the vLLM VLM endpoint (``GET /models``).

    Only "nobody answered" counts as unreachable (refused, DNS, connect
    timeout, malformed URL).  A *slow* answer (read/pool timeout) means the
    host is up and merely busy — the real call decides, so a loaded shared
    endpoint is not mistaken for a dead one.
    """
    try:
        response = httpx.get(
            f"{settings.vllm_vlm_url.rstrip('/')}/models", timeout=timeout_s
        )
        return response.status_code < 500
    except (httpx.ReadTimeout, httpx.PoolTimeout):
        return True
    except (httpx.HTTPError, httpx.InvalidURL):
        # InvalidURL (a malformed configured URL) is not an HTTPError.
        return False


def resolve_clients(
    payload: Dict[str, Any], settings: Optional[Settings] = None
) -> AIClients:
    """Choose the live client or the honest stub for this inspection.

    * ``demo_case`` set → the scripted stub (provenance ``"stub"``).
    * Otherwise the live client — unless the endpoint is unreachable.  Then
      the request must not be answered with the GREEN script as if it were an
      analysis: with ``allow_stub_fallback`` off it raises
      :class:`LiveAIUnavailableError` (the API's 503); with it on it returns a
      stub marked ``stub_fallback_live_error`` carrying a ``fallback_reason``.

    A live failure *during* the pipeline is handled by :func:`run_inspection`
    with the same two outcomes.  The cheap probe stays: it turns a dead or
    blackholed endpoint into an answer in 2 s instead of a 90 s read budget.
    """
    settings = settings or get_settings()
    demo_case = payload.get("demo_case")
    if demo_case:
        return StubAIClients(demo_case=demo_case)
    if _vlm_reachable(settings):
        return VLLMClient(settings=settings)
    reason = f"live endpoint unreachable ({settings.vllm_vlm_url})"
    if not settings.allow_stub_fallback:
        raise LiveAIUnavailableError(f"{reason}; stub fallback disabled")
    return StubAIClients(
        provenance="stub_fallback_live_error", fallback_reason=reason
    )


def _assist_reachable(
    settings: Settings, timeout_s: float = 2.0, *, base_url: Optional[str] = None
) -> bool:
    """Cheap liveness probe of the assist endpoint, or of ``base_url`` when
    given (the explain role), via ``GET /models``."""
    url = base_url if base_url is not None else settings.assist_url
    try:
        response = httpx.get(
            f"{url.rstrip('/')}/models",
            headers=VLLMClient(settings=settings)._auth_headers(),
            timeout=timeout_s,
        )
        return response.status_code < 500
    except (httpx.HTTPError, httpx.InvalidURL):
        return False


def resolve_assist_client(
    settings: Optional[Settings] = None,
) -> Optional[VLLMClient]:
    """The live Pythia client, or ``None`` when the assist endpoint is down.

    ``None`` selects the extractive stub in :func:`lynceus.assist.answer`.  A
    live failure on an individual question is *not* routed to the stub; that
    would present a canned answer as a model one.
    """
    settings = settings or get_settings()
    if _assist_reachable(settings):
        return VLLMClient(settings=settings)
    return None


def resolve_explain_client(
    settings: Optional[Settings] = None,
) -> Optional[VLLMClient]:
    """The live client for shift-report explanations, or ``None`` when the
    explain endpoint (``EXPLAIN_URL``, defaulting to the assist one) is down.

    Probes the endpoint :meth:`VLLMClient.explain` calls, not the assist one:
    with the explain role on its own endpoint a dead explain host must
    select the rule sentence up front instead of costing a timeout per row.
    """
    settings = settings or get_settings()
    if _assist_reachable(settings, base_url=settings.explain_url):
        return VLLMClient(settings=settings)
    return None


#: Sentinel distinguishing "no precomputed gas supplied" from an explicit
#: ``None`` (collector already ran and found nothing).  Without it,
#: :func:`run_inspection` could not tell whether to collect gas itself.
_GAS_NOT_SUPPLIED = object()


def collect_gate_gas(
    payload: Dict[str, Any], record_id: Optional[str]
) -> Optional[Dict[str, Any]]:
    """Collect this inspection's gate gas readings exactly once.

    Called by the API *before* the audit record is begun so the readings are
    frozen into the begin-time inputs (audit invariant 3).  The result is
    then handed to :func:`run_inspection` via ``precomputed_gas`` so the
    sensor/twin never runs a second time (a live sensor could otherwise
    return different values and break the frozen snapshot).
    """
    return _gate_gas_readings(payload, record_id)


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


#: Provenance of an inspection decided on the CPU detector alone because the
#: live vision model failed with stub fallback disabled.
DEGRADED_PROVENANCE = "detector_only_degraded"
#: Same sentinel idea as ``_GAS_NOT_SUPPLIED``, for a detector result the API
#: already computed (the probe-failure path runs it before the record begins).
_DETECTOR_NOT_SUPPLIED = object()

_log = logging.getLogger(__name__)


class UnavailableAIClients:
    """Live clients whose endpoint already failed its probe.

    Used only when the detector can still answer: every call raises
    :class:`LiveAIUnavailableError` with the probe's reason, so
    :func:`run_inspection` takes its degraded path with that reason.
    """

    provenance = "live"

    def __init__(self, reason: str) -> None:
        self.reason = reason

    def vlm(self, photo: Optional[str]) -> Dict[str, Any]:
        raise LiveAIUnavailableError(self.reason)

    def llm(self, manifest_text: str, context: Dict[str, Any]) -> Dict[str, Any]:
        raise LiveAIUnavailableError(self.reason)


def _photo_bytes(photo: Any) -> bytes:
    """Raw bytes of a base64 photo (raw or ``data:`` URI); ``b""`` when the
    payload carries none or it is not base64 (the API validated it already)."""
    if not isinstance(photo, str) or not photo.strip():
        return b""
    text = photo.strip()
    if text[:5].lower() == "data:":
        text = text.partition(",")[2]
    try:
        return base64.b64decode("".join(text.split()), validate=True)
    except (binascii.Error, ValueError):
        return b""


def safe_detect(photo_bytes: bytes, settings: Settings) -> Optional[Dict[str, Any]]:
    """:func:`detector.detect`, with any failure logged and turned into None:
    the second opinion must never fail the inspection."""
    try:
        return detector.detect(photo_bytes, settings)
    except Exception as exc:  # noqa: BLE001 — logged, never raised
        _log.warning("detector skipped: %s: %s", type(exc).__name__, exc)
        return None


def run_inspection(
    payload: Dict[str, Any],
    ai_clients: AIClients,
    record_id: Optional[str] = None,
    allow_stub_fallback: bool = True,
    precomputed_gas: Any = _GAS_NOT_SUPPLIED,
    settings: Optional[Settings] = None,
    precomputed_detector: Any = _DETECTOR_NOT_SUPPLIED,
) -> Dict[str, Any]:
    """Run the VLM + LLM + detector + gas-twin stages for one inspection payload.

    Args:
        payload: The raw ``/inspect`` request payload (``truck_id``,
            ``demo_case``, ``photo_base64``, ``manifest_text``, weights, ...).
        ai_clients: A live :class:`VLLMClient` or a :class:`StubAIClients`.
        record_id: The audit record identity — part of the deterministic
            noise seed of the gas twin, so the same truck + record always
            reproduce the same readings.
        precomputed_gas: Gas already collected by the API (see
            :func:`collect_gate_gas`).  The default sentinel means "collect
            here"; an explicit value (including ``None``) is used as-is and
            never triggers another collection.
        settings: Detector configuration (default: :func:`get_settings`).
        precomputed_detector: A detector result the caller already has (the
            default sentinel means "run it here when a photo is present").

    Returns:
        ``{"vlm": ..., "llm": ..., "gas": ..., "detector": ...,
        "provenance": "live"|"stub"}``.  ``detector`` is the CPU detector's
        second opinion (:mod:`lynceus.detector`) or ``None`` when it did not
        run (disabled, no photo bytes, or it failed: logged, never raised).
        A live failure with stub fallback disabled returns provenance
        ``"detector_only_degraded"`` (``vlm``/``llm`` None, ``failed_stage``
        ``"vlm"`` or ``"llm"`` naming the call that failed) when the detector
        answered, and raises :class:`LiveAIUnavailableError` otherwise.
        ``gas`` carries the digital-twin gate readings (see
        :mod:`lynceus.gas_twin`) or ``None`` when the twin could not run
        (incomplete batch description or engine unavailable).  When the
        live client raises, the call falls back to the stub for the *same*
        payload and reports ``provenance: "stub_fallback_live_error"`` with
        the original error message — the stub result is marked honestly,
        never passed off as live output.
    """
    payload = dict(payload or {})
    gas_result = (
        _gate_gas_readings(payload, record_id)
        if precomputed_gas is _GAS_NOT_SUPPLIED
        else precomputed_gas
    )
    settings = settings or get_settings()
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

    # The CPU detector reads the real photo bytes only: a scripted demo case
    # without a photo stays exactly as scripted.
    photo_bytes = _photo_bytes(photo)
    detector_result: Optional[Dict[str, Any]] = (
        precomputed_detector if precomputed_detector is not _DETECTOR_NOT_SUPPLIED else None
    )

    with ThreadPoolExecutor(max_workers=3) as pool:
        # The detector runs beside the model calls (~150 ms on CPU, no network).
        detector_future = (
            pool.submit(safe_detect, photo_bytes, settings)
            if precomputed_detector is _DETECTOR_NOT_SUPPLIED and photo_bytes
            else None
        )
        try:
            # The two calls are independent and each takes seconds on a shared
            # endpoint, so run them concurrently; .result() re-raises either error.
            vlm_future = pool.submit(ai_clients.vlm, photo)
            llm_future = pool.submit(ai_clients.llm, manifest_text, context)
            # Which call failed decides the degraded wording: a vision answer
            # without its waybill check is still discarded, but it did run.
            failed_stage = "vlm"
            vlm_result = vlm_future.result()
            failed_stage = "llm"
            llm_result = llm_future.result()
            live_error: Optional[Exception] = None
        except Exception as exc:  # noqa: BLE001 — any live failure falls back
            if ai_clients.provenance != "live":
                raise
            live_error = exc
        if detector_future is not None:
            detector_result = detector_future.result()

    if live_error is not None:
        exc = live_error
        reason = f"{type(exc).__name__}: {exc}"
        if not allow_stub_fallback:
            if detector_result is not None:
                # Degraded, not dark: the detector answered, so the truck
                # is held for a human instead of the gate returning 503.
                # A vision answer whose waybill call failed is not fused.
                return {
                    "vlm": None,
                    "llm": None,
                    "gas": gas_result,
                    "detector": detector_result,
                    "provenance": DEGRADED_PROVENANCE,
                    "fallback_reason": reason,
                    "failed_stage": failed_stage,
                }
            raise LiveAIUnavailableError(
                f"live AI failed ({reason}); stub fallback disabled"
            ) from exc
        fallback = StubAIClients(demo_case=payload.get("demo_case"))
        return {
            "vlm": fallback.vlm(photo),
            "llm": fallback.llm(manifest_text, context),
            "gas": gas_result,
            "detector": detector_result,
            "provenance": "stub_fallback_live_error",
            "fallback_reason": reason,
        }

    result = {
        "vlm": vlm_result,
        "llm": llm_result,
        "gas": gas_result,
        "detector": detector_result,
        "provenance": ai_clients.provenance,
    }
    fallback_reason = getattr(ai_clients, "fallback_reason", None)
    if fallback_reason:
        result["fallback_reason"] = fallback_reason
    return result

