"""Audit record format v2: supplier, provenance, boxes, SOP-cited actions.

Writer always stamps 2; reader accepts 1 and 2 and rejects everything else.
"""

from __future__ import annotations

import json

import pytest

from lynceus import audit as A

APP = {"name": "lynceus", "version": "1.0.0"}
PHOTO = b"\xff\xd8fake-jpeg"
MANIFEST = b"WASTE MANIFEST"


def _inputs():
    return {
        "truck_id": "B-1-KT",
        "photo": {
            "filename": "p.jpg",
            "sha256": A.sha256_field(PHOTO),
            "captured_at_utc": "2026-10-13T02:14:52Z",
            "provenance": "gate_camera",
        },
        "manifest_text": {
            "source": "manual_text",
            "raw_text_sha256": A.sha256_field(MANIFEST),
            "extracted_fields": {},
            "ocr_confidence": 0.9,
        },
        "weight": {"value_kg": 4000.0, "source": "weighbridge", "measured_at_utc": "2026-10-13T02:14:55Z"},
        "gas": {"readings_ppm": {"ch4": 1.0}, "source": "digital_twin", "measured_at_utc": "2026-10-13T02:14:58Z"},
    }


def _ai(**vlm_extra):
    return {
        "vlm": {
            "model": "m",
            "model_version": "1",
            "raw_output_sha256": A.sha256_field(b"v"),
            "detected": {},
            "confidence": 0.8,
            **vlm_extra,
        },
        "llm": {
            "model": "m",
            "model_version": "1",
            "prompt_sha256": A.sha256_field(b"p"),
            "raw_output_sha256": A.sha256_field(b"l"),
            "reasoning": "ok",
            "confidence": 0.8,
        },
    }


def _engine(**rec_extra):
    return {
        "suitability": {"classification": "x", "score": 0.5, "rule": "r"},
        "recommendation": {
            "actionable": True,
            "route": "accept_processing",
            "headline": "ok",
            "insufficient": False,
            "missing": [],
            "caveats": [],
            "alternative": "",
            **rec_extra,
        },
    }


_VERDICT = {
    "decision": "accept",
    "decided_at_utc": "2026-10-13T02:15:40Z",
    "classification": "screening_estimate",
    "uncertainty": "u",
}
_GATES = {
    g: {"state": "passed", "value": None, "threshold": None, "reason": None}
    for g in A.GATE_NAMES
}
_DIGESTS = {"photo": A.sha256_field(PHOTO), "manifest_text": A.sha256_field(MANIFEST)}


def _write(tmp_path, inputs=None, ai=None, engine=None):
    inputs = inputs or _inputs()
    rec = A.begin_record(tmp_path, APP, inputs, _DIGESTS)
    return A.finish_record(
        tmp_path,
        rec.record_id,
        "completed",
        A.now_utc(),
        APP,
        inputs,
        ai or _ai(),
        engine or _engine(),
        _VERDICT,
        _GATES,
    )


def _path(tmp_path, rec):
    return tmp_path / rec.record_id / A.RECORD_FILENAME


def test_constants():
    assert A.AUDIT_FORMAT_VERSION == 2
    assert A.SUPPORTED_FORMAT_VERSIONS == (1, 2)


def test_writes_v2(tmp_path):
    rec = _write(tmp_path)
    assert rec.format_version == 2
    assert json.loads(_path(tmp_path, rec).read_text(encoding="utf-8"))["format_version"] == 2


def test_begin_record_writes_v2(tmp_path):
    rec = A.begin_record(tmp_path, APP, _inputs(), _DIGESTS)
    assert rec.format_version == 2
    assert rec.ai_outputs.vlm.boxes == []
    assert rec.inputs.supplier is None


def test_reads_v1_record(tmp_path):
    rec = _write(tmp_path)
    path = _path(tmp_path, rec)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["format_version"] = 1
    data["inputs"].pop("supplier", None)
    for key in ("provider", "latency_ms", "boxes", "localisation"):
        data["ai_outputs"]["vlm"].pop(key, None)
    for key in ("provider", "latency_ms"):
        data["ai_outputs"]["llm"].pop(key, None)
    data["engine_outputs"]["recommendation"].pop("actions", None)
    path.write_text(json.dumps(data), encoding="utf-8")

    loaded = A.load_record(path)
    assert loaded.format_version == 1
    assert loaded.inputs.supplier is None
    assert loaded.ai_outputs.vlm.boxes == []
    assert loaded.ai_outputs.vlm.localisation is None
    assert loaded.ai_outputs.vlm.provider is None
    assert loaded.ai_outputs.llm.latency_ms is None
    assert loaded.engine_outputs.recommendation.actions == []


@pytest.mark.parametrize("version", [0, 3, 99])
def test_rejects_unsupported_version(tmp_path, version):
    rec = _write(tmp_path)
    path = _path(tmp_path, rec)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["format_version"] = version
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(A.AuditError, match="format_version"):
        A.load_record(path)


def test_v2_fields_roundtrip(tmp_path):
    inputs = _inputs()
    inputs["supplier"] = "CV Sampah Jaya"
    ai = _ai(
        provider="amd-token-factory",
        latency_ms=812.5,
        localisation="box",
        boxes=[{"label": "metal", "x0": 0.1, "y0": 0.2, "x1": 0.5, "y1": 0.6}],
    )
    ai["llm"]["provider"] = "openai-compatible"
    ai["llm"]["latency_ms"] = 0.0
    engine = _engine(actions=[{"order": 1, "text": "Segregate load", "sop_ref": "SOP-RDF-5.3"}])
    rec = _write(tmp_path, inputs, ai, engine)
    loaded = A.load_record(_path(tmp_path, rec))
    assert loaded.inputs.supplier == "CV Sampah Jaya"
    assert loaded.ai_outputs.vlm.provider == "amd-token-factory"
    assert loaded.ai_outputs.vlm.latency_ms == 812.5
    assert loaded.ai_outputs.vlm.localisation == "box"
    assert loaded.ai_outputs.vlm.boxes[0].label == "metal"
    assert loaded.ai_outputs.llm.latency_ms == 0.0
    assert loaded.engine_outputs.recommendation.actions[0].sop_ref == "SOP-RDF-5.3"


def _box(**kw):
    b = {"label": "metal", "x0": 0.1, "y0": 0.1, "x1": 0.5, "y1": 0.5}
    b.update(kw)
    return b


@pytest.mark.parametrize(
    "bad",
    [
        _box(x0=0.5, x1=0.5),  # x0 >= x1
        _box(y0=0.7, y1=0.2),  # y0 >= y1
        _box(x1=1.2),  # out of range
        _box(x0=-0.1),
        _box(y1=float("nan")),
    ],
)
def test_box_validation(tmp_path, bad):
    with pytest.raises(A.AuditError):
        _write(tmp_path, ai=_ai(boxes=[bad]))


def test_box_boundary_values_accepted(tmp_path):
    rec = _write(tmp_path, ai=_ai(boxes=[_box(x0=0.0, y0=0.0, x1=1.0, y1=1.0)]))
    assert rec.ai_outputs.vlm.boxes[0].x1 == 1.0


@pytest.mark.parametrize(
    "ref", ["SOP-X", "SOP-RDF-5", "sop-rdf-5.3", "SOP-RDF-5.3.1", " SOP-RDF-5.3", "SOP-RDF-5.3\n"]
)
def test_action_sop_ref_pattern(tmp_path, ref):
    with pytest.raises(A.AuditError):
        _write(tmp_path, engine=_engine(actions=[{"order": 1, "text": "t", "sop_ref": ref}]))


def test_action_order_and_text_validation(tmp_path):
    for bad in (
        {"order": 0, "text": "t", "sop_ref": "SOP-RDF-1.1"},
        {"order": 1, "text": "", "sop_ref": "SOP-RDF-1.1"},
    ):
        with pytest.raises(A.AuditError):
            _write(tmp_path, engine=_engine(actions=[bad]))


def test_localisation_closed_enum(tmp_path):
    with pytest.raises(A.AuditError, match="localisation"):
        _write(tmp_path, ai=_ai(localisation="polygon"))


@pytest.mark.parametrize("latency", [-1.0, float("inf")])
def test_latency_must_be_finite_non_negative(tmp_path, latency):
    with pytest.raises(A.AuditError):
        _write(tmp_path, ai=_ai(latency_ms=latency))


def test_v2_strictness_unchanged_extra_keys_rejected(tmp_path):
    with pytest.raises(A.AuditError):
        _write(tmp_path, ai=_ai(boxes=[{**_box(), "color": "red"}]))
