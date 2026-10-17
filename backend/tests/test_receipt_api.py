"""The decision receipt at the top level of every inspection route.

``POST /inspect``, the ``/inspect/stream`` result event and
``GET /inspections/{id}`` all carry ``receipt``: every decision rule in
priority order, fired or not, with its effect and evidence.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from test_intake import _jpeg, _waybill_payload

from lynceus import api, audit, decision, pipeline
from lynceus.api import create_app
from lynceus.config import LYNCEUS_STORAGE_DIR_ENV

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


def test_checks_failure_keeps_the_response(client, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("x")

    monkeypatch.setattr(api._optional_module("checks"), "build_checks", boom)
    body = client.post("/inspect", json=_waybill_payload(photo_base64=_jpeg(b"z"))).json()
    assert body["checks"] is None and body["why"] is None
    _assert_receipt(body)  # the live trace still answers
