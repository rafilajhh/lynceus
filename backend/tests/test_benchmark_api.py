"""GET /benchmark/latest and /benchmark/manifest.csv — static benchmark results."""

from __future__ import annotations

import json

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lynceus import api

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

FRAMING = "component validation on public RealWaste images — not field data from a plant"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "_BENCHMARK_DIR", tmp_path)
    (tmp_path / "results").mkdir()
    return TestClient(api.create_app()), tmp_path


def _write(results, name, body):
    (results / name).write_text(json.dumps(body), encoding="utf-8")


def test_latest_returns_newest_summary_with_framing(client):
    c, root = client
    _write(root / "results", "2026-10-13.summary.json", {"n": 1, "date": "2026-10-13"})
    _write(root / "results", "2026-10-14.summary.json", {"n": 80, "date": "2026-10-14"})
    _write(root / "results", "2026-10-14.jsonl", {"ignored": True})
    body = c.get("/benchmark/latest").json()
    assert body["n"] == 80 and body["date"] == "2026-10-14"
    assert body["framing"] == FRAMING


def test_latest_is_404_when_no_run_exists(client):
    c, _ = client
    r = c.get("/benchmark/latest")
    assert r.status_code == 404
    assert r.json()["detail"]["error"] == "no_benchmark"


def test_latest_skips_an_unreadable_newest_file(client):
    c, root = client
    _write(root / "results", "2026-10-13.summary.json", {"n": 5})
    (root / "results" / "2026-10-14.summary.json").write_text("{not json", encoding="utf-8")
    assert c.get("/benchmark/latest").json()["n"] == 5


def test_latest_ignores_replays_and_attaches_the_matching_one(client):
    c, root = client
    results = root / "results"
    _write(results, "2026-10-13.summary.json", {"n": 80, "date": "2026-10-13"})
    # Sorts after the live file name-wise; must never be served as the live run.
    _write(results, "2026-10-14.rescore.summary.json",
           {"kind": "replay", "source_run": "2026-10-14", "n": 1})
    _write(results, "2026-10-13.rescore.summary.json",
           {"kind": "replay", "source_run": "2026-10-13", "n": 80, "clean_accept_rate": 0.875})
    body = c.get("/benchmark/latest").json()
    assert body["date"] == "2026-10-13" and body["framing"] == FRAMING
    assert "kind" not in body
    assert body["replay"]["source_run"] == "2026-10-13"
    assert body["replay"]["clean_accept_rate"] == 0.875


def test_latest_replay_is_null_without_a_matching_rescore(client):
    c, root = client
    _write(root / "results", "2026-10-13.summary.json", {"n": 80, "date": "2026-10-13"})
    _write(root / "results", "2026-10-12.rescore.summary.json",
           {"kind": "replay", "source_run": "2026-10-12"})
    assert c.get("/benchmark/latest").json()["replay"] is None


def _hybrid(source_run, metal_accepted=0):
    """A minimal ``hybrid_replay`` summary in the committed shape."""
    return {
        "kind": "hybrid_replay",
        "source_run": source_run,
        "framing": "What-if re-score: recorded VLM outputs fused with the CPU detector.",
        "disclosure": "In-domain and optimistic.",
        "vlm_model": "DeepSeek-V4-Flash-Vision-Exp",
        "detector": {"model": "yolo26m-realwaste-taco", "runtime": "onnxruntime-cpu",
                     "hard_conf_default": 0.35, "light_conf": 0.05},
        "table": {"hybrid_light_escalation_on": {
            "clean_accept_rate": 0.85, "review_rate": 0.42, "metal_reject_recall": 0.4,
            "metal_reject_precision": 1.0, "metal_accepted": metal_accepted,
            "escalate_recall": 0.9, "gate_accuracy": 0.75}},
        "variants": {"hybrid_light_escalation_on": {
            "n": 80, "errors": 8, "gate_correct": "60/80", "graded": 72,
            "metal_reject": {"precision": 1.0, "recall": 0.4, "tp": 8, "fp": 0, "fn": 12},
            "metal_accepted": metal_accepted,
            "confusion": {
                "reject": {"reject": 8, "escalate": 10, "accept": 0, "error": 2},
                "escalate": {"reject": 0, "escalate": 18, "accept": 0, "error": 2},
                "accept": {"reject": 0, "escalate": 2, "accept": 34, "error": 4}}}},
    }


def test_latest_attaches_the_hybrid_of_this_run(client):
    c, root = client
    results = root / "results"
    _write(results, "2026-10-17.x.summary.json", {"kind": "live", "date": "2026-10-17.x", "n": 80})
    _write(results, "2026-10-17.x.hybrid-rescore.summary.json", _hybrid("2026-10-17.x"))
    # Sorts newer by name but re-scores an older run: never attached here.
    _write(results, "2026-10-17.zz-hybrid.summary.json", _hybrid("2026-10-13", metal_accepted=3))
    body = c.get("/benchmark/latest").json()
    assert body["date"] == "2026-10-17.x" and body["n"] == 80
    hybrid = body["hybrid"]
    assert hybrid["kind"] == "hybrid_replay" and hybrid["source_run"] == "2026-10-17.x"
    shipped = hybrid["table"]["hybrid_light_escalation_on"]
    assert shipped["metal_accepted"] == 0 and shipped["gate_accuracy"] == 0.75
    variant = hybrid["variants"]["hybrid_light_escalation_on"]
    assert variant["confusion"]["reject"]["escalate"] == 10
    assert hybrid["detector"]["model"] == "yolo26m-realwaste-taco"
    assert hybrid["framing"] and hybrid["disclosure"]


def test_latest_hybrid_is_null_without_a_matching_rescore(client):
    c, root = client
    _write(root / "results", "2026-10-17.summary.json", {"kind": "live", "date": "2026-10-17"})
    _write(root / "results", "2026-10-16.hybrid-rescore.summary.json", _hybrid("2026-10-13"))
    body = c.get("/benchmark/latest").json()
    assert body["date"] == "2026-10-17"
    assert body["hybrid"] is None and body["replay"] is None


def test_a_hybrid_named_like_a_live_run_is_never_the_live_run(client):
    c, root = client
    _write(root / "results", "2026-10-13.summary.json", {"date": "2026-10-13"})
    _write(root / "results", "2026-10-14.summary.json", _hybrid("2026-10-13"))
    body = c.get("/benchmark/latest").json()
    assert body["date"] == "2026-10-13"
    assert body["hybrid"]["source_run"] == "2026-10-13"


def test_committed_latest_carries_the_shipped_gate_hybrid():
    """The committed newest live run has its VLM + CPU detector re-score attached."""
    from lynceus import impact

    results = Path(__file__).resolve().parents[1] / "benchmark" / "results"
    live = next(impact.benchmark_summaries(results, "live"))[0]
    found = impact.matching_summary(results, "hybrid_replay", live)
    assert found is not None
    hybrid, name = found
    assert name.endswith(".hybrid-rescore.summary.json")
    assert hybrid["source_run"] == live["date"]
    assert hybrid["vlm_model"] == live["vlm_model"]
    assert "metal_accepted" in hybrid["table"]["hybrid_light_escalation_on"]


def test_latest_is_404_when_only_a_replay_exists(client):
    c, root = client
    _write(root / "results", "2026-10-13.rescore.summary.json",
           {"kind": "replay", "source_run": "2026-10-13"})
    assert c.get("/benchmark/latest").status_code == 404


def test_replay_endpoint_serves_the_newest_rescore(client):
    c, root = client
    assert c.get("/benchmark/replay").json()["detail"]["error"] == "no_replay"
    _write(root / "results", "2026-10-13.summary.json", {"n": 80, "date": "2026-10-13"})
    _write(root / "results", "2026-10-13.rescore.summary.json",
           {"kind": "replay", "source_run": "2026-10-13", "framing": "Re-scored: x"})
    body = c.get("/benchmark/replay").json()
    assert body["kind"] == "replay" and body["framing"] == "Re-scored: x"


def test_committed_replay_matches_its_live_run():
    """The committed 2026-10-13 replay re-scores exactly the committed live run."""
    results = Path(__file__).resolve().parents[1] / "benchmark" / "results"
    live = json.loads((results / "2026-10-13.summary.json").read_text(encoding="utf-8"))
    replay = json.loads((results / "2026-10-13.rescore.summary.json").read_text(encoding="utf-8"))
    assert replay["kind"] == "replay" and replay["source_run"] == live["date"]
    assert replay["n"] == live["n"] == 80
    assert replay["recorded_confusion"] == live["confusion"]
    assert sum(replay["confusion"]["accept"].values()) == 40
    assert "not a held-out" in replay["disclosure"]


def test_manifest_csv_is_served(client):
    c, root = client
    (root / "manifest.csv").write_text("image,category,expected\na.jpg,Metal,reject\n", encoding="utf-8")
    r = c.get("/benchmark/manifest.csv")
    assert r.status_code == 200 and "a.jpg,Metal,reject" in r.text
    assert r.headers["content-type"].startswith("text/csv")


def test_summary_framing_matches_the_api_framing():
    from benchmark import run as bench

    assert bench.FRAMING == api.BENCHMARK_FRAMING
