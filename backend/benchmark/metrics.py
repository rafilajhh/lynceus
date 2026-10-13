"""Benchmark metrics for the Lynceus vision gate.

The headline is a binary hard-contaminant gate: a row is *positive* when its
expected verdict is ``reject`` (RealWaste "Metal").  Every other expected
verdict is negative.  The 3x3 confusion matrix (plus an ``error`` column) is
reported alongside, because accept <-> escalate disagreement partly reflects
the gate's policy (glass / plastic film / textile are *light* contaminants),
not vision error.

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
    }
