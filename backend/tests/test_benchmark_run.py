"""Benchmark harness: payload shape, provenance abort, resume, error stop.

Uses a fake ``post`` callable; no network and no model call.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from benchmark import run as bench  # noqa: E402

JPEG = bytes([0xFF, 0xD8, 0xFF, 0xE0]) + b"fake"


@pytest.fixture
def workspace(tmp_path):
    images = tmp_path / "images"
    images.mkdir()
    rows = [("a.jpg", "Metal", "reject"), ("b.jpg", "Paper", "accept"), ("c.jpg", "Glass", "escalate")]
    for name, _, _ in rows:
        (images / name).write_bytes(JPEG)
    manifest = tmp_path / "manifest.csv"
    manifest.write_text(
        "image,category,expected\n" + "".join(f"{n},{c},{e}\n" for n, c, e in rows),
        encoding="utf-8",
    )
    return manifest, images, tmp_path / "out.jsonl"


def _ok_body(decision="reject", provenance="live"):
    return {
        "record_id": "inspection-000001",
        "verdict": {"decision": decision},
        "gates": {"vlm_confidence": {"state": "passed"}, "weight_plausibility": {"state": "passed"}},
        "reasons": ["r"],
        "provenance": provenance,
        "ai_outputs": {
            "vlm": {
                "model": "vlm-x",
                "provider": "amd-token-factory",
                "latency_ms": 12000.5,
                "confidence": 0.9,
                "boxes": [{}, {}],
                "detected": {"contamination": "metal", "hard_contaminants": ["metal"], "light_contaminants": []},
            },
            "llm": {"model": "llm-y", "latency_ms": 2000.0},
        },
    }


def _run(workspace, post, **kw):
    manifest, images, out = workspace
    return bench.run(
        out=out, min_interval=0, manifest=manifest, images_dir=images,
        post=post, sleep=lambda s: None, log=lambda m: None, **kw,
    )


def test_payload_is_live_neutral_and_has_no_demo_case():
    item = {"image": "a.jpg", "category": "Metal", "expected": "reject"}
    p = bench.build_payload(item, 7, "QUJD")
    assert p["truck_id"] == "BENCH-7"
    assert p["weight_kg"] == 5200 and p["declared_weight_kg"] == 5200
    assert p["supplier"] == "Benchmark" and p["photo_base64"] == "QUJD"
    assert "demo_case" not in p
    assert "metal" not in p["photo_filename"].lower()
    low = p["manifest_text"].lower()
    assert "moisture" not in low and "metal" not in low


def test_row_records_the_measurement_fields(workspace):
    calls = []

    def post(payload):
        calls.append(payload)
        return 200, _ok_body()

    summary = _run(workspace, post)
    rows = [json.loads(l) for l in workspace[2].read_text(encoding="utf-8").splitlines()]
    assert [r["image"] for r in rows] == ["a.jpg", "b.jpg", "c.jpg"]
    r = rows[0]
    assert r["predicted"] == "reject" and r["boxes"] == 2 and r["latency_ms"] == 12000.5
    assert r["vlm_model"] == "vlm-x" and r["llm_model"] == "llm-y" and r["provenance"] == "live"
    assert r["gates"]["vlm_confidence"] == "passed" and r["detected"]["hard_contaminants"] == ["metal"]
    assert [c["truck_id"] for c in calls] == ["BENCH-1", "BENCH-2", "BENCH-3"]
    assert summary["n"] == 3 and summary["complete"] is True
    assert summary["vlm_model"] == "vlm-x"
    assert workspace[2].with_name("out.summary.json").is_file()


def test_non_live_provenance_aborts_and_writes_no_row(workspace):
    with pytest.raises(bench.ProvenanceError, match="not 'live'"):
        _run(workspace, lambda p: (200, _ok_body(provenance="stub")))
    assert not workspace[2].exists() or workspace[2].read_text(encoding="utf-8") == ""


def test_resume_skips_finished_images(workspace):
    _run(workspace, lambda p: (200, _ok_body()), limit=2)
    seen = []

    def post(payload):
        seen.append(payload["truck_id"])
        return 200, _ok_body()

    _run(workspace, post)
    assert seen == ["BENCH-3"]


def test_error_rows_are_retried_and_last_row_wins(workspace):
    _run(workspace, lambda p: (503, {"detail": {"message": "live_ai_unavailable"}}), limit=1)
    first = [json.loads(l) for l in workspace[2].read_text(encoding="utf-8").splitlines()]
    assert first[0]["error"].startswith("HTTP 503")
    seen = []

    def post(payload):
        seen.append(payload["truck_id"])
        return 200, _ok_body()

    summary = _run(workspace, post)
    assert seen == ["BENCH-1", "BENCH-2", "BENCH-3"]  # BENCH-1 retried
    assert summary["n"] == 3 and summary["errors"] == 0


def test_three_consecutive_errors_stop_the_run(workspace):
    manifest, images, out = workspace
    # A fourth item, so the stop is real: without the guard d.jpg would be posted.
    (images / "d.jpg").write_bytes(JPEG)
    with manifest.open("a", encoding="utf-8") as fh:
        fh.write("d.jpg,Paper,accept" + chr(10))
    calls = []

    def post(payload):
        calls.append(payload["truck_id"])
        return 429, {"detail": {"message": "rate limited"}}

    summary = _run(workspace, post)
    assert calls == ["BENCH-1", "BENCH-2", "BENCH-3"]
    assert summary["errors"] == 3 and summary["n"] == 3
    assert summary["complete"] is False


def test_summary_discloses_retries_and_framing(workspace):
    _run(workspace, lambda p: (503, {"detail": {"message": "ReadTimeout"}}), limit=1)
    summary = _run(workspace, lambda p: (200, _ok_body()))
    assert summary["framing"] == bench.FRAMING
    assert summary["attempt_stats"]["attempts"] == 4  # 1 failed attempt + 3 completed
    assert summary["attempt_stats"]["retried"] == 1
    assert summary["errors"] == 0 and summary["complete"] is True


def test_complete_counts_good_rows_not_error_rows(workspace):
    # Every image has a row, but none is a completed request: not complete.
    rows = [
        {"image": n, "category": "Paper", "expected": "accept", "predicted": None,
         "error": "HTTP 503", "total_ms": 1.0}
        for n in ("a.jpg", "b.jpg", "c.jpg")
    ]
    summary = bench.build_summary(rows, "2026-10-13", 3)
    assert summary["n"] == 3 and summary["complete"] is False


# --- Task 11: resilience under rate limiting -------------------------------

#: What the API returns (fail-closed) when the live client's own 429 retries are
#: exhausted: VLLMClient._chat raises "endpoint rate-limited after 3 attempts",
#: pipeline wraps it in LiveAIUnavailableError, api.py maps that to 503.
RATE_LIMITED_503 = (
    503,
    {
        "detail": {
            "error": "live_ai_unavailable",
            "message": "live AI failed (ValueError: endpoint rate-limited after 3 "
            "attempts (https://endpoint.example)); stub fallback disabled",
        }
    },
)


def _lines(path):
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


_REAL_RUN = bench.run  # captured once: main() is patched per call below


def _main_with(monkeypatch, workspace, post):
    """Drive the real main() (arg parsing + exit-code mapping) with a fake post."""
    manifest, images, out = workspace
    monkeypatch.setattr(
        bench,
        "run",
        lambda **kw: _REAL_RUN(
            **kw, manifest=manifest, images_dir=images, post=post,
            sleep=lambda s: None, log=lambda m: None,
        ),
    )
    return bench.main(["--out", str(out), "--min-interval", "0"])


def test_rate_limit_on_item_3_stops_immediately_with_exit_2(workspace, monkeypatch):
    manifest, images, out = workspace
    (images / "d.jpg").write_bytes(JPEG)
    with manifest.open("a", encoding="utf-8") as fh:
        fh.write("d.jpg,Paper,accept\n")
    calls = []

    def post(payload):
        calls.append(payload["truck_id"])
        return RATE_LIMITED_503 if payload["truck_id"] == "BENCH-3" else (200, _ok_body())

    code = _main_with(monkeypatch, workspace, post)
    assert code == 2
    # Stopped at the first rate limit: not retried, item 4 never posted.
    assert calls == ["BENCH-1", "BENCH-2", "BENCH-3"]
    rows = _lines(out)
    assert [r["image"] for r in rows] == ["a.jpg", "b.jpg"]  # items 1-2 persisted
    assert all(not r.get("error") for r in rows)  # no row for item 3: not a measurement


def test_rate_limit_is_not_a_measurement_via_run(workspace):
    def post(payload):
        return RATE_LIMITED_503 if payload["truck_id"] == "BENCH-3" else (200, _ok_body())

    with pytest.raises(bench.RateLimitedError):
        _run(workspace, post)
    assert [r["image"] for r in _lines(workspace[2])] == ["a.jpg", "b.jpg"]


def test_rerun_after_rate_limit_skips_done_items_and_finishes(workspace, monkeypatch):
    def limited(payload):
        return RATE_LIMITED_503 if payload["truck_id"] == "BENCH-3" else (200, _ok_body())

    assert _main_with(monkeypatch, workspace, limited) == 2
    seen = []

    def post(payload):
        seen.append(payload["truck_id"])
        return 200, _ok_body()

    assert _main_with(monkeypatch, workspace, post) == 0
    assert seen == ["BENCH-3"]  # items 1-2 not re-spent
    rows = _lines(workspace[2])
    assert [r["image"] for r in rows] == ["a.jpg", "b.jpg", "c.jpg"]
    summary = json.loads(workspace[2].with_name("out.summary.json").read_text(encoding="utf-8"))
    assert summary["n"] == 3 and summary["complete"] is True
    assert summary["attempt_stats"]["attempts"] == 3  # no wasted/erroneous attempts logged


@pytest.mark.parametrize(
    "status, body",
    [
        (503, {"detail": {"message": "live_ai_unavailable: ReadTimeout"}}),  # other 503
        (429, {"detail": {"message": "rate limited"}}),  # not the API's rate-limit shape
        (500, {"detail": {"message": "endpoint rate-limited after 3 attempts"}}),  # wrong status
    ],
)
def test_other_errors_are_not_treated_as_rate_limit(status, body):
    assert bench.is_rate_limited(status, body) is False
    assert bench.is_rate_limited(*RATE_LIMITED_503) is True


def test_non_rate_limit_error_still_records_row_and_continues(workspace):
    calls = []

    def post(payload):
        calls.append(payload["truck_id"])
        if payload["truck_id"] == "BENCH-2":
            return 503, {"detail": {"message": "live_ai_unavailable: ReadTimeout"}}
        return 200, _ok_body()

    summary = _run(workspace, post)
    assert calls == ["BENCH-1", "BENCH-2", "BENCH-3"]
    assert summary["errors"] == 1 and summary["n"] == 3


def test_provenance_abort_mid_run_keeps_earlier_rows_and_writes_none_for_the_stub(
    workspace, monkeypatch
):
    def post(payload):
        stub = payload["truck_id"] == "BENCH-2"
        return 200, _ok_body(provenance="stub" if stub else "live")

    assert _main_with(monkeypatch, workspace, post) == 2
    assert [r["image"] for r in _lines(workspace[2])] == ["a.jpg"]  # nothing for item 2


def test_non_live_provenance_on_first_item_exits_2_before_any_row(workspace, monkeypatch):
    assert _main_with(monkeypatch, workspace, lambda p: (200, _ok_body(provenance="stub"))) == 2
    assert not workspace[2].exists() or workspace[2].read_text(encoding="utf-8") == ""
