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
        ("Wed, 21 Oct 2015 07:28:00 GMT", 0.0),
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


def test_retry_after_past_http_date_retries_without_date_delay(monkeypatch):
    client = _client_with_429(monkeypatch, "Wed, 21 Oct 2015 07:28:00 GMT")
    sleeps = []
    monkeypatch.setattr(pipeline.time, "sleep", sleeps.append)
    with pytest.raises(ValueError, match="rate-limited after 3 attempts"):
        client._chat("http://x/v1", "m", [])
    assert sleeps == [0.25, 0.5]


def test_retry_after_over_10s_waits_only_at_cap(monkeypatch):
    client = _client_with_429(monkeypatch, "3600")
    sleeps = []
    monkeypatch.setattr(pipeline.time, "sleep", sleeps.append)
    with pytest.raises(ValueError, match="rate-limited"):
        client._chat("http://x/v1", "m", [])
    assert sleeps == [10.0, 10.0]


def test_retry_after_within_cap_still_sleeps(monkeypatch):
    client = _client_with_429(monkeypatch, "10")
    sleeps = []
    monkeypatch.setattr(pipeline.time, "sleep", sleeps.append)
    with pytest.raises(ValueError, match="rate-limited after 3 attempts"):
        client._chat("http://x/v1", "m", [])
    assert sleeps == [10.0, 10.0]


# ---------------------------------------------------------------------------
# Fail-closed: unreachable live endpoint never yields a scripted verdict
# ---------------------------------------------------------------------------

_JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
#: A real upload / "Run live" request: no demo_case.
_LIVE_REQ = {
    "truck_id": "B-9174-KT",
    "photo_base64": base64.b64encode(_JPEG).decode("ascii"),
    "photo_filename": "metal.jpg",
    "manifest_text": "Declared weight: 18,400 kg. Moisture declared: 10% (dry).",
    "weight_kg": 18500,
    "waste_stream": "rdf-feedstock",
    "moisture": 0.095,
    "age_h": 5,
}


@pytest.fixture()
def unreachable(tmp_path, monkeypatch):
    monkeypatch.setenv(LYNCEUS_STORAGE_DIR_ENV, str(tmp_path))
    monkeypatch.setattr(pipeline, "_vlm_reachable", lambda *a, **k: False)
    return tmp_path


def test_unreachable_live_with_fallback_disabled_is_503_and_no_record(
    unreachable, monkeypatch
):
    monkeypatch.setenv("LYNCEUS_ALLOW_STUB_FALLBACK", "0")
    resp = TestClient(create_app()).post("/inspect", json=_LIVE_REQ)
    assert resp.status_code == 503, resp.text
    assert resp.json()["detail"]["error"] == "live_ai_unavailable"
    assert "verdict" not in resp.json()
    # Not even an in_progress shell: nothing was begun, nothing claims a verdict.
    assert list(unreachable.glob("inspection-*")) == []


def test_unreachable_live_with_fallback_allowed_is_labelled_fallback(
    unreachable, monkeypatch
):
    monkeypatch.setenv("LYNCEUS_ALLOW_STUB_FALLBACK", "1")
    resp = TestClient(create_app()).post("/inspect", json=_LIVE_REQ)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["provenance"] == "stub_fallback_live_error"
    assert "unreachable" in body["verdict"]["uncertainty"]


def test_demo_case_stays_plain_scripted_stub(unreachable, monkeypatch):
    monkeypatch.setenv("LYNCEUS_ALLOW_STUB_FALLBACK", "0")
    resp = TestClient(create_app()).post(
        "/inspect", json={**_LIVE_REQ, "demo_case": "red"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["provenance"] == "stub"


def test_resolve_clients_unreachable_variants(monkeypatch):
    monkeypatch.setattr(pipeline, "_vlm_reachable", lambda *a, **k: False)
    monkeypatch.setenv("LYNCEUS_ALLOW_STUB_FALLBACK", "1")
    clients = pipeline.resolve_clients({}, get_settings())
    assert clients.provenance == "stub_fallback_live_error"
    assert isinstance(clients, pipeline.StubAIClients)
    assert clients.fallback_reason is not None
    assert "unreachable" in clients.fallback_reason
    out = pipeline.run_inspection({"photo_base64": "x"}, clients)
    assert out["provenance"] == "stub_fallback_live_error"
    assert "unreachable" in out["fallback_reason"]
    monkeypatch.setenv("LYNCEUS_ALLOW_STUB_FALLBACK", "0")
    with pytest.raises(pipeline.LiveAIUnavailableError):
        pipeline.resolve_clients({}, get_settings())
    assert pipeline.resolve_clients({"demo_case": "red"}, get_settings()).provenance == "stub"


def test_probe_treats_read_timeout_as_reachable(monkeypatch):
    def slow(*a, **k):
        raise pipeline.httpx.ReadTimeout("slow /models")

    monkeypatch.setattr(pipeline.httpx, "get", slow)
    assert pipeline._vlm_reachable(get_settings()) is True

    def refused(*a, **k):
        raise pipeline.httpx.ConnectError("refused")

    monkeypatch.setattr(pipeline.httpx, "get", refused)
    assert pipeline._vlm_reachable(get_settings()) is False


# ---------------------------------------------------------------------------
# Ruling 40: at most 2 concurrent LIVE inspections; supplier length cap
# ---------------------------------------------------------------------------


def test_third_concurrent_live_inspection_is_busy_and_demo_is_never_blocked(
    tmp_path, monkeypatch
):
    monkeypatch.setenv(LYNCEUS_STORAGE_DIR_ENV, str(tmp_path))
    monkeypatch.setattr(
        pipeline, "resolve_clients",
        lambda payload, settings=None: pipeline.StubAIClients(
            demo_case=payload.get("demo_case")
        ),
    )
    real_run = pipeline.run_inspection
    entered = threading.Semaphore(0)
    release = threading.Event()

    def blocking_run(payload, ai_clients, *args, **kwargs):
        if not payload.get("demo_case"):
            entered.release()
            assert release.wait(timeout=20)
        return real_run(payload, ai_clients, *args, **kwargs)

    monkeypatch.setattr(pipeline, "run_inspection", blocking_run)
    client = TestClient(create_app())
    results: list[int] = []

    def live():
        results.append(client.post("/inspect", json=_LIVE_REQ).status_code)

    workers = [threading.Thread(target=live) for _ in range(2)]
    for w in workers:
        w.start()
    try:
        for _ in range(2):  # both live requests are now inside the pipeline
            assert entered.acquire(timeout=20)
        before = sorted(p.name for p in tmp_path.glob("inspection-*"))
        assert len(before) == 2

        busy = client.post("/inspect", json=_LIVE_REQ)
        assert busy.status_code == 503, busy.text
        detail = busy.json()["detail"]
        assert detail["error"] == "busy"
        assert detail["message"] == (
            "The live AMD pipeline is busy \u2014 try again in a moment or use a scripted case."
        )
        assert sorted(p.name for p in tmp_path.glob("inspection-*")) == before

        demo = client.post("/inspect", json={"demo_case": "green", "weight_kg": 5000})
        assert demo.status_code == 200, demo.text
    finally:
        release.set()
        for w in workers:
            w.join(timeout=30)
    assert results == [200, 200]

    # Slots were released in finally: a live request is admitted again.
    again = client.post("/inspect", json=_LIVE_REQ)
    assert again.status_code == 200, again.text


def test_live_slot_is_released_when_the_inspection_fails(tmp_path, monkeypatch):
    monkeypatch.setenv(LYNCEUS_STORAGE_DIR_ENV, str(tmp_path))
    monkeypatch.setenv("LYNCEUS_ALLOW_STUB_FALLBACK", "0")
    monkeypatch.setattr(pipeline, "_vlm_reachable", lambda *a, **k: False)
    client = TestClient(create_app())
    for _ in range(5):  # more failures than slots: each must give its slot back
        assert client.post("/inspect", json=_LIVE_REQ).status_code == 503


def test_supplier_longer_than_120_chars_is_422(tmp_path, monkeypatch):
    monkeypatch.setenv(LYNCEUS_STORAGE_DIR_ENV, str(tmp_path))
    client = TestClient(create_app())
    ok = client.post("/inspect", json={"demo_case": "green", "supplier": "S" * 120})
    assert ok.status_code == 200, ok.text
    bad = client.post("/inspect", json={"demo_case": "green", "supplier": "S" * 121})
    assert bad.status_code == 422


def test_id_allocation_race_loser_takes_the_next_number(tmp_path, monkeypatch):
    """Two concurrent inspections scan the same directory listing: the mkdir
    loser must rescan and take the next number instead of failing with a 500."""
    from pathlib import Path

    from lynceus import audit

    (tmp_path / "inspection-000001").mkdir()
    real_iterdir = Path.iterdir
    calls = {"n": 0}

    def stale_first_scan(self):
        calls["n"] += 1
        if calls["n"] == 1:
            return iter([])  # the scan raced: inspection-000001 not yet visible
        return real_iterdir(self)

    monkeypatch.setattr(Path, "iterdir", stale_first_scan)
    record_id, path = audit.allocate_inspection_id(tmp_path)
    assert record_id == "inspection-000002" and path.is_dir()
