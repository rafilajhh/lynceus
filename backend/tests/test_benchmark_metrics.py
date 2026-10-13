"""Benchmark metrics: hand-computed expectations, no network, no fixtures.

The positive class is the hard-contaminant REJECT gate: a row is positive when
its *expected* verdict is ``reject`` (RealWaste "Metal"); every other expected
verdict is negative.  Expected values below are worked out by hand from the
table, never read from the implementation under test.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from benchmark import metrics  # noqa: E402


def _row(expected, verdict, latency=None, total=None, error=None):
    return {
        "expected": expected,
        "predicted": verdict,
        "latency_ms": latency,
        "total_ms": total,
        "error": error,
    }


# Six rows, worked by hand:
#   TP = 2 (rows 1, 2)            FN = 2 (row 3 escalated, row 4 refused->error)
#   FP = 1 (row 5)                TN = 1 (row 6)
#   precision = 2/3   recall = 2/4 = 1/2   F1 = 2PR/(P+R) = 4/7
SIX = [
    _row("reject", "reject", 100, 1100),
    _row("reject", "reject", 200, 1200),
    _row("reject", "escalate_human", 300, 1300),
    _row("reject", "refuse_insufficient_input", 400, 1400),
    _row("escalate", "reject", 500, 1500),
    _row("accept", "accept", 600, 1600),
]


def test_reject_precision_recall_f1_exact():
    out = metrics.compute(SIX)
    assert out["n"] == 6
    assert out["reject"]["precision"] == pytest.approx(2 / 3)
    assert out["reject"]["recall"] == pytest.approx(1 / 2)
    assert out["reject"]["f1"] == pytest.approx(4 / 7)
    assert (out["reject"]["tp"], out["reject"]["fp"], out["reject"]["fn"]) == (2, 1, 2)


def test_confusion_maps_escalate_human_and_refuse_to_error():
    out = metrics.compute(SIX)
    assert out["confusion"]["reject"] == {"reject": 2, "escalate": 1, "accept": 0, "error": 1}
    assert out["confusion"]["escalate"] == {"reject": 1, "escalate": 0, "accept": 0, "error": 0}
    assert out["confusion"]["accept"] == {"reject": 0, "escalate": 0, "accept": 1, "error": 0}


def test_errors_counted_for_refusals_and_error_rows():
    rows = SIX + [_row("accept", None, error="HTTP 503 live_ai_unavailable")]
    out = metrics.compute(rows)
    assert out["errors"] == 2  # refuse_insufficient_input + the explicit error row
    assert out["confusion"]["accept"]["error"] == 1


def test_latency_nearest_rank_percentiles():
    rows = [_row("accept", "accept", latency=ms, total=ms + 1000) for ms in range(100, 1100, 100)]
    out = metrics.compute(rows)
    # ten values 100..1000: nearest rank p50 = 5th = 500, p95 = ceil(9.5) = 10th = 1000
    assert out["latency_ms"] == {"p50": 500, "p95": 1000}
    assert out["total_ms"] == {"p50": 1500, "p95": 2000}


def test_latency_ignores_rows_without_a_measurement():
    rows = [_row("accept", "accept", 200, 900), _row("accept", None, None, None, error="boom")]
    out = metrics.compute(rows)
    assert out["latency_ms"] == {"p50": 200, "p95": 200}


def test_empty_input_is_honest_not_a_crash():
    out = metrics.compute([])
    assert out["n"] == 0
    assert out["errors"] == 0
    assert out["reject"] == {"precision": None, "recall": None, "f1": None, "tp": 0, "fp": 0, "fn": 0}
    assert out["latency_ms"] == {"p50": None, "p95": None}
    assert out["confusion"]["reject"] == {"reject": 0, "escalate": 0, "accept": 0, "error": 0}


def test_no_predicted_reject_has_undefined_precision():
    out = metrics.compute([_row("reject", "accept", 1, 2)])
    assert out["reject"]["precision"] is None
    assert out["reject"]["recall"] == 0.0
    assert out["reject"]["f1"] is None


def test_attempt_stats_count_retries_and_all_attempt_latency():
    # Raw jsonl order: a.jpg timed out, was retried and then succeeded; b.jpg never succeeded;
    # c.jpg succeeded first time.
    attempts = [
        {"image": "a.jpg", "predicted": None, "error": "HTTP 503: ReadTimeout", "total_ms": 90000},
        {"image": "b.jpg", "predicted": None, "error": "HTTP 503: ReadTimeout", "total_ms": 50000},
        {"image": "c.jpg", "predicted": "accept", "error": None, "total_ms": 10000},
        {"image": "a.jpg", "predicted": "accept", "error": None, "total_ms": 20000},
    ]
    out = metrics.attempt_stats(attempts)
    assert out["attempts"] == 4
    assert out["retried"] == 1  # only a.jpg's error line was superseded by a later good row
    # nearest rank over [10000, 20000, 50000, 90000]: p95 = ceil(3.8) = 4th = 90000
    assert out["total_ms"] == {"p95": 90000, "max": 90000}


def test_attempt_stats_empty():
    assert metrics.attempt_stats([]) == {
        "attempts": 0,
        "retried": 0,
        "total_ms": {"p95": None, "max": None},
    }
