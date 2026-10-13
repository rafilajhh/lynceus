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
        seen.append(payload["photo_filename"])
        return 200, _ok_body()

    _run(workspace, post)
    assert seen == ["c.jpg"]


def test_error_rows_are_retried_and_last_row_wins(workspace):
    _run(workspace, lambda p: (503, {"detail": {"message": "live_ai_unavailable"}}), limit=1)
    first = [json.loads(l) for l in workspace[2].read_text(encoding="utf-8").splitlines()]
    assert first[0]["error"].startswith("HTTP 503")
    seen = []

    def post(payload):
        seen.append(payload["photo_filename"])
        return 200, _ok_body()

    summary = _run(workspace, post)
    assert seen == ["a.jpg", "b.jpg", "c.jpg"]  # a.jpg retried
    assert summary["n"] == 3 and summary["errors"] == 0


def test_three_consecutive_errors_stop_the_run(workspace):
    calls = []

    def post(payload):
        calls.append(1)
        return 429, {"detail": {"message": "rate limited"}}

    summary = _run(workspace, post)
    assert len(calls) == bench.MAX_CONSECUTIVE_ERRORS
    assert summary["errors"] == 3
