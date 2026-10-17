"""Control room: alarm feed and dashboard summary (``lynceus.control``)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from lynceus import auth, control, followups, fuel, pipeline, suppliers
from lynceus.api import create_app
from lynceus.config import LYNCEUS_STORAGE_DIR_ENV
from _ops_records import write_record

NOW = "2026-10-14T02:00:00Z"


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    monkeypatch.delenv(fuel.CHLORINE_BUDGET_ENV, raising=False)
    suppliers.clear_cache()
    yield
    suppliers.clear_cache()


@pytest.fixture
def ledger(tmp_path):
    s = tmp_path
    ids = {
        # Two days old: too old for the 24 h kinds, but an open hold stays open.
        "old_reject": write_record(s, 1, decision="reject", hard=["metal"],
                                   started="2026-10-12T01:00:00Z"),
        "old_hold": write_record(s, 2, decision="escalate_human", supplier="CV Lama",
                                 started="2026-10-12T02:00:00Z"),
        "hold": write_record(s, 3, decision="escalate_human", supplier="CV Tunggu"),
        "hold_done": write_record(s, 4, decision="escalate_human"),
        "reject": write_record(s, 5, decision="reject", hard=["metal"], conflict=True,
                               supplier="PT Logam"),
        "reject_done": write_record(s, 6, decision="reject", hard=["metal"]),
        "wet": [write_record(s, n, supplier="CV Basah") for n in (7, 8, 9)],
        "fresh_hold": write_record(s, 50, decision="escalate_human"),  # 01:50, 10 min old
    }
    followups.append_resolution(s, ids["hold_done"], "sort_then_accept", actor="s")
    followups.append_resolution(s, ids["reject_done"], "reject", actor="s")
    for record_id in ids["wet"]:
        followups.append_lab(s, record_id, moisture_pct=25, ncv_mj_kg=14, chlorine_pct=0.5,
                             actor="lab")
    return s, ids


def test_alerts_cover_every_kind_deterministically(ledger):
    storage, ids = ledger
    feed = control.alerts(storage, now=NOW)
    assert feed == control.alerts(storage, now=NOW)
    by_id = {a["id"]: a for a in feed}
    assert set(by_id) == {
        f"hold_unresolved:{ids['old_hold']}",
        f"hold_unresolved:{ids['hold']}",
        f"reject_unconfirmed:{ids['reject']}",
        "declaration_conflict:pt logam",
        "supplier_out_of_spec:cv basah",
    }
    hold = by_id[f"hold_unresolved:{ids['hold']}"]
    # Finished 01:03:14; now 02:00 -> 56.8 min.
    assert hold["title"] == "Hold waiting 57 min for a supervisor"
    assert (hold["severity"], hold["record_id"], hold["supplier"]) == (
        "warning", ids["hold"], "CV Tunggu")
    reject = by_id[f"reject_unconfirmed:{ids['reject']}"]
    assert "(metal)" in reject["detail"]
    conflict = by_id["declaration_conflict:pt logam"]
    assert conflict["severity"] == "info"
    assert conflict["title"] == "PT Logam: 1 waybill declaration disagreed with the load"
    assert conflict["record_id"] == ids["reject"]
    trend = by_id["supplier_out_of_spec:cv basah"]
    assert trend["record_id"] == ids["wet"][-1]
    assert "moisture_pct" in trend["detail"]
    # Severity first, then newest first.
    assert [a["severity"] for a in feed] == ["warning"] * 4 + ["info"]
    warnings = [a["at_utc"] for a in feed if a["severity"] == "warning"]
    assert warnings == sorted(warnings, reverse=True)
    assert {"id", "severity", "kind", "title", "detail", "at_utc"} <= set(feed[0])


def test_supplier_trend_needs_three_breaching_labs(ledger):
    storage, ids = ledger
    followups.append_lab(storage, write_record(storage, 10, supplier="CV Basah"),
                         moisture_pct=18, ncv_mj_kg=14, chlorine_pct=0.5, actor="lab")
    kinds = {a["kind"] for a in control.alerts(storage, now=NOW)}
    assert "supplier_out_of_spec" not in kinds


def test_chlorine_budget_alert(ledger, monkeypatch):
    storage, _ = ledger
    # Accepted in the shift: 3 x 10 t lab-sampled at 25 % moisture, 0.5 % Cl
    # (3 x 7.5 dry t x 5 kg/t = 112.5 kg) plus the sorted-then-accepted hold
    # at contract values (8 dry t x 10 kg/t = 80 kg): 192.5 kg.
    monkeypatch.setenv(fuel.CHLORINE_BUDGET_ENV, "220")
    warn = [a for a in control.alerts(storage, now=NOW) if a["kind"] == "chlorine_budget"]
    assert [(a["severity"], a["title"]) for a in warn] == [
        ("warning", "Chlorine at 87.5 % of the shift budget")]
    assert "Example plant budget" in warn[0]["detail"]
    monkeypatch.setenv(fuel.CHLORINE_BUDGET_ENV, "150")
    feed = control.alerts(storage, now=NOW)
    assert feed[0]["kind"] == "chlorine_budget"
    assert (feed[0]["severity"], feed[0]["title"]) == ("critical", "Chlorine budget exceeded")


def test_no_alerts_on_an_empty_ledger(tmp_path):
    assert control.alerts(tmp_path, now=NOW) == []


def test_control_summary(ledger):
    storage, ids = ledger
    for n in range(11, 25):
        write_record(storage, n, supplier="CV Sumber Bersih")
    summary = control.control_summary(storage, now=NOW)
    assert set(summary) == {
        "generated_at_utc", "shift", "kiln", "carbon", "alerts", "queue", "held",
        "suppliers", "lab_trend", "amd", "contract_note",
    }
    assert summary["generated_at_utc"] == NOW
    assert summary["shift"]["window"] == {"since": "2026-10-13T18:00:00Z", "until": NOW}
    assert summary["shift"]["trucks"] == 22  # the two-day-old records are outside
    assert summary["kiln"]["window"]["name"] == "shift"
    assert summary["carbon"]["af_energy_gj"] == summary["kiln"]["energy_gj"]
    # Queue: the 12 latest, newest first, as compact cards.
    queue = summary["queue"]
    assert len(queue) == 12
    assert queue[0]["record_id"] == ids["fresh_hold"]
    assert [c["record_id"] for c in queue[1:]] == [
        f"inspection-{n:06d}" for n in range(24, 13, -1)]
    card = queue[0]
    assert set(card) == {"record_id", "truck_id", "supplier", "decision", "why", "at_utc",
                         "decision_s", "followups", "resolution"}
    assert card["decision_s"] == 14.0
    assert card["followups"] == {"reviewed": False, "lab": False, "notice": False}
    # Held: unresolved holds, oldest first, with their age.
    held = summary["held"]
    assert [c["record_id"] for c in held] == [ids["old_hold"], ids["hold"], ids["fresh_hold"]]
    assert held[-1]["age_min"] == 10
    # Suppliers: top 6 by risk.
    risks = [p["risk_score"] for p in summary["suppliers"]]
    assert len(risks) == 6 and risks == sorted(risks, reverse=True)
    # Lab trend: the three wet samples, against the spec.
    trend = summary["lab_trend"]
    assert trend["spec"]["moisture_pct_max"] == 20.0
    assert [(p["record_id"], p["in_spec"], p["tier"]) for p in trend["points"]] == [
        (record_id, False, "C") for record_id in ids["wet"]]


def test_routes_and_auth(tmp_path, monkeypatch):
    for name in (auth.LYNCEUS_ADMIN_USERNAME_ENV, auth.LYNCEUS_ADMIN_PASSWORD_ENV,
                 auth.LYNCEUS_ADMIN_PASSWORD_SHA256_ENV):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(LYNCEUS_STORAGE_DIR_ENV, str(tmp_path))
    monkeypatch.setattr(pipeline, "resolve_assist_client", lambda *a, **k: None)
    auth.reset_signer()
    write_record(tmp_path, 1, decision="reject", hard=["metal"])
    client = TestClient(create_app())
    body = client.get("/alerts").json()
    assert set(body) == {"generated_at_utc", "rules", "alerts"}
    assert [r["kind"] for r in body["rules"]] == [r["kind"] for r in control.ALERT_RULES]
    summary = client.get("/control/summary")
    assert summary.status_code == 200
    assert summary.json()["queue"][0]["record_id"] == "inspection-000001"

    monkeypatch.setenv(auth.LYNCEUS_ADMIN_USERNAME_ENV, "u")
    monkeypatch.setenv(auth.LYNCEUS_ADMIN_PASSWORD_ENV, "p-secret")
    auth.reset_signer()
    locked = TestClient(create_app())
    assert locked.get("/alerts").status_code == 401
    assert locked.get("/control/summary").status_code == 401
    auth.reset_signer()
