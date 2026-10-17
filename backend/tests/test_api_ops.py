"""Ops-loop API (``lynceus.api_ops`` routes mounted by ``create_app``)."""

from __future__ import annotations

import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient

from lynceus import audit, auth, followups, pipeline, suppliers
from lynceus.api import create_app
from lynceus.config import LYNCEUS_STORAGE_DIR_ENV
from _ops_records import write_record

_USER, _PASSWORD = "supervisor1", "s3cret-pass"


def _env(monkeypatch, tmp_path, *, auth_on: bool):
    for name in (auth.LYNCEUS_ADMIN_USERNAME_ENV, auth.LYNCEUS_ADMIN_PASSWORD_ENV,
                 auth.LYNCEUS_ADMIN_PASSWORD_SHA256_ENV):
        monkeypatch.delenv(name, raising=False)
    if auth_on:
        monkeypatch.setenv(auth.LYNCEUS_ADMIN_USERNAME_ENV, _USER)
        monkeypatch.setenv(auth.LYNCEUS_ADMIN_PASSWORD_ENV, _PASSWORD)
    monkeypatch.setenv(LYNCEUS_STORAGE_DIR_ENV, str(tmp_path))
    # Never probe a live endpoint from a test.
    monkeypatch.setattr(pipeline, "resolve_assist_client", lambda *a, **k: None)
    suppliers.clear_cache()
    auth.reset_signer()


@pytest.fixture
def api(tmp_path, monkeypatch):
    _env(monkeypatch, tmp_path, auth_on=False)
    yield TestClient(create_app()), tmp_path
    auth.reset_signer()


@pytest.fixture
def records(api):
    client, storage = api
    ids = {
        "reject": write_record(storage, 1, decision="reject", hard=["metal"], conflict=True,
                               supplier="PT. Hijau Lestari Transport", weight_kg=16340),
        "accept": write_record(storage, 2, supplier="CV Sumber Bersih"),
        "held": write_record(storage, 3, decision="escalate_human", supplier="CV Sumber Bersih"),
        "running": write_record(storage, 4, status="in_progress", decision="escalate_human"),
    }
    return client, storage, ids


# ---------------------------------------------------------------------------
# Follow-ups
# ---------------------------------------------------------------------------


def test_get_followups_empty_then_listed(records):
    client, _, ids = records
    response = client.get(f"/inspections/{ids['reject']}/followups")
    assert response.status_code == 200
    assert response.json() == {"record_id": ids["reject"], "followups": [],
                               "chain": {"ok": True, "problems": []}}

    sealed = client.post(f"/inspections/{ids['reject']}/resolution",
                         json={"decision": "reject", "note": "Confirmed refusal"}).json()
    listed = client.get(f"/inspections/{ids['reject']}/followups").json()
    assert listed["followups"] == [sealed]
    assert listed["chain"] == {"ok": True, "problems": []}


def test_get_followups_on_in_progress_record_is_empty(records):
    client, _, ids = records
    assert client.get(f"/inspections/{ids['running']}/followups").json()["followups"] == []


def test_post_resolution_seals_with_demo_actor(records):
    client, _, ids = records
    response = client.post(f"/inspections/{ids['held']}/resolution",
                           json={"decision": "sort_then_accept", "hand_check_minutes": 4.5})
    assert response.status_code == 200
    sealed = response.json()
    assert sealed["kind"] == "resolution"
    assert sealed["actor"] == "demo"
    assert sealed["seq"] == 1
    assert sealed["body"] == {"decision": "sort_then_accept", "note": "",
                              "ai_decision": "escalate_human", "agrees_with_ai": None,
                              "hand_check_minutes": 4.5}


@pytest.mark.parametrize("body", [
    {"decision": "approve"},
    {"decision": "accept", "note": "x" * 501},
    {"decision": "accept", "hand_check_minutes": -1},
    {"decision": "accept", "extra": 1},
    {},
])
def test_post_resolution_bad_body_is_422(records, body):
    client, _, ids = records
    assert client.post(f"/inspections/{ids['accept']}/resolution", json=body).status_code == 422


def test_record_errors_404_409_422(records):
    client, _, ids = records
    body = {"decision": "accept"}
    assert client.post("/inspections/inspection-000099/resolution", json=body).status_code == 404
    assert client.post(f"/inspections/{ids['running']}/resolution", json=body).status_code == 409
    assert client.post("/inspections/not-an-id/resolution", json=body).status_code == 422
    assert client.get("/inspections/inspection-000099/followups").status_code == 404
    assert client.get("/inspections/bad-id/followups").status_code == 422
    lab = {"moisture_pct": 18, "ncv_mj_kg": 14, "chlorine_pct": 0.5}
    assert client.post(f"/inspections/{ids['running']}/lab", json=lab).status_code == 409
    assert client.post("/inspections/inspection-000099/lab", json=lab).status_code == 404
    assert client.post(f"/inspections/{ids['running']}/notice", json={}).status_code == 409
    assert client.post("/inspections/inspection-000099/notice", json={}).status_code == 404
    assert client.post("/inspections/x/notice", json={}).status_code == 422


def test_broken_chain_is_409(records):
    client, storage, ids = records
    client.post(f"/inspections/{ids['accept']}/resolution", json={"decision": "accept"})
    path = storage / ids["accept"] / "followups" / "001-resolution.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["body"]["note"] = "edited"
    path.write_text(json.dumps(data), encoding="utf-8")

    chain = client.get(f"/inspections/{ids['accept']}/followups").json()["chain"]
    assert chain["ok"] is False and chain["problems"]
    response = client.post(f"/inspections/{ids['accept']}/resolution", json={"decision": "reject"})
    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "chain_broken"


# ---------------------------------------------------------------------------
# Lab
# ---------------------------------------------------------------------------


def test_post_lab_returns_contract_eval(records):
    client, _, ids = records
    response = client.post(f"/inspections/{ids['reject']}/lab", json={
        "moisture_pct": 25, "ncv_mj_kg": 14, "chlorine_pct": 0.5, "ash_pct": 12.5,
        "sample_id": "LAB-1", "lab": "Sucofindo"})
    assert response.status_code == 200
    body = response.json()["body"]
    assert body["sample_id"] == "LAB-1" and body["lab"] == "Sucofindo" and body["ash_pct"] == 12.5
    effect = body["contract_eval"]
    assert effect["adjusted_price_idr_per_t"] == 324_000
    assert effect["net_t"] == 16.34
    assert effect["deduction_idr"] == 588_240
    assert [b["param"] for b in effect["breaches"]] == ["moisture_pct"]
    # 16.34 t x 324,000 = 5,294,160: tier C settles at the adjusted price.
    assert (effect["tier"], effect["settlement_idr"], effect["premium_idr"]) == (
        "C", 5_294_160, 0)


@pytest.mark.parametrize("override", [
    {"moisture_pct": 101}, {"moisture_pct": -1}, {"ncv_mj_kg": 41}, {"chlorine_pct": 11},
    {"ash_pct": 120}, {"sample_id": "x" * 65}, {"moisture_pct": "wet"}, {"unknown": 1},
])
def test_post_lab_bad_body_is_422(records, override):
    client, _, ids = records
    body = {"moisture_pct": 18, "ncv_mj_kg": 14, "chlorine_pct": 0.5, **override}
    assert client.post(f"/inspections/{ids['accept']}/lab", json=body).status_code == 422


def test_post_lab_missing_field_is_422(records):
    client, _, ids = records
    response = client.post(f"/inspections/{ids['accept']}/lab",
                           json={"moisture_pct": 18, "ncv_mj_kg": 14})
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Notice
# ---------------------------------------------------------------------------


def test_post_notice_template_when_assist_offline(records):
    client, _, ids = records
    response = client.post(f"/inspections/{ids['reject']}/notice", json={})
    assert response.status_code == 200
    sealed = response.json()
    assert sealed["kind"] == "notice"
    assert sealed["body"]["provenance"] == "template"
    assert sealed["body"]["to"] == "PT. Hijau Lestari Transport"


def test_post_notice_live_when_model_text_is_grounded(records, monkeypatch):
    client, _, ids = records
    record_id = ids["reject"]

    class Live:
        def assist(self, messages, max_tokens=700):
            return {"subject": f"Load refused: {record_id}",
                    "text": f"Record {record_id}: the camera saw metal. A breach fee of "
                            "Rp 1,500,000 applies."}, 900.0

    monkeypatch.setattr(pipeline, "resolve_assist_client", lambda *a, **k: Live())
    body = client.post(f"/inspections/{record_id}/notice").json()["body"]
    assert body["provenance"] == "live"
    assert body["latency_ms"] == 900.0


def test_post_notice_rejects_a_body_with_fields(records):
    client, _, ids = records
    assert client.post(f"/inspections/{ids['reject']}/notice",
                       json={"text": "my own"}).status_code == 422


# ---------------------------------------------------------------------------
# Suppliers and contract
# ---------------------------------------------------------------------------


def test_get_suppliers(records):
    client, _, ids = records
    client.post(f"/inspections/{ids['reject']}/resolution", json={"decision": "reject"})
    data = client.get("/suppliers").json()
    assert set(data) == {"generated_at_utc", "contract", "suppliers"}
    assert data["contract"]["base_price_idr_per_t"] == 360_000
    assert data["contract"]["tier_rules"]
    by_name = {p["supplier"]: p for p in data["suppliers"]}
    # The in-progress record has no supplier and is not counted.
    assert set(by_name) == {"PT. Hijau Lestari Transport", "CV Sumber Bersih"}
    hijau = by_name["PT. Hijau Lestari Transport"]
    assert (hijau["trucks"], hijau["rejected"], hijau["reviews"]) == (1, 1, 1)
    assert hijau["breach_fees_idr"] == 1_500_000
    assert hijau["tier"] == "new"


def test_get_contract_states_terms_and_tier_rules(api):
    client, _ = api
    contract = client.get("/contract").json()
    assert contract["note"] == "Example supply contract: terms are set per contract (SOP-RDF-5.3)."
    assert contract["specs"]["chlorine_pct_max"] == 1.0
    assert [r["tier"] for r in contract["tier_rules"]] == ["new", "high", "medium", "low"]
    assert "risk score" in contract["risk_formula"]


# ---------------------------------------------------------------------------
# Follow-up summary, evidence pack, kiln intake, carbon
# ---------------------------------------------------------------------------


def test_followups_summary_lists_only_records_with_followups(records):
    client, _, ids = records
    assert client.get("/followups/summary").json() == {"records": {}}
    client.post(f"/inspections/{ids['reject']}/resolution", json={"decision": "reject"})
    client.post(f"/inspections/{ids['reject']}/lab",
                json={"moisture_pct": 18, "ncv_mj_kg": 14, "chlorine_pct": 0.5})
    client.post(f"/inspections/{ids['held']}/resolution", json={"decision": "sort_then_accept"})
    client.post(f"/inspections/{ids['held']}/resolution", json={"decision": "accept"})
    assert client.get("/followups/summary").json() == {"records": {
        ids["reject"]: {"kinds": ["resolution", "lab_result"], "count": 2, "chain_ok": True,
                        "latest_resolution": "reject"},
        ids["held"]: {"kinds": ["resolution"], "count": 2, "chain_ok": True,
                      "latest_resolution": "accept"},
    }}


def _with_photo(storage, record_id, data=b"\xff\xd8 jpeg bytes"):
    """Give a record a stored photo.jpg and re-stamp its digest."""
    path = storage / record_id / audit.RECORD_FILENAME
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["inputs"]["photo"].update(path="photo.jpg", sha256=audit.sha256_field(data))
    raw["digest"]["input_digests"] = {"photo": audit.sha256_field(data)}
    audit._stamp_record_digest(raw)
    path.write_text(json.dumps(raw, indent=2), encoding="utf-8")
    (storage / record_id / "photo.jpg").write_bytes(data)


def test_evidence_pack_json(records):
    client, storage, ids = records
    record_id = ids["reject"]
    _with_photo(storage, record_id)
    client.post(f"/inspections/{record_id}/resolution", json={"decision": "reject"})
    client.post(f"/inspections/{record_id}/lab",
                json={"moisture_pct": 18, "ncv_mj_kg": 14, "chlorine_pct": 0.5,
                      "hg_mg_mj": 0.03})
    response = client.get(f"/inspections/{record_id}/evidence-pack")
    assert response.status_code == 200
    pack = response.json()
    assert (pack["kind"], pack["format"], pack["record_id"]) == (
        "lynceus_evidence_pack", 1, record_id)
    assert pack["record"]["record_id"] == record_id
    assert pack["record_digest"] == pack["record"]["digest"]["record_sha256"]
    assert pack["input_digests"] == {"photo": pack["record"]["inputs"]["photo"]["sha256"]}
    assert [f["kind"] for f in pack["followups"]] == ["resolution", "lab_result"]
    assert pack["followups"][1]["body"]["contract_eval"]["iso21640"]["code"] == "NCV 4; Cl 2; Hg 2"
    assert pack["chain"] == {"ok": True, "problems": []}
    rule = pack["rule_fired"]
    assert rule["decision"] == "reject"
    assert rule["failed_gates"] == {
        "manifest_crosscheck": "Waybill declares sorted RDF fluff; the camera sees metal"}
    assert rule["gate_states"]["manifest_crosscheck"] == "failed"
    by_path = {f["path"]: f for f in pack["files"]}
    assert set(by_path) == {audit.RECORD_FILENAME, "photo.jpg",
                            "followups/001-resolution.json", "followups/002-lab_result.json"}
    photo = by_path["photo.jpg"]
    assert (photo["role"], photo["missing"], photo["matches_record"]) == ("photo", False, True)
    record_bytes = (storage / record_id / audit.RECORD_FILENAME).read_bytes()
    assert by_path[audit.RECORD_FILENAME]["sha256"] == audit.sha256_field(record_bytes)
    # The pack hash covers everything but itself.
    body = {k: v for k, v in pack.items() if k != "pack_sha256"}
    assert pack["pack_sha256"] == audit.sha256_field(audit._canonical_bytes(body))


def test_evidence_pack_flags_a_changed_photo(records):
    client, storage, ids = records
    _with_photo(storage, ids["accept"])
    (storage / ids["accept"] / "photo.jpg").write_bytes(b"swapped")
    files = client.get(f"/inspections/{ids['accept']}/evidence-pack").json()["files"]
    photo = next(f for f in files if f["role"] == "photo")
    assert photo["matches_record"] is False


def test_evidence_pack_zip_carries_the_files(records):
    client, storage, ids = records
    record_id = ids["reject"]
    _with_photo(storage, record_id)
    client.post(f"/inspections/{record_id}/resolution", json={"decision": "reject"})
    response = client.get(f"/inspections/{record_id}/evidence-pack?format=zip")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert f'{record_id}-evidence.zip' in response.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        names = set(archive.namelist())
        assert names == {"evidence-pack.json", audit.RECORD_FILENAME, "photo.jpg",
                         "followups/001-resolution.json"}
        pack = json.loads(archive.read("evidence-pack.json"))
        for entry in pack["files"]:
            assert audit.sha256_field(archive.read(entry["path"])) == entry["sha256"]


def test_evidence_pack_errors(records):
    client, _, ids = records
    assert client.get("/inspections/inspection-999999/evidence-pack").status_code == 404
    assert client.get("/inspections/not-an-id/evidence-pack").status_code == 422
    assert client.get(f"/inspections/{ids['accept']}/evidence-pack?format=pdf").status_code == 422


def test_kiln_intake_and_carbon_routes(records):
    client, _, ids = records
    client.post(f"/inspections/{ids['held']}/resolution", json={"decision": "accept"})
    intake = client.get("/kiln/intake?window=all").json()
    # The plain ACCEPT and the hold the supervisor accepted; the reject is out.
    assert intake["trucks_accepted"] == 2
    assert intake["methods"] == {"lab": 0, "supplier_average": 0, "contract_spec": 2}
    assert intake["energy_gj"] == 2 * 10 * 12.6
    assert client.get("/kiln/intake").json()["window"]["name"] == "shift"
    carbon = client.get("/carbon?window=all").json()
    assert carbon["af_energy_gj"] == intake["energy_gj"]
    assert carbon["net_co2_avoided_t"] > 0
    for path in ("/kiln/intake?window=week", "/carbon?window=week"):
        response = client.get(path)
        assert response.status_code == 422
        assert response.json()["detail"]["error"] == "invalid_window"


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


def test_every_route_requires_auth_and_records_the_session_user(tmp_path, monkeypatch):
    _env(monkeypatch, tmp_path, auth_on=True)
    record_id = write_record(tmp_path, 1, decision="reject", hard=["metal"])
    client = TestClient(create_app())
    lab = {"moisture_pct": 18, "ncv_mj_kg": 14, "chlorine_pct": 0.5}
    calls = [
        ("get", f"/inspections/{record_id}/followups", None),
        ("post", f"/inspections/{record_id}/resolution", {"decision": "reject"}),
        ("post", f"/inspections/{record_id}/lab", lab),
        ("post", f"/inspections/{record_id}/notice", {}),
        ("get", "/suppliers", None),
        ("get", "/contract", None),
        ("get", "/followups/summary", None),
        ("get", f"/inspections/{record_id}/evidence-pack", None),
        ("get", f"/inspections/{record_id}/evidence-pack?format=zip", None),
        ("get", "/kiln/intake", None),
        ("get", "/carbon", None),
    ]
    for method, path, body in calls:
        response = getattr(client, method)(path, **({"json": body} if body is not None else {}))
        assert response.status_code == 401, path

    login = client.post("/auth/login", json={"username": _USER, "password": _PASSWORD})
    assert login.status_code == 200
    for method, path, body in calls:
        response = getattr(client, method)(path, **({"json": body} if body is not None else {}))
        assert response.status_code == 200, (path, response.text)
    chain, problems = followups.read_chain(tmp_path, record_id)
    assert problems == []
    assert {item["actor"] for item in chain} == {_USER}
    auth.reset_signer()
