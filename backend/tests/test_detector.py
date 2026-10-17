"""CPU detector second opinion: runtime, fusion, degraded mode, audit, API.

The runtime tests run the bundled ONNX model on committed benchmark images;
everything else stubs ``detector.detect`` so verdicts are deterministic.  No
test touches the network.
"""

from __future__ import annotations

import base64
import io
import json
import time
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from lynceus import api, audit, config, decision, detector, pipeline
from lynceus.api import create_app
from lynceus.config import LYNCEUS_STORAGE_DIR_ENV, get_settings

D = audit.Decision
G = audit.GateState
IMAGES = Path(__file__).resolve().parents[1] / "benchmark" / "images"

_MANIFEST = "Declared weight: 5,200 kg. Mixed RDF feedstock."
_INPUTS = {"photo_base64": "x", "manifest_text": _MANIFEST, "weight_kg": 5200,
           "declared_weight_kg": 5200}
_ENGINE = {"recommendation": {"actionable": True, "route": "rdf", "tied": False}}


def _vlm(hard=(), light=(), confidence=0.9):
    return {
        "detected": {"contamination": "none detected", "moisture": 0.05,
                     "hard_contaminants": list(hard), "light_contaminants": list(light)},
        "confidence": confidence,
    }


_LLM = {"confidence": 0.9, "crosscheck_failed": False}


def _det(*boxes):
    """A detector result from ``(label, confidence)`` pairs."""
    return detector.summarize(
        [{"label": label, "confidence": conf, "box": [0.1, 0.1, 0.6, 0.6]}
         for label, conf in boxes],
        150.0, 0.25, 0.25,
    )


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def test_settings_default_to_the_bundled_model(monkeypatch):
    for name in ("DETECTOR_MODEL_PATH", "DETECTOR_HARD_CONF", "DETECTOR_LIGHT_CONF",
                 "DETECTOR_ESCALATE_LIGHT"):
        monkeypatch.delenv(name, raising=False)
    s = get_settings()
    assert config.BUNDLED_DETECTOR_MODEL.is_file()
    assert s.detector_model_path == str(config.BUNDLED_DETECTOR_MODEL)
    assert (s.detector_hard_conf, s.detector_light_conf, s.detector_escalate_light) == (
        0.35, 0.05, True)


def test_decision_and_config_share_the_detector_defaults():
    s = config.Settings("v", "l", "vm", "lm", "a", "am", "e", "em", "box", "", True,
                        "./runs", 1, "0")
    assert (decision.DETECTOR_HARD_CONFIDENCE, decision.DETECTOR_LIGHT_CONFIDENCE) == (
        s.detector_hard_conf, s.detector_light_conf)


def test_settings_empty_path_disables_and_bad_thresholds_keep_defaults(monkeypatch):
    monkeypatch.setenv("DETECTOR_MODEL_PATH", "")
    monkeypatch.setenv("DETECTOR_HARD_CONF", "lots")
    monkeypatch.setenv("DETECTOR_LIGHT_CONF", "1.5")
    monkeypatch.setenv("DETECTOR_ESCALATE_LIGHT", "0")
    s = get_settings()
    assert s.detector_model_path == ""
    assert s.detector_hard_conf == 0.35 and s.detector_light_conf == 0.05
    assert s.detector_escalate_light is False
    assert detector.enabled(s) is False
    assert detector.detect(b"\xff\xd8\xff", s) is None


def test_settings_keep_older_positional_construction():
    """New fields sit at the end with defaults: older Settings(...) calls work."""
    s = config.Settings("v", "l", "vm", "lm", "a", "am", "e", "em", "box", "", True,
                        "./runs", 1, "0")
    assert s.detector_model_path == "" and s.detector_hard_conf == 0.35


# ---------------------------------------------------------------------------
# Runtime (the bundled ONNX model, no network)
# ---------------------------------------------------------------------------


def test_detect_finds_metal_on_a_metal_image():
    result = detector.detect((IMAGES / "metal_1.jpg").read_bytes())
    assert result["model"] == "yolo26s-realwaste-taco"
    assert result["runtime"] == "onnxruntime-cpu"
    assert result["latency_ms"] > 0
    assert result["hard_contaminants"] == ["metal"]
    top = result["boxes"][0]
    assert top["label"] == "metal" and top["confidence"] >= 0.9
    x0, y0, x1, y1 = top["box"]
    assert 0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1
    # The output is exactly what the audit schema accepts.
    audit.DetectorOutput.model_validate(result)


def test_feedstock_classes_never_flag():
    result = detector.detect((IMAGES / "paper_51.jpg").read_bytes())
    assert {b["label"] for b in result["boxes"]} == {"paper", "plastic"}
    assert result["hard_contaminants"] == [] and result["light_contaminants"] == []


def test_detect_reads_png_and_raises_on_garbage():
    buf = io.BytesIO()
    Image.new("RGB", (64, 48), (90, 90, 90)).save(buf, format="PNG")
    result = detector.detect(buf.getvalue(), min_conf=0.99)
    assert result["boxes"] == []
    with pytest.raises(Exception):
        detector.detect(b"\xff\xd8\xff\xe0not-a-jpeg")
    # The pipeline wrapper turns that into None instead.
    assert pipeline.safe_detect(b"\xff\xd8\xff\xe0not-a-jpeg", get_settings()) is None


def test_flagged_applies_thresholds_and_label_mapping():
    result = _det(("metal", 0.3), ("organic", 0.2), ("glass", 0.5), ("plastic", 0.99))
    assert detector.flagged(result, 0.25, 0.25) == ({"metal": 0.3}, {"glass": 0.5})
    assert detector.flagged(result, 0.5, 0.1) == (
        {}, {"glass": 0.5, "organic_residue": 0.2})
    assert result["hard_contaminants"] == ["metal"]
    assert result["light_contaminants"] == ["glass"]


# ---------------------------------------------------------------------------
# Fusion in decision.decide
# ---------------------------------------------------------------------------


def test_decide_without_detector_is_unchanged_and_states_not_run():
    verdict, gates, reasons = decision.decide(_INPUTS, _vlm(), _LLM, _ENGINE)
    assert verdict == D.ACCEPT
    assert gates["detector_second_opinion"]["state"] == G.NOT_RUN


def test_unconfirmed_detector_metal_escalates_never_rejects():
    verdict, gates, reasons = decision.decide(
        _INPUTS, _vlm(), _LLM, _ENGINE, _det(("metal", 0.93)))
    assert verdict == D.ESCALATE_HUMAN
    assert reasons == [
        "Detector (YOLO26s) flagged metal (0.93) that the vision model did not confirm; "
        "hold for a manual check."
    ]
    gate = gates["detector_second_opinion"]
    assert gate["state"] == G.FAILED and gate["value"] == 0.93 and gate["threshold"] == 0.35


def test_detector_metal_below_vlm_trust_still_holds_the_truck():
    # The VLM listed metal but under its 0.6 trust bar: not a confirmation.
    verdict, _, _ = decision.decide(
        _INPUTS, _vlm(hard=["metal"], confidence=0.5), _LLM, _ENGINE, _det(("metal", 0.9)))
    assert verdict == D.ESCALATE_HUMAN


def test_confirmed_metal_rejects_and_the_gate_passes():
    verdict, gates, reasons = decision.decide(
        _INPUTS, _vlm(hard=["metal"]), _LLM, _ENGINE, _det(("metal", 0.95)))
    assert verdict == D.REJECT
    assert gates["detector_second_opinion"]["state"] == G.PASSED
    assert "agree" in gates["detector_second_opinion"]["reason"]


def test_detector_metal_under_threshold_does_not_move_the_verdict():
    verdict, gates, _ = decision.decide(
        _INPUTS, _vlm(), _LLM, _ENGINE, _det(("metal", 0.2)), detector_hard_conf=0.25)
    assert verdict == D.ACCEPT
    assert gates["detector_second_opinion"]["state"] == G.PASSED


def test_light_escalation_is_switchable():
    det = _det(("glass", 0.88))
    on = decision.decide(_INPUTS, _vlm(), _LLM, _ENGINE, det)
    off = decision.decide(_INPUTS, _vlm(), _LLM, _ENGINE, det, detector_escalate_light=False)
    assert on[0] == D.ESCALATE_HUMAN
    assert "flagged glass (0.88)" in on[2][0]
    assert off[0] == D.ACCEPT
    assert off[1]["detector_second_opinion"]["state"] == G.PASSED
    assert "set not to escalate" in off[1]["detector_second_opinion"]["reason"]


def test_light_finding_the_vlm_reported_is_a_confirmation():
    verdict, gates, reasons = decision.decide(
        _INPUTS, _vlm(light=["organic_residue"]), _LLM, _ENGINE, _det(("organic", 0.8)))
    assert verdict == D.ESCALATE_HUMAN
    assert gates["detector_second_opinion"]["state"] == G.PASSED
    assert not any("Detector" in r for r in reasons)


def test_refused_input_keeps_the_detector_gate_stated():
    verdict, gates, _ = decision.decide(
        {"manifest_text": _MANIFEST}, None, _LLM, _ENGINE, _det(("metal", 0.9)))
    assert verdict == D.REFUSE_INSUFFICIENT_INPUT
    assert gates["detector_second_opinion"]["state"] == G.NOT_EVALUATED


def test_decide_degraded_always_escalates_and_lists_findings():
    verdict, gates, reasons = decision.decide_degraded(
        _det(("metal", 0.96), ("glass", 0.4)), "ReadTimeout: no reply")
    assert verdict == D.ESCALATE_HUMAN
    assert reasons[0].startswith("The AMD vision model was unavailable (ReadTimeout: no reply).")
    assert "metal (0.96)" in reasons[1] and "glass (0.40)" in reasons[2]
    assert gates["vlm_confidence"]["state"] == G.NOT_RUN
    assert gates["detector_second_opinion"]["state"] == G.FAILED
    clean = decision.decide_degraded(_det(("paper", 0.9)), "x", vision_label="live vision model")
    assert clean[0] == D.ESCALATE_HUMAN
    assert "cannot clear a load" in " ".join(clean[2])
    assert clean[2][0].startswith("The live vision model was unavailable")


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


class _Live:
    provenance = "live"

    def __init__(self, fail=False, fail_llm=False):
        self.fail = fail
        self.fail_llm = fail_llm

    def vlm(self, photo):
        if self.fail:
            raise httpx.ReadTimeout("no workers")
        return {**_vlm(), "model": "vlm-x", "raw_output": "{}"}

    def llm(self, text, context):
        if self.fail_llm:
            raise httpx.ReadTimeout("waybill model down")
        return {**_LLM, "reasoning": "ok", "model": "llm-y", "raw_output": "{}"}


_PHOTO = base64.b64encode((IMAGES / "metal_1.jpg").read_bytes()).decode("ascii")


def test_run_inspection_runs_the_detector_on_the_photo_bytes(monkeypatch):
    seen = []
    monkeypatch.setattr(detector, "detect", lambda raw, settings: seen.append(raw) or _det())
    out = pipeline.run_inspection({"photo_base64": "data:image/jpeg;base64," + _PHOTO},
                                  _Live(), precomputed_gas=None)
    assert seen == [(IMAGES / "metal_1.jpg").read_bytes()]
    assert out["detector"]["model"] == detector.MODEL_NAME
    assert out["provenance"] == "live"


def test_detector_failure_never_fails_the_inspection(monkeypatch, caplog):
    def boom(raw, settings):
        raise RuntimeError("onnx exploded")

    monkeypatch.setattr(detector, "detect", boom)
    out = pipeline.run_inspection({"photo_base64": _PHOTO}, _Live(), precomputed_gas=None)
    assert out["detector"] is None and out["vlm"]["model"] == "vlm-x"
    assert "onnx exploded" in caplog.text


def test_scripted_demo_without_photo_skips_the_detector(monkeypatch):
    monkeypatch.setattr(detector, "detect", lambda *a: pytest.fail("detector ran"))
    out = pipeline.run_inspection({"demo_case": "red", "photo_filename": "red-1.jpg"},
                                  pipeline.StubAIClients("red"), precomputed_gas=None)
    assert out["detector"] is None and out["provenance"] == "stub"


def test_live_failure_with_detector_is_degraded_not_503(monkeypatch):
    monkeypatch.setattr(detector, "detect", lambda raw, settings: _det(("metal", 0.9)))
    out = pipeline.run_inspection({"photo_base64": _PHOTO}, _Live(fail=True),
                                  allow_stub_fallback=False, precomputed_gas=None)
    assert out["provenance"] == pipeline.DEGRADED_PROVENANCE
    assert out["vlm"] is None and out["llm"] is None
    assert out["detector"]["hard_contaminants"] == ["metal"]
    assert "ReadTimeout" in out["fallback_reason"]
    assert out["failed_stage"] == "vlm"


def test_waybill_failure_is_degraded_and_names_the_llm_stage(monkeypatch):
    monkeypatch.setattr(detector, "detect", lambda raw, settings: _det(("metal", 0.9)))
    out = pipeline.run_inspection({"photo_base64": _PHOTO}, _Live(fail_llm=True),
                                  allow_stub_fallback=False, precomputed_gas=None)
    assert out["provenance"] == pipeline.DEGRADED_PROVENANCE
    assert out["failed_stage"] == "llm"
    # The vision answer is not fused without its waybill check.
    assert out["vlm"] is None and out["llm"] is None


def test_live_failure_without_detector_still_raises(monkeypatch):
    monkeypatch.setattr(detector, "detect", lambda raw, settings: None)
    with pytest.raises(pipeline.LiveAIUnavailableError):
        pipeline.run_inspection({"photo_base64": _PHOTO}, _Live(fail=True),
                                allow_stub_fallback=False, precomputed_gas=None)


# ---------------------------------------------------------------------------
# Audit schema
# ---------------------------------------------------------------------------


def test_detector_box_validation():
    ok = {"label": "metal", "confidence": 0.5, "box": [0.1, 0.2, 0.3, 0.4]}
    audit.DetectorBox.model_validate(ok)
    for bad in ({**ok, "box": [0.3, 0.2, 0.1, 0.4]}, {**ok, "box": [0.1, 0.2, 0.3]},
                {**ok, "box": [0.1, 0.2, 1.3, 0.4]}, {**ok, "confidence": 1.2},
                {**ok, "extra": 1}):
        with pytest.raises(Exception):
            audit.DetectorBox.model_validate(bad)


def test_a_record_written_before_the_detector_still_loads(tmp_path):
    rec = audit.begin_record(tmp_path, {"name": "lynceus", "version": "0"}, {
        "truck_id": "T-1",
        "photo": {"filename": "p.jpg", "sha256": audit.sha256_field(b""),
                  "captured_at_utc": audit.now_utc(), "provenance": "user_upload"},
        "manifest_text": {"source": "manual_text", "raw_text_sha256": audit.sha256_field(b""),
                          "extracted_fields": {}, "ocr_confidence": 0.95},
        "weight": {"value_kg": 1.0, "source": "weighbridge", "measured_at_utc": audit.now_utc()},
        "gas": {"readings_ppm": {}, "source": "not_measured", "measured_at_utc": audit.now_utc()},
    }, {"photo": audit.sha256_field(b"")})
    path = tmp_path / rec.record_id / audit.RECORD_FILENAME
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert "detector" not in raw["ai_outputs"] and "detector_second_opinion" not in raw["gates"]
    loaded = audit.load_record(path)
    assert loaded.ai_outputs.detector is None and loaded.gates.detector_second_opinion is None


# ---------------------------------------------------------------------------
# API: hybrid and degraded inspections end to end
# ---------------------------------------------------------------------------

_BODY = {
    "truck_id": "B-1",
    "photo_base64": _PHOTO,
    "manifest_text": _MANIFEST,
    "weight_kg": 5200,
    "declared_weight_kg": 5200,
}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv(LYNCEUS_STORAGE_DIR_ENV, str(tmp_path))
    monkeypatch.setenv("LYNCEUS_ALLOW_STUB_FALLBACK", "0")
    monkeypatch.setenv("VLLM_VLM_URL", "https://developer.amd.com.cn/radeon/api/v1")
    monkeypatch.delenv("LYNCEUS_GAS_SENSOR_URL", raising=False)
    return TestClient(create_app())


def test_inspect_fuses_the_detector_and_records_it(client, tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "resolve_clients", lambda payload, settings=None: _Live())
    monkeypatch.setattr(detector, "detect", lambda raw, settings: _det(("metal", 0.93)))
    resp = client.post("/inspect", json=_BODY)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["verdict"]["decision"] == D.ESCALATE_HUMAN
    assert body["gates"]["detector_second_opinion"]["state"] == G.FAILED
    assert body["ai_outputs"]["detector"]["hard_contaminants"] == ["metal"]
    record = audit.load_record(tmp_path / body["record_id"] / audit.RECORD_FILENAME)
    assert record.ai_outputs.detector.boxes[0].confidence == 0.93
    assert record.gates.detector_second_opinion.state == G.FAILED


def test_probe_failure_with_detector_returns_a_degraded_verdict(client, tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "_vlm_reachable", lambda *a, **k: False)
    monkeypatch.setattr(detector, "detect", lambda raw, settings: _det(("metal", 0.96)))
    resp = client.post("/inspect", json=_BODY)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["provenance"] == "detector_only_degraded"
    assert body["verdict"]["decision"] == D.ESCALATE_HUMAN
    assert body["reasons"][0].startswith("The AMD vision model was unavailable (")
    assert "metal (0.96)" in body["reasons"][1]
    uncertainty = body["verdict"]["uncertainty"]
    assert "detector_only_degraded" in uncertainty and "was unavailable" in uncertainty
    assert "stub used" not in uncertainty
    record = audit.load_record(tmp_path / body["record_id"] / audit.RECORD_FILENAME)
    assert record.ai_outputs.vlm.model == "unavailable"
    assert record.ai_outputs.vlm.confidence == 0.0
    assert record.ai_outputs.detector.hard_contaminants == ["metal"]
    assert record.verdict.decision == D.ESCALATE_HUMAN


def test_pipeline_failure_with_detector_returns_a_degraded_verdict(client, monkeypatch):
    monkeypatch.setattr(pipeline, "resolve_clients",
                        lambda payload, settings=None: _Live(fail=True))
    monkeypatch.setattr(detector, "detect", lambda raw, settings: _det(("glass", 0.7)))
    body = client.post("/inspect", json=_BODY).json()
    assert body["provenance"] == "detector_only_degraded"
    assert body["verdict"]["decision"] == D.ESCALATE_HUMAN
    assert "ReadTimeout" in body["reasons"][0]
    assert body["failed_stage"] == "vlm"


def test_waybill_failure_is_worded_as_a_waybill_failure(client, monkeypatch):
    monkeypatch.setattr(pipeline, "resolve_clients",
                        lambda payload, settings=None: _Live(fail_llm=True))
    monkeypatch.setattr(detector, "detect", lambda raw, settings: _det(("glass", 0.7)))
    body = client.post("/inspect", json=_BODY).json()
    assert body["provenance"] == "detector_only_degraded"
    assert body["failed_stage"] == "llm"
    assert body["verdict"]["decision"] == D.ESCALATE_HUMAN
    assert body["reasons"][0].startswith("The waybill model was unavailable (")
    assert "vision answer was not fused and is discarded" in body["reasons"][0]
    uncertainty = body["verdict"]["uncertainty"]
    assert "waybill model was unavailable" in uncertainty
    assert "vision model was unavailable" not in uncertainty
    assert "no vision-language" not in uncertainty
    assert "vision answer was discarded" in body["engine_outputs"]["suitability"]["rule"]
    gate = body["gates"]["vlm_confidence"]
    assert gate["state"] == G.NOT_RUN and "waybill model" in gate["reason"]


def test_ok_run_reports_no_failed_stage(client, monkeypatch):
    monkeypatch.setattr(pipeline, "resolve_clients", lambda payload, settings=None: _Live())
    monkeypatch.setattr(detector, "detect", lambda raw, settings: _det())
    body = client.post("/inspect", json=_BODY).json()
    assert body["provenance"] == "live" and body["failed_stage"] is None


def test_probe_failure_without_detector_is_still_503_and_leaves_no_record(
    client, tmp_path, monkeypatch
):
    monkeypatch.setattr(pipeline, "_vlm_reachable", lambda *a, **k: False)
    monkeypatch.setattr(detector, "detect", lambda raw, settings: None)
    resp = client.post("/inspect", json=_BODY)
    assert resp.status_code == 503
    assert resp.json()["detail"]["error"] == "live_ai_unavailable"
    assert list(tmp_path.glob("inspection-*")) == []


def test_a_hybrid_rescore_summary_is_never_served_as_a_run(tmp_path, monkeypatch):
    results = tmp_path / "results"
    results.mkdir()
    (results / "2026-10-13.summary.json").write_text(json.dumps({"date": "2026-10-13"}))
    (results / "2026-10-13.rescore.summary.json").write_text(
        json.dumps({"kind": "replay", "source_run": "2026-10-13"}))
    (results / "2026-10-16.hybrid-rescore.summary.json").write_text(
        json.dumps({"kind": "hybrid_replay", "date": "2026-10-16"}))
    monkeypatch.setattr(api, "_BENCHMARK_DIR", tmp_path)
    c = TestClient(create_app())
    assert c.get("/benchmark/latest").json()["date"] == "2026-10-13"
    assert c.get("/benchmark/replay").json()["kind"] == "replay"


def test_summaries_are_allow_listed_by_kind_not_file_name(tmp_path, monkeypatch):
    results = tmp_path / "results"
    results.mkdir()
    (results / "2026-10-13.summary.json").write_text(json.dumps({"date": "2026-10-13"}))
    # Newer, and named like a live run, but a what-if: never served as live.
    (results / "2026-10-18.summary.json").write_text(
        json.dumps({"kind": "hybrid_replay", "date": "2026-10-18"}))
    # No kind and not a plain dated name: not a live run either.
    (results / "2026-10-17-partial.summary.json").write_text(json.dumps({"date": "2026-10-17"}))
    monkeypatch.setattr(api, "_BENCHMARK_DIR", tmp_path)
    c = TestClient(create_app())
    assert c.get("/benchmark/latest").json()["date"] == "2026-10-13"
    # A summary that says it is live counts whatever its name.
    (results / "2026-10-19-gate.summary.json").write_text(
        json.dumps({"kind": "live", "date": "2026-10-19"}))
    assert c.get("/benchmark/latest").json()["date"] == "2026-10-19"


def test_committed_live_summary_is_still_served():
    body = TestClient(create_app()).get("/benchmark/latest").json()
    assert body["date"] == "2026-10-13" and body["replay"]["kind"] == "replay"


# ---------------------------------------------------------------------------
# Review fixes: fallback cap, threshold units, wording, degraded refusal
# ---------------------------------------------------------------------------


def _fallback_vlm(model, **kw):
    return {**_vlm(**kw), "model": model,
            "fallback_from": ["MiniCPM-V-4.7-35B-A3B: HTTPStatusError after 2.0 s"]}


def test_unbenchmarked_fallback_model_cannot_accept():
    verdict, _, reasons = decision.decide(_INPUTS, _fallback_vlm("Other-VL"), _LLM, _ENGINE)
    assert verdict == D.ESCALATE_HUMAN
    assert "Other-VL" in reasons[0] and "no benchmark run" in reasons[0]
    assert "cannot accept or reject a load on its own" in reasons[0]
    assert "MiniCPM-V-4.7-35B-A3B: HTTPStatusError" in reasons[0]


def test_unbenchmarked_fallback_model_cannot_reject_either():
    verdict, _, reasons = decision.decide(
        _INPUTS, _fallback_vlm("Other-VL", hard=["metal"]), _LLM, _ENGINE)
    assert verdict == D.ESCALATE_HUMAN
    assert "Other-VL" in reasons[0] and "cannot accept or reject" in reasons[0]
    # The would-be reject grounds stay visible to the human.
    assert any("Hard contamination detected" in r for r in reasons[1:])
    # A low-confidence reject is capped the same way, and the detector's
    # unconfirmed finding is then a hold, not "outranked".
    verdict, gates, reasons = decision.decide(
        _INPUTS, _fallback_vlm("Other-VL", confidence=0.1), _LLM, _ENGINE,
        _det(("metal", 0.93)))
    assert verdict == D.ESCALATE_HUMAN
    assert gates["detector_second_opinion"]["reason"].endswith(
        "The truck is held for a manual check.")
    assert any("manual check" in r and "metal" in r for r in reasons)
    # A benchmarked fallback still rejects.
    benchmarked = decision.decide(
        _INPUTS, _fallback_vlm("Other-VL", hard=["metal"]), _LLM, _ENGINE,
        benchmarked_vlm_models=("Other-VL",))
    assert benchmarked[0] == D.REJECT


def test_vlm_output_records_fallback_from_and_old_records_load():
    base = {"model": "Other-VL", "model_version": "Other-VL",
            "raw_output_sha256": audit.sha256_field(b"{}"), "detected": {}, "confidence": 0.8}
    assert audit.VLMOutput(**base).fallback_from is None  # older records
    chain = ["MiniCPM-V-4.7-35B-A3B: HTTPStatusError after 2.0 s"]
    assert audit.VLMOutput(**base, fallback_from=chain).fallback_from == chain


def test_inspect_records_the_vision_fallback_chain(client, tmp_path, monkeypatch):
    chain = ["MiniCPM-V-4.7-35B-A3B: HTTPStatusError after 2.0 s"]

    class _Fallback(_Live):
        def vlm(self, photo):
            return {**super().vlm(photo), "model": "Other-VL", "fallback_from": chain}

    monkeypatch.setattr(pipeline, "resolve_clients", lambda payload, settings=None: _Fallback())
    monkeypatch.setattr(detector, "detect", lambda raw, settings: _det())
    body = client.post("/inspect", json=_BODY).json()
    assert body["ai_outputs"]["vlm"]["fallback_from"] == chain
    assert body["verdict"]["decision"] == D.ESCALATE_HUMAN  # unbenchmarked fallback
    record = audit.load_record(tmp_path / body["record_id"] / audit.RECORD_FILENAME)
    assert record.ai_outputs.vlm.fallback_from == chain


def test_vlm_result_without_confidence_never_accepts():
    verdict, gates, _ = decision.decide({"photo_base64": "x", "manifest_text": "m"}, {}, {}, None)
    assert verdict == D.REFUSE_INSUFFICIENT_INPUT
    assert gates["missing"] == ["vlm_result"]
    no_conf = {k: v for k, v in _vlm().items() if k != "confidence"}
    assert decision.decide(_INPUTS, no_conf, _LLM, _ENGINE)[0] == D.REFUSE_INSUFFICIENT_INPUT
    bad = {**_vlm(), "confidence": "0.9"}
    assert decision.decide(_INPUTS, bad, _LLM, _ENGINE)[0] == D.REFUSE_INSUFFICIENT_INPUT


def test_degraded_detector_silence_is_not_a_green_pass():
    _, gates, reasons = decision.decide_degraded(_det(), "ReadTimeout", inputs=_INPUTS)
    gate = gates["detector_second_opinion"]
    assert gate["state"] == G.NOT_EVALUATED and "not a clearance" in gate["reason"]
    assert reasons[0].startswith("The AMD vision model was unavailable (ReadTimeout).")


def test_degraded_llm_stage_wording():
    _, gates, reasons = decision.decide_degraded(
        _det(("metal", 0.9)), "ReadTimeout", inputs=_INPUTS, failed_stage="llm")
    assert reasons[0].startswith("The waybill model was unavailable (ReadTimeout)")
    assert "vision answer was not fused and is discarded" in reasons[0]
    assert not any("vision model was unavailable" in r for r in reasons)
    assert "waybill model" in gates["vlm_confidence"]["reason"]


def test_benchmarked_fallback_or_primary_answer_accepts():
    benchmarked = decision.decide(
        _INPUTS, _fallback_vlm("Other-VL"), _LLM, _ENGINE,
        benchmarked_vlm_models=("Other-VL",))
    assert benchmarked[0] == D.ACCEPT
    # No fallback happened: the allow-list does not apply to the primary.
    primary = decision.decide(_INPUTS, {**_vlm(), "model": "Other-VL"}, _LLM, _ENGINE)
    assert primary[0] == D.ACCEPT


def test_benchmarked_models_setting(monkeypatch):
    monkeypatch.delenv("VLM_BENCHMARKED_MODELS", raising=False)
    assert get_settings().vlm_benchmarked_models == ("MiniCPM-V-4.7-35B-A3B",)
    monkeypatch.setenv("VLM_BENCHMARKED_MODELS", " a, b ,a")
    assert get_settings().vlm_benchmarked_models == ("a", "b")
    monkeypatch.setenv("VLM_BENCHMARKED_MODELS", "")
    assert get_settings().vlm_benchmarked_models == ()


def test_detector_gate_threshold_matches_the_value_class():
    det = _det(("metal", 0.3), ("glass", 0.9))
    _, gates, _ = decision.decide(_INPUTS, _vlm(), _LLM, _ENGINE, det,
                                  detector_hard_conf=0.25, detector_light_conf=0.5)
    gate = gates["detector_second_opinion"]
    assert (gate["value"], gate["threshold"]) == (0.9, 0.5)  # glass, light threshold
    _, gates, _ = decision.decide(_INPUTS, _vlm(), _LLM, _ENGINE, _det(("metal", 0.3)),
                                  detector_hard_conf=0.25, detector_light_conf=0.5)
    assert (gates["detector_second_opinion"]["value"],
            gates["detector_second_opinion"]["threshold"]) == (0.3, 0.25)
    _, gates, _ = decision.decide_degraded(det, "x", detector_hard_conf=0.25,
                                           detector_light_conf=0.5)
    assert (gates["detector_second_opinion"]["value"],
            gates["detector_second_opinion"]["threshold"]) == (0.9, 0.5)


def test_detector_gate_wording_follows_the_verdict():
    held = decision.decide(_INPUTS, _vlm(), _LLM, _ENGINE, _det(("metal", 0.93)))
    assert held[0] == D.ESCALATE_HUMAN
    assert held[1]["detector_second_opinion"]["reason"].endswith(
        "The truck is held for a manual check.")
    # A weight mismatch rejects: the detector gate must not claim a hold.
    heavy = {**_INPUTS, "weight_kg": 9000}
    rejected = decision.decide(heavy, _vlm(), _LLM, _ENGINE, _det(("metal", 0.93)))
    assert rejected[0] == D.REJECT
    reason = rejected[1]["detector_second_opinion"]["reason"]
    assert "hold" not in reason.lower() and "held" not in reason.lower()
    assert "rejected on other grounds" in reason
    assert not any("manual check" in r for r in rejected[2])


def test_degraded_mode_refuses_missing_input_first():
    det = _det(("metal", 0.96))
    verdict, gates, reasons = decision.decide_degraded(
        det, "ReadTimeout", inputs={"photo_base64": "x", "manifest_text": "  "})
    assert verdict == D.REFUSE_INSUFFICIENT_INPUT
    assert gates["missing"] == ["manifest_text"]
    assert reasons == ["Mandatory input missing: manifest_text. The inspection cannot "
                       "proceed without it."]
    assert gates["detector_second_opinion"]["state"] == G.NOT_EVALUATED
    full = decision.decide_degraded(det, "ReadTimeout", inputs=_INPUTS)
    assert full[0] == D.ESCALATE_HUMAN


def test_degraded_api_without_manifest_refuses(client, monkeypatch):
    monkeypatch.setattr(pipeline, "_vlm_reachable", lambda *a, **k: False)
    monkeypatch.setattr(detector, "detect", lambda raw, settings: _det(("metal", 0.96)))
    body = client.post("/inspect", json={**_BODY, "manifest_text": ""}).json()
    assert body["provenance"] == "detector_only_degraded"
    assert body["verdict"]["decision"] == D.REFUSE_INSUFFICIENT_INPUT
    assert "refused" in body["verdict"]["uncertainty"]
    assert body["engine_outputs"]["recommendation"]["missing"] == ["manifest_text"]


def test_degraded_wording_claims_no_fusion(client, monkeypatch):
    monkeypatch.setattr(pipeline, "_vlm_reachable", lambda *a, **k: False)
    monkeypatch.setattr(detector, "detect", lambda raw, settings: _det(("glass", 0.7)))
    body = client.post("/inspect", json=_BODY).json()
    rule = body["engine_outputs"]["suitability"]["rule"]
    assert rule.startswith("detector-only degraded mode") and "fusion of" not in rule
    note = body["impact"]["note"]
    assert "no vision-language analysis was used" in note and "VLM reported" not in note


def test_ledger_rows_carry_the_detector_gate(client, monkeypatch):
    monkeypatch.setattr(pipeline, "resolve_clients", lambda payload, settings=None: _Live())
    monkeypatch.setattr(detector, "detect", lambda raw, settings: _det(("metal", 0.93)))
    assert client.post("/inspect", json=_BODY).status_code == 200
    rows = client.get("/inspections", headers={"accept": "application/json"}).json()
    assert rows["inspections"][0]["gate_states"]["detector_second_opinion"] == G.FAILED


# ---------------------------------------------------------------------------
# Review fixes: image limits, concurrency, threads, provenance, warm-up
# ---------------------------------------------------------------------------


def _png(size):
    buf = io.BytesIO()
    Image.new("RGB", size, (90, 90, 90)).save(buf, format="PNG")
    return buf.getvalue()


def test_oversized_photo_is_refused_before_decoding(monkeypatch):
    monkeypatch.setattr(detector, "MAX_PIXELS", 100)
    with pytest.raises(detector.DetectorImageError, match="over 100 pixels"):
        detector.detect(_png((20, 20)))
    assert pipeline.safe_detect(_png((20, 20)), get_settings()) is None


def test_decompression_bomb_error_is_refused(monkeypatch):
    # Over 2x Pillow's limit, Image.open itself raises DecompressionBombError.
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 1000)  # 64x48 = 3072 > 2x
    with pytest.raises(detector.DetectorImageError, match="image refused"):
        detector._decode(_png((64, 48)))


def test_max_pixels_is_below_pillows_bomb_warning():
    # The explicit header check must fire before Pillow would only warn.
    assert detector.MAX_PIXELS < Image.MAX_IMAGE_PIXELS


def test_jpeg_is_decoded_at_a_reduced_scale(monkeypatch):
    # Pillow picks the smallest DCT scale that keeps both sides >= the draft size.
    monkeypatch.setattr(detector, "_DRAFT_SIZE", (300, 300))
    buf = io.BytesIO()
    Image.new("RGB", (1300, 1000), (90, 90, 90)).save(buf, format="JPEG")
    assert detector._decode(buf.getvalue()).size == (650, 500)
    assert detector._decode(_png((1300, 1000))).size == (1300, 1000)  # PNG: no draft


def test_detector_runs_are_bounded(monkeypatch):
    monkeypatch.setattr(detector, "_SLOT_WAIT_S", 0.01)
    held = [detector._RUN_SLOTS.acquire(timeout=1) for _ in range(detector.MAX_CONCURRENT_RUNS)]
    try:
        assert all(held)
        with pytest.raises(RuntimeError, match="busy"):
            detector.detect(_png((64, 48)))
    finally:
        for _ in held:
            detector._RUN_SLOTS.release()
    assert detector.detect(_png((64, 48)), min_conf=0.99)["boxes"] == []


def test_png_has_a_lower_pixel_cap_than_jpeg(monkeypatch):
    # A PNG decodes at full size (no DCT scaling), so it gets its own cap.
    monkeypatch.setattr(detector, "MAX_PNG_PIXELS", 100)
    with pytest.raises(detector.DetectorImageError, match="PNG 20x20 is over 100 pixels"):
        detector._decode(_png((20, 20)))
    buf = io.BytesIO()
    Image.new("RGB", (20, 20), (90, 90, 90)).save(buf, format="JPEG")
    assert detector._decode(buf.getvalue()).size == (20, 20)


def test_only_jpeg_and_png_are_decoded():
    buf = io.BytesIO()
    Image.new("RGB", (20, 20), (90, 90, 90)).save(buf, format="GIF")
    with pytest.raises(detector.DetectorImageError, match="image refused"):
        detector._decode(buf.getvalue())
    assert pipeline.safe_detect(buf.getvalue(), get_settings()) is None


def test_phone_mpo_photo_is_decoded_at_a_reduced_scale(monkeypatch):
    monkeypatch.setattr(detector, "_DRAFT_SIZE", (300, 300))
    buf = io.BytesIO()
    # Two frames, as a phone writes it (one frame opens as plain JPEG).
    frame = Image.new("RGB", (1300, 1000), (90, 90, 90))
    frame.save(buf, format="MPO", save_all=True, append_images=[frame.copy()])
    assert Image.open(io.BytesIO(buf.getvalue())).format == "MPO"
    assert detector._decode(buf.getvalue()).size == (650, 500)


def test_a_busy_detector_refuses_a_no_wait_run_at_once():
    assert detector._settings_model(get_settings()) is not None  # model load not timed
    held = [detector._RUN_SLOTS.acquire(timeout=1) for _ in range(detector.MAX_CONCURRENT_RUNS)]
    try:
        assert all(held)
        started = time.perf_counter()
        with pytest.raises(RuntimeError, match="busy"):
            detector.detect(_png((64, 48)), slot_wait_s=0.0)
        assert time.perf_counter() - started < 1.0
    finally:
        for ok in held:
            if ok:
                detector._RUN_SLOTS.release()


def test_no_wait_runs_never_take_the_last_live_slot():
    # One no-wait (demo) run in flight: a second is refused while a run slot
    # is still free, and that slot stays usable by a live run.
    assert detector._NO_WAIT_SLOT.acquire(timeout=1)
    try:
        with pytest.raises(RuntimeError, match="no-wait run is already in flight"):
            detector.detect(_png((64, 48)), slot_wait_s=0.0)
        assert detector.detect(_png((64, 48)), min_conf=0.99)["boxes"] == []
    finally:
        detector._NO_WAIT_SLOT.release()
    assert detector.detect(_png((64, 48)), min_conf=0.99, slot_wait_s=0.0)["boxes"] == []


def test_scripted_demo_photo_never_waits_for_a_detector_slot(monkeypatch):
    seen = []

    def _detect(raw, settings, slot_wait_s=detector._SLOT_WAIT_S):
        seen.append(slot_wait_s)
        return _det()

    monkeypatch.setattr(detector, "detect", _detect)
    pipeline.run_inspection({"photo_base64": _PHOTO, "demo_case": "red"}, _Live(),
                            precomputed_gas=None)
    pipeline.run_inspection({"photo_base64": _PHOTO}, _Live(), precomputed_gas=None)
    assert seen == [0.0, detector._SLOT_WAIT_S]


def test_detector_threads_setting_and_session(monkeypatch):
    monkeypatch.setenv("DETECTOR_THREADS", "0")
    assert get_settings().detector_threads == 2
    monkeypatch.setenv("DETECTOR_THREADS", "3")
    assert get_settings().detector_threads == 3
    model = detector._Model(str(config.BUNDLED_DETECTOR_MODEL), threads=1)
    assert model.session.get_session_options().intra_op_num_threads == 1


def test_result_names_the_exact_weights_and_thresholds():
    import hashlib

    result = detector.detect((IMAGES / "metal_1.jpg").read_bytes())
    digest = hashlib.sha256(config.BUNDLED_DETECTOR_MODEL.read_bytes()).hexdigest()
    assert result["model_sha256"] == "sha256:" + digest
    assert result["thresholds"] == {"hard": 0.35, "light": 0.05, "escalate_light": True}
    parsed = audit.DetectorOutput.model_validate(result)
    assert parsed.thresholds.hard == 0.35 and parsed.model_sha256 == result["model_sha256"]


def test_model_name_comes_from_the_file_name():
    assert detector.model_name(str(config.BUNDLED_DETECTOR_MODEL)) == detector.MODEL_NAME
    assert detector.model_name("/srv/models/rdf-det-v2.onnx") == "rdf-det-v2"


def test_detector_block_without_the_new_fields_still_loads():
    old = {"model": "yolo26s-realwaste", "runtime": "onnxruntime-cpu", "latency_ms": 150.0,
           "boxes": [{"label": "metal", "confidence": 0.9, "box": [0.1, 0.1, 0.5, 0.5]}],
           "hard_contaminants": ["metal"], "light_contaminants": []}
    parsed = audit.DetectorOutput.model_validate(old)
    assert parsed.model_sha256 is None and parsed.thresholds is None
    for bad in ({**old, "model_sha256": "abc"},
                {**old, "thresholds": {"hard": 2.0, "light": 0.2, "escalate_light": True}},
                {**old, "thresholds": {"hard": 0.2, "light": 0.2}}):
        with pytest.raises(Exception):
            audit.DetectorOutput.model_validate(bad)


def test_app_startup_warms_the_detector(tmp_path, monkeypatch):
    monkeypatch.setenv(LYNCEUS_STORAGE_DIR_ENV, str(tmp_path))
    calls = []
    monkeypatch.setattr(detector, "warm", lambda *a: calls.append(1) or True)
    with TestClient(create_app()):
        assert calls == [1]


# ---------------------------------------------------------------------------
# Execution provider: the detector is CPU-only
# ---------------------------------------------------------------------------


def test_detector_providers_setting(monkeypatch):
    monkeypatch.delenv("DETECTOR_PROVIDERS", raising=False)
    s = get_settings()
    assert s.detector_providers == ("CPUExecutionProvider",)
    monkeypatch.setenv("DETECTOR_PROVIDERS", "CPUExecutionProvider")
    assert get_settings().detector_providers == ("CPUExecutionProvider",)
    monkeypatch.setenv("DETECTOR_PROVIDERS", " , ")
    assert get_settings().detector_providers == ("CPUExecutionProvider",)
    # Older Settings(...) calls get the CPU default.
    old = config.Settings("v", "l", "vm", "lm", "a", "am", "e", "em", "box", "", True,
                          "./runs", 1, "0")
    assert old.detector_providers == ("CPUExecutionProvider",)


def test_runtime_name_maps_providers():
    assert detector.runtime_name("CPUExecutionProvider") == "onnxruntime-cpu"
    assert detector.runtime_name("CUDAExecutionProvider") == "onnxruntime-cuda"


def test_model_cache_keys_on_threads_and_providers(monkeypatch):
    monkeypatch.setattr(detector, "_MODELS", {})
    cpu = detector._model(str(config.BUNDLED_DETECTOR_MODEL))
    assert detector._model(str(config.BUNDLED_DETECTOR_MODEL)) is cpu
    other = detector._model(str(config.BUNDLED_DETECTOR_MODEL), threads=1)
    assert other is not cpu


def test_warm_logs_once_when_disabled(monkeypatch, caplog):
    monkeypatch.setenv("DETECTOR_MODEL_PATH", "")
    monkeypatch.setattr(detector, "_DISABLED_LOGGED", False)
    assert detector.warm() is False
    assert detector.warm() is False
    assert caplog.text.count("detector disabled") == 1
    monkeypatch.delenv("DETECTOR_MODEL_PATH")
    assert detector.warm() is True
