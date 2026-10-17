"""Follow-up actions — GET/POST /inspections/{record_id}/actions.

Records are seeded through POST /inspect on the offline stub (no network).
The chain digests are recomputed here with hashlib from the stated rule
(sha256 over sorted-key, whitespace-free JSON of the entry without
``entry_sha256``), never through the module under test.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from lynceus import audit, auth, followup, pipeline
from lynceus.api import create_app
from lynceus.config import LYNCEUS_STORAGE_DIR_ENV, SUPPLIER_NOTIFY_WEBHOOK_ENV

_WEBHOOK = "https://hooks.example.test/lynceus"

_RED = {
    "truck_id": "F 7702 TS",
    "supplier": "UD Sinar Abadi",
    "demo_case": "red",
    "manifest_text": (
        "Waste type: clean RDF fluff, dry, no contamination\n"
        "Declared weight: 15,500 kg\nMoisture declared: 12%"
    ),
    "weight_kg": 19300,
    "waste_stream": "mixed-msw",
    "moisture": 0.14,
    "age_h": 8,
}
_GREEN = {
    "truck_id": "B 9174 KT",
    "demo_case": "green",
    "manifest_text": "Waste type: SRF / RDF fluff\nDeclared weight: 18,400 kg",
    "weight_kg": 18500,
    "waste_stream": "rdf-feedstock",
    "moisture": 0.095,
    "age_h": 5,
}


def _clear_auth(monkeypatch) -> None:
    for name in (
        auth.LYNCEUS_ADMIN_USERNAME_ENV,
        auth.LYNCEUS_ADMIN_PASSWORD_ENV,
        auth.LYNCEUS_ADMIN_PASSWORD_SHA256_ENV,
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture()
def storage(tmp_path) -> Path:
    return tmp_path


@pytest.fixture()
def client(storage, monkeypatch):
    """Open app on the offline stub, no supplier webhook configured."""
    _clear_auth(monkeypatch)
    monkeypatch.setenv(LYNCEUS_STORAGE_DIR_ENV, str(storage))
    monkeypatch.delenv(SUPPLIER_NOTIFY_WEBHOOK_ENV, raising=False)
    monkeypatch.setattr(pipeline, "_vlm_reachable", lambda *a, **k: False)
    auth.reset_signer()
    yield TestClient(create_app())
    auth.reset_signer()


def _seed(client, payload: dict) -> str:
    resp = client.post("/inspect", json=payload)
    assert resp.status_code == 200, resp.text
    return resp.json()["record_id"]


def _post(client, record_id: str, kind: str, note=None):
    return client.post(f"/inspections/{record_id}/actions", json={"kind": kind, "note": note})


def _digest(entry: dict) -> str:
    body = {k: v for k, v in entry.items() if k != "entry_sha256"}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _log(storage: Path, record_id: str) -> Path:
    return storage / record_id / followup.ACTIONS_FILENAME


# ---------------------------------------------------------------------------
# Chain
# ---------------------------------------------------------------------------


def test_no_log_yet_is_an_empty_intact_chain(client):
    record_id = _seed(client, _RED)
    resp = client.get(f"/inspections/{record_id}/actions")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"actions": [], "chain_ok": True}


def test_append_builds_a_verifiable_chain(client, storage):
    record_id = _seed(client, _RED)
    first = _post(client, record_id, "escalate", "  supervisor to check  ")
    assert first.status_code == 201, first.text
    second = _post(client, record_id, "notify_supplier")
    assert second.status_code == 201, second.text

    a1, a2 = first.json()["action"], second.json()["action"]
    assert a1["action_id"] == "act-0001" and a2["action_id"] == "act-0002"
    assert a1["record_id"] == a2["record_id"] == record_id
    assert a1["kind"] == "escalate" and a2["kind"] == "notify_supplier"
    assert a1["note"] == "supervisor to check"  # stripped
    assert a2["note"] is None
    assert a1["actor"] is None  # auth off: no user
    assert audit.TIMESTAMP_RE.match(a1["created_at_utc"])
    assert a1["notice"] is None and a1["delivery"] is None
    # Chain: genesis is the empty-bytes digest, then each links to the last.
    assert a1["prev_sha256"] == "sha256:" + hashlib.sha256(b"").hexdigest()
    assert a2["prev_sha256"] == a1["entry_sha256"]
    assert a1["entry_sha256"] == _digest(a1)
    assert a2["entry_sha256"] == _digest(a2)

    # One JSON object per line on disk, exactly what the API returned.
    lines = _log(storage, record_id).read_text(encoding="utf-8").splitlines()
    assert [json.loads(line) for line in lines] == [a1, a2]

    listed = client.get(f"/inspections/{record_id}/actions").json()
    assert listed == {"actions": [a1, a2], "chain_ok": True}


def test_edited_line_breaks_the_chain(client, storage):
    record_id = _seed(client, _RED)
    _post(client, record_id, "escalate", "first")
    _post(client, record_id, "escalate", "second")
    path = _log(storage, record_id)
    lines = path.read_text(encoding="utf-8").splitlines()
    edited = json.loads(lines[0])
    edited["note"] = "rewritten later"
    lines[0] = json.dumps(edited)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    body = client.get(f"/inspections/{record_id}/actions").json()
    assert body["chain_ok"] is False
    assert [a["note"] for a in body["actions"]] == ["rewritten later", "second"]


def test_removed_line_breaks_the_chain(client, storage):
    record_id = _seed(client, _RED)
    for note in ("one", "two", "three"):
        _post(client, record_id, "escalate", note)
    path = _log(storage, record_id)
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text("\n".join([lines[0], lines[2]]) + "\n", encoding="utf-8")
    assert client.get(f"/inspections/{record_id}/actions").json()["chain_ok"] is False


def test_unparseable_line_breaks_the_chain_but_keeps_the_rest(client, storage):
    record_id = _seed(client, _RED)
    _post(client, record_id, "escalate", "kept")
    with _log(storage, record_id).open("a", encoding="utf-8") as handle:
        handle.write("{not json\n")
    body = client.get(f"/inspections/{record_id}/actions").json()
    assert body["chain_ok"] is False
    assert [a["note"] for a in body["actions"]] == ["kept"]


def test_sealed_record_bytes_never_change(client, storage):
    record_id = _seed(client, _RED)
    record_path = storage / record_id / audit.RECORD_FILENAME
    before = record_path.read_bytes()
    _post(client, record_id, "notify_supplier", "pls fix")
    _post(client, record_id, "escalate")
    assert record_path.read_bytes() == before
    audit.load_record(record_path)  # still strict-loads (digest intact)


# ---------------------------------------------------------------------------
# Supplier notice + delivery
# ---------------------------------------------------------------------------


def test_reject_notice_is_built_from_the_sealed_record(client):
    record_id = _seed(client, _RED)
    record = client.get(f"/inspections/{record_id}").json()
    action = _post(client, record_id, "notify_supplier", "Third metal load this week").json()[
        "action"
    ]
    notice = action["notice"]
    assert notice["to"] == "UD Sinar Abadi"
    assert notice["subject"] == f"Load rejected at gate — F 7702 TS ({record_id})"
    body = notice["body"]
    assert "F 7702 TS" in body
    assert "UD Sinar Abadi" in body
    assert "rejected at the gate" in body
    assert record["verdict"]["decided_at_utc"] in body
    assert "metal" in body  # the stub's hard contaminant
    for step in record["engine_outputs"]["recommendation"]["actions"]:
        assert step["text"] in body and step["sop_ref"] in body
    assert record_id in body
    assert record["digest"]["record_sha256"][: len("sha256:") + 12] in body
    assert "Operator note: Third metal load this week" in body
    assert "corrective action" in body and "next delivery" in body
    assert action["delivery"] == "logged"
    assert action["delivery_error"] is None


def test_notice_without_supplier_names_supplier_on_file(client):
    record_id = _seed(client, _GREEN)
    notice = _post(client, record_id, "notify_supplier").json()["action"]["notice"]
    assert notice["to"] == "Supplier on file"
    assert notice["subject"] == f"Load accepted at gate — B 9174 KT ({record_id})"
    assert "corrective action" not in notice["body"]


def test_webhook_success_delivers_the_notice(client, monkeypatch):
    monkeypatch.setenv(SUPPLIER_NOTIFY_WEBHOOK_ENV, _WEBHOOK)
    sent = []

    def fake_post(url, json=None, timeout=None, **kwargs):
        sent.append({"url": url, "json": json, "timeout": timeout})
        return httpx.Response(202)

    monkeypatch.setattr(followup.httpx, "post", fake_post)
    record_id = _seed(client, _RED)
    action = _post(client, record_id, "notify_supplier").json()["action"]
    assert action["delivery"] == "webhook"
    assert action["delivery_error"] is None
    assert len(sent) == 1
    assert sent[0]["url"] == _WEBHOOK
    assert sent[0]["timeout"] == 5.0
    assert sent[0]["json"]["record_id"] == record_id
    assert sent[0]["json"]["subject"] == action["notice"]["subject"]
    assert sent[0]["json"]["body"] == action["notice"]["body"]


@pytest.mark.parametrize(
    ("outcome", "error_part"),
    [
        (httpx.ConnectError("connection refused"), "ConnectError"),
        (httpx.ReadTimeout("slow"), "ReadTimeout"),
        (httpx.Response(500), "HTTP 500"),
    ],
)
def test_webhook_failure_is_logged_with_its_error(client, monkeypatch, outcome, error_part):
    monkeypatch.setenv(SUPPLIER_NOTIFY_WEBHOOK_ENV, _WEBHOOK)

    def fake_post(url, json=None, timeout=None, **kwargs):
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    monkeypatch.setattr(followup.httpx, "post", fake_post)
    record_id = _seed(client, _RED)
    resp = _post(client, record_id, "notify_supplier")
    assert resp.status_code == 201, resp.text
    action = resp.json()["action"]
    assert action["delivery"] == "logged"
    assert error_part in action["delivery_error"]
    assert action["entry_sha256"] == _digest(action)


def test_non_https_webhook_is_never_called(client, monkeypatch):
    monkeypatch.setenv(SUPPLIER_NOTIFY_WEBHOOK_ENV, "http://plain.example.test/hook")
    monkeypatch.setattr(
        followup.httpx, "post", lambda *a, **k: pytest.fail("must not POST over http")
    )
    record_id = _seed(client, _RED)
    action = _post(client, record_id, "notify_supplier").json()["action"]
    assert action["delivery"] == "logged"
    assert "https" in action["delivery_error"]


def test_escalate_never_notifies(client, monkeypatch):
    monkeypatch.setenv(SUPPLIER_NOTIFY_WEBHOOK_ENV, _WEBHOOK)
    monkeypatch.setattr(
        followup.httpx, "post", lambda *a, **k: pytest.fail("escalate must not POST")
    )
    record_id = _seed(client, _GREEN)  # any verdict may be escalated
    action = _post(client, record_id, "escalate").json()["action"]
    assert action["notice"] is None
    assert action["delivery"] is None


# ---------------------------------------------------------------------------
# Validation, auth, ledger
# ---------------------------------------------------------------------------


def test_unknown_record_is_404(client):
    assert client.get("/inspections/inspection-999999/actions").status_code == 404
    resp = _post(client, "inspection-999999", "escalate")
    assert resp.status_code == 404
    assert resp.json()["detail"]["error"] == "record_not_found"


def test_bad_record_id_is_422(client):
    assert client.get("/inspections/not-a-record/actions").status_code == 422
    resp = _post(client, "not-a-record", "escalate")
    assert resp.status_code == 422
    assert resp.json()["detail"]["error"] == "invalid_record_id"


def test_bad_kind_and_long_note_are_422(client, storage):
    record_id = _seed(client, _RED)
    assert _post(client, record_id, "delete_record").status_code == 422
    assert _post(client, record_id, "escalate", "x" * 501).status_code == 422
    # The cap is on the stripped note.
    ok = _post(client, record_id, "escalate", "  " + "x" * 500 + "  ")
    assert ok.status_code == 201
    blank = _post(client, record_id, "escalate", "   ").json()["action"]
    assert blank["note"] is None
    assert len(client.get(f"/inspections/{record_id}/actions").json()["actions"]) == 2


def test_auth_on_without_session_is_401(storage, monkeypatch):
    # Seed with auth off, then switch it on.
    _clear_auth(monkeypatch)
    monkeypatch.setenv(LYNCEUS_STORAGE_DIR_ENV, str(storage))
    monkeypatch.setattr(pipeline, "_vlm_reachable", lambda *a, **k: False)
    record_id = _seed(TestClient(create_app()), _RED)

    monkeypatch.setenv(auth.LYNCEUS_ADMIN_USERNAME_ENV, "operator")
    monkeypatch.setenv(auth.LYNCEUS_ADMIN_PASSWORD_ENV, "pw")
    auth.reset_signer()
    try:
        guarded = TestClient(create_app())
        for resp in (
            guarded.get(f"/inspections/{record_id}/actions"),
            _post(guarded, record_id, "escalate"),
        ):
            assert resp.status_code == 401
            assert resp.json()["detail"]["error"] == "authentication_required"
        assert not _log(storage, record_id).exists()

        # Signed in: the actor is the session user.
        guarded.post("/auth/login", json={"username": "operator", "password": "pw"})
        action = _post(guarded, record_id, "escalate").json()["action"]
        assert action["actor"] == "operator"
    finally:
        auth.reset_signer()


def test_ledger_rows_count_followups(client):
    rejected = _seed(client, _RED)
    accepted = _seed(client, _GREEN)
    _post(client, rejected, "notify_supplier")
    _post(client, rejected, "escalate")
    _post(client, rejected, "escalate")
    rows = {row["record_id"]: row for row in client.get("/inspections").json()["inspections"]}
    assert rows[rejected]["followups"] == {"notify_supplier": 1, "escalate": 2}
    assert rows[accepted]["followups"] == {"notify_supplier": 0, "escalate": 0}
