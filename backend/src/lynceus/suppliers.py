"""Supplier scorecard and risk-based lab sampling, computed from the ledger.

Every figure comes from completed inspection records (``inputs.supplier``,
verdict, gates, weight) and their sealed follow-ups
(:func:`lynceus.followups.ledger_row`); nothing is stored separately.  A
missing or blank supplier is ``"unknown"``.  Names match ignoring case,
punctuation and spacing ("PT. Hijau Lestari" is "pt hijau lestari").

Counts per supplier:

* ``hard_contaminant_loads``: REJECT verdicts that name a hard contaminant.
* ``declaration_conflicts``: records whose ``manifest_crosscheck`` gate
  (the declaration check, "Waybill vs load") FAILED.
* ``reviews``: records with a supervisor resolution; ``overrides``: the
  latest resolution disagrees with an ACCEPT or REJECT verdict.
* ``spec_breaches``: lab samples with a refusal or penalty breach of the
  example contract (warnings excluded); ``deductions_idr`` sums their
  contract deductions; ``breach_fees_idr`` is the example flat fee per
  declared-sorted load that carried a hard contaminant.
* ``net_t``: weighbridge net of every truck, in tonnes.
* ``risk_score = (rejected + 0.5 x escalated) / trucks``, 2 dp: the shift
  report's formula, so a supplier flagged there is high risk here.

Tier rules, checked in this order (:data:`TIER_RULES` states them for
``GET /contract``):

1. ``new``: fewer than 3 trucks; sample every 3rd truck.
2. ``high``: a hard contaminant in the last 10 trucks, or risk score >= 0.34,
   or a lab spec breach in the last 5 samples; sample every truck.
3. ``medium``: risk score >= 0.10, or a declaration conflict in the last 10
   trucks, or any older lab spec breach; sample every 3rd truck.
4. ``low``: none of the above; sample every 10th truck.

:func:`sampling_for` is deterministic: a truck whose waybill declares
moisture above the contract spec is always sampled (the price must be
settled on a lab value); so is a high-risk supplier's truck; otherwise truck
``k`` (the supplier's ``k``-th, counting this one) is sampled when
``k % every_n == 0``.
"""

from __future__ import annotations

import math
import os
import re
import threading
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from lynceus import audit, contracts, followups, shift

__all__ = [
    "TIER_RULES",
    "SAMPLING_EVERY",
    "ledger_rows",
    "supplier_key",
    "profiles",
    "profile",
    "sampling_for",
    "clear_cache",
]

NEW_MIN_TRUCKS = 3
RECENT_TRUCKS = 10
RECENT_SAMPLES = 5
HIGH_RISK = shift.FLAG_MIN_RISK
MEDIUM_RISK = 0.10

SAMPLING_EVERY = {"high": 1, "medium": 3, "low": 10, "new": 3}

TIER_RULES: List[Dict[str, Any]] = [
    {"tier": "new", "every_n": 3, "rule": "Fewer than 3 trucks on record."},
    {
        "tier": "high", "every_n": 1,
        "rule": (
            "A hard contaminant in the last 10 trucks, or risk score 0.34 or more, "
            "or a lab spec breach in the last 5 samples."
        ),
    },
    {
        "tier": "medium", "every_n": 3,
        "rule": (
            "Risk score 0.10 or more, or a declaration conflict in the last 10 "
            "trucks, or an older lab spec breach."
        ),
    },
    {"tier": "low", "every_n": 10, "rule": "None of the above."},
]
RISK_FORMULA = "risk score = (rejected + 0.5 x held) / trucks, as on the shift report"


def supplier_key(name: Optional[str]) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).strip()


def _label(every_n: int) -> str:
    return "Every truck sampled" if every_n == 1 else f"1 in {every_n} sampled"


# ---------------------------------------------------------------------------
# Ledger scan with an mtime-keyed cache
# ---------------------------------------------------------------------------

#: record dir -> (signature, ledger row or None for a non-completed record).
_CACHE: Dict[str, tuple] = {}
_CACHE_LOCK = threading.Lock()


def clear_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()


def _signature(record_dir: Path) -> Optional[tuple]:
    try:
        st = (record_dir / audit.RECORD_FILENAME).stat()
    except OSError:
        return None
    parts: List[tuple] = [(st.st_mtime_ns, st.st_size)]
    folder = record_dir / followups.FOLLOWUPS_DIRNAME
    if folder.is_dir():
        with os.scandir(folder) as entries:
            for entry in sorted(entries, key=lambda e: e.name):
                if entry.is_file():
                    fst = entry.stat()
                    parts.append((entry.name, fst.st_mtime_ns, fst.st_size))
    return tuple(parts)


def _row(record_dir: Path) -> Optional[Dict[str, Any]]:
    try:
        record = audit.load_record(record_dir / audit.RECORD_FILENAME)
    except audit.AuditError:
        return None
    if record.execution_status != audit.ExecutionStatus.COMPLETED:
        return None
    chain, _problems = followups.read_chain(record_dir.parent, record.record_id)
    return followups.ledger_row(record, chain)


def ledger_rows(storage_dir: "str | os.PathLike[str]") -> List[Dict[str, Any]]:
    """Ledger rows (:func:`lynceus.followups.ledger_row`) of every completed
    record, in arrival order; cached per record by file mtimes."""
    storage = Path(storage_dir)
    if not storage.is_dir():
        return []
    rows: List[Dict[str, Any]] = []
    for entry in storage.iterdir():
        if not entry.is_dir() or not audit.INSPECTION_DIR_RE.match(entry.name):
            continue
        signature = _signature(entry)
        if signature is None:
            continue
        cache_key = str(entry.resolve())
        with _CACHE_LOCK:
            hit = _CACHE.get(cache_key)
        if hit is not None and hit[0] == signature:
            row = hit[1]
        else:
            row = _row(entry)
            with _CACHE_LOCK:
                _CACHE[cache_key] = (signature, row)
        if row is not None:
            rows.append(row)
    rows.sort(key=lambda r: (r["started_at_utc"], r["record_id"]))
    return rows


# ---------------------------------------------------------------------------
# Profiles
# ---------------------------------------------------------------------------


def _avg(values: List[float]) -> Optional[float]:
    return round(sum(values) / len(values), 2) if values else None


def _breach(lab: Dict[str, Any]) -> bool:
    """A refusal or penalty breach (a warning is not a spec breach)."""
    return any(b["severity"] != "warning" for b in lab["contract_eval"]["breaches"])


def _tier(rows: List[Dict[str, Any]], labs: List[Dict[str, Any]], risk: float) -> tuple[str, str]:
    trucks = len(rows)
    if trucks < NEW_MIN_TRUCKS:
        return "new", f"New supplier: {trucks} truck(s) on record, fewer than {NEW_MIN_TRUCKS}."
    recent = rows[-RECENT_TRUCKS:]
    recent_hard = sum(1 for r in recent if r["hard_contaminant_load"])
    recent_labs = labs[-RECENT_SAMPLES:]
    recent_breaches = sum(1 for lab in recent_labs if _breach(lab))
    reasons = []
    if recent_hard:
        reasons.append(f"hard contaminant in {recent_hard} of the last {len(recent)} trucks")
    if risk >= HIGH_RISK:
        reasons.append(f"risk score {risk:.2f}")
    if recent_breaches:
        reasons.append(f"lab spec breach in {recent_breaches} of the last {len(recent_labs)} samples")
    if reasons:
        return "high", "High risk: " + "; ".join(reasons) + "."
    recent_conflicts = sum(1 for r in recent if r["declaration_conflict"])
    if risk >= MEDIUM_RISK:
        reasons.append(f"risk score {risk:.2f}")
    if recent_conflicts:
        reasons.append(f"declaration conflict in {recent_conflicts} of the last {len(recent)} trucks")
    if any(_breach(lab) for lab in labs):
        reasons.append("an older lab spec breach")
    if reasons:
        return "medium", "Medium risk: " + "; ".join(reasons) + "."
    return "low", (
        f"Low risk: no hard contaminant in the last {len(recent)} trucks, "
        f"risk score {risk:.2f}, no recent lab breach."
    )


def _profile(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    labs = [lab for r in rows for lab in r["labs"]]
    trucks = len(rows)
    rejected = sum(1 for r in rows if r["decision"] == audit.Decision.REJECT)
    escalated = sum(1 for r in rows if r["decision"] == audit.Decision.ESCALATE_HUMAN)
    risk = shift.risk_score(trucks, rejected, escalated)
    tier, reason = _tier(rows, labs, risk)
    every_n = SAMPLING_EVERY[tier]
    return {
        "supplier": rows[-1]["supplier"],
        "trucks": trucks,
        "accepted": sum(1 for r in rows if r["decision"] == audit.Decision.ACCEPT),
        "escalated": escalated,
        "rejected": rejected,
        "hard_contaminant_loads": sum(1 for r in rows if r["hard_contaminant_load"]),
        "declaration_conflicts": sum(1 for r in rows if r["declaration_conflict"]),
        "reviews": sum(1 for r in rows if r["reviewed"]),
        "overrides": sum(1 for r in rows if r["overridden"]),
        "lab_samples": len(labs),
        "avg_moisture_pct": _avg([lab["moisture_pct"] for lab in labs]),
        "avg_ncv_mj_kg": _avg([lab["ncv_mj_kg"] for lab in labs]),
        "avg_chlorine_pct": _avg([lab["chlorine_pct"] for lab in labs]),
        "spec_breaches": sum(r["spec_breach_samples"] for r in rows),
        "deductions_idr": sum(r["deductions_idr"] for r in rows),
        "breach_fees_idr": sum(r["breach_fee_idr"] for r in rows),
        "net_t": round(sum(r["net_kg"] for r in rows) / 1000.0, 2),
        "risk_score": risk,
        "tier": tier,
        "tier_reason": reason,
        "sampling": {"every_n": every_n, "label": _label(every_n)},
        "last_seen_utc": rows[-1]["started_at_utc"],
    }


def _grouped(
    storage_dir: "str | os.PathLike[str]", exclude_record_id: Optional[str]
) -> Dict[str, List[Dict[str, Any]]]:
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for row in ledger_rows(storage_dir):
        if row["record_id"] == exclude_record_id:
            continue
        groups.setdefault(supplier_key(row["supplier"]), []).append(row)
    return groups


def profiles(
    storage_dir: "str | os.PathLike[str]", *, exclude_record_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Every supplier's profile, riskiest first."""
    out = [_profile(rows) for rows in _grouped(storage_dir, exclude_record_id).values()]
    out.sort(key=lambda p: (-p["risk_score"], -p["trucks"], p["supplier"]))
    return out


def profile(
    storage_dir: "str | os.PathLike[str]",
    name: Optional[str],
    *,
    exclude_record_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """One supplier's profile, or ``None`` when it has no completed record."""
    key = supplier_key(name)
    if not key:
        return None
    rows = _grouped(storage_dir, exclude_record_id).get(key)
    return _profile(rows) if rows else None


def _declared_moisture(declared: Optional[Mapping[str, Any]]) -> Optional[float]:
    value = (declared or {}).get("moisture_pct")
    if isinstance(value, dict):  # a {value, confidence} read field
        value = value.get("value")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def sampling_for(
    storage_dir: "str | os.PathLike[str]",
    supplier: Optional[str],
    declared: Optional[Mapping[str, Any]] = None,
    *,
    exclude_record_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Whether this supplier's next truck gets a risk-based lab sample.

    ``declared`` is the waybill's field values: a declared moisture above
    the contract spec is sampled whatever the tier, because the price must
    be settled on a lab value.  Counts only completed records, so call it
    before the current record is sealed, or pass ``exclude_record_id`` for
    the current truck.
    """
    prof = profile(storage_dir, supplier, exclude_record_id=exclude_record_id)
    if prof is None:
        tier, trucks_so_far = "new", 0
        reason = "New supplier: no completed truck on record yet."
    else:
        tier, trucks_so_far, reason = prof["tier"], prof["trucks"], prof["tier_reason"]
    every_n = SAMPLING_EVERY[tier]
    nth = trucks_so_far + 1
    moisture = _declared_moisture(declared)
    spec = contracts.SPECS["moisture_pct_max"]
    if moisture is not None and moisture > spec:
        return {
            "sample_this_truck": True,
            "tier": tier,
            "label": _label(every_n),
            "reason": (
                f"Declared moisture {moisture:g} % is above the {spec:g} % contract "
                "spec: sample to settle the price (SOP-RDF-5.4)."
            ),
        }
    sample = tier == "high" or nth % every_n == 0
    if tier == "high":
        reason += " Sample every truck (SOP-RDF-5.4)."
    elif sample:
        reason += f" Truck {nth} from this supplier is the 1 in {every_n} sample (SOP-RDF-5.4)."
    else:
        due = nth + (every_n - nth % every_n)
        reason += f" Next lab sample at truck {due} from this supplier."
    return {
        "sample_this_truck": sample,
        "tier": tier,
        "label": _label(every_n),
        "reason": reason,
    }
