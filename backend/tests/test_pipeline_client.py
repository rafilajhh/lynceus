"""Offline tests for provider provenance, latency, assist role, concurrency.

Nothing here touches the network: ``VLLMClient._chat_once`` is monkeypatched
and the pipeline concurrency tests use in-process fake clients.
"""

from __future__ import annotations

import contextlib
import json
import threading
import time
from email.utils import parsedate_to_datetime

import httpx


import pytest

from lynceus import pipeline
from lynceus.config import get_settings, provider_for_url
from lynceus.pipeline import (
    LiveAIUnavailableError,
    VLLMClient,
    _RateLimitedError,
    run_inspection,
)

_VLM_JSON = json.dumps(
    {
        "contamination": "none detected",
        "moisture": 0.1,
        "hard_contaminants": [],
        "light_contaminants": [],
        "confidence": 0.8,
    }
)
_LLM_JSON = json.dumps(
    {"reasoning": "ok", "crosscheck_notes": "consistent", "confidence": 0.9}
)


def test_provider_for_url_token_factory():
    assert (
        provider_for_url("https://developer.amd.com.cn/radeon/api/v1")
        == "amd-token-factory"
    )
    assert provider_for_url("https://api.amd.com/v1") == "amd-token-factory"
    assert provider_for_url("http://localhost:8000/v1") == "openai-compatible"
    assert provider_for_url("https://notamd.com/v1") == "openai-compatible"


def test_settings_assist_defaults(monkeypatch):
    for name in ("ASSIST_URL", "ASSIST_MODEL", "LOCALISATION_MODE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("VLLM_LLM_URL", "http://llm.example/v1")
    monkeypatch.setenv("LLM_MODEL", "llm-x")
    s = get_settings()
    assert s.assist_url == "http://llm.example/v1"
    assert s.assist_model == "llm-x"
    assert s.localisation_mode == "box"
    monkeypatch.setenv("ASSIST_URL", "http://assist.example/v1")
    monkeypatch.setenv("ASSIST_MODEL", "assist-y")
    monkeypatch.setenv("LOCALISATION_MODE", "zone")
    s = get_settings()
    assert (s.assist_url, s.assist_model, s.localisation_mode) == (
        "http://assist.example/v1",
        "assist-y",
        "zone",
    )


def test_vlm_result_carries_provider_and_latency(monkeypatch):
    monkeypatch.setenv("VLLM_VLM_URL", "https://developer.amd.com.cn/radeon/api/v1")
    client = VLLMClient(settings=get_settings())
    monkeypatch.setattr(
        VLLMClient, "_chat_once", lambda self, *a, **k: _VLM_JSON
    )
    result = client.vlm("aGVsbG8=")
    assert result["provider"] == "amd-token-factory"
    assert result["latency_ms"] >= 0
    assert result["provenance"] == "live"


def test_llm_result_carries_provider_and_latency(monkeypatch):
    monkeypatch.setenv("VLLM_LLM_URL", "http://localhost:8001/v1")
    client = VLLMClient(settings=get_settings())
    monkeypatch.setattr(
        VLLMClient, "_chat_once", lambda self, *a, **k: _LLM_JSON
    )
    result = client.llm("waybill", {})
    assert result["provider"] == "openai-compatible"
    assert result["latency_ms"] >= 0


@pytest.mark.parametrize(
    "header, expected",
    [
        ("Wed, 21 Oct 2015 07:28:05 GMT", 5.0),
        ("Wed, 21 Oct 2015 07:27:59 GMT", 0.0),
        ("garbage", 1.0),
        ("3600", 10.0),
        ("Wed, 21 Oct 2015 08:28:00 GMT", 10.0),
    ],
)
def test_retry_after_date_and_cap(monkeypatch, header, expected):
    now = parsedate_to_datetime("Wed, 21 Oct 2015 07:28:00 GMT").timestamp()
    monkeypatch.setattr(pipeline.time, "time", lambda: now)
    assert pipeline._parse_retry_after(header) == pytest.approx(expected)


@pytest.mark.parametrize("status", [200, 429, 500])
def test_outbound_call_acquires_shared_budget_and_releases(monkeypatch, status):
    budget = getattr(pipeline, "_OUTBOUND_SLOTS", None)
    assert isinstance(budget, threading.BoundedSemaphore)

    @contextlib.contextmanager
    def transport(*args, **kwargs):
        # One slot is held by _chat_once; only three remain available.
        acquired = 0
        try:
            while budget.acquire(blocking=False):
                acquired += 1
            assert acquired == 3
        finally:
            for _ in range(acquired):
                budget.release()
        yield httpx.Response(
            status,
            request=httpx.Request("POST", "http://x/v1/chat/completions"),
            json={"choices": [{"message": {"content": "ok"}}]},
        )

    monkeypatch.setattr(pipeline.httpx, "stream", transport)
    client = VLLMClient(settings=get_settings())
    if status == 200:
        assert client._chat_once("http://x/v1", "m", []) == "ok"
    else:
        error = _RateLimitedError if status == 429 else httpx.HTTPStatusError
        with pytest.raises(error):
            client._chat_once("http://x/v1", "m", [])
    acquired = 0
    try:
        while budget.acquire(blocking=False):
            acquired += 1
        assert acquired == 4
    finally:
        for _ in range(acquired):
            budget.release()


def test_429_retry_then_raises(monkeypatch):
    calls = []

    def _always_limited(self, *args, **kwargs):
        calls.append(1)
        raise _RateLimitedError(0)

    monkeypatch.setattr(VLLMClient, "_chat_once", _always_limited)
    client = VLLMClient(settings=get_settings())
    with pytest.raises(ValueError, match="rate-limited"):
        client.vlm("aGVsbG8=")
    assert len(calls) == 3


def test_assist_returns_json_and_latency(monkeypatch):
    monkeypatch.setenv("ASSIST_URL", "http://assist.example/v1")
    monkeypatch.setenv("ASSIST_MODEL", "assist-y")
    seen = {}

    def _fake(self, base_url, model, messages, max_tokens=512):
        seen.update(base_url=base_url, model=model, max_tokens=max_tokens)
        return '{"answer": "15% penalty", "citations": ["SOP-RDF-5.3"]}'

    monkeypatch.setattr(VLLMClient, "_chat_once", _fake)
    client = VLLMClient(settings=get_settings())
    parsed, latency_ms = client.assist([{"role": "user", "content": "q"}])
    assert parsed == {"answer": "15% penalty", "citations": ["SOP-RDF-5.3"]}
    assert latency_ms >= 0
    assert seen == {
        "base_url": "http://assist.example/v1",
        "model": "assist-y",
        "max_tokens": 700,
    }


def test_vlm_llm_keep_default_max_tokens(monkeypatch):
    seen = []

    def _fake(self, base_url, model, messages, max_tokens=512):
        seen.append(max_tokens)
        return _VLM_JSON

    monkeypatch.setattr(VLLMClient, "_chat_once", _fake)
    VLLMClient(settings=get_settings()).vlm("aGVsbG8=")
    assert seen == [512]


# ---------------------------------------------------------------------------
# run_inspection: concurrent VLM + LLM, unchanged fallback semantics
# ---------------------------------------------------------------------------


class _SlowClients:
    provenance = "live"

    def __init__(self, llm_error=None, delay=0.3):
        self._llm_error = llm_error
        self._delay = delay

    def vlm(self, photo):
        time.sleep(self._delay)
        return {"detected": {}, "confidence": 0.5, "provenance": "live"}

    def llm(self, manifest_text, context):
        time.sleep(self._delay)
        if self._llm_error:
            raise self._llm_error
        return {"reasoning": "", "confidence": 0.5, "provenance": "live"}


def test_vlm_and_llm_run_concurrently():
    start = time.perf_counter()
    result = run_inspection({"photo_base64": "x"}, _SlowClients())
    elapsed = time.perf_counter() - start
    assert result["provenance"] == "live"
    assert elapsed < 0.5, f"calls did not overlap ({elapsed:.2f}s)"


def test_llm_error_with_vlm_success_falls_back():
    result = run_inspection(
        {"photo_base64": "x", "demo_case": "red"},
        _SlowClients(llm_error=RuntimeError("boom"), delay=0.01),
    )
    assert result["provenance"] == "stub_fallback_live_error"
    assert "boom" in result["fallback_reason"]
    assert result["vlm"]["provenance"] == "stub"


def test_fail_closed_raises():
    with pytest.raises(LiveAIUnavailableError):
        run_inspection(
            {"photo_base64": "x"},
            _SlowClients(llm_error=RuntimeError("boom"), delay=0.01),
            allow_stub_fallback=False,
        )


def test_non_live_errors_reraise():
    class _Bad(_SlowClients):
        provenance = "stub"

    with pytest.raises(RuntimeError, match="boom"):
        run_inspection(
            {"photo_base64": "x"}, _Bad(llm_error=RuntimeError("boom"), delay=0.01)
        )


# ---------------------------------------------------------------------------
# Wall-clock deadline: httpx timeouts are per read, so a trickling stream
# never trips them.  Fake streams only; nothing touches the network.
# ---------------------------------------------------------------------------

_SSE_CHUNK = b'data: {"choices": [{"delta": {"content": "x"}}]}\n'


def _streaming_transport(chunks, content_type="text/event-stream"):
    @contextlib.contextmanager
    def transport(*args, **kwargs):
        yield httpx.Response(
            200,
            headers={"content-type": content_type},
            content=chunks(),
            request=httpx.Request("POST", "http://x/v1/chat/completions"),
        )

    return transport


def _trickle(chunk=_SSE_CHUNK, every_s=0.05):
    def chunks():
        while True:  # never sends [DONE]: only the deadline can end it
            time.sleep(every_s)
            yield chunk

    return chunks


def _slots_restored(timeout_s=2.0):
    """True once all four outbound slots are free again (worker exited)."""
    budget = pipeline._OUTBOUND_SLOTS
    end = time.monotonic() + timeout_s
    while time.monotonic() < end:
        acquired = 0
        while budget.acquire(blocking=False):
            acquired += 1
        for _ in range(acquired):
            budget.release()
        if acquired == 4:
            return True
        time.sleep(0.01)
    return False


@pytest.mark.parametrize(
    "chunks, content_type",
    [
        (_trickle(), "text/event-stream"),  # SSE events keep arriving
        (_trickle(chunk=b"d"), "text/event-stream"),  # bytes, never a newline
        (_trickle(chunk=b" "), "application/json"),  # JSON body trickling
    ],
)
def test_trickling_stream_hits_wall_clock_deadline(monkeypatch, chunks, content_type):
    monkeypatch.setattr(
        pipeline.httpx, "stream", _streaming_transport(chunks, content_type)
    )
    client = VLLMClient(settings=get_settings(), timeout_s=0.3)
    start = time.perf_counter()
    with pytest.raises(httpx.ReadTimeout, match="0.3 s"):
        client._chat_once("http://x/v1", "m", [])
    elapsed = time.perf_counter() - start
    assert 0.25 <= elapsed < 0.6, f"deadline not enforced ({elapsed:.2f}s)"
    # The abandoned worker stops at its next chunk and frees its slot.
    assert _slots_restored()


def test_stalled_stream_returns_at_deadline_and_frees_slot(monkeypatch):
    unblock = threading.Event()

    def stalled():
        unblock.wait(5.0)  # a read that would only end at the per-read timeout
        yield _SSE_CHUNK

    monkeypatch.setattr(pipeline.httpx, "stream", _streaming_transport(stalled))
    client = VLLMClient(settings=get_settings(), timeout_s=0.2)
    start = time.perf_counter()
    try:
        with pytest.raises(httpx.ReadTimeout):
            client._chat_once("http://x/v1", "m", [])
        assert time.perf_counter() - start < 0.5
    finally:
        unblock.set()
    assert _slots_restored()


def test_fast_stream_within_deadline_still_returns(monkeypatch):
    def finished():
        yield _SSE_CHUNK + b'data: {"choices": [{"delta": {"content": "y"}}]}\n'
        yield b"data: [DONE]\n"

    monkeypatch.setattr(pipeline.httpx, "stream", _streaming_transport(finished))
    client = VLLMClient(settings=get_settings(), timeout_s=0.5)
    assert client._chat_once("http://x/v1", "m", []) == "xy"


def test_deadline_takes_the_existing_fallback_and_fail_closed_paths(monkeypatch):
    monkeypatch.setattr(pipeline.httpx, "stream", _streaming_transport(_trickle()))
    client = VLLMClient(settings=get_settings(), timeout_s=0.3)
    start = time.perf_counter()
    result = run_inspection({"photo_base64": "aGVsbG8=", "manifest_text": "w"}, client)
    assert time.perf_counter() - start < 1.0
    assert result["provenance"] == "stub_fallback_live_error"
    assert result["fallback_reason"].startswith("ReadTimeout")
    with pytest.raises(LiveAIUnavailableError, match="ReadTimeout"):
        run_inspection(
            {"photo_base64": "aGVsbG8="}, client, allow_stub_fallback=False
        )
    assert _slots_restored()


def test_deadline_gives_pythia_cannot_answer(monkeypatch):
    from lynceus import assist

    monkeypatch.setattr(pipeline.httpx, "stream", _streaming_transport(_trickle()))
    client = VLLMClient(settings=get_settings(), timeout_s=0.3)
    start = time.perf_counter()
    out = assist.answer("What penalty applies at 0.30 moisture?", None, client)
    assert time.perf_counter() - start < 1.0
    assert out["answer"] == assist.CANNOT_ANSWER and out["grounded"] is False
    assert _slots_restored()


# ---------------------------------------------------------------------------
# Explain role (shift-report supplier explanations)
# ---------------------------------------------------------------------------


def test_settings_explain_defaults_to_assist(monkeypatch):
    for name in ("EXPLAIN_URL", "EXPLAIN_MODEL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ASSIST_URL", "http://assist.example/v1")
    monkeypatch.setenv("ASSIST_MODEL", "assist-y")
    s = get_settings()
    assert (s.explain_url, s.explain_model) == ("http://assist.example/v1", "assist-y")
    monkeypatch.setenv("EXPLAIN_URL", "http://explain.example/v1")
    monkeypatch.setenv("EXPLAIN_MODEL", "explain-z")
    s = get_settings()
    assert (s.explain_url, s.explain_model) == ("http://explain.example/v1", "explain-z")


def test_explain_uses_explain_role(monkeypatch):
    monkeypatch.setenv("ASSIST_URL", "http://assist.example/v1")
    monkeypatch.setenv("ASSIST_MODEL", "assist-y")
    monkeypatch.setenv("EXPLAIN_URL", "http://explain.example/v1")
    monkeypatch.setenv("EXPLAIN_MODEL", "explain-z")
    seen = {}

    def _fake(self, base_url, model, messages, max_tokens=512):
        seen.update(base_url=base_url, model=model, max_tokens=max_tokens,
                    timeout_s=self._timeout_s)
        return '{"stats": {}, "recommendation": "visual_check"}'

    monkeypatch.setattr(VLLMClient, "_chat_once", _fake)
    parsed, latency_ms = VLLMClient(settings=get_settings()).explain(
        [{"role": "user", "content": "q"}]
    )
    assert parsed == {"stats": {}, "recommendation": "visual_check"}
    assert latency_ms >= 0
    assert seen == {
        "base_url": "http://explain.example/v1",
        "model": "explain-z",
        "max_tokens": 700,
        "timeout_s": pipeline.EXPLAIN_TIMEOUT_S,
    }


def test_fold_system_messages_merges_into_first_user_turn():
    folded = pipeline._fold_system_messages(
        [
            {"role": "system", "content": "Rules."},
            {"role": "user", "content": "Stats."},
            {"role": "assistant", "content": "x"},
            {"role": "user", "content": "Again."},
        ]
    )
    assert folded == [
        {"role": "user", "content": "Rules.\n\nStats."},
        {"role": "assistant", "content": "x"},
        {"role": "user", "content": "Again."},
    ]
    assert pipeline._fold_system_messages([{"role": "system", "content": "Only."}]) == [
        {"role": "user", "content": "Only."}
    ]
    plain = [{"role": "user", "content": "Hi."}]
    assert pipeline._fold_system_messages(plain) == plain


def test_explain_sends_no_system_role(monkeypatch):
    sent: list = []

    def _fake(self, base_url, model, messages, max_tokens=512):
        sent.extend(messages)
        return '{"stats": {}, "recommendation": "visual_check"}'

    monkeypatch.setattr(VLLMClient, "_chat_once", _fake)
    VLLMClient(settings=get_settings()).explain(
        [{"role": "system", "content": "Rules."}, {"role": "user", "content": "Stats."}]
    )
    assert [m["role"] for m in sent] == ["user"]
    assert sent[0]["content"] == "Rules.\n\nStats."
