"""POST /waybill/extract — waybill OCR by the live vision model.

No network: ``_vlm_reachable`` and ``VLLMClient._chat_json`` are patched, so
the real ``read_waybill`` chain and the Python post-processing
(``pipeline.waybill_fields``) run on a scripted model transcription.  The
expected values are the ones printed on web/public/demo/waybill-1.jpg.
"""

from __future__ import annotations

import base64

import httpx
import pytest
from fastapi.testclient import TestClient

from lynceus import api, auth, pipeline
from lynceus.api import MAX_PHOTO_BYTES, create_app
from lynceus.config import (
    LYNCEUS_ALLOW_STUB_FALLBACK_ENV,
    LYNCEUS_STORAGE_DIR_ENV,
    VLLM_VLM_URL_ENV,
    VLM_FALLBACK_MODELS_ENV,
    VLM_MODEL_ENV,
)

_AMD_URL = "https://developer.amd.com.cn/radeon/api/v1"
_PRIMARY = "DeepSeek-V4-Flash-Vision-Exp"
_FALLBACK = "Gemma-4-31B-IT"
#: A JPEG by magic bytes; the model is scripted, so the pixels never matter.
_JPEG_B64 = base64.b64encode(b"\xff\xd8\xff\xe0" + b"\x00" * 64).decode("ascii")

#: What the model transcribes from the sample waybill, as written on paper.
_SAMPLE_READ = {
    "truck_id": "b 9723  kxw",
    "supplier": "PT. Hijau Lestari Transport",
    "weight_kg": "16.340",
    "stream_raw": "RDF fluff",
    "moisture_pct": "28 %",
    "waybill_no": "007842",
    "date": "14 / 05 / 2025",
    "origin": "TPST Bantargebang Bekasi",
    "destination": "PLTSa Rorotan Jakarta Utara",
    "driver": "Slamet Riyadi",
    "reference": "DO - 250514 - 0198",  # as the live model read it
    "confidence": 0.91,
}

_FIELD_NAMES = (
    "truck_id", "supplier", "weight_kg", "stream", "moisture_pct", "waybill_no",
    "date", "origin", "destination", "driver", "reference",
)


def _clear_auth(monkeypatch) -> None:
    for name in (
        auth.LYNCEUS_ADMIN_USERNAME_ENV,
        auth.LYNCEUS_ADMIN_PASSWORD_ENV,
        auth.LYNCEUS_ADMIN_PASSWORD_SHA256_ENV,
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """Open (auth off) app on the AMD URL, endpoint reachable, no network."""
    _clear_auth(monkeypatch)
    monkeypatch.setenv(LYNCEUS_STORAGE_DIR_ENV, str(tmp_path))
    monkeypatch.setenv(VLLM_VLM_URL_ENV, _AMD_URL)
    monkeypatch.setenv(VLM_MODEL_ENV, _PRIMARY)
    monkeypatch.setenv(VLM_FALLBACK_MODELS_ENV, "")
    monkeypatch.setattr(pipeline, "_vlm_reachable", lambda *a, **k: True)
    auth.reset_signer()
    yield TestClient(create_app())
    auth.reset_signer()


def _script(monkeypatch, *answers):
    """Each ``_chat_json`` call pops the next answer (raised when an exception)."""
    calls = []
    queue = list(answers)

    def fake_chat_json(self, base_url, model, messages, max_tokens=1024):
        calls.append({"url": base_url, "model": model, "messages": messages})
        answer = queue.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return dict(answer)

    monkeypatch.setattr(pipeline.VLLMClient, "_chat_json", fake_chat_json)
    return calls


def _post(client, image_b64=_JPEG_B64, filename="waybill-1.jpg"):
    return client.post(
        "/waybill/extract", json={"image_base64": image_b64, "filename": filename}
    )


def test_sample_waybill_maps_to_register_fields(client, monkeypatch):
    calls = _script(monkeypatch, _SAMPLE_READ)
    resp = _post(client)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["fields"] == {
        "truck_id": "B 9723 KXW",
        "supplier": "PT. Hijau Lestari Transport",
        "weight_kg": 16340,
        "stream": "rdf-feedstock",
        "moisture_pct": 28,
        "waybill_no": "007842",
        "date": "2025-05-14",
        "origin": "TPST Bantargebang Bekasi",
        "destination": "PLTSa Rorotan Jakarta Utara",
        "driver": "Slamet Riyadi",
        "reference": "DO-250514-0198",
    }
    assert body["stream_raw"] == "RDF fluff"
    assert body["confidence"] == pytest.approx(0.91)
    assert body["model"] == _PRIMARY
    assert body["provider"] == "amd-token-factory"
    assert body["provenance"] == "live"
    assert isinstance(body["latency_ms"], (int, float)) and body["latency_ms"] >= 0
    assert "fallback_from" not in body
    # One read (no votes), sent to the vision endpoint with the image attached.
    assert len(calls) == 1
    assert calls[0]["url"] == _AMD_URL
    image_part = calls[0]["messages"][0]["content"][1]
    assert image_part["image_url"]["url"] == f"data:image/jpeg;base64,{_JPEG_B64}"


@pytest.mark.parametrize(
    ("written", "expected"),
    [
        ("16.340", 16340),
        ("16,340", 16340),
        ("16340 kg", 16340),
        ("16 340 kg", 16340),
        ("16.340,5", 16340.5),
        ("16,340.5", 16340.5),
        (16340, 16340),
        ("1.234.567", None),  # > 100 000 kg: not one truck load
        ("0", None),
        ("-500", None),
        ("-", None),
        ("berat", None),
        (None, None),
    ],
)
def test_indonesian_weight_parsing(written, expected):
    fields, _ = pipeline.waybill_fields({"weight_kg": written})
    assert fields["weight_kg"] == expected


@pytest.mark.parametrize(
    ("written", "expected"),
    [("28 %", 28), ("28,5", 28.5), ("140", None), ("-3", None), ("n/a", None)],
)
def test_moisture_parsing(written, expected):
    fields, _ = pipeline.waybill_fields({"moisture_pct": written})
    assert fields["moisture_pct"] == expected


@pytest.mark.parametrize(
    ("written", "expected"),
    [
        ("RDF fluff", "rdf-feedstock"),
        ("Sampah organik pasar", "organic-rich"),
        ("Sampah taman", "green-waste"),
        ("Plastik & paper bales", "dry-recyclables"),
        ("Sampah campuran", "mixed-msw"),
        ("Co-disposal MSW + sludge", "co-disposal"),
        ("mixed-msw", "mixed-msw"),
        ("Limbah B3 medis", None),
    ],
)
def test_stream_mapping(written, expected):
    fields, stream_raw = pipeline.waybill_fields({"stream_raw": written})
    assert fields["stream"] == expected
    assert stream_raw == written


def test_unknown_stream_is_null_but_raw_is_kept(client, monkeypatch):
    _script(monkeypatch, {**_SAMPLE_READ, "stream_raw": "Limbah B3 medis"})
    body = _post(client).json()
    assert body["fields"]["stream"] is None
    assert body["stream_raw"] == "Limbah B3 medis"


def test_unreadable_waybill_is_all_nulls(client, monkeypatch):
    _script(monkeypatch, {**{k: None for k in _SAMPLE_READ}, "confidence": 0.05})
    resp = _post(client)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["fields"] == {name: None for name in _FIELD_NAMES}
    assert body["stream_raw"] is None
    assert body["confidence"] == pytest.approx(0.05)


def test_confidence_is_clamped(client, monkeypatch):
    _script(monkeypatch, {**_SAMPLE_READ, "confidence": 7})
    assert _post(client).json()["confidence"] == 1.0


def test_fallback_model_answers_and_is_named(client, monkeypatch):
    monkeypatch.setenv(VLM_FALLBACK_MODELS_ENV, _FALLBACK)
    calls = _script(monkeypatch, ValueError("not JSON"), _SAMPLE_READ)
    body = _post(client).json()
    assert [c["model"] for c in calls] == [_PRIMARY, _FALLBACK]
    assert body["model"] == _FALLBACK
    assert body["fallback_from"][0].startswith(f"{_PRIMARY}: ValueError")
    assert body["fields"]["truck_id"] == "B 9723 KXW"


def test_data_uri_is_accepted(client, monkeypatch):
    _script(monkeypatch, _SAMPLE_READ)
    resp = _post(client, image_b64=f"data:image/jpeg;base64,{_JPEG_B64}")
    assert resp.status_code == 200, resp.text


def test_bad_image_is_422(client, monkeypatch):
    calls = _script(monkeypatch, _SAMPLE_READ)
    not_an_image = base64.b64encode(b"GIF89a not accepted").decode("ascii")
    resp = _post(client, image_b64=not_an_image)
    assert resp.status_code == 422
    assert resp.json()["detail"]["error"] == "invalid_photo"
    assert _post(client, image_b64="%%% not base64").status_code == 422
    assert calls == []


def test_too_big_image_is_413(client, monkeypatch):
    calls = _script(monkeypatch, _SAMPLE_READ)
    huge = base64.b64encode(b"\xff\xd8\xff" + b"\x00" * MAX_PHOTO_BYTES).decode("ascii")
    resp = _post(client, image_b64=huge)
    assert resp.status_code == 413
    assert resp.json()["detail"]["error"] == "photo_too_large"
    assert calls == []


def test_auth_on_without_session_is_401(tmp_path, monkeypatch):
    monkeypatch.setenv(auth.LYNCEUS_ADMIN_USERNAME_ENV, "operator")
    monkeypatch.setenv(auth.LYNCEUS_ADMIN_PASSWORD_ENV, "pw")
    monkeypatch.delenv(auth.LYNCEUS_ADMIN_PASSWORD_SHA256_ENV, raising=False)
    monkeypatch.setenv(LYNCEUS_STORAGE_DIR_ENV, str(tmp_path))
    calls = _script(monkeypatch, _SAMPLE_READ)
    auth.reset_signer()
    try:
        resp = _post(TestClient(create_app()))
    finally:
        auth.reset_signer()
    assert resp.status_code == 401
    assert resp.json()["detail"]["error"] == "authentication_required"
    assert calls == []


def _assert_ocr_unavailable(resp) -> None:
    assert resp.status_code == 503, resp.text
    detail = resp.json()["detail"]
    assert detail["error"] == "ocr_unavailable"
    assert "fill in the register by hand" in detail["message"]


@pytest.mark.parametrize("stub_fallback", ["1", "0"])
def test_endpoint_down_is_503_never_stub(client, monkeypatch, stub_fallback):
    monkeypatch.setenv(LYNCEUS_ALLOW_STUB_FALLBACK_ENV, stub_fallback)
    monkeypatch.setattr(pipeline, "_vlm_reachable", lambda *a, **k: False)
    calls = _script(monkeypatch, _SAMPLE_READ)
    _assert_ocr_unavailable(_post(client))
    assert calls == []


def test_model_chain_failure_is_503(client, monkeypatch):
    monkeypatch.setenv(VLM_FALLBACK_MODELS_ENV, _FALLBACK)
    monkeypatch.setenv(LYNCEUS_ALLOW_STUB_FALLBACK_ENV, "1")
    _script(monkeypatch, ValueError("not JSON"), ValueError("not JSON either"))
    _assert_ocr_unavailable(_post(client))


def test_connection_failure_is_503(client, monkeypatch):
    _script(monkeypatch, httpx.ConnectError("refused"))
    _assert_ocr_unavailable(_post(client))


def test_busy_reader_is_503(client, monkeypatch):
    _script(monkeypatch, _SAMPLE_READ)
    taken = 0
    try:
        while api._WAYBILL_SLOTS.acquire(blocking=False):
            taken += 1
        resp = _post(client)
    finally:
        for _ in range(taken):
            api._WAYBILL_SLOTS.release()
    assert resp.status_code == 503
    assert resp.json()["detail"]["error"] == "busy"
    # Slots were returned: the next read goes through.
    assert _post(client).status_code == 200


def test_large_photo_is_reencoded_before_upload():
    """A big phone photo goes to the model as a smaller, upright JPEG."""
    import io

    from PIL import Image

    # Sensor-noise texture at max quality: heavy like a raw phone photo.
    big = Image.effect_noise((4000, 3000), 40).convert("RGB")
    buf = io.BytesIO()
    big.save(buf, "JPEG", quality=100)
    raw_b64 = base64.b64encode(buf.getvalue()).decode("ascii")

    uri = pipeline._compact_waybill_image(raw_b64)
    assert uri.startswith("data:image/jpeg;base64,")
    payload = base64.b64decode(uri.split(",", 1)[1])
    assert len(payload) < len(buf.getvalue())
    with Image.open(io.BytesIO(payload)) as out:
        assert max(out.size) == pipeline.WAYBILL_MAX_SIDE_PX
        assert out.size == (2000, 1500)


def test_unreadable_image_is_sent_as_is():
    assert pipeline._compact_waybill_image(_JPEG_B64) == f"data:image/jpeg;base64,{_JPEG_B64}"
