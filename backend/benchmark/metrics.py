"""Benchmark metrics for the Lynceus vision gate.

The headline is a binary hard-contaminant gate: a row is *positive* when its
expected verdict is ``reject`` (RealWaste "Metal").  Every other expected
verdict is negative.  The 3x3 confusion matrix (plus an ``error`` column) is
reported alongside, because accept <-> escalate disagreement partly reflects
the gate's policy (glass / organic residue / wet mix are *light* contaminants
and escalate by rule), not vision error.

Operator-load rates sit next to the headline: ``clean_*_rate`` is the share of
expected-accept rows (errors stay in the denominator) per predicted label,
``review_rate`` the share of all non-error rows sent to a human (escalate), and
``escalate_recall`` the share of expected-escalate rows escalated (an error
counts as a miss).  Each is ``None`` when its denominator is empty.

Rows are plain dicts: ``expected`` (reject|escalate|accept), ``predicted`` (the
raw ``/inspect`` verdict, or None on a request error), ``latency_ms`` (the VLM
call), ``total_ms`` (the whole request), ``error``.
"""

from __future__ import annotations

import math
from typing import Any, Optional

LABELS = ("reject", "escalate", "accept")
COLUMNS = LABELS + ("error",)

#: Raw gate verdict -> benchmark label.  Anything unlisted (refuse_*, None,
#: unknown) is an error: the gate declined to answer, which is not a verdict.
_VERDICT_TO_LABEL = {
    "reject": "reject",
    "escalate_human": "escalate",
    "escalate": "escalate",
    "accept": "accept",
}


def label_for(row: dict[str, Any]) -> str:
    """Predicted benchmark label for one row (``error`` when unusable)."""
    if row.get("error"):
        return "error"
    return _VERDICT_TO_LABEL.get(str(row.get("predicted")), "error")


def _percentile(values: list[float], q: float) -> Optional[float]:
    """Nearest-rank percentile (deterministic; no interpolation)."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(q * len(ordered)))
    return ordered[rank - 1]


def _latency(rows: list[dict[str, Any]], key: str) -> dict[str, Optional[float]]:
    values = [
        float(r[key])
        for r in rows
        if label_for(r) != "error" and isinstance(r.get(key), (int, float))
    ]
    return {"p50": _percentile(values, 0.50), "p95": _percentile(values, 0.95)}


def compute(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarise benchmark rows: confusion, REJECT precision/recall/F1, latency."""
    confusion = {exp: {col: 0 for col in COLUMNS} for exp in LABELS}
    tp = fp = fn = 0
    errors = 0
    for row in rows:
        expected = row.get("expected")
        predicted = label_for(row)
        if predicted == "error":
            errors += 1
        if expected in confusion:
            confusion[expected][predicted] += 1
        positive = expected == "reject"
        if positive and predicted == "reject":
            tp += 1
        elif positive:
            fn += 1  # an error on a Metal image is a miss, not a pass
        elif predicted == "reject":
            fp += 1

    clean = confusion["accept"]
    clean_n = sum(clean.values())
    graded = [label for label in map(label_for, rows) if label != "error"]
    escalate_n = sum(confusion["escalate"].values())

    precision = tp / (tp + fp) if (tp + fp) else None
    recall = tp / (tp + fn) if (tp + fn) else None
    f1 = None
    if precision is not None and recall is not None:
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {
        "n": len(rows),
        "confusion": confusion,
        "reject": {"precision": precision, "recall": recall, "f1": f1, "tp": tp, "fp": fp, "fn": fn},
        "latency_ms": _latency(rows, "latency_ms"),
        "total_ms": _latency(rows, "total_ms"),
        "errors": errors,
        "clean_accept_rate": _share(clean["accept"], clean_n),
        "clean_escalate_rate": _share(clean["escalate"], clean_n),
        "clean_reject_rate": _share(clean["reject"], clean_n),
        "review_rate": _share(graded.count("escalate"), len(graded)),
        "escalate_recall": _share(confusion["escalate"]["escalate"], escalate_n),
    }


def _share(part: int, whole: int) -> Optional[float]:
    return part / whole if whole else None


def attempt_stats(attempts: list[dict[str, Any]]) -> dict[str, Any]:
    """Raw request attempts, in jsonl order, including failed ones.

    ``retried`` counts error lines superseded by a *later* good row for the
    same image.  The latency figures cover every attempt (timeouts included),
    unlike ``compute()``, which covers completed requests only.
    """
    retried = 0
    for i, row in enumerate(attempts):
        if row.get("error") and any(
            later["image"] == row["image"] and not later.get("error") for later in attempts[i + 1 :]
        ):
            retried += 1
    values = [float(r["total_ms"]) for r in attempts if isinstance(r.get("total_ms"), (int, float))]
    return {
        "attempts": len(attempts),
        "retried": retried,
        "total_ms": {"p95": _percentile(values, 0.95), "max": max(values) if values else None},
    }
