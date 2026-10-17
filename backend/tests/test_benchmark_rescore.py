"""Replay re-score: recorded VLM outputs through the current /inspect path.

Fake recorded rows and fake JPEG bytes in a temp dir; any network attempt
fails the test.  Expected verdicts follow from the current decision rules.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from benchmark import rescore  # noqa: E402
from lynceus import config, detector, pipeline  # noqa: E402

JPEG = bytes([0xFF, 0xD8, 0xFF, 0xE0]) + b"fake"
PASSED = {
    "vlm_confidence": "passed",
    "ocr_confidence": "passed",
    "manifest_crosscheck": "passed",
    "gas_plausibility": "not_run",
    "weight_plausibility": "passed",
}


def _row(image, category, expected, predicted, hard=(), light=(), prose="none detected",
         confidence=0.95, gates=None):
    return {
        "image": image,
        "category": category,
        "expected": expected,
        "predicted": predicted,
        "gates": dict(gates or PASSED),
        "detected": {
            "contamination": prose,
            "moisture": 0.05,
            "hard_contaminants": list(hard),
            "light_contaminants": list(light),
        },
        "vlm_confidence": confidence,
        "latency_ms": 15000.0,
        "total_ms": 18000.0,
        "vlm_model": "vlm-x",
        "llm_model": "llm-y",
        "provider": "amd-token-factory",
        "provenance": "live",
        "error": None,
    }


RECORDED = [
    _row("metal_1.jpg", "Metal", "reject", "reject", hard=["metal"], prose="metal can"),
    _row("textile_1.jpg", "Textile Trash", "accept", "escalate_human", light=["textile"],
         prose="textile strip"),
    _row("plastic_1.jpg", "Plastic", "accept", "reject", light=["plastic_film"],
         prose="plastic object on a concrete floor"),  # old prose-based reject
    _row("glass_1.jpg", "Glass", "escalate", "escalate_human", light=["glass"], prose="glass jar"),
    _row("paper_1.jpg", "Paper", "accept", "escalate_human",
         gates={**PASSED, "manifest_crosscheck": "failed"}),
    # vegetation_1: timed out, then retried successfully (latest row wins).
    {"image": "veg_1.jpg", "category": "Vegetation", "expected": "escalate", "predicted": None,
     "total_ms": 49000.0, "error": "HTTP 503: ReadTimeout"},
    _row("veg_1.jpg", "Vegetation", "escalate", "escalate_human", light=["organic_residue"]),
    # food_1 never succeeded: stays an error row.
    {"image": "food_1.jpg", "category": "Food Organics", "expected": "escalate",
     "predicted": None, "total_ms": 50000.0, "error": "HTTP 503: ReadTimeout"},
]


@pytest.fixture
def replayed(tmp_path, monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("the replay must not touch the network")

    # The real network transport (TestClient uses its own in-process one).
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", no_network)
    monkeypatch.setattr(httpx, "get", no_network)
    monkeypatch.setenv("LYNCEUS_GAS_SENSOR_URL", "http://gas.invalid")
    images = tmp_path / "images"
    images.mkdir()
    names = sorted({r["image"] for r in RECORDED})
    for name in names:
        (images / name).write_bytes(JPEG)
    manifest = tmp_path / "manifest.csv"
    manifest.write_text("image,category,expected\n" + "".join(f"{n},x,y\n" for n in names),
                        encoding="utf-8")
    results = tmp_path / "results"
    results.mkdir()
    source = results / "2026-10-13.jsonl"
    source_text = "".join(json.dumps(r) + "\n" for r in RECORDED)
    source.write_text(source_text, encoding="utf-8")
    original_resolve = pipeline.resolve_clients
    summary = rescore.rescore(source, images_dir=images, manifest=manifest,
                              log=lambda m: None, today="2026-10-14")
    rows = [json.loads(l) for l in (results / "2026-10-13.rescore.jsonl").read_text(
        encoding="utf-8").splitlines()]
    return {
        "summary": summary,
        "rows": {r["image"]: r for r in rows},
        "n_rows": len(rows),
        "source": source,
        "source_text": source_text,
        "results": results,
        "original_resolve": original_resolve,
    }


def test_current_rules_decide_each_recorded_output(replayed):
    rows = replayed["rows"]
    assert replayed["n_rows"] == 7  # latest row per image
    assert rows["metal_1.jpg"]["predicted"] == "reject"
    assert rows["textile_1.jpg"]["predicted"] == "accept"  # textile is RDF feedstock
    assert rows["plastic_1.jpg"]["predicted"] == "accept"  # prose "concrete" is not evidence
    assert rows["glass_1.jpg"]["predicted"] == "escalate_human"
    assert rows["veg_1.jpg"]["predicted"] == "escalate_human"
    # The recorded failed cross-check is replayed, so it still escalates.
    assert rows["paper_1.jpg"]["predicted"] == "escalate_human"
    assert rows["paper_1.jpg"]["gates"]["manifest_crosscheck"] == "failed"
    assert rows["textile_1.jpg"]["recorded_predicted"] == "escalate_human"
    for name in ("metal_1.jpg", "textile_1.jpg", "glass_1.jpg"):
        assert rows[name]["provenance"] == "replay"
        assert rows[name]["source_provenance"] == "live"
        assert "latency_ms" not in rows[name]  # nothing was re-measured


def test_recorded_error_rows_stay_error_rows(replayed):
    food = replayed["rows"]["food_1.jpg"]
    assert food["predicted"] is None and food["error"] == "HTTP 503: ReadTimeout"
    assert replayed["summary"]["errors"] == 1


def test_summary_kind_framing_and_disclosure(replayed):
    s = replayed["summary"]
    assert s["kind"] == "replay"
    assert s["source_run"] == "2026-10-13"
    assert s["framing"] == (
        "Re-scored: the recorded live model outputs of the 2026-10-13 AMD Token Factory run, "
        "replayed through the current decision rules. No new model calls."
    )
    assert "motivated by this same run" in s["disclosure"]
    assert "not a held-out" in s["disclosure"]
    assert s["provenance"] == ["replay"] and s["source_provenance"] == ["live"]
    assert s["latency_ms"] == {"p50": None, "p95": None}
    assert s["rescored_on"] == "2026-10-14"
    written = json.loads((replayed["results"] / "2026-10-13.rescore.summary.json").read_text(
        encoding="utf-8"))
    assert written == s


def test_summary_metrics_and_changes(replayed):
    s = replayed["summary"]
    # expected accept: textile, plastic -> accept; paper -> escalate (failed cross-check)
    assert s["confusion"]["accept"] == {"reject": 0, "escalate": 1, "accept": 2, "error": 0}
    assert s["recorded_confusion"]["accept"] == {"reject": 1, "escalate": 2, "accept": 0, "error": 0}
    assert s["clean_accept_rate"] == pytest.approx(2 / 3)
    assert s["clean_escalate_rate"] == pytest.approx(1 / 3)
    assert s["clean_reject_rate"] == 0.0
    # non-error rows 6; escalated: glass, veg, paper
    assert s["review_rate"] == pytest.approx(3 / 6)
    # expected escalate: glass, veg (escalated), food (error) -> 2/3
    assert s["escalate_recall"] == pytest.approx(2 / 3)
    assert {c["image"] for c in s["changed"]} == {"textile_1.jpg", "plastic_1.jpg"}
    assert s["gates_changed"] == []


def test_live_source_untouched_and_globals_restored(replayed):
    assert replayed["source"].read_text(encoding="utf-8") == replayed["source_text"]
    assert pipeline.resolve_clients is replayed["original_resolve"]
    assert os.environ.get("LYNCEUS_GAS_SENSOR_URL") == "http://gas.invalid"


def test_plain_replay_runs_with_the_detector_off(replayed):
    # The recorded run had no detector: the replay states the gate not_run.
    for row in replayed["rows"].values():
        if not row.get("error"):
            assert row["gates"]["detector_second_opinion"] == "not_run"


# ---------------------------------------------------------------------------
# Hybrid what-if: the same recorded rows fused with recorded detections.
# ---------------------------------------------------------------------------


def _boxes(*pairs):
    return {"boxes": [{"label": label, "confidence": conf, "box": [0.1, 0.1, 0.5, 0.5]}
                      for label, conf in pairs], "latency_ms": None}


HYBRID_RECORDED = [
    _row("metal_1.jpg", "Metal", "reject", "reject", hard=["metal"], prose="metal can"),
    # The VLM missed this metal item; the detector did not.
    _row("metal_2.jpg", "Metal", "reject", "accept"),
    # The VLM missed this glass item; only light escalation catches it.
    _row("glass_1.jpg", "Glass", "escalate", "accept"),
    _row("paper_1.jpg", "Paper", "accept", "accept"),
]
DETECTIONS = {
    "metal_1.jpg": _boxes(("metal", 0.96)),
    "metal_2.jpg": _boxes(("metal", 0.4)),  # above the 0.35 default, below 0.5
    "glass_1.jpg": _boxes(("glass", 0.8)),
    "paper_1.jpg": _boxes(("paper", 0.9)),
}


@pytest.fixture
def hybrid(tmp_path, monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("the replay must not touch the network")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", no_network)
    monkeypatch.setattr(httpx, "get", no_network)
    images = tmp_path / "images"
    images.mkdir()
    for row in HYBRID_RECORDED:  # distinct bytes: detections are matched by photo digest
        (images / row["image"]).write_bytes(JPEG + row["image"].encode("ascii"))
    manifest = tmp_path / "manifest.csv"
    manifest.write_text("image,category,expected\n" + "".join(
        f"{r['image']},x,y\n" for r in HYBRID_RECORDED), encoding="utf-8")
    source = tmp_path / "2026-10-13.jsonl"
    source.write_text("".join(json.dumps(r) + "\n" for r in HYBRID_RECORDED), encoding="utf-8")
    out = tmp_path / "2026-10-16.hybrid-rescore.summary.json"
    original_detect = pipeline.safe_detect
    summary = rescore.hybrid_rescore(source, DETECTIONS, detections_source="test",
                                     detector_runtime="ultralytics-predict",
                                     out=out, images_dir=images, manifest=manifest,
                                     log=lambda m: None, today="2026-10-16")
    assert pipeline.safe_detect is original_detect  # restored after every variant
    return {"summary": summary, "out": out}


def test_hybrid_variants(hybrid):
    s = hybrid["summary"]
    assert s["kind"] == "hybrid_replay" and "separate val split" in s["disclosure"]
    assert s["detector"]["model"] == detector.model_name(str(config.BUNDLED_DETECTOR_MODEL))
    assert (s["detector"]["hard_conf_default"], s["detector"]["light_conf"]) == (0.35, 0.05)
    assert json.loads(hybrid["out"].read_text(encoding="utf-8")) == s
    # The summary names what produced the boxes, not a runtime it did not use.
    assert s["detector"]["runtime"] == "ultralytics-predict"
    t = s["table"]
    assert t["vlm_only"]["metal_accepted"] == 1
    assert t["hybrid_light_escalation_on"]["metal_accepted"] == 0
    assert t["hybrid_light_escalation_on"]["escalate_recall"] == 1.0
    assert t["hybrid_light_escalation_off"]["escalate_recall"] == 0.0
    # The detector alone never rejects: metal recall stays the VLM's.
    assert t["hybrid_light_escalation_on"]["metal_reject_recall"] == 0.5
    changed = {c["image"]: c for c in
               s["variants"]["hybrid_light_escalation_on"]["changed_vs_vlm_only"]}
    assert set(changed) == {"metal_2.jpg", "glass_1.jpg"}
    assert changed["metal_2.jpg"]["hybrid"] == "escalate"
    # At 0.5 the 0.4 metal box no longer holds the truck; at 0.1 it does.
    assert s["sweep_detector_hard_conf"]["0.5"]["light_escalation_off"]["metal_accepted"] == 1
    assert s["sweep_detector_hard_conf"]["0.1"]["light_escalation_off"]["metal_accepted"] == 0


@pytest.mark.parametrize("name", ["2026-10-16.hybrid-rescore.summary.json",
                                  "2026-10-16.hybrid-rescore.realwaste-taco.summary.json",
                                  "2026-10-17.hybrid-rescore.realwaste-taco-m.summary.json"])
def test_committed_hybrid_summary_was_produced_by_lynceus_detector(name):
    path = Path(rescore.__file__).resolve().parent / "results" / name
    d = json.loads(path.read_text(encoding="utf-8"))["detector"]
    assert d["runtime"] == "onnxruntime-cpu" and d["detections_source"].startswith("lynceus.detector")
    assert d["model_sha256"].startswith("sha256:")


def test_committed_summary_of_the_bundled_model_matches_its_weights():
    import hashlib

    from lynceus import config, decision, detector

    path = (Path(rescore.__file__).resolve().parent / "results"
            / "2026-10-17.hybrid-rescore.realwaste-taco-m.summary.json")
    d = json.loads(path.read_text(encoding="utf-8"))["detector"]
    digest = hashlib.sha256(config.BUNDLED_DETECTOR_MODEL.read_bytes()).hexdigest()
    # The committed numbers describe the shipped weights at the shipped defaults.
    assert d["model"] == detector.MODEL_NAME and d["model_sha256"] == "sha256:" + digest
    assert (d["hard_conf_default"], d["light_conf"]) == (
        decision.DETECTOR_HARD_CONFIDENCE, decision.DETECTOR_LIGHT_CONFIDENCE)


def test_hybrid_degraded_mode_holds_every_truck(hybrid):
    d = hybrid["summary"]["variants"]["detector_only_degraded"]
    assert d["confusion"]["accept"]["escalate"] == 1 and d["review_rate"] == 1.0
    assert d["errors"] == 0
    f = d["detector_findings"]
    assert f["thresholds"] == {"hard": 0.35, "light": 0.05}
    assert f["by_expected"]["reject"] == {"n": 2, "metal": 2, "light": 0, "nothing": 0}
    assert f["by_expected"]["accept"]["nothing"] == 1
    assert f["advisory_gate"] == "4/4"
