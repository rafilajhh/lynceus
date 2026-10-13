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

``readings_ppm`` is the only mandatory key; ``instrument`` (an object)
and a valid ISO 8601 UTC ``measured_at_utc`` enrich the audit record
when present.  Every reading must be a finite, non-negative number —
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
    except (httpx.HTTPError, ValueError):
        # Unreachable gateway, non-JSON body, HTTP error — twin takes over.
        return None
    if not isinstance(payload, dict):
        return None
    readings = _clean_readings(payload.get("readings_ppm"))
    if readings is None:
        return None
    result: Dict[str, Any] = dict(payload)
    result["readings_ppm"] = readings
    result["source"] = LIVE_GAS_SOURCE
    # Optional enrichments: keep only well-formed values so a sloppy
    # gateway can never make the audit record undecodable.
    if not isinstance(result.get("instrument"), dict):
        result.pop("instrument", None)
    try:
        audit.validate_timestamp(result.get("measured_at_utc"), "measured_at_utc")
    except audit.AuditError:
        result.pop("measured_at_utc", None)
    return result


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
