"""The decision receipt at the top level of every inspection route.

``POST /inspect``, the ``/inspect/stream`` result event and
``GET /inspections/{id}`` all carry ``receipt``: every decision rule in
priority order, fired or not, with its effect and evidence.
"""

from __future__ import annotations

import json
import threading

import pytest
from fastapi.testclient import TestClient
from test_early_majority import _LLM_JSON, CONFIRMED_FIELDS, PHOTO, _Script
from test_intake import _jpeg, _waybill_payload

from lynceus import api, audit, decision, pipeline
from lynceus.api import create_app
from lynceus.config import LYNCEUS_STORAGE_DIR_ENV
from lynceus.pipeline import VLLMClient

RULE_IDS = [rule_id for rule_id, _, _ in decision.RULES]
EFFECT = {
    audit.Decision.REJECT: "reject",
    audit.Decision.ESCALATE_HUMAN: "hold",
    audit.Decision.ACCEPT: "accept",
    audit.Decision.REFUSE_INSUFFICIENT_INPUT: "refuse",
}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv(LYNCEUS_STORAGE_DIR_ENV, str(tmp_path))
    monkeypatch.setattr(pipeline, "_vlm_reachable", lambda *a, **k: False)
    monkeypatch.setattr(pipeline, "safe_detect", lambda *a, **k: None)
    return TestClient(create_app())


def _assert_receipt(body):
    rows = body["receipt"]
    assert isinstance(rows, list) and rows
    assert [row["id"] for row in rows[: len(RULE_IDS)]] == RULE_IDS
    for row in rows:
        assert set(row) == {"id", "rule", "fired", "evidence", "effect"}
        assert row["effect"] == "none" or row["fired"]
    # The verdict the response states is one a fired rule gives.
    fired = {row["effect"] for row in rows if row["fired"]}
    assert EFFECT[body["verdict"]["decision"]] in fired, rows


def test_inspect_returns_the_live_rule_trace(client):
    body = client.post("/inspect", json=_waybill_payload()).json()
    _assert_receipt(body)
    assert [row["id"] for row in body["receipt"]] == RULE_IDS  # exact, not replayed


def test_inspect_receipt_on_a_refusal(client):
    body = client.post("/inspect", json={"weight_kg": 5000, "manifest_text": "SJ"}).json()
    assert body["verdict"]["decision"] == audit.Decision.REFUSE_INSUFFICIENT_INPUT
    _assert_receipt(body)
    assert body["receipt"][0]["fired"] and body["receipt"][0]["effect"] == "refuse"


def test_stream_result_carries_the_receipt(client):
    resp = client.post("/inspect/stream", json=_waybill_payload())
    events = [json.loads(line) for line in resp.text.splitlines() if line.strip()]
    assert events[-1]["event"] == "result"
    result = events[-1]["data"]
    _assert_receipt(result)
    direct = client.post("/inspect", json=_waybill_payload()).json()
    assert result["receipt"] == direct["receipt"]


def test_get_inspection_carries_the_receipt(client):
    created = client.post("/inspect", json=_waybill_payload()).json()
    body = client.get(f"/inspections/{created['record_id']}").json()
    _assert_receipt(body)
    # Replayed from the sealed outputs: the same rules fire as at the gate.
    fired = [row["id"] for row in body["receipt"] if row["fired"]]
    assert fired == [row["id"] for row in created["receipt"] if row["fired"]]


@pytest.fixture()
def live_client(tmp_path, monkeypatch):
    """The real vision client with scripted model calls, no detector."""
    monkeypatch.setenv(LYNCEUS_STORAGE_DIR_ENV, str(tmp_path))
    monkeypatch.setattr(pipeline, "safe_detect", lambda *a, **k: None)
    monkeypatch.setattr(
        pipeline, "resolve_clients", lambda payload, settings=None: VLLMClient(settings)
    )
    monkeypatch.setenv("VLM_VOTES", "3")
    monkeypatch.delenv("VLM_FALLBACK_MODELS", raising=False)
    return TestClient(create_app())


def _inspect(client, *routes):
    created = client.post(
        "/inspect", json={"photo_base64": PHOTO, "waybill_fields": CONFIRMED_FIELDS,
                          "weight_kg": 16340},
    ).json()
    return created, client.get(f"/inspections/{created['record_id']}").json()


def _fired(body):
    return [row["id"] for row in body["receipt"] if row["fired"]]


def test_api_holds_a_hard_item_listed_below_the_bar(live_client, monkeypatch):
    low_metal = json.dumps({"contamination": "x", "moisture": 0.1, "hard_contaminants": ["metal"],
                            "light_contaminants": [], "confidence": 0.5, "locations": []})

    def chat_once(client, base_url, model, messages, max_tokens=512):
        return low_metal if "image_url" in json.dumps(messages) else _LLM_JSON

    monkeypatch.setattr(VLLMClient, "_chat_once", chat_once)
    created, fetched = _inspect(live_client)
    assert created["verdict"]["decision"] == audit.Decision.ESCALATE_HUMAN
    assert any("below the confidence bar" in r for r in created["reasons"])
    for body in (created, fetched):
        _assert_receipt(body)
        assert "hard_below_bar" in _fired(body) and "accept" not in _fired(body)


@pytest.fixture()
def held():
    """Holds the third vision read past the grace window; released after."""
    gate = threading.Event()
    yield gate
    gate.set()


def test_api_holds_a_clean_early_majority_without_the_detector(live_client, monkeypatch, held):
    monkeypatch.setenv("VLM_VOTE_GRACE_S", "0.2")
    _Script([{"hard": []}, {"hard": []}, {"hard": [], "gate": held}]).install(monkeypatch)
    created, fetched = _inspect(live_client)
    assert created["ai_outputs"]["vlm"]["third_read"] == "late"
    assert created["verdict"]["decision"] == audit.Decision.ESCALATE_HUMAN
    assert created["reasons"][0].startswith("Vision decided on 2 of 3 reads")
    for body in (created, fetched):
        _assert_receipt(body)
        assert "early_majority" in _fired(body)


def test_api_says_the_plate_camera_is_simulated(client):
    # The demo ANPR echoes the typed truck id; this one is not the waybill's.
    created = client.post("/inspect", json=_waybill_payload(truck_id="B 9406 KXW")).json()
    fetched = client.get(f"/inspections/{created['record_id']}").json()
    assert created["verdict"]["decision"] == audit.Decision.ESCALATE_HUMAN
    assert created["reasons"][0].startswith(
        "Plate mismatch: the simulated plate camera reads B 9406 KXW")
    for body in (created, fetched):
        weight = next(c for c in body["checks"] if c["key"] == "weight")
        assert weight["finding"] == "Simulated plate ≠ waybill"
        plate = next(r for r in body["receipt"] if r["id"] == "plate_mismatch")
        assert plate["fired"] and "simulated plate camera" in plate["evidence"]


def test_checks_failure_keeps_the_response(client, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("x")

    monkeypatch.setattr(api._optional_module("checks"), "build_checks", boom)
    body = client.post("/inspect", json=_waybill_payload(photo_base64=_jpeg(b"z"))).json()
    assert body["checks"] is None and body["why"] is None
    _assert_receipt(body)  # the live trace still answers
