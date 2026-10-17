"""Shift report: what the gate caught, what it saved, which suppliers repeat.

:func:`build_report` is pure aggregation over strictly loaded audit records
in a time window — no clock; its only I/O is reading the benchmark summary
for ``value_model`` (``impact.value_model_from_benchmark``, the same for
every window).  :func:`explain_supplier` asks the
explain-role model (``EXPLAIN_MODEL``, default the assist model) for structured statistics and a recommendation code for one
flagged supplier row. Supplier identity and all prose are rendered from the
row and fixed templates; malformed output uses the deterministic fallback.

Rules (spec §4.5, plan Task 9):

* Only ``completed`` records count; an ``in_progress`` record carries a
  placeholder verdict, not a decision.
* The window is half-open on ``started_at_utc``: ``since`` inclusive,
  ``until`` exclusive, so back-to-back shifts never count a truck twice.
* ``prevented_loss_idr`` sums the ``impact`` estimate of reject and escalate
  verdicts only.  For an accepted load that estimate is the load's market
  value, which ``impact.py`` itself says is not a prevented loss.  Each
  reject's estimate assumes the damage was certain, so the sum is a
  worst-case exposure; ``loss_exposure_idr`` repeats it under that name and
  ``value_model`` gives the probability-weighted value per 1,000 trucks
  (``None`` when no benchmark summary is readable).
* ``risk_score = (reject + 0.5 * escalate) / trucks`` rounded to 2 dp;
  ``flagged = trucks >= 3 and risk_score >= 0.34``.  A missing or blank
  supplier (all v1 records) is ``"unknown"``.
* ``sample`` is true only when every counted record came from scripted data
  (photo provenance green / amber / red / sample).
* ``improvement`` (:func:`improvement`) is what the UI leads with: measured
  from the same records plus their sealed follow-ups (passed in, never read
  here), every assumption labelled in its ``notes``.
"""

from __future__ import annotations

import json
import math
import re
import statistics
import time
from datetime import datetime
from typing import Any, Iterable, Mapping, Sequence

from lynceus import audit, contracts, followups, impact
from lynceus.decision import LIGHT_CONTAMINANTS

__all__ = [
    "FLAG_MIN_TRUCKS",
    "FLAG_MIN_RISK",
    "SAMPLE_PROVENANCES",
    "FAILURE_RETRY_S",
    "build_report",
    "improvement",
    "risk_score",
    "explain_supplier",
    "needs_model",
    "fallback_explanation",
    "allowed_numbers",
    "clear_explanation_cache",
    "cached_explanation",
]

FLAG_MIN_TRUCKS = 3
FLAG_MIN_RISK = 0.34
UNKNOWN_SUPPLIER = "unknown"

#: Photo provenances written only by scripted paths (demo buttons, seeding).
SAMPLE_PROVENANCES = frozenset({"green", "amber", "red", "sample"})

#: Verdicts whose impact estimate is a prevented loss.
_LOSS_VERDICTS = (audit.Decision.REJECT, audit.Decision.ESCALATE_HUMAN)

#: A failed or ungrounded model answer is not retried for this long, so a
#: page refresh during an outage does not spend the shared rate limit.
FAILURE_RETRY_S = 300.0

_MAX_SENTENCES = 3
_MAX_CHARS = 600
_NUMBER_RE = re.compile(r"\d+(\.\d+)?")
#: "1,200" / "3.000.000" → "1200" / "3000000" before the number check, so a
#: grouped number is ONE number.  Safe for the row's own figures: risk_score is
#: rounded to 2 decimals, so a legitimate "0.67" never has three digits after
#: the dot.
_THOUSANDS_RE = re.compile(r"(?<=\d)[.,](?=\d{3}(?!\d))")
#: The row carries no money, so any currency or magnitude word is invented.
_MONEY_RE = re.compile(
    r"\b(?:rp|idr|rupiah|usd|juta|ribu|million|thousand|billion|miliar)s?\b|\bus\$",
    re.IGNORECASE,
)
_SENTENCE_RE = re.compile(r"[.!?]+(?=\s|$)")


# ---------------------------------------------------------------------------
# build_report
# ---------------------------------------------------------------------------


def _parse_utc(value: str, field: str) -> datetime:
    """Strict ISO 8601 UTC ``Z`` → naive UTC datetime (``ValueError`` if not)."""
    try:
        audit.validate_timestamp(value, field)
    except audit.AuditError as exc:
        raise ValueError(str(exc)) from exc
    body = value[:-1]
    fmt = "%Y-%m-%dT%H:%M:%S.%f" if "." in body else "%Y-%m-%dT%H:%M:%S"
    return datetime.strptime(body, fmt)


def _supplier_name(record: audit.AuditRecord) -> str:
    name = (record.inputs.supplier or "").strip()
    return name or UNKNOWN_SUPPLIER


def _labels(detected: dict, key: str) -> list[str]:
    items = detected.get(key)
    if not isinstance(items, list):
        return []
    return [str(i).strip() for i in items if isinstance(i, str) and i.strip()]


def risk_score(trucks: int, reject: int, escalate: int) -> float:
    if trucks <= 0:
        return 0.0
    return round((reject + 0.5 * escalate) / trucks, 2)


def build_report(
    records: Iterable[audit.AuditRecord],
    since: str | None,
    until: str | None,
    followups_by_record: Mapping[str, Sequence[dict]] | None = None,
) -> dict:
    """Aggregate completed inspections whose ``started_at_utc`` is in the window.

    ``followups_by_record`` maps a record id to its sealed follow-ups
    (:func:`lynceus.followups.load_many`); they feed the ``improvement`` block.

    Raises ``ValueError`` for a ``since``/``until`` that is not ISO 8601 UTC
    with a trailing ``Z``, or when ``since`` is after ``until``.
    """
    since_dt = _parse_utc(since, "since") if since is not None else None
    until_dt = _parse_utc(until, "until") if until is not None else None
    if since_dt is not None and until_dt is not None and since_dt > until_dt:
        raise ValueError(f"since {since!r} is after until {until!r}")

    kept: list[tuple[datetime, audit.AuditRecord]] = []
    for record in records:
        if record.execution_status != audit.ExecutionStatus.COMPLETED:
            continue
        started = _parse_utc(record.started_at_utc, "started_at_utc")
        if since_dt is not None and started < since_dt:
            continue
        if until_dt is not None and started >= until_dt:
            continue
        kept.append((started, record))
    kept.sort(key=lambda item: item[0])

    by_verdict = {decision: 0 for decision in audit.Decision.ALL}
    contaminants: dict[str, int] = {}
    prevented = 0.0
    durations: list[float] = []
    sample_records = 0
    suppliers: dict[str, dict] = {}

    for started, record in kept:
        decision = record.verdict.decision
        by_verdict[decision] += 1

        detected = record.ai_outputs.vlm.detected or {}
        # Light labels follow the decision policy: plastic film and textile
        # are RDF feedstock, so the VLM's mention of them is not a catch.
        labels = _labels(detected, "hard_contaminants") + [
            label for label in _labels(detected, "light_contaminants")
            if label in LIGHT_CONTAMINANTS
        ]
        for label in dict.fromkeys(labels):  # once per truck, order kept
            contaminants[label] = contaminants.get(label, 0) + 1

        if decision in _LOSS_VERDICTS:
            prevented += float(
                impact.estimate_prevented_loss(
                    decision, {"detected": detected}, record.inputs.weight.value_kg
                )["prevented_loss_idr"]
            )

        if record.finished_at_utc is not None:
            finished = _parse_utc(record.finished_at_utc, "finished_at_utc")
            durations.append((finished - started).total_seconds())

        if record.inputs.photo.provenance in SAMPLE_PROVENANCES:
            sample_records += 1

        row = suppliers.setdefault(
            _supplier_name(record), {"trucks": 0, "reject": 0, "escalate": 0}
        )
        row["trucks"] += 1
        if decision == audit.Decision.REJECT:
            row["reject"] += 1
        elif decision == audit.Decision.ESCALATE_HUMAN:
            row["escalate"] += 1

    supplier_rows = []
    for name, counts in suppliers.items():
        score = risk_score(counts["trucks"], counts["reject"], counts["escalate"])
        supplier_rows.append(
            {
                "supplier": name,
                "trucks": counts["trucks"],
                "reject": counts["reject"],
                "escalate": counts["escalate"],
                "risk_score": score,
                "flagged": counts["trucks"] >= FLAG_MIN_TRUCKS and score >= FLAG_MIN_RISK,
            }
        )
    supplier_rows.sort(key=lambda r: (-r["risk_score"], -r["trucks"], r["supplier"]))

    trucks = len(kept)
    return {
        "window": {
            "since": since,
            "until": until,
            "first_truck_utc": kept[0][1].started_at_utc if kept else None,
            "last_truck_utc": kept[-1][1].started_at_utc if kept else None,
        },
        "trucks": trucks,
        "by_verdict": by_verdict,
        "contaminants": dict(sorted(contaminants.items(), key=lambda kv: (-kv[1], kv[0]))),
        "prevented_loss_idr": prevented,
        # Same figure under its honest name: worst-case exposure, not certain loss.
        "loss_exposure_idr": prevented,
        "value_model": impact.value_model_from_benchmark(),
        "median_seconds_per_truck": float(statistics.median(durations)) if durations else None,
        "suppliers": supplier_rows,
        "sample": trucks > 0 and sample_records == trucks,
        "sample_records": sample_records,
        "improvement": improvement(
            [record for _, record in kept], followups_by_record, durations
        ),
    }


def _p95(values: list[float]) -> float | None:
    """Nearest-rank 95th percentile."""
    if not values:
        return None
    ordered = sorted(values)
    return float(ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)])


def improvement(
    records: Sequence[audit.AuditRecord],
    followups_by_record: Mapping[str, Sequence[dict]] | None,
    durations: Sequence[float],
) -> dict:
    """What the gate measurably changed this shift, from records + follow-ups.

    * ``hand_checks_avoided``: ACCEPT verdicts with no supervisor resolution;
      ``staff_minutes_freed`` multiplies them by the value model's assumed
      manual check time (``impact.MANUAL_CHECK_MINUTES_BASE``).
    * Decision time is ``started_at_utc`` to ``finished_at_utc`` of each
      record (the same durations as ``median_seconds_per_truck``): what the
      operator waits for, AI and sealing included.
    * ``hazardous_loads_stopped``: REJECTs naming a hard contaminant;
      ``exposure_if_tipped_idr``: the worst-case exposure of those a
      supervisor accepted anyway (resolution ``accept``, not sorted).
    * Review, lab and contract figures come from the sealed follow-ups
      (:func:`lynceus.followups.ledger_row`), contract terms from the example
      contract.
    """
    chains = followups_by_record or {}
    rows = [followups.ledger_row(r, list(chains.get(r.record_id, ()))) for r in records]
    by_id = {r.record_id: r for r in records}
    minutes = impact.MANUAL_CHECK_MINUTES_BASE
    avoided = sum(1 for r in rows if r["decision"] == audit.Decision.ACCEPT and not r["reviewed"])
    exposure = 0
    for row in rows:
        if row["hard_contaminant_load"] and (row["resolution"] or {}).get("decision") == "accept":
            record = by_id[row["record_id"]]
            exposure += round(impact.estimate_prevented_loss(
                audit.Decision.REJECT,
                {"detected": record.ai_outputs.vlm.detected},
                record.inputs.weight.value_kg,
            )["prevented_loss_idr"])
    notes = [
        f"Manual check time is an assumption ({minutes:g} min per truck, the "
        "value model's manual_check_minutes; no published duration was found, "
        "docs/research/token-factory-probe.md); staff minutes freed = trucks "
        "cleared without a hand check x that time, before the photo and "
        "waybill capture time.",
        "Decision time is measured from record start to seal (started_at_utc to "
        "finished_at_utc): what the operator waits for.",
        "Deductions and breach fees use the example supply contract: terms are "
        f"set per contract ({contracts.DEFAULT_CONTRACT['sop_ref']}).",
    ]
    if followups_by_record is None:
        notes.append("Follow-ups were not loaded: review, lab and contract figures are 0.")
    return {
        "trucks": len(rows),
        "auto_cleared": sum(1 for r in rows if r["decision"] == audit.Decision.ACCEPT),
        "held": sum(1 for r in rows if r["decision"] == audit.Decision.ESCALATE_HUMAN),
        "rejected": sum(1 for r in rows if r["decision"] == audit.Decision.REJECT),
        "refused": sum(
            1 for r in rows if r["decision"] == audit.Decision.REFUSE_INSUFFICIENT_INPUT
        ),
        "hand_checks_avoided": avoided,
        "manual_check_minutes_assumed": minutes,
        "staff_minutes_freed": round(avoided * minutes, 1),
        "median_decision_s": float(statistics.median(durations)) if durations else None,
        "p95_decision_s": _p95(list(durations)),
        "hazardous_loads_stopped": sum(1 for r in rows if r["hard_contaminant_load"]),
        "declaration_conflicts": sum(1 for r in rows if r["declaration_conflict"]),
        "supervisor_reviews": sum(1 for r in rows if r["reviewed"]),
        "ai_confirmed": sum(1 for r in rows if r["confirmed"]),
        "ai_overridden": sum(1 for r in rows if r["overridden"]),
        "lab_samples": sum(len(r["labs"]) for r in rows),
        "spec_breaches": sum(r["spec_breach_samples"] for r in rows),
        "deductions_idr": sum(r["deductions_idr"] for r in rows),
        "breach_fees_idr": sum(r["breach_fee_idr"] for r in rows),
        "notices": sum(r["notices"] for r in rows),
        "exposure_if_tipped_idr": exposure,
        "notes": notes,
    }


# ---------------------------------------------------------------------------
# explain_supplier
# ---------------------------------------------------------------------------

_INSTRUCTIONS = (
    "You write for the shift supervisor at the RDF waste receiving gate of a "
    "cement plant. Using ONLY the supplier statistics given by the user, write "
    "at most three short plain sentences: what this supplier's loads did this "
    "shift, and one recommendation. Rules: use only numbers that appear in the "
    "statistics, written as given; the risk score may also be written as a "
    "percentage (0.5 as 50%). Do not compute any other number, rate, total, "
    "price, weight or date. risk_score weighs a rejected load fully and an "
    "escalated load by half. "
    'Reply with ONLY a JSON object: {"stats": {"trucks": 7, "reject": 3, '
    '"escalate": 1, "risk_score": 0.5}, "recommendation": "quality_review"}. '
    "Copy the supplied statistics exactly. recommendation must be either "
    "quality_review or visual_check. Do not output supplier names, plates, "
    "identities, or free-form prose. The backend supplies the identity."
)


def fallback_explanation(row: dict) -> str:
    """The deterministic sentence used whenever the model's text is not usable."""
    return (
        f"{row['supplier']}: {row['reject']} of {row['trucks']} loads rejected "
        f"and {row['escalate']} escalated. Recommend a supplier quality review "
        "before the next delivery."
    )


def _numbers_in(text: str) -> list[float]:
    flat = _THOUSANDS_RE.sub("", text)
    return [float(m.group(0)) for m in _NUMBER_RE.finditer(flat)]


def allowed_numbers(row: dict) -> set[float]:
    """Every number the explanation may contain, in normalised forms.

    Counts and the risk score as given, the risk score as a whole-number
    percentage (0.67 → 67), and any digits in the supplier name.
    """
    allowed: set[float] = set()
    for key in ("trucks", "reject", "escalate", "risk_score"):
        value = row.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            allowed.add(float(value))
    score = row.get("risk_score")
    if isinstance(score, (int, float)) and not isinstance(score, bool):
        allowed.add(float(round(score * 100)))
    allowed.update(_numbers_in(str(row.get("supplier", ""))))
    return allowed


def _grounded(text: Any, row: dict) -> str | None:
    """``text`` stripped when it passes every check, else ``None``."""
    if not isinstance(text, str):
        return None
    text = " ".join(text.split())
    if not text or len(text) > _MAX_CHARS:
        return None
    sentences = [s for s in _SENTENCE_RE.split(text) if s.strip()]
    if len(sentences) > _MAX_SENTENCES:
        return None
    if _MONEY_RE.search(text):
        return None
    allowed = allowed_numbers(row)
    if any(n not in allowed for n in _numbers_in(text)):
        return None
    return text


def _structured_explanation(parsed: Any, row: dict) -> str | None:
    if not isinstance(parsed, dict):
        return None
    stats = parsed.get("stats")
    expected = {k: row.get(k) for k in ("trucks", "reject", "escalate", "risk_score")}
    if not isinstance(stats, dict) or stats != expected:
        return None
    recommendations = {
        "quality_review": "Recommend a supplier quality review before the next delivery.",
        "visual_check": "Hold the next delivery for a full visual check.",
    }
    recommendation = parsed.get("recommendation")
    if not isinstance(recommendation, str) or recommendation not in recommendations:
        return None
    return (
        f"{row['supplier']}: {row['reject']} of {row['trucks']} loads rejected "
        f"and {row['escalate']} escalated. {recommendations[recommendation]}"
    )


def _cache_key(row: dict) -> tuple:
    return (
        row.get("supplier"), row.get("trucks"), row.get("reject"),
        row.get("escalate"), row.get("risk_score"), row.get("flagged"),
    )


#: key → (text or None for a failure, monotonic time stored).
_CACHE: dict[tuple, tuple[str | None, float]] = {}


def _now() -> float:
    return time.monotonic()


def clear_explanation_cache() -> None:
    _CACHE.clear()


def cached_explanation(row: dict) -> str | None:
    """A cached model explanation for these exact stats, else ``None``."""
    hit = _CACHE.get(_cache_key(row))
    return hit[0] if hit else None


def _failure_fresh(row: dict) -> bool:
    hit = _CACHE.get(_cache_key(row))
    return bool(hit and hit[0] is None and _now() - hit[1] < FAILURE_RETRY_S)


def needs_model(row: dict) -> bool:
    """True when a model call would actually be made for this row."""
    return cached_explanation(row) is None and not _failure_fresh(row)


def _messages(row: dict) -> list[dict]:
    stats = {k: row.get(k) for k in ("trucks", "reject", "escalate", "risk_score")}
    return [
        {"role": "system", "content": _INSTRUCTIONS},
        {"role": "user", "content": "Supplier statistics for this shift:\n"
                                    + json.dumps(stats, ensure_ascii=True)},
    ]


def explain_supplier(row: dict, client: Any | None) -> str:
    """Up to three sentences on one supplier row, grounded in the row only.

    Model statistics must exactly match the row, and its recommendation must
    be a supported code. Identity and prose are never taken from the model.
    Invalid output, no client, or a client error uses the deterministic fallback.
    Successful explanations are cached per (supplier, stats) for the process;
    failures for :data:`FAILURE_RETRY_S` seconds.
    """
    key = _cache_key(row)
    cached = cached_explanation(row)
    if cached is not None:
        return cached
    if client is None or _failure_fresh(row):
        return fallback_explanation(row)
    try:
        parsed, _latency_ms = client.explain(_messages(row), max_tokens=700)
    except Exception:
        parsed = None
    text = _structured_explanation(parsed, row)
    _CACHE[key] = (text, _now())
    return text if text is not None else fallback_explanation(row)
