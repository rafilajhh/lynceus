"""Kiln intake and carbon: what the accepted alternative fuel brings to the kiln.

Both views are computed from the ledger (completed records plus sealed
follow-ups, :func:`lynceus.suppliers.ledger_rows`); nothing is stored.

Accepted load: an ACCEPT verdict, or any verdict whose latest supervisor
resolution is ``accept`` or ``sort_then_accept`` (the load was tipped).

Quality per accepted load, first available (``method`` on each row):

1. ``lab``: the load's own (latest) lab result.
2. ``supplier_average``: the mean of the supplier's last
   :data:`ROLLING_SAMPLES` lab results up to that truck.
3. ``contract_spec``: the example contract's spec values (NCV minimum,
   moisture and chlorine maximum): the worst load the contract accepts.

Then, per load: energy ``GJ = net t x NCV`` (NCV as received, MJ/kg = GJ/t);
dry tonnes ``= net t x (1 - moisture)``; chlorine ``kg = dry t x Cl % x 10``.
Carbon follows the GCCA / CSI cement CO2 protocol: biomass CO2 is climate
neutral (a memo item), fossil CO2 from the fuel counts in gross emissions,
and the coal it replaces is the displaced CO2.  Every assumption (chlorine
budget, biogenic share, emission factors) is configuration and labelled.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from lynceus import audit, contracts, suppliers

__all__ = [
    "WINDOWS",
    "CHLORINE_BUDGET_KG_PER_SHIFT",
    "BIOGENIC_SHARE",
    "kiln_intake",
    "carbon",
]

#: Window name -> hours back from ``now``; ``None`` means the whole ledger.
WINDOWS: Dict[str, Optional[float]] = {"shift": 8.0, "day": 24.0, "all": None}
SHIFT_HOURS = 8.0
ROLLING_SAMPLES = 5

#: Example plant chlorine budget per 8 h shift, set by the kiln's chlorine
#: bypass capacity; a site sets its own (``LYNCEUS_CL_BUDGET_KG_PER_SHIFT``).
#: 3,000 kg is about 500 t of RDF a shift at 0.7 % dry chlorine.
CHLORINE_BUDGET_ENV = "LYNCEUS_CL_BUDGET_KG_PER_SHIFT"
CHLORINE_BUDGET_KG_PER_SHIFT = 3_000.0
CHLORINE_BUDGET_LABEL = "Example plant budget; set per kiln (bypass capacity)"
CHLORINE_WARN_SHARE = 0.8

#: Biogenic share of the RDF's carbon: a default until an ISO 21644 (C-14)
#: result exists for the fuel.
BIOGENIC_SHARE = 0.5
#: IPCC 2006 Guidelines Vol. 2 defaults, t CO2 per TJ.
COAL_CO2_T_PER_TJ = 96.1  # sub-bituminous coal
AF_CO2_T_PER_TJ = 91.7  # non-biomass fraction of municipal waste
CARBON_SOURCES = {
    "protocol": "GCCA / CSI Cement CO2 and Energy Protocol v2.0 "
                "(https://ghgprotocol.org/sites/default/files/co2_CSI_Cement_Protocol-V2.0_0.pdf)",
    "emission_factors": "IPCC 2006 Guidelines, Vol. 2 Energy: sub-bituminous coal 96.1, "
                        "municipal waste (non-biomass fraction) 91.7 t CO2/TJ",
}

_TIPPED = ("accept", "sort_then_accept")


def chlorine_budget_kg_per_shift() -> float:
    """The configured budget, else :data:`CHLORINE_BUDGET_KG_PER_SHIFT`."""
    try:
        value = float(os.environ.get(CHLORINE_BUDGET_ENV, ""))
    except ValueError:
        return CHLORINE_BUDGET_KG_PER_SHIFT
    return value if value > 0 and value != float("inf") else CHLORINE_BUDGET_KG_PER_SHIFT


def _window_bounds(window: str, now: Optional[str]) -> tuple[Optional[str], str]:
    if window not in WINDOWS:
        raise ValueError(f"window must be one of {'|'.join(WINDOWS)} (got {window!r})")
    end = now or audit.now_utc()
    audit.validate_timestamp(end, "now")
    hours = WINDOWS[window]
    if hours is None:
        return None, end
    end_dt = datetime.strptime(end[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    return (end_dt - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ"), end


def _accepted(row: Dict[str, Any]) -> bool:
    resolution = row["resolution"]
    if resolution is not None:
        return resolution["decision"] in _TIPPED
    return row["decision"] == audit.Decision.ACCEPT


def _quality(
    row: Dict[str, Any], history: List[Dict[str, Any]]
) -> tuple[str, Dict[str, float]]:
    keys = ("moisture_pct", "ncv_mj_kg", "chlorine_pct")
    if row["labs"]:
        lab = row["labs"][-1]
        return "lab", {k: float(lab[k]) for k in keys}
    recent = history[-ROLLING_SAMPLES:]
    if recent:
        return "supplier_average", {
            k: round(sum(float(lab[k]) for lab in recent) / len(recent), 2) for k in keys
        }
    spec = contracts.SPECS
    return "contract_spec", {
        "moisture_pct": spec["moisture_pct_max"],
        "ncv_mj_kg": spec["ncv_mj_kg_min"],
        "chlorine_pct": spec["chlorine_pct_max"],
    }


def _intake_rows(
    storage_dir: "str | os.PathLike[str]", since: Optional[str], until: str
) -> List[Dict[str, Any]]:
    history: Dict[str, List[Dict[str, Any]]] = {}
    rows = []
    for row in suppliers.ledger_rows(storage_dir):
        key = suppliers.supplier_key(row["supplier"])
        if row["started_at_utc"] >= until:
            break
        in_window = since is None or row["started_at_utc"] >= since
        if in_window and _accepted(row):
            method, q = _quality(row, history.get(key, []))
            net_t = row["net_kg"] / 1000.0
            dry_t = net_t * (1.0 - q["moisture_pct"] / 100.0)
            rows.append({
                "record_id": row["record_id"],
                "supplier": row["supplier"],
                "started_at_utc": row["started_at_utc"],
                "net_t": round(net_t, 3),
                "dry_t": round(dry_t, 3),
                **q,
                "method": method,
                "energy_gj": round(net_t * q["ncv_mj_kg"], 2),
                "chlorine_kg": round(dry_t * q["chlorine_pct"] * 10.0, 2),
            })
        history.setdefault(key, []).extend(row["labs"])
    return rows


def _weighted(rows: List[Dict[str, Any]], key: str, weight: str) -> Optional[float]:
    total = sum(r[weight] for r in rows)
    if total <= 0:
        return None
    return round(sum(r[key] * r[weight] for r in rows) / total, 2)


def kiln_intake(
    storage_dir: "str | os.PathLike[str]", window: str = "shift", *, now: Optional[str] = None
) -> Dict[str, Any]:
    """Accepted fuel energy and chlorine input over ``window`` ending ``now``.

    ``window`` is ``shift`` (last 8 h), ``day`` (last 24 h) or ``all``;
    anything else raises ``ValueError``.  The chlorine budget scales with the
    window's length (none for ``all``).
    """
    since, until = _window_bounds(window, now)
    rows = _intake_rows(storage_dir, since, until)
    hours = WINDOWS[window]
    per_shift = chlorine_budget_kg_per_shift()
    budget = None if hours is None else per_shift * hours / SHIFT_HOURS
    chlorine_kg = round(sum(r["chlorine_kg"] for r in rows), 1)
    share = None if budget is None else round(chlorine_kg / budget * 100.0, 1)
    if share is None:
        status = None
    elif share >= 100.0:
        status = "over"
    elif share >= CHLORINE_WARN_SHARE * 100.0:
        status = "warn"
    else:
        status = "ok"
    weighted = {
        "moisture_pct": _weighted(rows, "moisture_pct", "net_t"),
        "ncv_mj_kg": _weighted(rows, "ncv_mj_kg", "net_t"),
        "chlorine_pct": _weighted(rows, "chlorine_pct", "dry_t"),
    }
    spec = contracts.SPECS
    methods = {m: sum(1 for r in rows if r["method"] == m)
               for m in ("lab", "supplier_average", "contract_spec")}
    return {
        "window": {"name": window, "since": since, "until": until},
        "trucks_accepted": len(rows),
        "accepted_t": round(sum(r["net_t"] for r in rows), 2),
        "dry_t": round(sum(r["dry_t"] for r in rows), 2),
        "energy_gj": round(sum(r["energy_gj"] for r in rows), 1),
        "chlorine_kg": chlorine_kg,
        "chlorine_budget_kg": budget,
        "chlorine_budget_pct": share,
        "chlorine_status": status,
        "chlorine_budget_note": (
            f"{CHLORINE_BUDGET_LABEL}: {per_shift:g} kg "
            f"chlorine per 8 h shift. Warns at {CHLORINE_WARN_SHARE * 100:g} %."
        ),
        "weighted": weighted,
        "spec": dict(spec),
        "vs_spec": {
            "moisture_pct": None if weighted["moisture_pct"] is None
            else weighted["moisture_pct"] <= spec["moisture_pct_max"],
            "ncv_mj_kg": None if weighted["ncv_mj_kg"] is None
            else weighted["ncv_mj_kg"] >= spec["ncv_mj_kg_min"],
            "chlorine_pct": None if weighted["chlorine_pct"] is None
            else weighted["chlorine_pct"] <= spec["chlorine_pct_max"],
        },
        "methods": methods,
        # Provenance of the estimate, e.g. "Cl from lab on 8 loads, supplier
        # average on 19, contract limit on 4". No Cl per t clinker: Lynceus
        # has no sourced clinker output for the kiln.
        "method_mix": (
            f"Cl from lab on {methods['lab']} load{'' if methods['lab'] == 1 else 's'}, "
            f"supplier average on {methods['supplier_average']}, "
            f"contract limit on {methods['contract_spec']}"
            if rows else "No accepted loads in this window"
        ),
        "rows": rows,
        "notes": [
            "Accepted loads: ACCEPT verdicts, plus loads a supervisor accepted or "
            "sorted then accepted.",
            "Quality per load: its own lab result, else the supplier's average of "
            f"its last {ROLLING_SAMPLES} lab results, else the example contract's "
            "spec limits (the worst load the contract accepts).",
            "Energy = net t x NCV as received; chlorine = dry t x Cl % (dry basis). "
            "Moisture and NCV are weighted by net tonnes, chlorine by dry tonnes.",
            contracts.CONTRACT_NOTE,
        ],
    }


def carbon(
    storage_dir: "str | os.PathLike[str]", window: str = "shift", *, now: Optional[str] = None
) -> Dict[str, Any]:
    """CO2 view of the accepted fuel over ``window`` (GCCA gross / net terms)."""
    intake = kiln_intake(storage_dir, window, now=now)
    tj = intake["energy_gj"] / 1000.0
    coal = tj * COAL_CO2_T_PER_TJ
    total_af = tj * AF_CO2_T_PER_TJ
    fossil = total_af * (1.0 - BIOGENIC_SHARE)
    biogenic = total_af * BIOGENIC_SHARE
    return {
        "window": intake["window"],
        "trucks_accepted": intake["trucks_accepted"],
        "accepted_t": intake["accepted_t"],
        "af_energy_gj": intake["energy_gj"],
        "biogenic_share": BIOGENIC_SHARE,
        "biogenic_share_note": (
            f"Assumption: {BIOGENIC_SHARE:.0%} of the fuel's carbon is biogenic until an "
            "ISO 21644 (C-14) result exists for this fuel."
        ),
        "coal_co2_displaced_t": round(coal, 2),
        "af_fossil_co2_t": round(fossil, 2),
        "af_biogenic_co2_t": round(biogenic, 2),
        "net_co2_avoided_t": round(coal - fossil, 2),
        "gcca": {
            "gross_emissions_from_af_t": round(fossil, 2),
            "biogenic_memo_item_t": round(biogenic, 2),
            "net_co2_avoided_t": round(coal - fossil, 2),
        },
        "tsr": {
            "af_energy_gj": intake["energy_gj"],
            "note": (
                "TSR = alternative-fuel heat / total kiln heat. Lynceus knows the AF "
                "heat only; the kiln's total heat comes from the plant."
            ),
        },
        "factors": {
            "coal_co2_t_per_tj": COAL_CO2_T_PER_TJ,
            "af_co2_t_per_tj": AF_CO2_T_PER_TJ,
        },
        "sources": CARBON_SOURCES,
        "notes": [
            "Biomass CO2 is climate neutral under the GCCA protocol and reported as a "
            "memo item; fossil CO2 from the fuel counts in gross emissions.",
            "Displaced CO2 assumes the fuel replaces sub-bituminous coal heat for heat.",
            "Landfill methane avoided is not included.",
            *intake["notes"][1:3],
        ],
    }
