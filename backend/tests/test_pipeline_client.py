"""Offline tests for provider provenance, latency, assist role, concurrency.

Nothing here touches the network: ``VLLMClient._chat_once`` is monkeypatched
and the pipeline concurrency tests use in-process fake clients.
"""

from __future__ import annotations

import contextlib
import json
import re
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


def test_vlm_fallback_models_parsed_deduped_and_exclude_primary(monkeypatch):
    monkeypatch.setenv("VLM_MODEL", "vlm-a")
    monkeypatch.setenv("VLM_FALLBACK_MODELS", " vlm-b, vlm-a,,vlm-b , vlm-c")
    assert get_settings().vlm_fallback_models == ("vlm-b", "vlm-c")
    monkeypatch.delenv("VLM_FALLBACK_MODELS")
    assert get_settings().vlm_fallback_models == ()


def test_vlm_falls_back_to_next_model_and_reports_it(monkeypatch):
    # Chain tests count one read per model; votes are covered on their own.
    monkeypatch.setenv("VLM_VOTES", "1")
    monkeypatch.setenv("VLM_MODEL", "vlm-a")
    monkeypatch.setenv("VLM_FALLBACK_MODELS", "vlm-b")
    calls = []

    def _chat_once(self, base_url, model, messages, max_tokens=512):
        calls.append(model)
        if model == "vlm-a":
            raise httpx.HTTPStatusError("503", request=None, response=None)
        return _VLM_JSON

    monkeypatch.setattr(VLLMClient, "_chat_once", _chat_once)
    result = VLLMClient(settings=get_settings()).vlm("aGVsbG8=")
    assert calls == ["vlm-a", "vlm-b"]
    assert result["model"] == result["model_version"] == "vlm-b"
    assert len(result["fallback_from"]) == 1
    assert re.fullmatch(r"vlm-a: HTTPStatusError after \d+\.\d s", result["fallback_from"][0])


class _Clock:
    """A fake ``time.monotonic`` / ``time.perf_counter`` the test advances."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _with_clock(monkeypatch) -> _Clock:
    clock = _Clock()
    monkeypatch.setattr(pipeline.time, "monotonic", clock)
    monkeypatch.setattr(pipeline.time, "perf_counter", clock)
    return clock


def test_vlm_fallback_chain_shares_one_budget_and_times_each_attempt(monkeypatch):
    monkeypatch.setenv("VLM_VOTES", "1")
    monkeypatch.setenv("VLM_MODEL", "vlm-a")
    monkeypatch.setenv("VLM_FALLBACK_MODELS", "vlm-b")
    clock = _with_clock(monkeypatch)
    budgets = []

    def _chat_once(self, base_url, model, messages, max_tokens=512):
        budgets.append((model, self._timeout_s))
        if model == "vlm-a":
            clock.now += 4.0
            raise httpx.HTTPStatusError("500 no available workers", request=None, response=None)
        clock.now += 1.5
        return _VLM_JSON

    monkeypatch.setattr(VLLMClient, "_chat_once", _chat_once)
    result = VLLMClient(settings=get_settings(), timeout_s=10.0).vlm("aGVsbG8=")
    assert budgets == [("vlm-a", 10.0), ("vlm-b", 6.0)]
    assert result["fallback_from"] == ["vlm-a: HTTPStatusError after 4.0 s"]
    assert result["latency_ms"] == pytest.approx(1500.0)  # the answering attempt only


def test_vlm_json_retry_only_gets_what_is_left_of_the_budget(monkeypatch):
    monkeypatch.setenv("VLM_VOTES", "1")
    monkeypatch.setenv("VLM_MODEL", "vlm-a")
    monkeypatch.delenv("VLM_FALLBACK_MODELS", raising=False)
    clock = _with_clock(monkeypatch)
    budgets = []

    def _chat_once(self, base_url, model, messages, max_tokens=512):
        budgets.append(self._timeout_s)
        clock.now += 7.0
        return "not json" if len(budgets) == 1 else _VLM_JSON

    monkeypatch.setattr(VLLMClient, "_chat_once", _chat_once)
    VLLMClient(settings=get_settings(), timeout_s=10.0).vlm("aGVsbG8=")
    assert budgets == [10.0, 3.0]


def test_vlm_unreachable_endpoint_does_not_fall_back(monkeypatch):
    monkeypatch.setenv("VLM_VOTES", "1")
    monkeypatch.setenv("VLM_MODEL", "vlm-a")
    monkeypatch.setenv("VLM_FALLBACK_MODELS", "vlm-b")
    calls = []

    def _down(self, base_url, model, messages, max_tokens=512):
        calls.append(model)
        raise httpx.ConnectError(f"{model}: connection refused")

    monkeypatch.setattr(VLLMClient, "_chat_once", _down)
    with pytest.raises(httpx.ConnectError, match="vlm-a"):
        VLLMClient(settings=get_settings()).vlm("aGVsbG8=")
    assert calls == ["vlm-a"]


def test_vlm_budget_spent_by_the_primary_ends_the_chain(monkeypatch):
    monkeypatch.setenv("VLM_VOTES", "1")
    monkeypatch.setenv("VLM_MODEL", "vlm-a")
    monkeypatch.setenv("VLM_FALLBACK_MODELS", "vlm-b")
    clock = _with_clock(monkeypatch)
    calls = []

    def _chat_once(self, base_url, model, messages, max_tokens=512):
        calls.append(model)
        clock.now += 11.0
        raise httpx.HTTPStatusError("503", request=None, response=None)

    monkeypatch.setattr(VLLMClient, "_chat_once", _chat_once)
    with pytest.raises(pipeline.VisionModelsFailedError) as info:
        VLLMClient(settings=get_settings(), timeout_s=10.0).vlm("aGVsbG8=")
    assert calls == ["vlm-a"]
    assert "vlm-a: HTTPStatusError after 11.0 s" in str(info.value)
    assert "vlm-b: ReadTimeout" in str(info.value)


def test_vlm_every_model_failing_lists_every_attempt(monkeypatch):
    monkeypatch.setenv("VLM_MODEL", "vlm-a")
    monkeypatch.setenv("VLM_FALLBACK_MODELS", "vlm-b")

    def _chat_once(self, base_url, model, messages, max_tokens=512):
        if model == "vlm-a":
            raise httpx.HTTPStatusError("400 model not supported", request=None, response=None)
        raise httpx.ReadTimeout(f"{model} down")

    monkeypatch.setattr(VLLMClient, "_chat_once", _chat_once)
    with pytest.raises(pipeline.VisionModelsFailedError) as info:
        VLLMClient(settings=get_settings()).vlm("aGVsbG8=")
    message = str(info.value)
    assert message.index("vlm-a: HTTPStatusError") < message.index("vlm-b: ReadTimeout")
    assert "model not supported" in message
    assert isinstance(info.value.__cause__, httpx.ReadTimeout)


def test_all_vision_models_failing_surfaces_the_primary_in_fallback_reason(monkeypatch):
    monkeypatch.setenv("VLM_MODEL", "vlm-a")
    monkeypatch.setenv("VLM_FALLBACK_MODELS", "vlm-b")
    monkeypatch.setattr(pipeline, "safe_detect", lambda raw, settings: None)

    def _chat_once(self, base_url, model, messages, max_tokens=512):
        if "image_url" in json.dumps(messages):
            raise httpx.HTTPStatusError(f"{model} 503", request=None, response=None)
        return _LLM_JSON

    monkeypatch.setattr(VLLMClient, "_chat_once", _chat_once)
    out = run_inspection(
        {"photo_base64": "aGVsbG8=", "manifest_text": "x"},
        VLLMClient(settings=get_settings()),
        precomputed_gas=None,
    )
    assert out["provenance"] == "stub_fallback_live_error"
    assert "vlm-a: HTTPStatusError" in out["fallback_reason"]
    assert "vlm-b: HTTPStatusError" in out["fallback_reason"]


def test_vlm_without_fallback_reraises_the_original_error(monkeypatch):
    monkeypatch.setenv("VLM_MODEL", "vlm-a")
    monkeypatch.delenv("VLM_FALLBACK_MODELS", raising=False)

    def _down(self, base_url, model, messages, max_tokens=512):
        raise httpx.ReadTimeout(f"{model} down")

    monkeypatch.setattr(VLLMClient, "_chat_once", _down)
    with pytest.raises(httpx.ReadTimeout, match="vlm-a down"):
        VLLMClient(settings=get_settings()).vlm("aGVsbG8=")


def test_vlm_primary_success_has_no_fallback_marker(monkeypatch):
    monkeypatch.setenv("VLM_MODEL", "vlm-a")
    monkeypatch.setenv("VLM_FALLBACK_MODELS", "vlm-b")
    monkeypatch.setattr(VLLMClient, "_chat_once", lambda self, *a, **k: _VLM_JSON)
    result = VLLMClient(settings=get_settings()).vlm("aGVsbG8=")
    assert result["model"] == "vlm-a"
    assert "fallback_from" not in result


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
    monkeypatch.setenv("VLM_VOTES", "1")  # retries of one read, not of three
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

    def _fake(self, base_url, model, messages, max_tokens=1024):
        seen.append(max_tokens)
        return _VLM_JSON

    monkeypatch.setattr(VLLMClient, "_chat_once", _fake)
    VLLMClient(settings=get_settings()).vlm("aGVsbG8=")
    # vlm() votes over 3 reads; all keep the default 1024 max_tokens —
    # 512 truncated the VLM's JSON (contaminants + several locations boxes)
    # mid-answer and wasted the whole read on the retry path.
    assert seen == [1024, 1024, 1024]


@pytest.mark.parametrize(
    ("raw", "votes"), [(None, 3), ("1", 1), ("3", 3), ("4", 3), ("0", 1), ("9", 3), ("three", 3)]
)
def test_vlm_votes_env_is_clamped(monkeypatch, raw, votes):
    if raw is None:
        monkeypatch.delenv("VLM_VOTES", raising=False)
    else:
        monkeypatch.setenv("VLM_VOTES", raw)
    assert get_settings().vlm_votes == votes


def test_vlm_vote_reads_run_concurrently(monkeypatch):
    monkeypatch.delenv("VLM_FALLBACK_MODELS", raising=False)
    # Sequential reads would never get all three past the barrier.
    barrier = threading.Barrier(3, timeout=5)

    def _fake(self, base_url, model, messages, max_tokens=512):
        barrier.wait()
        return _VLM_JSON

    monkeypatch.setattr(VLLMClient, "_chat_once", _fake)
    result = VLLMClient(settings=get_settings()).vlm("aGVsbG8=")
    assert result["detected"]["contamination"] == "none detected"


def test_vlm_one_failed_vote_fails_the_model_and_falls_back(monkeypatch):
    monkeypatch.setenv("VLM_MODEL", "vlm-a")
    monkeypatch.setenv("VLM_FALLBACK_MODELS", "vlm-b")
    lock = threading.Lock()
    calls: list[str] = []

    def _fake(self, base_url, model, messages, max_tokens=512):
        with lock:
            calls.append(model)
            first_a = calls.count("vlm-a") == 1 and model == "vlm-a"
        if first_a:
            raise httpx.HTTPStatusError("503", request=None, response=None)
        return _VLM_JSON

    monkeypatch.setattr(VLLMClient, "_chat_once", _fake)
    result = VLLMClient(settings=get_settings()).vlm("aGVsbG8=")
    assert result["model"] == "vlm-b"
    assert result["fallback_from"][0].startswith("vlm-a: HTTPStatusError")
    assert calls.count("vlm-a") == 3 and calls.count("vlm-b") == 3


def test_vlm_failed_vote_fails_the_model_without_waiting_for_the_others(monkeypatch):
    monkeypatch.delenv("VLM_FALLBACK_MODELS", raising=False)
    release = threading.Event()
    lock = threading.Lock()
    calls: list[int] = []

    def _fake(self, base_url, model, messages, max_tokens=512):
        with lock:
            calls.append(1)
            first = len(calls) == 1
        if first:
            raise httpx.HTTPStatusError("503", request=None, response=None)
        release.wait(5)  # a slow read: the chain must not wait for it
        return _VLM_JSON

    monkeypatch.setattr(VLLMClient, "_chat_once", _fake)
    started = time.perf_counter()
    try:
        with pytest.raises(httpx.HTTPStatusError):
            VLLMClient(settings=get_settings()).vlm("aGVsbG8=")
        assert time.perf_counter() - started < 2.0
    finally:
        release.set()


def _status_error(status):
    request = httpx.Request("POST", "http://x/v1/chat/completions")
    return httpx.HTTPStatusError(
        f"{status}", request=request, response=httpx.Response(status, request=request)
    )


@pytest.mark.parametrize("status", [401, 403])
def test_refused_key_ends_the_vision_chain(monkeypatch, status):
    # Every model shares the key: a fallback would be refused the same way.
    monkeypatch.setenv("VLM_VOTES", "1")
    monkeypatch.setenv("VLM_MODEL", "vlm-a")
    monkeypatch.setenv("VLM_FALLBACK_MODELS", "vlm-b")
    calls = []

    def _fake(self, base_url, model, messages, max_tokens=512):
        calls.append(model)
        raise _status_error(status)

    monkeypatch.setattr(VLLMClient, "_chat_once", _fake)
    with pytest.raises(httpx.HTTPStatusError):
        VLLMClient(settings=get_settings()).vlm("aGVsbG8=")
    assert calls == ["vlm-a"]


def test_spent_rate_limit_ends_the_vision_chain(monkeypatch):
    monkeypatch.setenv("VLM_VOTES", "1")
    monkeypatch.setenv("VLM_MODEL", "vlm-a")
    monkeypatch.setenv("VLM_FALLBACK_MODELS", "vlm-b")
    calls = []

    def _fake(self, base_url, model, messages, max_tokens=512):
        calls.append(model)
        raise _RateLimitedError(0)

    monkeypatch.setattr(VLLMClient, "_chat_once", _fake)
    with pytest.raises(pipeline.RateLimitSpentError, match="rate-limited"):
        VLLMClient(settings=get_settings()).vlm("aGVsbG8=")
    assert calls == ["vlm-a"] * 3


def test_model_specific_failure_classification():
    assert pipeline._model_specific_failure(_status_error(503))
    assert pipeline._model_specific_failure(_status_error(400))
    assert pipeline._model_specific_failure(
        httpx.HTTPStatusError("503", request=None, response=None)
    )
    assert pipeline._model_specific_failure(ValueError("not JSON"))
    assert not pipeline._model_specific_failure(_status_error(401))
    assert not pipeline._model_specific_failure(pipeline.RateLimitSpentError("429"))
    assert not pipeline._model_specific_failure(httpx.ReadTimeout("slow"))


def test_a_chain_ending_failure_wins_over_a_model_failure_among_votes(monkeypatch):
    # Both reads have failed when the vote looks: a refused key must end the
    # chain even though the other read's 503 alone would move on to vlm-b.
    import concurrent.futures

    monkeypatch.setenv("VLM_VOTES", "2")
    monkeypatch.setenv("VLM_MODEL", "vlm-a")
    monkeypatch.setenv("VLM_FALLBACK_MODELS", "vlm-b")
    monkeypatch.setattr(pipeline, "wait", lambda fs, return_when=None: concurrent.futures.wait(
        fs, return_when=concurrent.futures.ALL_COMPLETED))
    lock = threading.Lock()
    calls: list[str] = []

    def _fake(self, base_url, model, messages, max_tokens=512):
        with lock:
            calls.append(model)
            status = 401 if calls.count(model) == 1 else 503
        raise _status_error(status)

    monkeypatch.setattr(VLLMClient, "_chat_once", _fake)
    for _ in range(5):  # the set order of finished futures must not matter
        calls.clear()
        with pytest.raises(httpx.HTTPStatusError) as info:
            VLLMClient(settings=get_settings()).vlm("aGVsbG8=")
        assert info.value.response.status_code == 401
        assert calls == ["vlm-a", "vlm-a"]


def test_votes_from_code_built_settings_never_exceed_the_read_slots(monkeypatch):
    import dataclasses

    seen = []
    monkeypatch.setattr(VLLMClient, "_chat_once",
                        lambda self, *a, **k: seen.append(1) or _VLM_JSON)
    settings = dataclasses.replace(get_settings(), vlm_votes=9)
    VLLMClient(settings=settings).vlm("aGVsbG8=")
    assert len(seen) == pipeline._VLM_READ_SLOT_COUNT


def test_vote_counts_each_read_once_and_ignores_malformed_entries():
    # One read naming metal twice is still one vote: no majority.
    merged = pipeline._vote_majority(
        [{"hard_contaminants": ["metal", "metal"]}, {"hard_contaminants": []},
         {"hard_contaminants": []}]
    )
    assert merged["hard_contaminants"] == []
    # A non-string (unhashable) entry is ignored instead of crashing the vote.
    merged = pipeline._vote_majority(
        [{"hard_contaminants": [["metal"], "metal"]}, {"hard_contaminants": ["metal"]},
         {"hard_contaminants": [{"x": 1}]}]
    )
    assert merged["hard_contaminants"] == ["metal"]


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


class _LateSlot:
    """An outbound slot that is granted only after ``delay_s`` (the deadline
    has passed by then); counts releases."""

    def __init__(self, delay_s: float) -> None:
        self.delay_s = delay_s
        self.released = 0

    def acquire(self, timeout=None):
        time.sleep(self.delay_s)
        return True

    def release(self):
        self.released += 1


def test_slot_granted_after_deadline_sends_nothing(monkeypatch):
    sent: list = []
    monkeypatch.setattr(pipeline.httpx, "stream", lambda *a, **k: sent.append(k))
    slot = _LateSlot(delay_s=0.1)
    monkeypatch.setattr(pipeline, "_OUTBOUND_SLOTS", slot)
    client = VLLMClient(settings=get_settings(), timeout_s=0.05)
    deadline = time.monotonic() + 0.05
    with pytest.raises(httpx.ReadTimeout):
        client._chat_attempt("http://x/v1", "m", [], 8, deadline)
    assert sent == []  # the request was never sent
    assert slot.released == 1  # and the slot went straight back


def test_request_timeout_is_the_budget_left(monkeypatch):
    seen: list[float] = []

    def transport(*args, **kwargs):
        seen.append(kwargs["timeout"])
        return _streaming_transport(
            lambda: iter([b'data: {"choices": [{"delta": {"content": "y"}}]}\n',
                          b"data: [DONE]\n"])
        )(*args, **kwargs)

    monkeypatch.setattr(pipeline.httpx, "stream", transport)
    monkeypatch.setattr(pipeline, "_OUTBOUND_SLOTS", _LateSlot(delay_s=0.2))
    client = VLLMClient(settings=get_settings(), timeout_s=1.0)
    deadline = time.monotonic() + 1.0
    assert client._chat_attempt("http://x/v1", "m", [], 8, deadline) == "y"
    # 0.2 s of the 1 s budget went on the slot wait: httpx gets the rest,
    # never the full budget. The upper bound leaves room for the ~15 ms
    # resolution of sleep/monotonic on Windows.
    assert 0.5 < seen[0] < 0.9


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
