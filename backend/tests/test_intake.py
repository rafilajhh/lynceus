"""Gate intake: waybill reading, the simulated weighbridge, waybill-driven
inspections, the NDJSON stream, warm-up and multi-angle photos.

No test touches the network: the vision endpoint probe is forced down (the
offline paths) or the chat call itself is replaced (the live paths).
"""

from __future__ import annotations

import base64
import json
import threading

import pytest
from fastapi.testclient import TestClient

from lynceus import api, audit, decision, pipeline, waybill, weighbridge
from lynceus.api import create_app
from lynceus.config import LYNCEUS_STORAGE_DIR_ENV, get_settings

SAMPLE_B64 = (
    base64.b64encode(waybill.SAMPLE_WAYBILL_PATH.read_bytes()).decode("ascii")
    if waybill.SAMPLE_WAYBILL_PATH.is_file()
    else None
)
needs_sample = pytest.mark.skipif(SAMPLE_B64 is None, reason="bundled sample waybill missing")


def _jpeg(tag: bytes) -> str:
    """A tiny JPEG-magic payload (decode_photo checks magic bytes only)."""
    return base64.b64encode(b"\xff\xd8\xff\xe0" + tag).decode("ascii")


#: The confirmed fields of the sample waybill, as the console sends them.
CONFIRMED_FIELDS = waybill.values_of(waybill.SAMPLE_FIELDS)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv(LYNCEUS_STORAGE_DIR_ENV, str(tmp_path))
    monkeypatch.setattr(pipeline, "_vlm_reachable", lambda *a, **k: False)
    # The detector's first load costs seconds and reads nothing in these
    # tiny payloads: keep it out unless a test puts its own in.
    monkeypatch.setattr(pipeline, "safe_detect", lambda *a, **k: None)
    return TestClient(create_app())


def _record(tmp_path, record_id):
    return audit.load_record(tmp_path / record_id / audit.RECORD_FILENAME)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, expected",
    [
        ("32.580", 32580.0),
        ("32,580", 32580.0),
        ("16 340 kg", 16340.0),
        ("28,5", 28.5),
        ("28.5 %", 28.5),
        ("32.580,5", 32580.5),
        ("32,580.5", 32580.5),
        (16340, 16340.0),
        ("-", None),
        (None, None),
        (True, None),
    ],
)
def test_parse_number_understands_indonesian_separators(text, expected):
    assert waybill.parse_number(text) == expected


@pytest.mark.parametrize(
    "text, expected",
    [
        ("14/05/2025", "2025-05-14"),
        ("14-05-2025", "2025-05-14"),
        ("14.05.25", "2025-05-14"),
        ("14 Mei 2025", "2025-05-14"),
        ("2025-05-14", "2025-05-14"),
        ("32/13/2025", None),
        ("soon", None),
    ],
)
def test_parse_date_is_day_first(text, expected):
    assert waybill.parse_date(text) == expected


@pytest.mark.parametrize(
    "load_type, stream, warned",
    [
        ("RDF fluff", "rdf-feedstock", False),
        ("SRF", "rdf-feedstock", False),
        ("Sampah campuran", "mixed-msw", False),
        ("MSW", "mixed-msw", False),
        ("Sampah organik", "organic-rich", False),
        ("Kayu bekas", "rdf-feedstock", True),
        (None, "rdf-feedstock", True),
    ],
)
def test_waste_stream_mapping(load_type, stream, warned):
    got, warning = waybill.waste_stream_for(load_type)
    assert got == stream
    assert (warning is not None) == warned


def test_derived_facts_of_the_sample():
    derived, warnings = waybill.derive(CONFIRMED_FIELDS)
    assert derived == {
        "waste_stream": "rdf-feedstock",
        "declares_processed_rdf": True,
        "arithmetic": {"gross_minus_tare_kg": 16340, "net_kg": 16340, "consistent": True},
    }
    assert warnings == []
    off = waybill.arithmetic({"gross_kg": 32580, "tare_kg": 16240, "net_kg": 15000})
    assert off["consistent"] is False
    assert waybill.arithmetic({"gross_kg": 1})["consistent"] is None
    assert not waybill.declares_processed_rdf({"load_type": "Sampah campuran"})
    assert waybill.declares_processed_rdf({"remarks": "hasil proses pemilahan"})


def test_normalize_fields_handles_both_shapes_and_missing():
    fields, warnings = waybill.normalize_fields(
        {
            "plate": {"value": "b-9723-kxw", "confidence": 0.9},
            "gross_kg": {"value": "32.580", "confidence": 1.4},
            "net_kg": "16.340",
            "date": {"value": "someday", "confidence": 0.5},
            "driver": {"value": None, "confidence": 0.8},
        }
    )
    assert fields["plate"] == {"value": "B 9723 KXW", "confidence": 0.9}
    assert fields["gross_kg"] == {"value": 32580, "confidence": 1.0}
    assert fields["net_kg"] == {"value": 16340, "confidence": 0.5}
    assert fields["driver"] == {"value": None, "confidence": 0.0}
    assert fields["remarks"] == {"value": None, "confidence": 0.0}
    assert fields["date"]["value"] == "someday" and warnings
    assert set(fields) == set(waybill.FIELD_NAMES)


def test_transcript_is_deterministic():
    text = waybill.transcript(CONFIRMED_FIELDS)
    assert text == waybill.transcript(dict(CONFIRMED_FIELDS))
    assert text.startswith("SURAT JALAN 007842 | Date 2025-05-14 | Plate B 9723 KXW")
    assert "Net 16,340 kg" in text and "Moisture 28 %" in text


# ---------------------------------------------------------------------------
# POST /waybill/read
# ---------------------------------------------------------------------------


@needs_sample
def test_waybill_read_offline_returns_the_sample_fields(client):
    resp = client.post("/waybill/read", json={"image_base64": SAMPLE_B64})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["fields"] == waybill.SAMPLE_FIELDS
    assert body["provenance"] == "stub"
    assert body["warnings"][0] == waybill.STUB_WARNING
    assert body["derived"]["waste_stream"] == "rdf-feedstock"
    assert body["derived"]["arithmetic"]["consistent"] is True
    assert 0.85 <= body["confidence"] <= 0.9
    assert body["transcript"] == waybill.transcript(CONFIRMED_FIELDS)
    assert body["model"] == waybill.STUB_MODEL and body["provider"] is None


@needs_sample
def test_waybill_read_demo_case_forces_the_stub(client, monkeypatch):
    monkeypatch.setattr(pipeline, "_vlm_reachable", lambda *a, **k: True)
    monkeypatch.setattr(
        pipeline.VLLMClient,
        "read_document",
        lambda *a, **k: pytest.fail("demo_case must not call the model"),
    )
    resp = client.post(
        "/waybill/read", json={"image_base64": SAMPLE_B64, "demo_case": "metal"}
    )
    assert resp.status_code == 200 and resp.json()["provenance"] == "stub"


def test_waybill_read_offline_other_photo_is_503(client):
    resp = client.post("/waybill/read", json={"image_base64": _jpeg(b"other")})
    assert resp.status_code == 503, resp.text
    assert resp.json()["detail"] == {
        "error": "waybill_reader_offline",
        "message": "Waybill reader offline: type the fields.",
    }


def test_waybill_read_rejects_bad_images(client):
    not_image = base64.b64encode(b"GIF89a....").decode("ascii")
    resp = client.post("/waybill/read", json={"image_base64": not_image})
    assert resp.status_code == 422
    assert resp.json()["detail"]["error"] == "invalid_photo"
    resp = client.post("/waybill/read", json={"image_base64": "%%%"})
    assert resp.status_code == 422
    assert client.post("/waybill/read", json={}).status_code == 422


def _live_waybill(monkeypatch, reply):
    monkeypatch.setattr(pipeline, "_vlm_reachable", lambda *a, **k: True)
    monkeypatch.setenv("VLLM_VLM_URL", "https://api.amd.com/v1")
    monkeypatch.setenv("VLM_MODEL", "vision-a")
    seen = []

    def chat_once(self, base_url, model, messages, max_tokens=512):
        seen.append((model, messages))
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setattr(pipeline.VLLMClient, "_chat_once", chat_once)
    return seen


def test_waybill_read_live_parses_the_model_reply(client, monkeypatch):
    reply = json.dumps(
        {
            "document_no": {"value": "SJ-1", "confidence": 0.9},
            "plate": {"value": "B 9118 TRQ", "confidence": 0.95},
            "carrier": {"value": "CV Maju", "confidence": 0.8},
            "gross_kg": {"value": "30.000", "confidence": 0.9},
            "tare_kg": {"value": "15.000", "confidence": 0.9},
            "net_kg": {"value": "15.000", "confidence": 0.9},
            "load_type": {"value": "Sampah campuran", "confidence": 0.7},
            "moisture_pct": {"value": "35,5", "confidence": 0.6},
        }
    )
    seen = _live_waybill(monkeypatch, reply)
    resp = client.post("/waybill/read", json={"image_base64": _jpeg(b"live")})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["provenance"] == "live" and body["model"] == "vision-a"
    assert body["provider"] == "amd-token-factory"
    assert body["fields"]["gross_kg"]["value"] == 30000
    assert body["fields"]["moisture_pct"]["value"] == 35.5
    assert body["fields"]["driver"] == {"value": None, "confidence": 0.0}
    assert body["derived"]["waste_stream"] == "mixed-msw"
    assert body["derived"]["declares_processed_rdf"] is False
    assert body["latency_ms"] is not None
    # One read (no voting), with the waybill prompt and the image.
    assert len(seen) == 1
    content = seen[0][1][0]["content"]
    assert content[0]["text"] == waybill.PROMPT and content[1]["type"] == "image_url"


def test_waybill_read_rate_limit_is_429(client, monkeypatch):
    monkeypatch.setattr(pipeline, "_vlm_reachable", lambda *a, **k: True)

    def throttled(*a, **k):
        raise pipeline.RateLimitSpentError("rate-limited after 3 attempts")

    monkeypatch.setattr(pipeline.VLLMClient, "read_document", throttled)
    resp = client.post("/waybill/read", json={"image_base64": _jpeg(b"x")})
    assert resp.status_code == 429
    assert resp.json()["detail"]["error"] == "rate_limited"


def test_waybill_read_live_failure_is_503_for_an_unknown_photo(client, monkeypatch):
    _live_waybill(monkeypatch, ConnectionError("down"))
    resp = client.post("/waybill/read", json={"image_base64": _jpeg(b"x")})
    assert resp.status_code == 503
    assert resp.json()["detail"]["error"] == "waybill_reader_offline"


@needs_sample
def test_waybill_read_live_failure_on_the_sample_says_so(client, monkeypatch):
    _live_waybill(monkeypatch, ConnectionError("down"))
    resp = client.post("/waybill/read", json={"image_base64": SAMPLE_B64})
    assert resp.status_code == 200
    body = resp.json()
    assert body["provenance"] == "stub"
    assert any("Live reader failed" in w for w in body["warnings"])


@needs_sample
def test_waybill_read_fail_closed_never_serves_the_stub(client, monkeypatch):
    monkeypatch.setenv("LYNCEUS_ALLOW_STUB_FALLBACK", "0")
    resp = client.post("/waybill/read", json={"image_base64": SAMPLE_B64})
    assert resp.status_code == 503


# ---------------------------------------------------------------------------
# GET /weighbridge/reading
# ---------------------------------------------------------------------------


def test_weighbridge_sample_truck_matches_its_waybill(client):
    resp = client.get("/weighbridge/reading", params={"plate": "b-9723-kxw"})
    assert resp.status_code == 200
    body = resp.json()
    assert {k: body[k] for k in ("plate", "gross_kg", "tare_kg", "net_kg")} == {
        "plate": "B 9723 KXW",
        "gross_kg": 32580,
        "tare_kg": 16240,
        "net_kg": 16340,
    }
    assert body["source"] == "simulated" and body["stable"] is True
    assert body["note"] == weighbridge.SIMULATED_NOTE
    assert body["scale"] == "Weighbridge A"
    audit.validate_timestamp(body["read_at_utc"])


def test_weighbridge_scenarios_and_determinism(client):
    def net(plate, declared=None):
        params = {"plate": plate}
        if declared is not None:
            params["declared_net_kg"] = declared
        body = client.get("/weighbridge/reading", params=params).json()
        assert body["gross_kg"] == body["tare_kg"] + body["net_kg"]
        return body["net_kg"]

    assert net("B 9118 TRQ", 15000) == 16080  # +7.2 %
    assert net("B 9001 RDF", 15000) == 14880  # -0.8 %
    first = net("D 1234 XY", 20000)
    assert first == net("D1234XY", 20000) == net("D 1234 XY", 20000)
    assert abs(first - 20000) <= 0.015 * 20000 + 10 and first % 10 == 0
    assert net("D 1234 XY") == net("D 1234 XY")


def test_weighbridge_rejects_bad_queries(client):
    assert client.get("/weighbridge/reading").status_code == 422
    assert client.get("/weighbridge/reading", params={"plate": " "}).status_code == 422
    assert (
        client.get(
            "/weighbridge/reading", params={"plate": "B 1 A", "declared_net_kg": -5}
        ).status_code
        == 422
    )


# ---------------------------------------------------------------------------
# POST /inspect with waybill fields
# ---------------------------------------------------------------------------


def _waybill_payload(**overrides):
    payload = {
        "photo_base64": _jpeg(b"load"),
        "waybill_fields": dict(CONFIRMED_FIELDS),
        "waybill_read": {
            "confidence": 0.89,
            "model": "stub-waybill-reader",
            "provenance": "stub",
            "latency_ms": None,
            "edited_fields": [],
        },
        "weight_kg": 16340,
        "weight_source": "weighbridge_simulated",
    }
    payload.update(overrides)
    return payload


def test_inspect_with_waybill_fields_records_the_read(client, tmp_path, monkeypatch):
    seen = {}
    real_decide = decision.decide

    def spy(inputs, *args, **kwargs):
        # The first call is the gate's; the decision receipt may replay it.
        seen.setdefault("inputs", dict(inputs))
        return real_decide(inputs, *args, **kwargs)

    monkeypatch.setattr(decision, "decide", spy)
    resp = client.post("/inspect", json=_waybill_payload())
    assert resp.status_code == 200, resp.text
    body = resp.json()
    rec = _record(tmp_path, body["record_id"])

    # Defaults come from the waybill.
    assert rec.inputs.truck_id == "B 9723 KXW"
    assert rec.inputs.supplier == "PT. Hijau Lestari Transport"
    manifest = rec.inputs.manifest_text
    assert manifest.source == "waybill_photo_ai_read"
    assert manifest.extracted_fields == CONFIRMED_FIELDS
    assert manifest.ocr_confidence == 0.89
    transcript = waybill.transcript(CONFIRMED_FIELDS)
    assert manifest.raw_text_sha256 == audit.sha256_field(transcript.encode("utf-8"))
    assert rec.inputs.weight.source == "weighbridge_simulated"
    assert rec.inputs.weight.value_kg == 16340

    # decide() reads the confirmed fields, the read and the declared weight.
    inputs = seen["inputs"]
    assert inputs["waybill_fields"] == CONFIRMED_FIELDS
    assert inputs["waybill_read"]["confidence"] == 0.89
    assert inputs["declared_weight_kg"] == 16340
    assert inputs["waste_stream"] == "rdf-feedstock"
    assert inputs["moisture"] == pytest.approx(0.28)
    assert inputs["manifest_text"] == transcript

    # No age typed: the engine assumed 24 h and says so.
    caveats = body["engine_outputs"]["recommendation"]["caveats"]
    assert any("assumed 24 h" in c for c in caveats), caveats

    # Response: the declared-vs-observed block and the operator checks.
    assert body["waybill"]["fields"] == CONFIRMED_FIELDS
    assert body["waybill"]["derived"]["declares_processed_rdf"] is True
    assert body["waybill"]["transcript"] == transcript
    assert isinstance(body["why"], str) and body["why"]
    assert [c["key"] for c in body["checks"]] == [
        "vision", "second_look", "waybill_read", "declaration", "weight", "supplier",
    ]
    assert body["sampling"]["tier"] == "new"
    assert body["supplier_profile"] is None  # first truck of this supplier


def test_inspect_edited_waybill_and_explicit_values_win(client, tmp_path):
    payload = _waybill_payload(
        truck_id="B 1111 ZZ",
        supplier="CV Lain",
        declared_weight_kg=16000,
        waste_stream="mixed-msw",
        age_h=6,
        weight_source="manual_entry",
    )
    payload["waybill_fields"]["net_kg"] = "16.000"  # an edited, typed number
    payload["waybill_read"]["edited_fields"] = ["net_kg"]
    resp = client.post("/inspect", json=payload)
    assert resp.status_code == 200, resp.text
    rec = _record(tmp_path, resp.json()["record_id"])
    assert rec.inputs.truck_id == "B 1111 ZZ"
    assert rec.inputs.supplier == "CV Lain"
    assert rec.inputs.manifest_text.source == "waybill_photo_ai_read_operator_edited"
    assert rec.inputs.manifest_text.extracted_fields["net_kg"] == 16000
    assert rec.inputs.weight.source == "manual_entry"
    caveats = resp.json()["engine_outputs"]["recommendation"]["caveats"]
    assert not any("assumed 24 h" in c for c in caveats)


def test_inspect_typed_fields_without_a_read(client, tmp_path):
    payload = _waybill_payload()
    payload.pop("waybill_read")
    resp = client.post("/inspect", json=payload)
    assert resp.status_code == 200, resp.text
    rec = _record(tmp_path, resp.json()["record_id"])
    assert rec.inputs.manifest_text.source == "operator_typed_fields"


def test_inspect_without_waybill_still_refuses_without_a_photo(client):
    resp = client.post("/inspect", json={"weight_kg": 5000, "manifest_text": "SJ"})
    assert resp.status_code == 200
    assert resp.json()["verdict"]["decision"] == audit.Decision.REFUSE_INSUFFICIENT_INPUT


def test_inspect_field_confidences_reach_the_checks(client):
    payload = _waybill_payload()
    payload["waybill_read"]["field_confidences"] = {
        name: entry["confidence"] for name, entry in waybill.SAMPLE_FIELDS.items()
    }
    payload["waybill_read"]["field_confidences"]["shipper"] = 0.3
    resp = client.post("/inspect", json=payload)
    assert resp.status_code == 200, resp.text
    read_check = next(c for c in resp.json()["checks"] if c["key"] == "waybill_read")
    assert read_check["status"] in ("pass", "warn")


def test_inspect_rejects_more_than_two_extra_angles(client):
    payload = _waybill_payload(extra_photos_base64=[_jpeg(b"a"), _jpeg(b"b"), _jpeg(b"c")])
    assert client.post("/inspect", json=payload).status_code == 422


# ---------------------------------------------------------------------------
# GET /inspections/{id}
# ---------------------------------------------------------------------------


def test_get_inspection_adds_checks_beside_the_record(client):
    record_id = client.post("/inspect", json=_waybill_payload()).json()["record_id"]
    body = client.get(f"/inspections/{record_id}").json()
    assert body["record_id"] == record_id and "inputs" in body
    assert body["why"] and len(body["checks"]) == 6
    assert body["supplier_profile"]["supplier"]


# ---------------------------------------------------------------------------
# POST /inspect/stream
# ---------------------------------------------------------------------------


def _events(resp):
    assert resp.headers["content-type"].startswith("application/x-ndjson")
    return [json.loads(line) for line in resp.text.splitlines() if line.strip()]


def test_stream_emits_stages_then_the_inspect_result(client, tmp_path):
    resp = client.post("/inspect/stream", json=_waybill_payload())
    assert resp.status_code == 200
    events = _events(resp)
    stages = [(e["stage"], e["status"]) for e in events if e["event"] == "stage"]
    assert stages[0] == ("queued", "done")
    names = [s for s, _ in stages]
    for stage in ("vision", "vision_read", "waybill_audit", "rules", "sealed"):
        assert stage in names, names
    assert names.index("rules") < names.index("sealed")
    assert ("vision", "running") in stages and ("vision", "done") in stages
    assert events[-1]["event"] == "result"
    assert all(e["t"] >= 0 for e in events if e["event"] == "stage")
    sealed = next(e for e in events if e.get("stage") == "sealed")
    result = events[-1]["data"]
    assert sealed["data"]["record_id"] == result["record_id"]

    # The result is exactly what /inspect answers for the same request.
    direct = client.post("/inspect", json=_waybill_payload()).json()
    assert set(result) == set(direct)
    assert result["verdict"]["decision"] == direct["verdict"]["decision"]
    # (The supplier check differs: the second truck has the first on record.)
    assert result["checks"][:5] == direct["checks"][:5]
    assert _record(tmp_path, result["record_id"]).execution_status == "completed"


def test_stream_reports_errors_as_lines(client):
    bad = _waybill_payload(photo_base64=base64.b64encode(b"GIF89a").decode("ascii"))
    events = _events(client.post("/inspect/stream", json=bad))
    assert events[-1] == {
        "event": "error",
        "status": 422,
        "error": "invalid_photo",
        "message": "photo must be a JPEG or PNG image.",
    }


def test_stream_shares_the_live_slots(client):
    taken = []
    for _ in range(api.MAX_LIVE_INSPECTIONS):
        assert api._LIVE_SLOTS.acquire(blocking=False)
        taken.append(True)
    try:
        events = _events(client.post("/inspect/stream", json=_waybill_payload()))
        assert events == [
            {
                "event": "error",
                "status": 503,
                "error": "busy",
                "message": (
                    "The live AMD pipeline is busy — try again in a moment or use a "
                    "scripted case."
                ),
            }
        ]
    finally:
        for _ in taken:
            api._LIVE_SLOTS.release()


def test_stream_vision_reads_count_up(client, monkeypatch):
    monkeypatch.setenv("VLM_VOTES", "3")
    monkeypatch.setattr(
        pipeline.VLLMClient,
        "_chat_once",
        lambda self, *a, **k: (
            '{"contamination": "metal pipe", "moisture": 0.2, '
            '"hard_contaminants": ["metal"], "light_contaminants": [], '
            '"reasoning": "ok", "crosscheck_notes": "consistent", "confidence": 0.8}'
        ),
    )
    monkeypatch.setattr(
        pipeline, "resolve_clients", lambda payload, settings=None: pipeline.VLLMClient(settings)
    )
    events = _events(client.post("/inspect/stream", json=_waybill_payload()))
    reads = [e["data"] for e in events if e.get("stage") == "vision_read"]
    assert [r["index"] for r in reads] == [1, 2, 3]
    assert all(r["of"] == 3 and r["hard"] == ["metal"] for r in reads)
    running = next(e for e in events if e.get("stage") == "vision" and e["status"] == "running")
    assert running["data"]["reads"] == 3 and running["data"]["frames"] == 1
    assert events[-1]["data"]["verdict"]["decision"] == audit.Decision.REJECT


# ---------------------------------------------------------------------------
# POST /warmup
# ---------------------------------------------------------------------------


def test_warmup_runs_at_most_once_a_minute(client, monkeypatch):
    calls = []
    done = threading.Event()

    def fake_warm(settings):
        calls.append(settings.vlm_model)
        done.set()

    monkeypatch.setattr(api, "_warm_backends", fake_warm)
    monkeypatch.setitem(api._WARMUP_STATE, "last", None)
    assert client.post("/warmup").json() == {"warmed": True}
    assert done.wait(5)
    assert client.post("/warmup").json() == {"warmed": False, "reason": "recent"}
    assert len(calls) == 1
    monkeypatch.setitem(api._WARMUP_STATE, "last", api._WARMUP_STATE["last"] - 61)
    assert client.post("/warmup").json() == {"warmed": True}


def test_warm_backends_never_raises(monkeypatch):
    monkeypatch.setattr(api.detector, "warm", lambda *a, **k: (_ for _ in ()).throw(OSError("x")))

    def fail(self, *a, **k):
        raise ConnectionError("down")

    monkeypatch.setattr(pipeline.VLLMClient, "_chat_once", fail)
    api._warm_backends(get_settings())


def test_vision_warm_ping_is_one_token(monkeypatch):
    sent = []
    monkeypatch.setattr(
        pipeline.VLLMClient,
        "_chat_once",
        lambda self, url, model, messages, max_tokens=512: sent.append((model, max_tokens)) or "",
    )
    monkeypatch.setenv("VLM_MODEL", "vision-a")
    pipeline.VLLMClient(settings=get_settings()).warm()
    assert sent == [("vision-a", 1)]


# ---------------------------------------------------------------------------
# Multi-angle photos
# ---------------------------------------------------------------------------

_MAIN, _SIDE = _jpeg(b"main"), _jpeg(b"side")


class _AngleClient:
    """Live-provenance fake: the side angle shows metal, the main one not."""

    provenance = "live"
    vision_model = "vision-a"
    vision_provider = "amd-token-factory"

    def vlm(self, photo):
        metal = photo == _SIDE
        return {
            "detected": {
                "contamination": "metal pipe" if metal else "none detected",
                "moisture": 0.3 if metal else 0.1,
                "hard_contaminants": ["metal"] if metal else [],
                "light_contaminants": ["glass"] if metal else [],
            },
            "confidence": 0.8 if metal else 0.9,
            "boxes": [{"label": "metal", "x0": 0.1, "y0": 0.1, "x1": 0.4, "y1": 0.5}]
            if metal
            else [],
            "localisation": "box",
            "model": "vision-a",
            "model_version": "vision-a",
            "raw_output": "{}",
            "provenance": "live",
            "provider": "amd-token-factory",
            "latency_ms": 900.0 if metal else 700.0,
        }

    def llm(self, manifest_text, context):
        return {
            "reasoning": "ok",
            "confidence": 0.9,
            "crosscheck_notes": "consistent",
            "crosscheck_failed": False,
            "model": "llm-a",
            "model_version": "llm-a",
            "raw_output": "{}",
            "provenance": "live",
        }


def test_multi_angle_union_evidence_and_digests(client, tmp_path, monkeypatch):
    monkeypatch.setenv("VLM_BENCHMARKED_MODELS", "vision-a")
    monkeypatch.setattr(
        pipeline, "resolve_clients", lambda payload, settings=None: _AngleClient()
    )
    detections = {
        base64.b64decode(_MAIN): [],
        base64.b64decode(_SIDE): [{"label": "metal", "confidence": 0.7, "box": [0.1, 0.1, 0.3, 0.3]}],
    }
    monkeypatch.setattr(
        pipeline,
        "safe_detect",
        lambda data, settings, **k: pipeline.detector.summarize(
            detections[data], 100.0, 0.35, 0.05
        ),
    )
    payload = _waybill_payload(
        photo_base64=_MAIN,
        extra_photos_base64=[_SIDE],
        extra_photo_filenames=["side.jpg"],
    )
    resp = client.post("/inspect", json=payload)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    record_id = body["record_id"]

    # The metal seen from one side only is in the load.
    assert body["verdict"]["decision"] == audit.Decision.REJECT
    vlm = body["ai_outputs"]["vlm"]
    assert vlm["detected"]["hard_contaminants"] == ["metal"]
    assert vlm["detected"]["moisture"] == 0.3
    assert vlm["boxes"][0]["frame"] == 1
    assert len(body["ai_outputs"]["vlm_frames"]) == 2
    detector_block = body["ai_outputs"]["detector"]
    assert detector_block["hard_contaminants"] == ["metal"]
    assert detector_block["boxes"][0]["frame"] == 1

    rec = _record(tmp_path, record_id)
    extra = rec.inputs.extra_photos[0]
    assert extra.filename == "side.jpg" and extra.path == "photo-2.jpg"
    side_bytes = base64.b64decode(_SIDE)
    assert extra.sha256 == audit.sha256_field(side_bytes)
    assert rec.digest.input_digests["photo_2"] == extra.sha256
    assert (tmp_path / record_id / "photo-2.jpg").read_bytes() == side_bytes
    assert len(rec.ai_outputs.vlm_frames) == 2

    served = client.get(f"/inspections/{record_id}/evidence/photo-2")
    assert served.status_code == 200 and served.content == side_bytes
    assert client.get(f"/inspections/{record_id}/evidence/photo-3").status_code == 404
    assert client.get(f"/inspections/{record_id}/evidence/photo-4").status_code == 422


def test_extra_angles_need_a_main_photo(client):
    payload = _waybill_payload(extra_photos_base64=[_SIDE])
    payload.pop("photo_base64")
    resp = client.post("/inspect", json=payload)
    assert resp.status_code == 422
    assert resp.json()["detail"]["error"] == "invalid_photo"


def test_single_photo_records_keep_the_old_shape(client, tmp_path):
    body = client.post("/inspect", json=_waybill_payload()).json()
    raw = json.loads((tmp_path / body["record_id"] / audit.RECORD_FILENAME).read_text("utf-8"))
    assert "extra_photos" not in raw["inputs"]
    assert "vlm_frames" not in raw["ai_outputs"]


def test_merge_frame_reads_rules():
    def read(hard, confidence, moisture, light=()):
        return {
            "detected": {
                "contamination": "x" if hard else "none detected",
                "moisture": moisture,
                "hard_contaminants": list(hard),
                "light_contaminants": list(light),
            },
            "confidence": confidence,
            "boxes": [],
            "model": "m",
        }

    merged = pipeline.merge_frame_reads(
        [read([], 0.25, 0.1), read(["metal"], 0.7, 0.4, ["glass"]), read(["tire"], 0.5, 0.2)]
    )
    # Tire was seen below the hard-contaminant confidence: not in the union.
    assert merged["detected"]["hard_contaminants"] == ["metal"]
    assert merged["detected"]["light_contaminants"] == ["glass"]
    assert merged["detected"]["moisture"] == 0.4
    assert merged["confidence"] == 0.7  # the frames that found it
    clean = pipeline.merge_frame_reads([read([], 0.9, 0.1), read([], 0.4, 0.1)])
    assert clean["confidence"] == 0.4  # otherwise the least sure frame
    assert clean["detected"]["hard_contaminants"] == []


def test_vlm_frames_reads_each_angle_once(monkeypatch):
    monkeypatch.setenv("VLM_VOTES", "3")
    calls = []

    def chat_once(self, base_url, model, messages, max_tokens=512):
        image = messages[0]["content"][1]["image_url"]["url"]
        calls.append(image)
        metal = image.endswith(_SIDE)
        return json.dumps(
            {
                "contamination": "pipe" if metal else "none detected",
                "moisture": 0.1,
                "hard_contaminants": ["metal"] if metal else [],
                "light_contaminants": [],
                "confidence": 0.8,
                "locations": [],
            }
        )

    monkeypatch.setattr(pipeline.VLLMClient, "_chat_once", chat_once)
    events = []
    results = pipeline.VLLMClient(settings=get_settings()).vlm_frames(
        [_MAIN, _SIDE], on_progress=lambda *e: events.append(e)
    )
    assert len(calls) == 2
    assert [r["detected"]["hard_contaminants"] for r in results] == [[], ["metal"]]
    reads = [data for stage, status, data in events if stage == "vision_read"]
    assert sorted(r["frame"] for r in reads) == [0, 1]
    assert {r["of"] for r in reads} == {2}
    assert sorted(r["index"] for r in reads) == [1, 2]
