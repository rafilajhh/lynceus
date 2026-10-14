"""Task 12 hardening: upload validation, engine insufficiency, tie margin,
malformed-URL probes and per-call AI timeouts.

No network: the AI layer is the offline stub, ``httpx`` is monkeypatched
wherever a probe would otherwise leave the process.
"""

from __future__ import annotations

import base64

import httpx
import pytest
from fastapi.testclient import TestClient

from lynceus import audit, engine_adapter, pipeline
from lynceus.api import create_app
from lynceus.config import LYNCEUS_STORAGE_DIR_ENV, get_settings
from lynceus_engine import recommend as rec_mod
from lynceus_engine import suitability as suit
from lynceus_engine.composition import PRESETS

_MB = 1024 * 1024
_JPEG_HEAD = b"\xff\xd8\xff\xe0"
_PNG_HEAD = b"\x89PNG\r\n\x1a\n"

_BASE = {
    "truck_id": "B-9174-KT",
    "demo_case": "green",
    "manifest_text": "Declared weight: 18,400 kg. Moisture declared: 10% (dry).",
    "weight_kg": 18500,
    "waste_stream": "rdf-feedstock",
    "moisture": 0.095,
    "age_h": 5,
}


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv(LYNCEUS_STORAGE_DIR_ENV, str(tmp_path))
    monkeypatch.setattr(pipeline, "_vlm_reachable", lambda *a, **k: False)
    return TestClient(create_app())


def _records(tmp_path):
    return sorted(p.name for p in tmp_path.glob("inspection-*"))


# ---------------------------------------------------------------------------
# Upload validation (ruling 3) — rejected BEFORE audit.begin_record.
# ---------------------------------------------------------------------------


def test_photo_over_8mb_is_413_and_leaves_no_record(client, tmp_path):
    big = _JPEG_HEAD + b"\x00" * (8 * _MB)  # 8 MB + 4 bytes decoded
    resp = client.post("/inspect", json={**_BASE, "photo_base64": _b64(big)})
    assert resp.status_code == 413, resp.text[:200]
    assert resp.json()["detail"]["error"] == "photo_too_large"
    assert _records(tmp_path) == []


def test_photo_of_exactly_8mb_is_accepted(client, tmp_path):
    exact = _JPEG_HEAD + b"\x00" * (8 * _MB - len(_JPEG_HEAD))
    resp = client.post("/inspect", json={**_BASE, "photo_base64": _b64(exact)})
    assert resp.status_code == 200, resp.text[:200]
    assert len(_records(tmp_path)) == 1


@pytest.mark.parametrize(
    "photo",
    [
        "!!! not base64 !!!",
        "c3R1Yi1waG90bw==",  # valid base64, bytes are not an image
        _b64(b"GIF89a" + b"\x00" * 32),
        _b64(b"RIFF\x00\x00\x00\x00WEBPVP8 "),
        "data:image/jpeg;base64,!!!",
        "data:image/jpeg;base64," + _b64(b"%PDF-1.7 not an image"),
    ],
)
def test_non_image_or_invalid_base64_is_422_and_leaves_no_record(
    client, tmp_path, photo
):
    resp = client.post("/inspect", json={**_BASE, "photo_base64": photo})
    assert resp.status_code == 422, resp.text[:200]
    assert resp.json()["detail"]["error"] == "invalid_photo"
    assert _records(tmp_path) == []


@pytest.mark.parametrize(
    "photo",
    [
        _b64(_JPEG_HEAD + b"jpeg-bytes"),
        _b64(_PNG_HEAD + b"png-bytes"),
        "data:image/jpeg;base64," + _b64(_JPEG_HEAD + b"jpeg-bytes"),
        "data:image/png;base64," + _b64(_PNG_HEAD + b"png-bytes"),
    ],
)
def test_jpeg_and_png_with_or_without_data_prefix_are_accepted(
    client, tmp_path, photo
):
    resp = client.post("/inspect", json={**_BASE, "photo_base64": photo})
    assert resp.status_code == 200, resp.text[:200]
    assert len(_records(tmp_path)) == 1


def test_no_photo_still_reaches_the_refusal_path(client, tmp_path):
    body = {k: v for k, v in _BASE.items() if k != "demo_case"}
    resp = client.post("/inspect", json=body)
    assert resp.status_code == 200
    assert resp.json()["verdict"]["decision"] == "refuse_insufficient_input"


def test_photo_digest_is_of_the_decoded_bytes(client, tmp_path):
    raw = _JPEG_HEAD + b"digest-me"
    resp = client.post("/inspect", json={**_BASE, "photo_base64": _b64(raw)})
    assert resp.status_code == 200
    record = resp.json()["audit_record"]
    assert record["inputs"]["photo"]["sha256"] == audit.sha256_field(raw)


# ---------------------------------------------------------------------------
# Engine insufficiency is read from the engine, not hard-coded.
# ---------------------------------------------------------------------------


def test_engine_tonnage_zero_is_insufficient_and_not_actionable():
    result = engine_adapter.run_assessment("mixed-msw", 0.0, 0.40, 48.0)
    rec = result["recommendation"]
    assert rec["insufficient"] is True
    assert rec["actionable"] is False
    assert rec["missing"] == ["tonnage_t"]
    assert rec["tied"] is False


def test_engine_insufficiency_reaches_verdict_and_audit_record(
    client, tmp_path, monkeypatch
):
    real = engine_adapter.run_assessment
    monkeypatch.setattr(
        engine_adapter,
        "run_assessment",
        lambda waste_stream, tonnage_t, moisture, age_h: real(
            waste_stream, 0.0, moisture, age_h
        ),
    )
    resp = client.post("/inspect", json={**_BASE, "photo_base64": _b64(_JPEG_HEAD + b"x")})
    assert resp.status_code == 200, resp.text[:300]
    body = resp.json()
    assert body["verdict"]["decision"] == "refuse_insufficient_input"
    rec = body["engine_outputs"]["recommendation"]
    assert rec["insufficient"] is True
    assert rec["actionable"] is False
    assert rec["missing"] == ["tonnage_t"]
    assert rec["route"] == audit.Route.HOLD_FOR_REVIEW


# ---------------------------------------------------------------------------
# Tie margin (ruling 2).
# ---------------------------------------------------------------------------


def _suitability(**scores: float) -> suit.Suitability:
    full = {route: 0.10 for route in suit.ROUTES}
    full.update(scores)
    return suit.Suitability(
        scores={
            route: suit.RouteScore(route=route, score=value, rule="stub rule", inputs={})
            for route, value in full.items()
        },
        quality=suit.QualityInputs(),
    )


def _recommend(monkeypatch, **scores: float) -> rec_mod.Recommendation:
    monkeypatch.setattr(
        rec_mod.suit, "assess", lambda comp, *, moisture, quality=None: _suitability(**scores)
    )
    return rec_mod.recommend(
        PRESETS["mixed-msw"], tonnage_t=10.0, moisture=0.30, age_h=24.0, screening=False
    )


def test_exact_tie_is_flagged(monkeypatch):
    rec = _recommend(monkeypatch, rdf=0.49, composting=0.49)
    assert rec.tied is True
    assert "routes tied within 0.02" in rec.caveats
    assert "tied" in rec.headline.lower()


def test_margin_of_exactly_two_hundredths_still_ties(monkeypatch):
    rec = _recommend(monkeypatch, rdf=0.50, composting=0.48)
    assert rec.tied is True


def test_clear_winner_is_not_tied(monkeypatch):
    rec = _recommend(monkeypatch, rdf=0.60, composting=0.49)
    assert rec.tied is False
    assert not any("tied" in c for c in rec.caveats)
    assert rec.headline == "Recommended for RDF processing."


def test_tied_flag_is_serialised():
    result = engine_adapter.run_assessment("mixed-msw", 10.0, 0.30, 24.0)
    assert result["recommendation"]["tied"] in (True, False)


def test_tie_maps_to_hold_for_review(client, tmp_path, monkeypatch):
    real = engine_adapter.run_assessment

    def tied(waste_stream, tonnage_t, moisture, age_h):
        out = real(waste_stream, tonnage_t, moisture, age_h)
        out["recommendation"]["route"] = "rdf"
        out["recommendation"]["tied"] = True
        return out

    monkeypatch.setattr(engine_adapter, "run_assessment", tied)
    resp = client.post("/inspect", json={**_BASE, "photo_base64": _b64(_JPEG_HEAD + b"x")})
    assert resp.status_code == 200, resp.text[:300]
    rec = resp.json()["engine_outputs"]["recommendation"]
    assert rec["route"] == audit.Route.HOLD_FOR_REVIEW
    assert rec["actionable"] is True


# ---------------------------------------------------------------------------
# Carried: malformed URL must not 500 the probes.
# ---------------------------------------------------------------------------


def test_vlm_probe_survives_malformed_url(monkeypatch):
    monkeypatch.setenv("VLLM_VLM_URL", "http://host:abc/v1")
    assert pipeline._vlm_reachable(get_settings()) is False


def test_assist_probe_survives_malformed_url(monkeypatch):
    monkeypatch.setenv("ASSIST_URL", "http://host:abc/v1")
    assert pipeline._assist_reachable(get_settings()) is False


def test_resolve_assist_client_is_none_for_malformed_url(monkeypatch):
    monkeypatch.setenv("ASSIST_URL", "http://host:abc/v1")
    assert pipeline.resolve_assist_client(get_settings()) is None


def test_inspect_with_malformed_vlm_url_degrades_to_labelled_fallback(
    tmp_path, monkeypatch
):
    # No reachability stub here: the real probe runs against a malformed URL.
    # A non-demo request with an unreachable endpoint is never plain "stub"
    # (that label is for scripted demo cases): it is the marked fallback.
    monkeypatch.setenv(LYNCEUS_STORAGE_DIR_ENV, str(tmp_path))
    monkeypatch.setenv("VLLM_VLM_URL", "http://host:abc/v1")
    body = {k: v for k, v in _BASE.items() if k != "demo_case"}
    resp = TestClient(create_app()).post(
        "/inspect", json={**body, "photo_base64": _b64(_JPEG_HEAD + b"x")}
    )
    assert resp.status_code == 200, resp.text[:300]
    assert resp.json()["provenance"] == "stub_fallback_live_error"


# ---------------------------------------------------------------------------
# Carried: per-call AI timeouts (VLM 90 s, LLM cross-check 45 s, assist 30 s).
# ---------------------------------------------------------------------------


class _FakeStream:
    status_code = 200
    headers = {"content-type": "application/json"}

    def __init__(self, content: str) -> None:
        self._content = content

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def raise_for_status(self):
        return None

    def read(self) -> bytes:
        import json

        return json.dumps({"choices": [{"message": {"content": self._content}}]}).encode()

    def iter_bytes(self):
        yield self.read()


def _capture_timeouts(monkeypatch, content: str) -> list[float]:
    seen: list[float] = []

    def fake_stream(method, url, **kwargs):
        seen.append(kwargs["timeout"])
        return _FakeStream(content)

    monkeypatch.setattr(httpx, "stream", fake_stream)
    return seen


def test_vlm_keeps_90s_llm_gets_45s(monkeypatch):
    client = pipeline.VLLMClient(settings=get_settings())
    seen = _capture_timeouts(
        monkeypatch,
        '{"contamination": "none", "moisture": 0.1, "hard_contaminants": [], '
        '"light_contaminants": [], "reasoning": "ok", "confidence": 0.8}',
    )
    client.vlm(_b64(_JPEG_HEAD + b"x"))
    client.llm("waybill", {})
    assert seen == [90.0, 45.0]


def test_assist_call_gets_30s(monkeypatch):
    client = pipeline.VLLMClient(settings=get_settings())
    seen = _capture_timeouts(monkeypatch, '{"answer": "x", "citations": []}')
    client.assist([{"role": "user", "content": "q"}])
    assert seen == [30.0]


def test_resolved_assist_client_uses_the_assist_budget(monkeypatch):
    monkeypatch.setattr(pipeline, "_assist_reachable", lambda *a, **k: True)
    client = pipeline.resolve_assist_client(get_settings())
    seen = _capture_timeouts(monkeypatch, '{"answer": "x", "citations": []}')
    client.assist([{"role": "user", "content": "q"}])
    assert seen == [30.0]


def test_png_upload_is_labelled_png_for_the_vlm(monkeypatch):
    sent: list[dict] = []

    def fake_stream(method, url, **kwargs):
        sent.append(kwargs["json"])
        return _FakeStream(
            '{"contamination": "none", "moisture": 0.1, "hard_contaminants": [], '
            '"light_contaminants": [], "confidence": 0.8}'
        )

    monkeypatch.setattr(httpx, "stream", fake_stream)
    client = pipeline.VLLMClient(settings=get_settings())
    client.vlm(_b64(_PNG_HEAD + b"png"))
    client.vlm(_b64(_JPEG_HEAD + b"jpg"))
    urls = [p["messages"][0]["content"][1]["image_url"]["url"] for p in sent]
    assert urls[0].startswith("data:image/png;base64,")
    assert urls[1].startswith("data:image/jpeg;base64,")


# ---------------------------------------------------------------------------
# Carried: the seeding script must print ASCII only (Windows cp1252 consoles).
# ---------------------------------------------------------------------------


def test_seed_demo_console_output_is_ascii(tmp_path, monkeypatch, capsys):
    import importlib.util
    from pathlib import Path

    script = Path(__file__).resolve().parents[1] / "scripts" / "seed_demo.py"
    spec = importlib.util.spec_from_file_location("seed_demo_under_test", script)
    seed_demo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(seed_demo)
    # main() patches the reachability probe and the storage env var globally;
    # register both with monkeypatch so they are restored after the test.
    monkeypatch.setattr(pipeline, "_vlm_reachable", pipeline._vlm_reachable)
    monkeypatch.setenv(LYNCEUS_STORAGE_DIR_ENV, str(tmp_path))
    assert seed_demo.main(["--storage-dir", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert out.isascii(), out
    assert "->" in out


# ---------------------------------------------------------------------------
# Carried: the ledger's "prevented" total is prevented loss only.
# ---------------------------------------------------------------------------


def test_ledger_splits_prevented_loss_from_admitted_value(client, tmp_path):
    for case, weight, stream, moisture in (
        ("green", 18500, "rdf-feedstock", 0.095),
        ("red", 19300, "mixed-msw", 0.14),
    ):
        resp = client.post(
            "/inspect",
            json={
                **_BASE,
                "demo_case": case,
                "weight_kg": weight,
                "waste_stream": stream,
                "moisture": moisture,
            },
        )
        assert resp.status_code == 200, resp.text[:200]
    rows = {
        row["decision"]: row
        for row in client.get(
            "/inspections", headers={"accept": "application/json"}
        ).json()["inspections"]
    }
    assert rows["accept"]["prevented_loss_idr"] == 0
    assert rows["accept"]["admitted_value_idr"] > 0
    assert rows["reject"]["prevented_loss_idr"] > 0
    assert rows["reject"]["admitted_value_idr"] == 0


# ---------------------------------------------------------------------------
# Tie must not leave an ACCEPT verdict beside a hold_for_review route.
# ---------------------------------------------------------------------------

_TIE_REASON = "Engine routes tied within 0.02; hold for supervisor review."


def _tied_engine(monkeypatch):
    real = engine_adapter.run_assessment

    def tied(waste_stream, tonnage_t, moisture, age_h):
        out = real(waste_stream, tonnage_t, moisture, age_h)
        out["recommendation"]["tied"] = True
        return out

    monkeypatch.setattr(engine_adapter, "run_assessment", tied)


def test_tied_clean_load_escalates_instead_of_accepting(client, tmp_path, monkeypatch):
    _tied_engine(monkeypatch)
    resp = client.post("/inspect", json={**_BASE, "photo_base64": _b64(_JPEG_HEAD + b"x")})
    assert resp.status_code == 200, resp.text[:300]
    body = resp.json()
    assert body["verdict"]["decision"] == "escalate_human"
    assert body["reasons"] == [_TIE_REASON]
    assert body["engine_outputs"]["recommendation"]["route"] == audit.Route.HOLD_FOR_REVIEW
    assert [(a["order"], a["sop_ref"]) for a in body["actions"]] == [(1, "SOP-RDF-5.2")]
    # The persisted record decodes strictly and says the same thing.
    record = audit.load_record(tmp_path / body["record_id"] / audit.RECORD_FILENAME)
    assert record.verdict.decision == "escalate_human"
    assert record.engine_outputs.recommendation.route == audit.Route.HOLD_FOR_REVIEW


def _decide_inputs():
    from lynceus import decision

    payload = {
        "truck_id": "T-1",
        "demo_case": "green",
        "manifest_text": "Declared weight: 18,400 kg. Moisture declared: 10% (dry).",
        "weight_kg": 18500,
        "moisture": 0.095,
    }
    vlm = {"detected": {"contamination": "none detected", "moisture": 0.10}, "confidence": 0.9}
    llm = {"reasoning": "ok", "confidence": 0.9, "crosscheck_failed": False}
    return decision, payload, vlm, llm


def test_tie_does_not_override_reject():
    decision, payload, vlm, llm = _decide_inputs()
    vlm["detected"]["hard_contaminants"] = ["metal"]
    engine = {"recommendation": {"tied": True, "actionable": True}}
    verdict, _, reasons = decision.decide(payload, vlm, llm, engine)
    assert verdict == audit.Decision.REJECT
    assert _TIE_REASON not in reasons


def test_tie_does_not_override_engine_refusal():
    decision, payload, vlm, llm = _decide_inputs()
    engine = {"recommendation": {"tied": True, "insufficient": True, "actionable": False}}
    verdict, _, _ = decision.decide(payload, vlm, llm, engine)
    assert verdict == audit.Decision.REFUSE_INSUFFICIENT_INPUT


def test_untied_clean_load_still_accepts():
    decision, payload, vlm, llm = _decide_inputs()
    engine = {"recommendation": {"tied": False, "actionable": True, "route": "rdf"}}
    verdict, _, _ = decision.decide(payload, vlm, llm, engine)
    assert verdict == audit.Decision.ACCEPT
