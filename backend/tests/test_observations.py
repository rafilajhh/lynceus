"""Gate sensor observations, per-read vision votes, and the offline stub's
handling of the bundled demo photos.  No network: see test_intake.py."""

from __future__ import annotations

import base64
import io
import json

import pytest
from fastapi.testclient import TestClient

from lynceus import api, audit, decision, observations, pipeline, waybill
from lynceus.api import create_app
from lynceus.config import LYNCEUS_STORAGE_DIR_ENV, get_settings

DEMO = waybill.SAMPLE_WAYBILL_PATH.parent
needs_demo = pytest.mark.skipif(not DEMO.is_dir(), reason="bundled demo photos missing")
NOW = "2026-10-17T10:00:00Z"
CONFIRMED_FIELDS = waybill.values_of(waybill.SAMPLE_FIELDS)


def _jpeg(tag: bytes) -> str:
    return base64.b64encode(b"\xff\xd8\xff\xe0" + tag).decode("ascii")


def _demo_b64(name: str) -> str:
    return base64.b64encode((DEMO / name).read_bytes()).decode("ascii")


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv(LYNCEUS_STORAGE_DIR_ENV, str(tmp_path))
    monkeypatch.setattr(pipeline, "_vlm_reachable", lambda *a, **k: False)
    monkeypatch.setattr(pipeline, "safe_detect", lambda *a, **k: None)
    return TestClient(create_app())


def _record(tmp_path, record_id):
    return audit.load_record(tmp_path / record_id / audit.RECORD_FILENAME)


def _blurred(name: str, radius: float = 3.0) -> bytes:
    from PIL import Image, ImageFilter

    image = Image.open(DEMO / name).convert("RGB").filter(ImageFilter.GaussianBlur(radius))
    out = io.BytesIO()
    image.save(out, "JPEG", quality=85)
    return out.getvalue()


# ---------------------------------------------------------------------------
# Offline stub: the bundled demo photos keep their story
# ---------------------------------------------------------------------------


def test_stub_case_by_digest_then_filename():
    assert pipeline.stub_case_for({"demo_case": "amber", "photo_filename": "t-metal-1.jpg"}) == "amber"
    assert pipeline.stub_case_for({"photo_filename": "/demo/T-Metal-2.jpg"}) == "red"
    assert pipeline.stub_case_for({"photo_filename": "t-ambiguous-1.jpg"}) == "amber"
    assert pipeline.stub_case_for({"photo_filename": "t-clean-2.jpg"}) == "green"
    assert pipeline.stub_case_for({"photo_filename": "truck.jpg"}) is None
    assert pipeline.stub_case_for({}) is None


@needs_demo
def test_stub_case_by_digest_of_the_bundled_file():
    payload = {"photo_base64": _demo_b64("t-metal-1.jpg"), "photo_filename": "upload.jpg"}
    assert pipeline.stub_case_for(payload) == "red"


def test_offline_metal_preset_is_rejected(client):
    resp = client.post(
        "/inspect",
        json={
            "photo_base64": _jpeg(b"downscaled"),
            "photo_filename": "t-metal-1.jpg",
            "waybill_fields": CONFIRMED_FIELDS,
            "weight_kg": 16340,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["provenance"] == "stub_fallback_live_error"
    assert body["verdict"]["decision"] == audit.Decision.REJECT


def test_seeded_waybill_photo_keeps_the_seed_provenance(tmp_path, monkeypatch):
    monkeypatch.setenv(LYNCEUS_STORAGE_DIR_ENV, str(tmp_path))
    monkeypatch.setattr(pipeline, "_vlm_reachable", lambda *a, **k: False)
    monkeypatch.setattr(pipeline, "safe_detect", lambda *a, **k: None)
    request = api.InspectRequest(
        photo_base64=_jpeg(b"load"),
        waybill_image_base64=_jpeg(b"waybill"),
        waybill_fields=CONFIRMED_FIELDS,
        weight_kg=16340,
    )
    body = api._run_inspection_with_audit(request, get_settings(), photo_provenance="sample")
    rec = _record(tmp_path, body["record_id"])
    assert rec.inputs.photo.provenance == "sample"
    assert rec.inputs.waybill_photo.provenance == "sample"


def test_declared_moisture_reaches_sampling(client, monkeypatch):
    seen = {}
    suppliers = api._optional_module("suppliers")
    if suppliers is None:
        pytest.skip("suppliers module not installed")
    real = suppliers.sampling_for

    def spy(storage_dir, supplier, declared=None, **kwargs):
        seen["declared"] = declared
        return real(storage_dir, supplier, declared, **kwargs)

    monkeypatch.setattr(suppliers, "sampling_for", spy)
    resp = client.post(
        "/inspect",
        json={"photo_base64": _jpeg(b"x"), "waybill_fields": CONFIRMED_FIELDS, "weight_kg": 16340},
    )
    assert resp.status_code == 200, resp.text
    assert seen["declared"]["moisture_pct"] == 28


# ---------------------------------------------------------------------------
# Votes
# ---------------------------------------------------------------------------


def test_votes_are_kept_streamed_and_sealed(client, tmp_path, monkeypatch):
    monkeypatch.setenv("VLM_VOTES", "3")
    replies = iter(
        [
            ["metal"], [], [],  # one read of three sees metal: the vote drops it
        ]
    )

    def chat_once(self, base_url, model, messages, max_tokens=512):
        if "image_url" not in json.dumps(messages):
            return '{"reasoning": "ok", "crosscheck_notes": "consistent", "confidence": 0.8}'
        return json.dumps(
            {
                "contamination": "x",
                "moisture": 0.1,
                "hard_contaminants": next(replies),
                "light_contaminants": ["glass"],
                "confidence": 0.8,
                "locations": [],
            }
        )

    monkeypatch.setattr(pipeline.VLLMClient, "_chat_once", chat_once)
    monkeypatch.setattr(
        pipeline, "resolve_clients", lambda payload, settings=None: pipeline.VLLMClient(settings)
    )
    resp = client.post(
        "/inspect/stream",
        json={"photo_base64": _jpeg(b"x"), "waybill_fields": CONFIRMED_FIELDS, "weight_kg": 16340},
    )
    events = [json.loads(line) for line in resp.text.splitlines()]
    reads = [e["data"] for e in events if e.get("stage") == "vision_read"]
    assert sorted(r["hard"] for r in reads) == [[], [], ["metal"]]
    assert all(r["light"] == ["glass"] for r in reads)

    result = events[-1]["data"]
    vlm = result["ai_outputs"]["vlm"]
    assert vlm["detected"]["hard_contaminants"] == []  # the majority
    assert sorted(v["hard"] for v in vlm["votes"]) == [[], [], ["metal"]]
    rec = _record(tmp_path, result["record_id"])
    assert len(rec.ai_outputs.vlm.votes) == 3
    raw = json.loads((tmp_path / result["record_id"] / audit.RECORD_FILENAME).read_text("utf-8"))
    assert "__votes__" not in json.dumps(raw)


def test_stub_answer_is_one_vote(client, tmp_path):
    body = client.post("/inspect", json={"demo_case": "red"}).json()
    assert body["ai_outputs"]["vlm"]["votes"] == [
        {"hard": ["metal"], "light": [], "confidence": 0.83}
    ]


def test_old_records_without_votes_or_observations_load(client, tmp_path):
    body = client.post("/inspect", json={"demo_case": "green"}).json()
    path = tmp_path / body["record_id"] / audit.RECORD_FILENAME
    data = json.loads(path.read_text("utf-8"))
    data["ai_outputs"]["vlm"].pop("votes")
    data["inputs"].pop("observations")
    data["digest"]["record_sha256"] = audit.EMPTY_SHA256_FIELD
    audit._stamp_record_digest(data)
    path.write_text(json.dumps(data), encoding="utf-8")
    rec = audit.load_record(path)
    assert rec.ai_outputs.vlm.votes is None and rec.inputs.observations is None


# ---------------------------------------------------------------------------
# Observations
# ---------------------------------------------------------------------------


@needs_demo
def test_image_quality_ok_and_poor():
    sharp = observations.image_quality((DEMO / "t-clean-1.jpg").read_bytes(), 0, NOW)
    assert sharp["status"] == "ok" and sharp["kind"] == "image_quality"
    assert sharp["source"] == "camera:main" and sharp["frame"] == 0
    assert sharp["value"]["width_px"] == 1448
    blurred_bytes = _blurred("t-clean-1.jpg")
    blurred = observations.image_quality(blurred_bytes, 1, NOW)
    assert blurred["status"] == "poor" and "blurred" in blurred["note"]
    assert blurred["source"] == "camera:angle-2"
    assert blurred["sha256"] == "sha256:" + __import__("hashlib").sha256(blurred_bytes).hexdigest()


def test_image_quality_unreadable_is_unavailable():
    record = observations.image_quality(b"\xff\xd8\xff\xe0garbage", 0, NOW)
    assert record["status"] == "unavailable" and record["value"] is None


def test_plate_reading_flags_the_wrong_truck():
    wrong = observations.plate_reading("b-9406-kxw", "B 9723 KXW", NOW)
    assert wrong["value"] == "B 9406 KXW" and wrong["status"] == "mismatch"
    assert wrong["simulated"] is True
    same = observations.plate_reading(None, "B 9723 KXW", NOW)
    assert same["status"] == "ok"
    assert observations.plate_reading(None, None, NOW) is None


@needs_demo
def test_inspect_records_observations_and_hands_them_to_the_rules(client, tmp_path, monkeypatch):
    seen = {}
    real = decision.decide

    def spy(inputs, *args, **kwargs):
        seen["observations"] = inputs["observations"]
        return real(inputs, *args, **kwargs)

    monkeypatch.setattr(decision, "decide", spy)
    resp = client.post(
        "/inspect",
        json={
            "truck_id": "B 9406 KXW",
            "photo_base64": base64.b64encode(_blurred("t-clean-1.jpg")).decode("ascii"),
            "photo_filename": "t-clean-1.jpg",
            "waybill_fields": CONFIRMED_FIELDS,
            "weight_kg": 16340,
            "weight_source": "weighbridge_simulated",
            "observations": [
                {"source": "portal-1", "kind": "radiation", "value": 0.08, "unit": "uSv/h"}
            ],
        },
    )
    assert resp.status_code == 200, resp.text
    rec = _record(tmp_path, resp.json()["record_id"])
    by_kind = {o.kind: o for o in rec.inputs.observations}
    assert by_kind["image_quality"].status == "poor"
    assert by_kind["plate"].status == "mismatch" and by_kind["plate"].value == "B 9406 KXW"
    assert by_kind["weighbridge"].simulated is True and by_kind["weighbridge"].value == 16340
    # The site's radiation portal replaces the not-installed placeholder.
    assert by_kind["radiation"].source == "portal-1" and by_kind["radiation"].status == "ok"
    assert by_kind["radiation"].sha256.startswith("sha256:")
    assert by_kind["nir_analyzer"].status == "not_installed"
    assert [o["kind"] for o in seen["observations"]] == [o.kind for o in rec.inputs.observations]


@needs_demo
def test_a_supplied_reading_never_switches_a_check_off():
    blurred = _blurred("t-clean-1.jpg")
    supplied = [
        {"source": "x", "kind": "image_quality", "status": "ok"},
        {"source": "x", "kind": "plate", "value": "B 9723 KXW", "status": "ok"},
    ]
    obs = observations.collect(
        supplied=supplied,
        frames=[blurred],
        weight_kg=None,
        weight_source=None,
        registered_plate="B 9406 KXW",
        waybill_plate="B 9723 KXW",
        measured_at_utc=NOW,
    )
    quality = [o for o in obs if o["kind"] == "image_quality"]
    assert [o["source"] for o in quality] == ["x", "camera:main"]  # computed beside it
    assert quality[1]["status"] == "poor"
    plates = [o for o in obs if o["kind"] == "plate"]
    assert [o["status"] for o in plates] == ["ok", "mismatch"]  # the mismatch stays
    inputs = {"observations": obs, "waybill_fields": {"plate": "B 9723 KXW"}}
    assert decision.poor_image_notes(inputs)
    assert decision.plate_mismatch(inputs) == ("B 9406 KXW", "B 9723 KXW")


def test_a_supplied_plate_replaces_only_an_agreeing_simulated_one():
    supplied = [{"source": "anpr-1", "kind": "plate", "value": "B 9723 KXW", "status": "ok"}]
    obs = observations.collect(
        supplied=supplied,
        frames=[],
        weight_kg=None,
        weight_source=None,
        registered_plate="B 9723 KXW",
        waybill_plate="B 9723 KXW",
        measured_at_utc=NOW,
    )
    assert [o["source"] for o in obs if o["kind"] == "plate"] == ["anpr-1"]


@needs_demo
def test_supplied_ok_readings_cannot_clear_a_blurred_wrong_truck(client):
    resp = client.post(
        "/inspect",
        json={
            "truck_id": "B 9406 KXW",
            "photo_base64": base64.b64encode(_blurred("t-clean-1.jpg")).decode("ascii"),
            "photo_filename": "t-clean-1.jpg",
            "waybill_fields": CONFIRMED_FIELDS,
            "weight_kg": 16340,
            "observations": [
                {"source": "x", "kind": "image_quality", "status": "ok"},
                {"source": "x", "kind": "plate", "value": "B 9723 KXW", "status": "ok"},
            ],
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["verdict"]["decision"] != audit.Decision.ACCEPT
    reasons = json.dumps(body)
    assert decision.PHOTO_QUALITY_MARKER in reasons
    assert decision.PLATE_MISMATCH_MARKER in reasons


def test_bad_supplied_observations_are_422(client):
    base = {"photo_base64": _jpeg(b"x"), "weight_kg": 1000}
    bad_status = {**base, "observations": [{"source": "s", "kind": "k", "status": "great"}]}
    assert client.post("/inspect", json=bad_status).status_code == 422
    bad_time = {**base, "observations": [{"source": "s", "kind": "k", "measured_at_utc": "today"}]}
    assert client.post("/inspect", json=bad_time).status_code == 422


def test_sensors_lists_the_plug_ins(client):
    body = client.get("/sensors").json()
    status = {s["kind"]: s["status"] for s in body["sensors"]}
    assert status == {
        "image_quality": "installed",
        "weighbridge": "simulated",
        "plate": "simulated",
        "radiation": "not_installed",
        "nir_analyzer": "not_installed",
    }
    assert "RS-232" in body["integration_note"] and "IEC 62022" in body["integration_note"]
    assert body["image_quality_thresholds"]["min_sharpness"] > 0


def test_wrong_truck_scale_ticket_matches_the_waybill_load(client):
    body = client.get("/weighbridge/reading", params={"plate": "B 9406 KXW"}).json()
    assert body["net_kg"] == 16340 and body["plate"] == "B 9406 KXW"
