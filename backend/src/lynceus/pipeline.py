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
import hashlib
import inspect
import json
import logging
import math
import re
import threading
import time
from concurrent.futures import FIRST_EXCEPTION, ThreadPoolExecutor, wait
from datetime import timezone
from email.utils import parsedate_to_datetime
from typing import Any, Callable, Dict, List, Optional, Protocol, Tuple

import httpx

from lynceus import detector
from lynceus import gas_ingest
from lynceus import gas_twin
from lynceus.config import Settings, get_settings, provider_for_url
from lynceus.decision import HARD_CONTAMINANT_CONFIDENCE
from lynceus.vision_boxes import parse_locations


#: Per-call read budgets (seconds).  The VLM is the slow, image-bearing call;
#: the text-only LLM cross-check and the assist answer must not hold the gate
#: (or the page) for a full VLM budget when a shared endpoint stalls.
VLM_TIMEOUT_S = 90.0
LLM_TIMEOUT_S = 45.0
ASSIST_TIMEOUT_S = 30.0
EXPLAIN_TIMEOUT_S = ASSIST_TIMEOUT_S
#: One waybill read, fallbacks included (``POST /waybill/read``).
DOCUMENT_TIMEOUT_S = 45.0
#: The warm-up ping (``POST /warmup``): one token, never worth a long wait.
WARMUP_TIMEOUT_S = 20.0

#: Stage progress callback ``on_progress(stage, status, data)`` behind
#: ``POST /inspect/stream``.  Called from worker threads; must not block.
ProgressFn = Callable[[str, str, Optional[Dict[str, Any]]], None]


def progress_emitter(on_progress: Optional[ProgressFn]) -> ProgressFn:
    """``on_progress`` made safe to call anywhere: a missing callback is a
    no-op and a failing one is logged, never raised into the inspection."""

    def emit(stage: str, status: str, data: Optional[Dict[str, Any]] = None) -> None:
        if on_progress is None:
            return
        try:
            on_progress(stage, status, data)
        except Exception as exc:  # noqa: BLE001 — progress is best-effort
            _log.warning("progress callback failed: %s: %s", type(exc).__name__, exc)

    return emit


#: Key under which :meth:`VLLMClient._vote_reads` hands the per-read
#: summaries to :meth:`VLLMClient._vlm_result` (never part of raw_output).
_VOTES_KEY = "__votes__"
#: Key under which it reports an early-majority decision
#: (``{votes_used, third_read}``); absent when every read was waited for.
_EARLY_KEY = "__early_majority__"
#: ``third_read`` values: the last read came back within the grace window,
#: did not, or failed inside it.  Either of the last two decides on the
#: agreeing reads alone.
THIRD_READ_STATES = ("arrived", "late", "failed")


class _ReadProgress:
    """Counts finished vision reads and reports each as a ``vision_read``
    stage; shared by the concurrent reads of one inspection."""

    def __init__(self, on_progress: Optional[ProgressFn], total: int) -> None:
        self._emit = progress_emitter(on_progress)
        self._total = total
        self._done = 0
        self._lock = threading.Lock()

    def read_done(self, parsed: Dict[str, Any], frame: Optional[int] = None) -> None:
        with self._lock:
            self._done += 1
            index = self._done
        data: Dict[str, Any] = {"index": index, "of": self._total, **vote_summary(parsed)}
        if frame is not None:
            data["frame"] = frame
        self._emit("vision_read", "done", data)


class LiveAIUnavailableError(RuntimeError):
    """Live AI failed and stub fallback is disabled (fail-closed mode)."""


class VisionModelsFailedError(RuntimeError):
    """The VLM and its fallbacks all failed; the message lists every attempt
    (the primary's first) and the last failure is chained as the cause."""


class RateLimitSpentError(ValueError):
    """Every 429 retry was spent: the shared key is throttled for all models."""


#: Statuses that mean the key, not the model, is refused: no other model helps.
_KEY_REFUSED_STATUSES = frozenset({401, 403})


def _model_specific_failure(exc: BaseException) -> bool:
    """True when the next vision model may still answer: the endpoint replied
    with an error status (400 "model not supported", 503 "no available
    workers") or the model's reply was not usable JSON.  Connection failures,
    timeouts, a refused key (401/403) and spent 429 retries are not: the
    endpoint is down, the budget is spent, or every model would be refused."""
    if isinstance(exc, RateLimitSpentError):
        return False
    if isinstance(exc, httpx.HTTPStatusError):
        response = getattr(exc, "response", None)
        return getattr(response, "status_code", None) not in _KEY_REFUSED_STATUSES
    return isinstance(exc, (ValueError, KeyError, TypeError)) and not isinstance(
        exc, httpx.HTTPError
    )


#: Bound each retry wait so a shared-key 429 cannot stall a request indefinitely.
MAX_RETRY_AFTER_S = 10.0
_DEFAULT_RETRY_AFTER_S = 1.0

#: One process-wide budget across VLM, LLM, assist and shift calls. Four leaves
#: headroom for teammates under Token Factory's eight-concurrent shared-key cap.
_OUTBOUND_SLOTS = threading.BoundedSemaphore(4)
#: VLM vote reads in flight process-wide.  One fewer than the outbound slots,
#: so in steady state a waybill, assist or shift call finds a slot even while
#: two inspections vote at once (they would otherwise queue behind six reads).
_VLM_READ_SLOT_COUNT = 3
_VLM_READ_SLOTS = threading.BoundedSemaphore(_VLM_READ_SLOT_COUNT)
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
    "Always report metal, rock, concrete, tire or e-waste in hard_contaminants "
    "whenever any piece is visible, however small or partially buried. "
    "Report organic_residue or wet_mix in light_contaminants, and a moisture "
    "fraction above 0.3, whenever the load looks damp, dark, or has food/organic "
    "residue. "
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


def _strings(value: Any) -> List[str]:
    return [v for v in value if isinstance(v, str)] if isinstance(value, list) else []


def vote_summary(parsed: Dict[str, Any]) -> Dict[str, Any]:
    """One vision read as ``{hard, light, confidence}`` (``votes`` entries)."""
    return {
        "hard": _strings(parsed.get("hard_contaminants")),
        "light": _strings(parsed.get("light_contaminants")),
        "confidence": _clamp01(parsed.get("confidence")),
    }


def _vote_majority(reads: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Merge N VLM reads by majority on hard_contaminants, median on numbers.

    hard_contaminants: a contaminant is kept when it appears in > half the reads.
    light_contaminants, boxes: taken from the read that has the majority's
    hard_contaminants (the most informative read).
    confidence/moisture: median across reads.
    """
    if not reads:
        return {}
    if len(reads) == 1:
        return reads[0]

    # Majority vote on hard_contaminants (the safety-critical field).
    hard_votes: Dict[str, int] = {}
    for r in reads:
        # Each read counts a contaminant once; a malformed (non-string) entry
        # is ignored instead of crashing the vote.
        for c in {c for c in (r.get("hard_contaminants") or []) if isinstance(c, str)}:
            hard_votes[c] = hard_votes.get(c, 0) + 1
    majority = len(reads) // 2 + 1
    agreed_hard = sorted([c for c, n in hard_votes.items() if n >= majority])

    # Pick the read that best matches the majority hard set (prefer one that
    # actually contains them) as the base for light/boxes.
    def score(r: Dict[str, Any]) -> int:
        h = {c for c in (r.get("hard_contaminants") or []) if isinstance(c, str)}
        return len(h & set(agreed_hard))

    base = max(reads, key=score)

    def median(vals: List[float]) -> float:
        s = sorted(vals)
        n = len(s)
        return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0

    moistures = [_clamp01(r.get("moisture")) for r in reads]
    confidences = [_clamp01(r.get("confidence")) for r in reads]

    return {
        "contamination": base.get("contamination", "unknown"),
        "moisture": median(moistures),
        "hard_contaminants": agreed_hard,
        "light_contaminants": base.get("light_contaminants", []),
        "confidence": median(confidences),
        "locations": base.get("locations", []),
    }


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
                    # Fixed seed so identical re-runs give the same verdict.
                    "seed": 0,
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
                    raise RateLimitSpentError(
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
        self, base_url: str, model: str, messages: list, max_tokens: int = 1024
    ) -> Dict[str, Any]:
        """Chat round trip with robust JSON parsing and exactly one retry.

        The retry gets only what is left of ``self._timeout_s``: one budget
        covers both round trips.  1024 tokens: the VLM prompt asks for
        ``locations`` boxes, and a full answer (contaminants + moisture +
        several boxes with zones) truncates at 512 — the truncated JSON is
        unparseable and wastes the whole read.
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

    def _vote_reads(
        self,
        model: str,
        messages: list,
        deadline: float,
        *,
        votes: Optional[int] = None,
        progress: Optional[_ReadProgress] = None,
        frame: Optional[int] = None,
    ) -> Dict[str, Any]:
        """``vlm_votes`` reads of one model, merged by :func:`_vote_majority`.

        Token Factory reads are bimodal: identical photos sometimes return
        "none detected", so no single read decides the verdict.  A hard
        contaminant seen by only a minority of reads is dropped; the detector
        second opinion still escalates what it sees.  The reads run
        concurrently inside the chain's budget, each holding a
        :data:`_VLM_READ_SLOTS` slot and an outbound slot, so N votes cost
        about one read of wall time.  The first failed read fails the model
        at once, as a single read would: the chain does not wait for the
        other reads (they end at the deadline and their answers are dropped).
        ``votes`` overrides the setting (multi-angle frames get one read
        each); ``progress`` hears of every read that returned.
        """
        # Settings built in code skip the env clamp: never more reads than slots.
        votes = min(
            max(1, self._settings.vlm_votes if votes is None else votes),
            _VLM_READ_SLOT_COUNT,
        )
        url = self._settings.vllm_vlm_url
        abandoned = threading.Event()

        def read() -> Dict[str, Any]:
            if not _VLM_READ_SLOTS.acquire(timeout=max(deadline - time.monotonic(), 0.0)):
                raise _deadline_error(self._timeout_s)
            try:
                if abandoned.is_set():  # the model already failed: spend nothing
                    raise _deadline_error(self._timeout_s)
                parsed = self._remaining(deadline)._chat_json(url, model, messages)
            finally:
                _VLM_READ_SLOTS.release()
            if progress is not None and not abandoned.is_set():
                progress.read_done(parsed, frame)
            return parsed

        if votes == 1:
            parsed = read()
            return {**parsed, _VOTES_KEY: [vote_summary(parsed)]}
        pool = ThreadPoolExecutor(max_workers=votes, thread_name_prefix="lynceus-vote")
        try:
            reads = [pool.submit(read) for _ in range(votes)]
            done, _ = wait(reads, return_when=FIRST_EXCEPTION)
            errors = [f.exception() for f in done if f.exception() is not None]
            if errors:
                # A failure that ends the chain (refused key, spent 429s,
                # timeout) wins over one that would move to the next model.
                raise next((e for e in errors if not _model_specific_failure(e)), errors[0])
            answers = [future.result() for future in reads]
            # Every read's own answer travels with the merge: a minority
            # sighting the vote dropped is still visible to the rules.
            return {**_vote_majority(answers), _VOTES_KEY: [vote_summary(a) for a in answers]}
        finally:
            abandoned.set()
            pool.shutdown(wait=False, cancel_futures=True)

    @staticmethod
    def _image_messages(prompt: str, photo: str) -> list:
        """One user turn: ``prompt`` plus the photo as a data-URI image."""
        # PNG base64 always starts "iVBOR" (the 0x89 'PNG' signature); the
        # API has already admitted only JPEG and PNG.
        mime = "image/png" if photo.startswith("iVBOR") else "image/jpeg"
        data_uri = photo if photo.startswith("data:") else f"data:{mime};base64,{photo}"
        return [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": data_uri}},
                ],
            }
        ]

    def _vision_chain(
        self, read_with: Callable[[str], Dict[str, Any]]
    ) -> Tuple[Dict[str, Any], str, List[str], float]:
        """Run ``read_with(model)`` down the vision model chain.

        VLM_MODEL first, then VLM_FALLBACK_MODELS in order: a shared endpoint
        can drop one model ("no available workers") while others still serve.
        The caller's ``read_with`` holds the one wall-clock budget of the
        whole chain.  Only a failure of the model itself (an HTTP error
        status, an unparseable reply) moves on; an unreachable endpoint or a
        spent budget ends the chain.  Returns ``(parsed, model, failed,
        latency_ms)``: the model that answered, and the ones that failed
        before it, so the audit never hides the switch.
        """
        models = (self._settings.vlm_model, *self._settings.vlm_fallback_models)
        failed: List[str] = []
        details: List[str] = []
        for model in models:
            started = time.perf_counter()
            try:
                parsed = read_with(model)
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
        return parsed, model, failed, (time.perf_counter() - started) * 1000.0

    @property
    def vision_model(self) -> str:
        """The vision model tried first (progress events name it)."""
        return self._settings.vlm_model

    @property
    def vision_provider(self) -> str:
        return provider_for_url(self._settings.vllm_vlm_url)

    def vlm(
        self, photo: Optional[str], on_progress: Optional[ProgressFn] = None
    ) -> Dict[str, Any]:
        if not photo:
            raise ValueError("VLMClient.vlm requires a base64 photo")
        messages = self._image_messages(_VLM_PROMPT, photo)
        deadline = time.monotonic() + self._timeout_s
        votes = min(max(1, self._settings.vlm_votes), _VLM_READ_SLOT_COUNT)

        def read_with(model: str) -> Dict[str, Any]:
            # A fallback model's reads count again from 1.
            progress = _ReadProgress(on_progress, votes)
            return self._vote_reads(model, messages, deadline, progress=progress)

        parsed, model, failed, latency_ms = self._vision_chain(read_with)
        result = self._vlm_result(parsed, model, latency_ms, self._settings.localisation_mode)
        if failed:
            result["fallback_from"] = failed
        return result

    def vlm_frames(
        self, photos: List[str], on_progress: Optional[ProgressFn] = None
    ) -> List[Dict[str, Any]]:
        """One read per camera angle, concurrent on the shared read slots.

        Each frame runs its own model chain inside one wall-clock budget; the
        first frame that fails fails the vision stage, as a single read would.
        """
        if not photos or not all(photos):
            raise ValueError("VLMClient.vlm_frames requires base64 photos")
        deadline = time.monotonic() + self._timeout_s
        progress = _ReadProgress(on_progress, len(photos))
        mode = self._settings.localisation_mode

        def one(frame: int, photo: str) -> Dict[str, Any]:
            messages = self._image_messages(_VLM_PROMPT, photo)
            parsed, model, failed, latency_ms = self._vision_chain(
                lambda m: self._vote_reads(
                    m, messages, deadline, votes=1, progress=progress, frame=frame
                )
            )
            result = self._vlm_result(parsed, model, latency_ms, mode)
            if failed:
                result["fallback_from"] = failed
            return result

        pool = ThreadPoolExecutor(max_workers=len(photos), thread_name_prefix="lynceus-frame")
        try:
            futures = [pool.submit(one, i, p) for i, p in enumerate(photos)]
            done, _ = wait(futures, return_when=FIRST_EXCEPTION)
            errors = [f.exception() for f in done if f.exception() is not None]
            if errors:
                raise errors[0]
            return [f.result() for f in futures]
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

    def read_document(
        self,
        image: str,
        prompt: str,
        *,
        budget_s: float = DOCUMENT_TIMEOUT_S,
        max_tokens: int = 1024,
    ) -> Tuple[Dict[str, Any], str, List[str], float]:
        """One JSON read of a document photo (no voting) down the vision chain.

        Used for the waybill.  Takes no vision read slot: a waybill read must
        never queue behind an inspection's votes (the caller caps its own
        concurrency).  Returns ``(parsed, model, failed, latency_ms)`` like
        :meth:`_vision_chain`; raises like :meth:`vlm`.
        """
        if not image:
            raise ValueError("VLLMClient.read_document requires a base64 image")
        client = self._scoped(budget_s)
        messages = self._image_messages(prompt, image)
        url = self._settings.vllm_vlm_url
        deadline = time.monotonic() + client._timeout_s
        return client._vision_chain(
            lambda m: client._remaining(deadline)._chat_json(url, m, messages, max_tokens)
        )

    def warm(self, budget_s: float = WARMUP_TIMEOUT_S) -> None:
        """A one-token text chat to the primary vision model (wakes a cold
        worker before the first truck).  Raises like any chat call."""
        self._scoped(budget_s)._chat_once(
            self._settings.vllm_vlm_url,
            self._settings.vlm_model,
            [{"role": "user", "content": "ping"}],
            max_tokens=1,
        )

    def _vlm_result(
        self, parsed: Dict[str, Any], model: str, latency_ms: float, mode: str
    ) -> Dict[str, Any]:
        parsed = dict(parsed)
        votes = parsed.pop(_VOTES_KEY, None)
        result = {
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
        if votes is not None:
            result["votes"] = votes
        return result

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

    vision_model = "stub-vlm"
    vision_provider = None

    def vlm(
        self, photo: Optional[str], on_progress: Optional[ProgressFn] = None
    ) -> Dict[str, Any]:
        script = _STUB_VLM[self._demo_case]
        read = {**script["detected"], "confidence": script["confidence"]}
        _ReadProgress(on_progress, 1).read_done(read)
        return {
            # The scripted answer counts as one read.
            "votes": [vote_summary(read)],
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
        demo_case=stub_case_for(payload),
        provenance="stub_fallback_live_error",
        fallback_reason=reason,
    )


#: The bundled demo load photos (web/public/demo, AI-generated) and the stub
#: script that tells their story, by sha256 of the exact file.
_DEMO_PHOTO_CASES = {
    "ee94de8be36e1cd288c0d8b8a206e997765850e140ce29b22f423d4d0dc3700b": "red",  # t-metal-1
    "b2ddbcb9ca800b387379070b5afe4c8deea912ae1900fd58fef6630c81dc63c5": "red",  # t-metal-2
    "b1344f36592ad0009def53c240084ee6b4f03e471ec0c41da8bd7a2cc61835d1": "green",  # t-clean-1
    "9d9892e979faf8063de1e42195adacfdf22c246567c060e24e2354e50a5fb559": "green",  # t-clean-2
    "7dab3b77d44f184a05a81c31287f34b4b3805d929478067db4c349c758898bc7": "amber",  # t-ambiguous-1
    "a7d4d48b1a4be099044b179218bd93fa8e9d4ecbcd024f9c8017d4311fe73862": "amber",  # t-ambiguous-2
}
#: Their filename prefixes: the console downscales photos over 1280 px, which
#: changes the bytes of these 1448 px files but keeps their names.
_DEMO_PHOTO_PREFIXES = (("t-metal-", "red"), ("t-clean-", "green"), ("t-ambiguous-", "amber"))


def stub_case_for(payload: Dict[str, Any]) -> Optional[str]:
    """The stub script for an offline inspection: ``demo_case`` when set,
    else the script of a bundled demo photo (by digest, then by filename),
    else ``None`` (the clean script).  The stub reads no image: this only
    keeps the bundled demo trucks telling their own story offline."""
    if payload.get("demo_case"):
        return str(payload["demo_case"])
    photo = _photo_bytes(payload.get("photo_base64") or payload.get("photo"))
    if photo:
        case = _DEMO_PHOTO_CASES.get(hashlib.sha256(photo).hexdigest())
        if case:
            return case
    name = str(payload.get("photo_filename") or "").replace("\\", "/").rsplit("/", 1)[-1].lower()
    for prefix, case in _DEMO_PHOTO_PREFIXES:
        if name.startswith(prefix):
            return case
    return None


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
    sensor never runs a second time (a live sensor could otherwise return
    different values and break the frozen snapshot).  ``None`` when no live
    sensor answered.
    """
    return _gate_gas_readings(payload, record_id)


def _gate_gas_readings(
    payload: Dict[str, Any], record_id: Optional[str]
) -> Optional[Dict[str, Any]]:
    """Gas readings for this inspection, from a live gate instrument only.

    A configured, reachable sensor gateway (:mod:`lynceus.gas_ingest`,
    env ``LYNCEUS_GAS_SENSOR_URL`` — e.g. a TDLAS gate monitor) provides
    *measured* values stamped ``sentinel_gate_sensor``.  Without one the
    inspection has no gas data (``None``; the record says ``not_measured``):
    the digital twin ran on operator-typed numbers, so it no longer feeds a
    gate verdict.  It stays available through ``/assess`` and
    :func:`_simulate_gas_readings`.
    """
    return gas_ingest.fetch_live_readings()


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


def safe_detect(
    photo_bytes: bytes, settings: Settings, *, wait_for_slot: bool = True
) -> Optional[Dict[str, Any]]:
    """:func:`detector.detect`, with any failure logged and turned into None:
    the second opinion must never fail the inspection.  ``wait_for_slot``
    False takes only an idle run slot (scripted demo requests: they must
    never make a live inspection wait for the detector)."""
    try:
        if not wait_for_slot:
            return detector.detect(photo_bytes, settings, slot_wait_s=0.0)
        return detector.detect(photo_bytes, settings)
    except Exception as exc:  # noqa: BLE001 — logged, never raised
        _log.warning("detector skipped: %s: %s", type(exc).__name__, exc)
        return None




def _accepts_progress(fn: Any) -> bool:
    """True when ``fn`` takes ``on_progress`` (test doubles often do not)."""
    try:
        return "on_progress" in inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False


def _read_frames(
    ai_clients: AIClients, frames: List[Optional[str]], on_progress: Optional[ProgressFn]
) -> List[Dict[str, Any]]:
    """The vision answer per frame: ``vlm_votes`` voted reads for one photo,
    one read per angle for two or three (concurrent when the client can)."""
    if len(frames) <= 1:
        photo = frames[0] if frames else None
        if _accepts_progress(ai_clients.vlm):
            return [ai_clients.vlm(photo, on_progress=on_progress)]
        return [ai_clients.vlm(photo)]
    vlm_frames = getattr(ai_clients, "vlm_frames", None)
    if vlm_frames is not None:
        return vlm_frames(frames, on_progress=on_progress)
    progress = _ReadProgress(on_progress, len(frames))
    results = []
    for index, photo in enumerate(frames):
        result = ai_clients.vlm(photo)
        progress.read_done(
            {**(result.get("detected") or {}), "confidence": result.get("confidence")},
            index,
        )
        results.append(result)
    return results


def merge_frame_reads(frames: List[Dict[str, Any]]) -> Dict[str, Any]:
    """One vision result from the reads of several camera angles.

    * hard contaminants: the union over frames read at/above
      ``HARD_CONTAMINANT_CONFIDENCE`` (a metal pipe seen from one side only
      is still in the load);
    * light contaminants: the union; moisture: the wettest frame;
    * confidence: the lowest frame confidence, except when a hard
      contaminant was found, then the lowest confidence among the frames
      that found one (an unreadable second angle must not hide a confident
      sighting in the first);
    * boxes and ``votes`` (each frame's reads) keep their ``frame`` index
      (0 = the main photo).
    """
    if len(frames) == 1:
        return frames[0]
    hard: set = set()
    light: List[str] = []
    moistures: List[float] = []
    confidences: List[float] = []
    hard_confidences: List[float] = []
    contamination: List[str] = []
    boxes: List[Dict[str, Any]] = []
    fallback_from: List[str] = []
    votes: List[Dict[str, Any]] = []
    for index, result in enumerate(frames):
        detected = result.get("detected") or {}
        confidence = _clamp01(result.get("confidence"))
        confidences.append(confidence)
        frame_hard = [h for h in detected.get("hard_contaminants") or [] if isinstance(h, str)]
        if frame_hard and confidence >= HARD_CONTAMINANT_CONFIDENCE:
            hard.update(frame_hard)
            hard_confidences.append(confidence)
        for name in detected.get("light_contaminants") or []:
            if isinstance(name, str) and name not in light:
                light.append(name)
        moisture = detected.get("moisture")
        if isinstance(moisture, (int, float)) and not isinstance(moisture, bool):
            moistures.append(_clamp01(moisture))
        text = str(detected.get("contamination") or "").strip()
        if text and text not in contamination:
            contamination.append(text)
        boxes += [{**box, "frame": index} for box in result.get("boxes") or []]
        votes += [{**vote, "frame": index} for vote in result.get("votes") or []]
        fallback_from += [f for f in result.get("fallback_from") or [] if f not in fallback_from]
    if len(contamination) > 1:
        contamination = [c for c in contamination if c.lower() != "none detected"]
    models = list(dict.fromkeys(str(r.get("model", "")) for r in frames))
    latencies = [r["latency_ms"] for r in frames if isinstance(r.get("latency_ms"), (int, float))]
    merged: Dict[str, Any] = {
        "detected": {
            "contamination": "; ".join(contamination) or "none detected",
            "moisture": max(moistures) if moistures else None,
            "hard_contaminants": sorted(hard),
            "light_contaminants": light,
        },
        "confidence": min(hard_confidences) if hard else min(confidences),
        "boxes": boxes,
        "localisation": frames[0].get("localisation"),
        # Different answering models are all named: a mixed answer is
        # never passed off as the benchmarked model's.
        "model": "+".join(models),
        "model_version": "+".join(
            dict.fromkeys(str(r.get("model_version", "")) for r in frames)
        ),
        "raw_output": json.dumps([r.get("raw_output") for r in frames]),
        "provenance": frames[0].get("provenance"),
        "provider": frames[0].get("provider"),
        "latency_ms": max(latencies) if latencies else None,
    }
    if fallback_from:
        merged["fallback_from"] = fallback_from
    if votes:
        merged["votes"] = votes
    return merged


def merge_frame_detections(
    results: List[Optional[Dict[str, Any]]], settings: Settings
) -> Optional[Dict[str, Any]]:
    """One detector block from per-frame runs; boxes keep their ``frame``.

    ``None`` when no frame was read (disabled or failed everywhere).
    """
    if len(results) == 1:
        return results[0]
    present = [(i, r) for i, r in enumerate(results) if r is not None]
    if not present:
        return None
    first = present[0][1]
    thresholds = first.get("thresholds") or {}
    latencies = [r["latency_ms"] for _, r in present if isinstance(r.get("latency_ms"), (int, float))]
    return detector.summarize(
        [{**box, "frame": i} for i, r in present for box in r.get("boxes") or []],
        sum(latencies) if latencies else None,
        float(thresholds.get("hard", settings.detector_hard_conf)),
        float(thresholds.get("light", settings.detector_light_conf)),
        escalate_light=bool(thresholds.get("escalate_light", settings.detector_escalate_light)),
        model=str(first.get("model", detector.MODEL_NAME)),
        model_sha256=first.get("model_sha256"),
        runtime=str(first.get("runtime", detector.RUNTIME)),
    )


def run_inspection(
    payload: Dict[str, Any],
    ai_clients: AIClients,
    record_id: Optional[str] = None,
    allow_stub_fallback: bool = True,
    precomputed_gas: Any = _GAS_NOT_SUPPLIED,
    settings: Optional[Settings] = None,
    precomputed_detector: Any = _DETECTOR_NOT_SUPPLIED,
    on_progress: Optional[ProgressFn] = None,
) -> Dict[str, Any]:
    """Run the VLM + LLM + detector stages for one inspection payload.

    Args:
        payload: The raw ``/inspect`` request payload (``truck_id``,
            ``demo_case``, ``photo_base64``, ``extra_photos_base64``,
            ``manifest_text``, weights, ...).
        ai_clients: A live :class:`VLLMClient` or a :class:`StubAIClients`.
        record_id: The audit record identity (kept for callers; the gas
            channel no longer needs it).
        precomputed_gas: Gas already collected by the API (see
            :func:`collect_gate_gas`).  The default sentinel means "collect
            here"; an explicit value (including ``None``) is used as-is and
            never triggers another collection.
        settings: Detector configuration (default: :func:`get_settings`).
        precomputed_detector: A detector result for the main photo the
            caller already has (the default sentinel means "run it here when
            a photo is present").
        on_progress: Optional stage callback (``detector``, ``vision``,
            ``vision_read``, ``waybill_audit``); see ``POST /inspect/stream``.

    Returns:
        ``{"vlm": ..., "llm": ..., "gas": ..., "detector": ...,
        "provenance": "live"|"stub"}`` plus ``vlm_frames`` (each angle's own
        answer) when extra camera angles were sent.  With two or three
        frames the detector runs per frame and the vision reads are merged
        by :func:`merge_frame_reads`; boxes carry their ``frame`` index.
        ``detector`` is the CPU detector's second opinion
        (:mod:`lynceus.detector`) or ``None`` when it did not run (disabled,
        no photo bytes, or it failed: logged, never raised).
        A live failure with stub fallback disabled returns provenance
        ``"detector_only_degraded"`` (``vlm``/``llm`` None, ``failed_stage``
        ``"vlm"`` or ``"llm"`` naming the call that failed) when the detector
        answered, and raises :class:`LiveAIUnavailableError` otherwise.
        ``gas`` carries a live gate sensor's readings or ``None`` (no
        sensor).  When the live client raises, the call falls back to the
        stub for the *same* payload and reports ``provenance:
        "stub_fallback_live_error"`` with the original error message — the
        stub result is marked honestly, never passed off as live output.
    """
    payload = dict(payload or {})
    emit = progress_emitter(on_progress)
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
    # Extra camera angles count only beside a main photo.
    frames: List[Optional[str]] = [photo]
    if photo:
        frames += [p for p in payload.get("extra_photos_base64") or [] if p]

    # The CPU detector reads the real photo bytes only: a scripted demo case
    # without a photo stays exactly as scripted.
    frame_bytes = [_photo_bytes(p) for p in frames]
    have_precomputed = precomputed_detector is not _DETECTOR_NOT_SUPPLIED
    detector_result: Optional[Dict[str, Any]] = (
        precomputed_detector if have_precomputed else None
    )
    # Scripted demo requests never queue for the detector and use at most
    # one of its run slots, so live inspections always keep one.
    wait_for_slot = not payload.get("demo_case")

    def detect(data: bytes) -> Optional[Dict[str, Any]]:
        if not data:
            return None
        if wait_for_slot:
            return safe_detect(data, settings)
        return safe_detect(data, settings, wait_for_slot=False)

    def detect_frames() -> Optional[Dict[str, Any]]:
        results = [
            precomputed_detector if index == 0 and have_precomputed else detect(data)
            for index, data in enumerate(frame_bytes)
        ]
        return merge_frame_detections(results, settings)

    def detector_done(result: Optional[Dict[str, Any]]) -> None:
        if result is None:
            emit("detector", "skipped")
            return
        emit(
            "detector",
            "done",
            {
                "labels": sorted(
                    set(result.get("hard_contaminants") or [])
                    | set(result.get("light_contaminants") or [])
                ),
                "latency_ms": result.get("latency_ms"),
            },
        )

    def stage_callback(stage: str, describe: Callable[[Any], Optional[Dict[str, Any]]]) -> Callable[[Any], None]:
        def done(future: Any) -> None:
            error = future.exception()
            if error is not None:
                emit(stage, "failed", {"error": type(error).__name__})
            else:
                emit(stage, "done", describe(future.result()))

        return done

    def vision_summary(results: List[Dict[str, Any]]) -> Dict[str, Any]:
        merged = merge_frame_reads(results)
        return {"model": merged.get("model"), "latency_ms": merged.get("latency_ms")}

    votes = min(max(1, settings.vlm_votes), _VLM_READ_SLOT_COUNT)
    emit(
        "vision",
        "running",
        {
            "model": getattr(ai_clients, "vision_model", None),
            "provider": getattr(ai_clients, "vision_provider", None),
            "reads": (votes if isinstance(ai_clients, VLLMClient) else 1)
            if len(frames) == 1
            else len(frames),
            "frames": len(frames),
        },
    )

    with ThreadPoolExecutor(max_workers=3) as pool:
        # The detector runs beside the model calls (~150 ms per frame on
        # CPU, no network).
        detector_future = None
        if any(frame_bytes[1:]) or (frame_bytes[0] and not have_precomputed):
            detector_future = pool.submit(detect_frames)
            detector_future.add_done_callback(
                lambda f: detector_done(f.result() if f.exception() is None else None)
            )
        elif have_precomputed:
            detector_done(detector_result)
        try:
            # The two calls are independent and each takes seconds on a shared
            # endpoint, so run them concurrently; .result() re-raises either error.
            vlm_future = pool.submit(_read_frames, ai_clients, frames, on_progress)
            vlm_future.add_done_callback(stage_callback("vision", vision_summary))
            llm_future = pool.submit(ai_clients.llm, manifest_text, context)
            llm_future.add_done_callback(
                stage_callback("waybill_audit", lambda r: {"model": r.get("model")})
            )
            # Which call failed decides the degraded wording: a vision answer
            # without its waybill check is still discarded, but it did run.
            failed_stage = "vlm"
            vlm_frames = vlm_future.result()
            vlm_result = merge_frame_reads(vlm_frames)
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
        fallback = StubAIClients(demo_case=stub_case_for(payload))
        emit("vision", "done", {"model": fallback.vision_model, "fallback": True})
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
    if len(vlm_frames) > 1:
        result["vlm_frames"] = vlm_frames
    fallback_reason = getattr(ai_clients, "fallback_reason", None)
    if fallback_reason:
        result["fallback_reason"] = fallback_reason
    return result
