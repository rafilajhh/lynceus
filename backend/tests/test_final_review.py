"""Whole-branch final-review fixes: Retry-After safety, fail-closed unreachable
live endpoint, and the live-concurrency cap.  Offline: fakes and monkeypatch only.
"""

from __future__ import annotations

import base64
import contextlib
import threading

import pytest
from fastapi.testclient import TestClient

from lynceus import pipeline
from lynceus.api import create_app
from lynceus.config import LYNCEUS_STORAGE_DIR_ENV, get_settings

# ---------------------------------------------------------------------------
# Retry-After: HTTP-date / garbage / huge values must not crash or hang
# ---------------------------------------------------------------------------


class _Resp:
    def __init__(self, status_code, headers):
        self.status_code = status_code
        self.headers = headers


def _client_with_429(monkeypatch, retry_after):
    headers = {} if retry_after is None else {"retry-after": retry_after}
    monkeypatch.setattr(
        pipeline.httpx,
        "stream",
        lambda *a, **k: contextlib.nullcontext(_Resp(429, headers)),
    )
    return pipeline.VLLMClient(settings=get_settings())


@pytest.mark.parametrize(
    "header, expected",
    [
        ("2", 2.0),
        ("0", 0.0),
        ("-5", 0.0),
        ("Wed, 21 Oct 2026 07:28:00 GMT", 1.0),  # HTTP-date: not seconds
        ("soon", 1.0),
        ("nan", 1.0),
        (None, 1.0),
    ],
)
def test_retry_after_is_parsed_safely(monkeypatch, header, expected):
    client = _client_with_429(monkeypatch, header)
    with pytest.raises(pipeline._RateLimitedError) as err:
        client._chat_once("http://x/v1", "m", [])
    assert err.value.retry_after == expected


def test_retry_after_http_date_does_not_raise_value_error_and_waits_1s(monkeypatch):
    client = _client_with_429(monkeypatch, "Wed, 21 Oct 2026 07:28:00 GMT")
    sleeps = []
    monkeypatch.setattr(pipeline.time, "sleep", sleeps.append)
    with pytest.raises(ValueError, match="rate-limited after 3 attempts"):
        client._chat("http://x/v1", "m", [])
    assert len(sleeps) == 2 and all(1.0 <= s <= 2.0 for s in sleeps)


def test_retry_after_over_10s_gives_up_immediately(monkeypatch):
    client = _client_with_429(monkeypatch, "3600")
    sleeps = []
    monkeypatch.setattr(pipeline.time, "sleep", sleeps.append)
    with pytest.raises(ValueError, match="rate-limited"):
        client._chat("http://x/v1", "m", [])
    assert sleeps == []


def test_retry_after_within_cap_still_sleeps(monkeypatch):
    client = _client_with_429(monkeypatch, "10")
    sleeps = []
    monkeypatch.setattr(pipeline.time, "sleep", sleeps.append)
    with pytest.raises(ValueError, match="rate-limited after 3 attempts"):
        client._chat("http://x/v1", "m", [])
    assert len(sleeps) == 2 and all(10.0 <= s <= 11.0 for s in sleeps)
