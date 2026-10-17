"""Control room: the alarm feed and the one-call dashboard summary.

Everything is computed from the ledger (sealed records plus sealed
follow-ups) at request time; nothing is stored.  Alerts are deterministic:
the same ledger and ``now`` always give the same list, ids included.

Alert kinds (:data:`ALERT_RULES`):

* ``chlorine_budget``: the shift's chlorine load at 80 % of the example
  budget (warning) or at 100 % (critical).
* ``supplier_out_of_spec``: a supplier's last 3 lab results all breached
  the contract spec (penalty or refusal; warnings excluded).
* ``hold_unresolved``: a HOLD with no supervisor decision for over 20 min.
* ``declaration_conflict``: waybill declarations that disagreed with the
  load in the last 24 h, one alert per supplier.
* ``reject_unconfirmed``: a REJECT in the last 24 h no human confirmed yet.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from lynceus import audit, contracts, followups, fuel, shift, suppliers

__all__ = ["ALERT_RULES", "HOLD_ALERT_MIN", "alerts", "control_summary"]

HOLD_ALERT_MIN = 20
TREND_LABS = 3
RECENT_HOURS = 24
QUEUE_SIZE = 12
HELD_SIZE = 20
TOP_SUPPLIERS = 6
LAB_TREND_SIZE = 20

ALERT_RULES: List[Dict[str, str]] = [
    {"kind": "chlorine_budget",
     "rule": "Shift chlorine load at 80 % of the example budget (warning) or 100 % (critical)."},
    {"kind": "supplier_out_of_spec",
     "rule": f"A supplier's last {TREND_LABS} lab results all breached the contract spec."},
    {"kind": "hold_unresolved",
     "rule": f"A HOLD with no supervisor decision for over {HOLD_ALERT_MIN} min."},
    {"kind": "declaration_conflict",
     "rule": f"Waybill declarations that disagreed with the load in the last "
             f"{RECENT_HOURS} h, one alert per supplier."},
    {"kind": "reject_unconfirmed",
     "rule": f"A REJECT in the last {RECENT_HOURS} h that no human has confirmed."},
]

_SEVERITY_RANK = {"critical": 0, "warning": 1, "info": 2}


def _dt(value: str) -> datetime:
    return datetime.strptime(value[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)


def _iso(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def _now(now: Optional[str]) -> str:
    end = now or audit.now_utc()
    audit.validate_timestamp(end, "now")
    return end


def _breached(lab: Dict[str, Any]) -> bool:
    return any(b["severity"] != "warning" for b in lab["contract_eval"]["breaches"])


def _open_hold(row: Dict[str, Any]) -> bool:
    return row["decision"] == audit.Decision.ESCALATE_HUMAN and row["resolution"] is None


def _alert(id_: str, severity: str, kind: str, title: str, detail: str, at_utc: str,
           record_id: Optional[str] = None, supplier: Optional[str] = None) -> Dict[str, Any]:
    item: Dict[str, Any] = {"id": id_, "severity": severity, "kind": kind, "title": title,
                            "detail": detail, "at_utc": at_utc}
    if record_id is not None:
        item["record_id"] = record_id
    if supplier is not None:
        item["supplier"] = supplier
    return item


def alerts(
    storage_dir: "str | os.PathLike[str]",
    *,
    now: Optional[str] = None,
    kiln: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """The alarm feed at ``now``: critical first, then newest first.

    ``kiln`` is this shift's :func:`lynceus.fuel.kiln_intake` when the caller
    already has it.
    """
    until = _now(now)
    now_dt = _dt(until)
    recent = _iso(now_dt - timedelta(hours=RECENT_HOURS))
    kiln = kiln if kiln is not None else fuel.kiln_intake(storage_dir, "shift", now=until)
    out: List[Dict[str, Any]] = []

    status = kiln["chlorine_status"]
    if status in ("warn", "over"):
        out.append(_alert(
            f"chlorine_budget:{status}:{kiln['window']['since']}",
            "critical" if status == "over" else "warning",
            "chlorine_budget",
            "Chlorine budget exceeded" if status == "over"
            else f"Chlorine at {kiln['chlorine_budget_pct']:g} % of the shift budget",
            f"{kiln['chlorine_kg']:g} kg of {kiln['chlorine_budget_kg']:g} kg this shift "
            f"({kiln['method_mix']}). {fuel.CHLORINE_BUDGET_LABEL}.",
            until,
        ))

    labs: Dict[str, List[tuple[Dict[str, Any], Dict[str, Any]]]] = {}
    conflicts: Dict[str, List[Dict[str, Any]]] = {}
    for row in suppliers.ledger_rows(storage_dir):
        if row["started_at_utc"] >= until:
            break
        labs.setdefault(suppliers.supplier_key(row["supplier"]), []).extend(
            (row, lab) for lab in row["labs"])
        record_id, supplier = row["record_id"], row["supplier"]
        at = row["finished_at_utc"] or row["started_at_utc"]
        if _open_hold(row):
            age = (now_dt - _dt(at)).total_seconds() / 60.0
            if age > HOLD_ALERT_MIN:
                out.append(_alert(
                    f"hold_unresolved:{record_id}", "warning", "hold_unresolved",
                    f"Hold waiting {age:.0f} min for a supervisor",
                    f"{record_id} from {supplier} has no supervisor decision after "
                    f"{age:.0f} min (alert after {HOLD_ALERT_MIN} min).",
                    at, record_id, supplier,
                ))
        if row["started_at_utc"] < recent:
            continue
        if row["declaration_conflict"]:
            conflicts.setdefault(suppliers.supplier_key(supplier), []).append(row)
        if row["decision"] == audit.Decision.REJECT and row["resolution"] is None:
            out.append(_alert(
                f"reject_unconfirmed:{record_id}", "warning", "reject_unconfirmed",
                "Reject not yet confirmed by a supervisor",
                f"{record_id} from {supplier} was rejected"
                + (f" ({', '.join(row['hard_contaminants'])})" if row["hard_contaminants"] else "")
                + "; no human has confirmed it.",
                at, record_id, supplier,
            ))

    # One alert per supplier, not per truck: the band stays readable.
    for key, items in conflicts.items():
        row = items[-1]
        count = len(items)
        out.append(_alert(
            f"declaration_conflict:{key}", "info", "declaration_conflict",
            f"{row['supplier']}: {count} waybill declaration{'s' if count > 1 else ''} "
            f"disagreed with the load",
            f"In the last {RECENT_HOURS} h: " + ", ".join(r["record_id"] for r in items)
            + f". Latest: {row['record_id']}.",
            row["finished_at_utc"] or row["started_at_utc"], row["record_id"], row["supplier"],
        ))

    for key, items in labs.items():
        last = items[-TREND_LABS:]
        if len(last) == TREND_LABS and all(_breached(lab) for _row, lab in last):
            row = last[-1][0]
            params = sorted({b["param"] for _r, lab in last
                             for b in lab["contract_eval"]["breaches"] if b["severity"] != "warning"})
            out.append(_alert(
                f"supplier_out_of_spec:{key}", "warning", "supplier_out_of_spec",
                f"{row['supplier']} out of spec on the last {TREND_LABS} lab results",
                f"Breached: {', '.join(params)}. Sampling is every truck until it recovers.",
                row["finished_at_utc"] or row["started_at_utc"], row["record_id"], row["supplier"],
            ))

    out.sort(key=lambda a: a["at_utc"], reverse=True)
    out.sort(key=lambda a: _SEVERITY_RANK[a["severity"]])
    return out


# ---------------------------------------------------------------------------
# Dashboard summary
# ---------------------------------------------------------------------------


def _records(storage_dir: "str | os.PathLike[str]") -> List[audit.AuditRecord]:
    records = []
    for entry in audit.list_inspections(storage_dir):
        if not entry.get("ok") or entry.get("execution_status") != audit.ExecutionStatus.COMPLETED:
            continue
        try:
            records.append(audit.load_record(
                Path(storage_dir) / entry["record_id"] / audit.RECORD_FILENAME))
        except audit.AuditError:
            continue
    return records


def _why(record: audit.AuditRecord) -> Optional[str]:
    try:
        from lynceus import checks

        return checks.build_checks(record.model_dump(), None).get("why")
    except Exception:  # noqa: BLE001 - a card never fails on the operator sentence
        return None


def _card(record: audit.AuditRecord, chain: List[Dict[str, Any]]) -> Dict[str, Any]:
    kinds = {f["kind"] for f in chain}
    resolutions = [f["body"]["decision"] for f in chain if f["kind"] == "resolution"]
    finished = record.finished_at_utc
    return {
        "record_id": record.record_id,
        "truck_id": record.inputs.truck_id,
        "supplier": (record.inputs.supplier or "").strip() or "unknown",
        "decision": record.verdict.decision,
        "why": _why(record),
        "at_utc": finished or record.started_at_utc,
        "decision_s": (
            round((_dt(finished) - _dt(record.started_at_utc)).total_seconds(), 1)
            if finished else None
        ),
        "followups": {
            "reviewed": "resolution" in kinds,
            "lab": "lab_result" in kinds,
            "notice": "notice" in kinds,
        },
        "resolution": resolutions[-1] if resolutions else None,
    }


def _lab_trend(rows: List[Dict[str, Any]], until: str) -> Dict[str, Any]:
    points = []
    for row in rows:
        if row["started_at_utc"] >= until:
            break
        for lab in row["labs"]:
            effect = lab["contract_eval"]
            points.append({
                "record_id": row["record_id"],
                "supplier": row["supplier"],
                "at_utc": row["finished_at_utc"] or row["started_at_utc"],
                "moisture_pct": lab["moisture_pct"],
                "ncv_mj_kg": lab["ncv_mj_kg"],
                "chlorine_pct": lab["chlorine_pct"],
                "in_spec": not _breached(lab),
                "tier": effect.get("tier"),
            })
    return {"spec": dict(contracts.SPECS), "points": points[-LAB_TREND_SIZE:]}


def _amd() -> Optional[Dict[str, Any]]:
    try:
        from lynceus import amd_bench

        return amd_bench.latest()
    except Exception:  # noqa: BLE001 - the panel is optional
        return None


def control_summary(
    storage_dir: "str | os.PathLike[str]", *, now: Optional[str] = None
) -> Dict[str, Any]:
    """Everything the control room shows, in one read of the ledger."""
    until = _now(now)
    since = _iso(_dt(until) - timedelta(hours=fuel.SHIFT_HOURS))
    records = _records(storage_dir)
    chains = followups.load_many(storage_dir, [r.record_id for r in records])
    report = shift.build_report(records, since, until, chains)
    kiln = fuel.kiln_intake(storage_dir, "shift", now=until)
    rows = suppliers.ledger_rows(storage_dir)
    open_holds = {r["record_id"] for r in rows if _open_hold(r)}

    by_start = sorted(records, key=lambda r: (r.started_at_utc, r.record_id))
    by_start = [r for r in by_start if r.started_at_utc < until]
    queue = [_card(r, chains.get(r.record_id, [])) for r in reversed(by_start[-QUEUE_SIZE:])]
    held = []
    for record in by_start:
        if record.record_id in open_holds:
            card = _card(record, chains.get(record.record_id, []))
            card["age_min"] = round((_dt(until) - _dt(card["at_utc"])).total_seconds() / 60.0)
            held.append(card)

    ranked = sorted(suppliers.profiles(storage_dir),
                    key=lambda p: (-p["risk_score"], -p["trucks"], p["supplier"]))
    return {
        "generated_at_utc": until,
        "shift": {"window": {"since": since, "until": until}, **report["improvement"]},
        "kiln": kiln,
        "carbon": fuel.carbon(storage_dir, "shift", now=until),
        "alerts": alerts(storage_dir, now=until, kiln=kiln),
        "queue": queue,
        "held": held[:HELD_SIZE],
        "suppliers": ranked[:TOP_SUPPLIERS],
        "lab_trend": _lab_trend(rows, until),
        "amd": _amd(),
        "contract_note": contracts.CONTRACT_NOTE,
    }
