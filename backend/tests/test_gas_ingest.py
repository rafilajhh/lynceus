"""Live gate-gas sensor ingest (lynceus.gas_ingest) — httpx is mocked."""

from __future__ import annotations

import httpx
import pytest

from lynceus import gas_ingest

URL = "http://gate-sensor.invalid/readings"


class _Resp:
    def __init__(self, body):
        self._body = body

    def raise_for_status(self):
        return None

    def json(self):
        return self._body


def _mock_gateway(monkeypatch, body):
    monkeypatch.setenv(gas_ingest.GAS_SENSOR_URL_ENV, URL)
    monkeypatch.setattr(gas_ingest.httpx, "get", lambda *a, **k: _Resp(body))


@pytest.mark.parametrize(
    "body",
    [
        {"readings_ppm": {"CH4": None}},
        {"readings_ppm": {"CH4": -5}},
        {"readings_ppm": {"CH4": "abc"}},
        {"readings_ppm": {"CH4": True}},
        {"readings_ppm": {"CH4": float("nan")}},
        {"readings_ppm": "x"},
        {"readings_ppm": {}},
        {},
        ["not", "an", "object"],
    ],
)
def test_bad_gateway_payload_returns_none(monkeypatch, body):
    _mock_gateway(monkeypatch, body)
    assert gas_ingest.fetch_live_readings() is None


def test_unreachable_gateway_returns_none(monkeypatch):
    monkeypatch.setenv(gas_ingest.GAS_SENSOR_URL_ENV, URL)

    def boom(*a, **k):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(gas_ingest.httpx, "get", boom)
    assert gas_ingest.fetch_live_readings() is None


def test_unset_url_returns_none(monkeypatch):
    monkeypatch.delenv(gas_ingest.GAS_SENSOR_URL_ENV, raising=False)

    def must_not_be_called(*a, **k):
        raise AssertionError("no URL configured: httpx must not be called")

    monkeypatch.setattr(gas_ingest.httpx, "get", must_not_be_called)
    assert gas_ingest.fetch_live_readings() is None


def test_good_payload_stamped(monkeypatch):
    _mock_gateway(
        monkeypatch,
        {
            "readings_ppm": {"ch4": 54, "co2": "56.4", "h2s": 0.0039},
            "instrument": {"model": "gateway-x"},
        },
    )
    out = gas_ingest.fetch_live_readings()
    assert out["source"] == "sentinel_gate_sensor"
    assert out["readings_ppm"] == {"ch4": 54.0, "co2": 56.4, "h2s": 0.0039}
    assert all(type(v) is float for v in out["readings_ppm"].values())
    assert out["instrument"] == {"model": "gateway-x"}


def test_valid_measured_at_is_kept_invalid_is_dropped(monkeypatch):
    _mock_gateway(
        monkeypatch,
        {"readings_ppm": {"ch4": 1}, "measured_at_utc": "2026-10-13T09:00:00Z"},
    )
    assert gas_ingest.fetch_live_readings()["measured_at_utc"] == "2026-10-13T09:00:00Z"

    _mock_gateway(
        monkeypatch, {"readings_ppm": {"ch4": 1}, "measured_at_utc": "yesterday"}
    )
    assert "measured_at_utc" not in gas_ingest.fetch_live_readings()


def test_non_object_instrument_is_dropped(monkeypatch):
    _mock_gateway(monkeypatch, {"readings_ppm": {"ch4": 1}, "instrument": "x"})
    assert "instrument" not in gas_ingest.fetch_live_readings()
