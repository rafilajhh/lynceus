"""Live gate-gas sensor ingestion — TDLAS-class gate monitors first.

When a real gate gas monitor (e.g. a TDLAS landfill-gas system) exposes an HTTP/JSON gateway, Lynceus reads the *measured* ppm
values directly and stamps ``source: "sentinel_gate_sensor"``.  When no
endpoint is configured (or it is unreachable), the physics digital twin
(:mod:`lynceus.gas_twin`) provides the readings and the record says
``digital_twin`` honestly.

Provenance is stated, never inferred (engine pattern 11): the record
always distinguishes a *measurement* from a *simulation*.

Contract expected from the sensor gateway (``GET {LYNCEUS_GAS_SENSOR_URL}``):

    {
      "readings_ppm": {"ch4": 54.1, "co2": 56.4, "h2s": 0.0039, "tvoc": 0.067},
      "instrument": {"model": "...", "technology": "...", ...},
      "measured_at_utc": "2026-10-13T09:00:00Z"
    }

``readings_ppm`` is the only mandatory key; ``instrument`` (only its string
``model`` / ``technology`` fields are kept) and a valid ISO 8601 UTC
``measured_at_utc`` enrich the audit record when present.  Every reading must be a finite, non-negative number —
anything else rejects the whole payload and the twin takes over.
"""

from __future__ import annotations

import math
import os
from typing import Any, Dict, Optional

import httpx

from lynceus import audit

__all__ = [
    "GAS_SENSOR_URL_ENV",
    "LIVE_GAS_SOURCE",
    "fetch_live_readings",
]

#: Environment variable holding the sensor gateway base URL (empty = twin).
GAS_SENSOR_URL_ENV = "LYNCEUS_GAS_SENSOR_URL"

#: Provenance stamped on readings fetched from a real instrument.
LIVE_GAS_SOURCE = "sentinel_gate_sensor"

_TIMEOUT_S = 5.0

#: Gateway ``instrument`` fields copied into the audit record (strings only).
_INSTRUMENT_FIELDS = ("model", "technology")


def fetch_live_readings(
    settings_url: Optional[str] = None, timeout_s: float = _TIMEOUT_S
) -> Optional[Dict[str, Any]]:
    """Read one set of gas readings from a live gate sensor gateway.

    Returns the gateway payload (with ``source`` set to
    :data:`LIVE_GAS_SOURCE`) or ``None`` when no endpoint is configured
    or the gateway fails — the caller then falls back to the digital
    twin.  A live sensor must never break the inspection: the gas
    channel is a supporting signal.
    """
    url = (settings_url or os.environ.get(GAS_SENSOR_URL_ENV, "")).strip()
    if not url:
        return None
    try:
        response = httpx.get(url.rstrip("/"), timeout=timeout_s)
        response.raise_for_status()
        payload: Dict[str, Any] = response.json()
    except (httpx.HTTPError, httpx.InvalidURL, ValueError):
        # Unreachable gateway, misconfigured URL, non-JSON body, HTTP
        # error — twin takes over.
        return None
    if not isinstance(payload, dict):
        return None
    readings = _clean_readings(payload.get("readings_ppm"))
    if readings is None:
        return None
    # Only whitelisted, well-formed values reach the audit record: a
    # sloppy gateway (NaN, nested junk, wrong types) must never be able
    # to make the record unwritable.
    result: Dict[str, Any] = {"readings_ppm": readings, "source": LIVE_GAS_SOURCE}
    instrument = _clean_instrument(payload.get("instrument"))
    if instrument:
        result["instrument"] = instrument
    measured_at = payload.get("measured_at_utc")
    try:
        result["measured_at_utc"] = audit.validate_timestamp(
            measured_at, "measured_at_utc"
        )
    except audit.AuditError:
        pass
    return result


def _clean_instrument(instrument: Any) -> Dict[str, str]:
    """Keep only the string ``model`` / ``technology`` fields of the block."""
    if not isinstance(instrument, dict):
        return {}
    return {
        key: instrument[key]
        for key in _INSTRUMENT_FIELDS
        if isinstance(instrument.get(key), str)
    }


def _clean_readings(readings: Any) -> Optional[Dict[str, float]]:
    """Coerce gateway readings to floats, or ``None`` if any is unusable."""
    if not isinstance(readings, dict) or not readings:
        return None
    cleaned: Dict[str, float] = {}
    for key, value in readings.items():
        if isinstance(value, bool):
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(number) or number < 0:
            return None
        cleaned[str(key)] = number
    return cleaned
