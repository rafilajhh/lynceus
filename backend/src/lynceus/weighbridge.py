"""Simulated weighbridge indicator feed for the gate demo.

A site reads its scale indicator over RS-232 or Modbus; this demo has no
scale, so :func:`reading` produces a deterministic simulated ticket and says
so in every response (``source: "simulated"`` plus a note).  The audit record
then stamps the weight ``weighbridge_simulated``, never ``weighbridge``.

Determinism: the same plate (and declared net) always gives the same numbers.

* A plate in :data:`DEMO_SCALE_SCENARIOS` uses its scenario: a fixed ticket,
  or a fixed deviation from the declared net.
* Any other plate with a declared net weighs that net times ``(1 + d)``,
  where ``d`` is a per-plate deviation in [-1.5 %, +1.5 %].
* Without a declared net the net is a per-plate value in 8–18 t.

Every weight is rounded to 10 kg, the usual division of a truck scale.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, Optional

from lynceus import audit

#: Scale name shown on the console's weighbridge block.
SCALE_NAME = "Weighbridge A"
#: Stated on every reading so no page can present it as a measured weight.
SIMULATED_NOTE = (
    "Simulated scale feed for the demo; a site reads the indicator over RS-232/Modbus."
)
#: Audit ``inputs.weight.source`` for a weight captured from this feed.
WEIGHT_SOURCE = "weighbridge_simulated"

#: Largest per-plate deviation from the declared net (fraction).
MAX_DEVIATION = 0.015
#: Truck scales weigh in 10 kg divisions.
DIVISION_KG = 10

#: Demo trucks with a scripted ticket.  ``net_kg`` (with ``gross_kg`` /
#: ``tare_kg``) is a fixed ticket; ``deviation`` is applied to the declared net.
DEMO_SCALE_SCENARIOS: Dict[str, Dict[str, Any]] = {
    # The sample waybill's truck: the scale agrees with its waybill exactly.
    "B 9723 KXW": {"gross_kg": 32580, "tare_kg": 16240, "net_kg": 16340},
    # "Wrong truck": arrives carrying B 9723 KXW's waybill (same load);
    # only the plate differs, which the ANPR plate check catches.
    "B 9406 KXW": {"gross_kg": 32580, "tare_kg": 16240, "net_kg": 16340},
    # Short-weight ticket: the scale reads 7.2 % above the waybill.
    "B 9118 TRQ": {"deviation": 0.072},
    # Within tolerance: 0.8 % light.
    "B 9001 RDF": {"deviation": -0.008},
}

_PLATE_RE = re.compile(r"^([A-Z]{1,2})\s*(\d{1,4})\s*([A-Z]{0,3})$")


def normalize_plate(plate: Optional[str]) -> str:
    """Indonesian plate in its printed form: ``"b-9723kxw"`` → ``"B 9723 KXW"``.

    Anything that does not look like a plate is only upper-cased with its
    whitespace collapsed, so foreign or fleet numbers still match themselves.
    """
    text = re.sub(r"[\s\-_.]+", " ", str(plate or "")).strip().upper()
    match = _PLATE_RE.match(text)
    if not match:
        return text
    return " ".join(part for part in match.groups() if part)


def _fraction(plate: str, salt: str) -> float:
    """A stable number in [0, 1) derived from the plate (no randomness)."""
    digest = hashlib.sha256(f"{salt}:{plate}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") / float(1 << 64)


def _round_division(kg: float) -> int:
    return int(round(kg / DIVISION_KG)) * DIVISION_KG


def deviation_for(plate: str) -> float:
    """The per-plate deviation in [-MAX_DEVIATION, +MAX_DEVIATION]."""
    return (2.0 * _fraction(plate, "deviation") - 1.0) * MAX_DEVIATION


def reading(
    plate: str,
    declared_net_kg: Optional[float] = None,
    *,
    read_at_utc: Optional[str] = None,
) -> Dict[str, Any]:
    """One simulated, stable ticket for ``plate``.

    Raises ``ValueError`` for an empty plate or a non-positive declared net.
    """
    normalized = normalize_plate(plate)
    if not normalized:
        raise ValueError("plate must not be empty")
    if declared_net_kg is not None and not declared_net_kg > 0:
        raise ValueError("declared_net_kg must be positive")

    scenario = DEMO_SCALE_SCENARIOS.get(normalized, {})
    tare_kg = scenario.get("tare_kg") or _round_division(
        8000 + _fraction(normalized, "tare") * 8500
    )
    if "net_kg" in scenario:
        net_kg = int(scenario["net_kg"])
    elif declared_net_kg is not None:
        deviation = scenario.get("deviation", deviation_for(normalized))
        net_kg = _round_division(float(declared_net_kg) * (1.0 + deviation))
    else:
        net_kg = _round_division(8000 + _fraction(normalized, "net") * 10000)
    gross_kg = scenario.get("gross_kg") or tare_kg + net_kg
    return {
        "scale": SCALE_NAME,
        "plate": normalized,
        "gross_kg": int(gross_kg),
        "tare_kg": int(tare_kg),
        "net_kg": int(net_kg),
        "stable": True,
        "source": "simulated",
        "read_at_utc": read_at_utc or audit.now_utc(),
        "note": SIMULATED_NOTE,
    }
