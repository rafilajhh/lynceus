"""Offline tests for provider provenance, latency, assist role, concurrency.

Nothing here touches the network: ``VLLMClient._chat_once`` is monkeypatched
and the pipeline concurrency tests use in-process fake clients.
"""

from __future__ import annotations

import json
import time

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
