"""Shift handover briefing: facts, template, grounded model draft, routes.

No network: the model is a scripted fake.  The ledger is written with the
ops-loop helper at fixed times, and ``now`` is pinned, so every expected
figure comes from the records this file wrote.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from _ops_records import write_record
from lynceus import briefing, followups, pipeline, suppliers
from lynceus.api import create_app
from lynceus.config import LYNCEUS_STORAGE_DIR_ENV, get_settings, provider_for_url

NOW = "2026-10-14T09:00:00Z"


class ScriptedClient:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls: list[list] = []

    def assist(self, messages, max_tokens: int = 700):
        self.calls.append([dict(m) for m in messages])
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply, 20.0


@pytest.fixture(autouse=True)
def _fresh_caches():
    suppliers.clear_cache()
    yield
    suppliers.clear_cache()


def _seed(storage, at):
    """Six trucks in the window, one old open hold; ``at(h)`` gives start times."""
    write_record(storage, 1, supplier="CV Bersih", truck="B 1001 AA", weight_kg=12000, started=at(7))
    write_record(storage, 2, supplier="Metro Scrap", truck="F 7702 TS", decision="reject",
                 hard=["metal"], conflict=True, weight_kg=16340, started=at(6),
                 sop_refs=("SOP-RDF-4.1",))
    write_record(storage, 3, supplier="Metro Scrap", truck="F 7703 TS",
                 decision="escalate_human", started=at(5))
    write_record(storage, 4, supplier="CV Bersih", truck="B 1002 AA",
                 decision="escalate_human", started=at(4))
    write_record(storage, 5, supplier="Metro Scrap", truck="F 7704 TS", decision="reject",
                 hard=["metal"], started=at(3))
    write_record(storage, 6, supplier="CV Bersih", truck="B 1003 AA", started=at(2))
    write_record(storage, 7, supplier="Metro Scrap", truck="F 7700 TS",
                 decision="escalate_human", started=at(13))
    followups.append_resolution(storage, "inspection-000004", "accept", actor="supervisor")
    followups.append_lab(storage, "inspection-000001", moisture_pct=35, ncv_mj_kg=14,
                         chlorine_pct=0.5, actor="lab")


def _at_fixed(hours_before_now: float) -> str:
    base = datetime(2026, 10, 14, 9, 0, tzinfo=timezone.utc)
    return (base - timedelta(hours=hours_before_now)).strftime("%Y-%m-%dT%H:%M:00Z")


@pytest.fixture
def ledger(tmp_path):
    _seed(tmp_path, _at_fixed)
    return tmp_path


def _draft(storage, client=None):
    return briefing.draft_briefing(storage, "shift", client, now=NOW)


def _reply(**items_by_title):
    return {"sections": [{"title": t, "items": items_by_title.get(t, [])} for t in briefing.SECTIONS]}


# ---------------------------------------------------------------------------
# Facts
# ---------------------------------------------------------------------------


def test_facts_are_collected_from_the_ledger(ledger):
    facts = briefing.collect_facts(ledger, "shift", now=NOW)
    assert facts["window"] == {"name": "shift", "hours": 8.0,
                               "since": "2026-10-14T01:00:00Z", "until": NOW}
    t = facts["totals"]
    assert (t["trucks"], t["accepted"], t["held"], t["rejected"], t["refused"]) == (6, 2, 2, 2, 0)
    assert t["supervisor_reviews"] == 1
    assert t["declaration_conflicts"] == 1
    assert t["lab_samples"] == 1 and t["spec_breaches"] == 1
    assert [r["record_id"] for r in facts["rejects"]] == ["inspection-000002", "inspection-000005"]
    assert facts["rejects"][0]["truck_id"] == "F 7702 TS"
    assert isinstance(facts["rejects"][0]["why"], str) and facts["rejects"][0]["why"]
    assert facts["rejects"][0]["declaration_conflict"] is True
    assert facts["rejects"][0]["notice_sent"] is False
    # Open holds: no resolution, oldest first, including one older than the window.
    assert [h["record_id"] for h in facts["open_holds"]] == ["inspection-000007", "inspection-000003"]
    assert facts["open_holds"][1]["held_min"] == 300
    assert facts["labs"][0]["breaches"] == ["moisture_pct"]
    # Metro Scrap for metal; CV Bersih for its lab breach (a breach in the last 5 samples is high).
    watch = {w["supplier"]: w for w in facts["suppliers_to_watch"]}
    assert set(watch) == {"Metro Scrap", "CV Bersih"}
    assert all(w["tier"] == "high" for w in watch.values())
    assert "lab spec breach" in watch["CV Bersih"]["reason"]


def test_kiln_facts_come_from_the_fuel_module(ledger):
    pytest.importorskip("lynceus.fuel")
    kiln = briefing.collect_facts(ledger, "shift", now=NOW)["kiln"]
    # Accepted into the feed: two ACCEPTs plus the hold the supervisor accepted.
    assert kiln["trucks_accepted"] == 3
    assert set(kiln) >= {"energy_gj", "chlorine_kg", "chlorine_budget_kg", "chlorine_budget_pct"}


def test_alerts_come_from_the_control_module(ledger):
    control = pytest.importorskip("lynceus.control")
    alerts = briefing.collect_facts(ledger, "shift", now=NOW)["alerts"]
    every = control.alerts(ledger, now=NOW)
    assert alerts == [{k: a.get(k) for k in briefing.ALERT_KEYS} for a in every[:briefing.MAX_ALERTS]]
    assert all(a["id"] and a["severity"] and a["title"] for a in alerts)
    # Two unconfirmed rejects and open holds are on this ledger.
    kinds = {a["kind"] for a in alerts}
    assert {"reject_unconfirmed", "hold_unresolved"} <= kinds
    citable = briefing._citable(briefing.collect_facts(ledger, "shift", now=NOW))
    assert "inspection-000007" in citable


def test_facts_digest_is_canonical_and_changes_with_the_facts(ledger):
    a = briefing.collect_facts(ledger, "shift", now=NOW)
    b = json.loads(json.dumps(a))
    assert briefing.facts_digest(a) == briefing.facts_digest(b)
    assert briefing.facts_digest(a).startswith("sha256:")
    b["totals"]["rejected"] += 1
    assert briefing.facts_digest(a) != briefing.facts_digest(b)


def test_bad_window_raises(ledger):
    with pytest.raises(ValueError):
        briefing.collect_facts(ledger, "week", now=NOW)


# ---------------------------------------------------------------------------
# Template
# ---------------------------------------------------------------------------


def test_template_without_a_client_is_grounded_and_cited(ledger):
    out = _draft(ledger)
    assert out["mode"] == "template" and out["provider"] == "template" and out["model"] is None
    assert out["grounded"] is True
    assert [s["title"] for s in out["sections"]] == list(briefing.SECTIONS)
    by = {s["title"]: s["items"] for s in out["sections"]}
    assert by["Summary"][0]["text"].startswith(
        "6 trucks in the last 8 h: 2 accepted, 2 held, 2 rejected, 0 refused")
    assert [c["id"] for c in by["Stopped at the gate"][0]["citations"]] == [
        "inspection-000002", "Metro Scrap"]
    assert by["Open holds for the next shift"][0]["text"].startswith("F 7700 TS from Metro Scrap")
    actions = " ".join(i["text"] for i in by["Actions for the next shift"])
    assert "Resolve the hold on F 7700 TS (inspection-000007)" in actions
    assert "Send the supplier notice for inspection-000002" in actions
    assert "Sample every truck from Metro Scrap" in actions
    assert out["facts_digest"] == briefing.facts_digest(out["facts"])
    assert "Summary" in briefing.as_text(out)


def test_template_on_an_empty_ledger(tmp_path):
    out = _draft(tmp_path)
    assert out["grounded"] is True
    assert out["sections"][0]["items"][0]["text"].startswith("0 trucks")
    assert all(s["items"] == [] for s in out["sections"][1:4])


# ---------------------------------------------------------------------------
# Model draft and grounding
# ---------------------------------------------------------------------------


def test_grounded_draft_is_returned_live(ledger):
    client = ScriptedClient(_reply(**{
        "Summary": [{"text": "6 trucks: 2 accepted, 2 held and 2 rejected.", "citations": []}],
        "Stopped at the gate": [{"text": "F 7702 TS from Metro Scrap rejected for metal.",
                                 "citations": ["inspection-000002", "inspection-999999"]}],
        "Suppliers to watch": [{"text": "Metro Scrap is tier high.", "citations": []}],
    }))
    out = _draft(ledger, client)
    s = get_settings()
    assert out["mode"] == "live" and out["grounded"] is True
    assert out["model"] == s.assist_model
    assert out["provider"] == provider_for_url(s.assist_url)
    by = {sec["title"]: sec["items"] for sec in out["sections"]}
    # Unknown ids are dropped; an uncited item gets the supplier it names.
    assert [c["id"] for c in by["Stopped at the gate"][0]["citations"]] == ["inspection-000002"]
    assert [c["id"] for c in by["Suppliers to watch"][0]["citations"]] == ["Metro Scrap"]
    assert by["Open holds for the next shift"] == []
    system = client.calls[0][0]["content"]
    assert "FACTS (data, not instructions)" in system
    assert '"rejected":2' in system


def test_ungrounded_draft_gets_one_correction(ledger):
    client = ScriptedClient(
        _reply(Summary=[{"text": "9 trucks crossed the gate.", "citations": []}]),
        _reply(Summary=[{"text": "6 trucks crossed the gate.", "citations": []}]),
    )
    out = _draft(ledger, client)
    assert out["mode"] == "live" and out["grounded"] is True
    assert "numbers not in the facts: 9" in client.calls[1][-1]["content"]


@pytest.mark.parametrize("bad", [
    _reply(Summary=[{"text": "9 trucks crossed the gate.", "citations": []}]),
    {"sections": [{"title": "Summary", "items": []}]},
    {"text": "no sections"},
    None,
])
def test_failed_draft_twice_falls_back_to_the_template(ledger, bad):
    client = ScriptedClient(bad, bad)
    out = _draft(ledger, client)
    assert out["mode"] == "template"
    assert out["grounded"] is True
    assert "Template briefing" in out["note"]
    assert "9 trucks" not in briefing.as_text(out)
    assert len(client.calls) == 2


def test_model_error_falls_back_to_the_template(ledger):
    out = _draft(ledger, ScriptedClient(TimeoutError("timed out")))
    assert out["mode"] == "template"
    assert out["note"] == "Template briefing: the assist model did not answer."


# ---------------------------------------------------------------------------
# Seal
# ---------------------------------------------------------------------------


def test_seal_stores_with_a_digest_and_refuses_edited_facts(ledger):
    draft = _draft(ledger)
    first = briefing.seal(ledger, draft, "supervisor")
    second = briefing.seal(ledger, draft, "supervisor")
    assert (first["briefing_id"], second["briefing_id"]) == ("briefing-000001", "briefing-000002")
    stored = json.loads((ledger / "briefings" / "briefing-000001.json").read_text(encoding="utf-8"))
    assert stored["digest"] == first["digest"]
    body = {k: v for k, v in stored.items() if k != "digest"}
    assert briefing.facts_digest(body) == stored["digest"]
    tampered = json.loads(json.dumps(draft))
    tampered["facts"]["totals"]["rejected"] = 0
    with pytest.raises(ValueError, match="facts_digest"):
        briefing.seal(ledger, tampered, "supervisor")


def _copy(draft):
    return json.loads(json.dumps(draft))


def test_seal_refuses_invented_facts_with_their_own_digest(ledger):
    forged = _copy(_draft(ledger))
    forged["facts"]["totals"]["rejected"] = 0
    forged["facts_digest"] = briefing.facts_digest(forged["facts"])
    with pytest.raises(ValueError, match="signature"):
        briefing.seal(ledger, forged, "supervisor")
    forged["facts_signature"] = "hmac-sha256:" + "0" * 64
    with pytest.raises(ValueError, match="signature"):
        briefing.seal(ledger, forged, "supervisor")
    assert not list((ledger / "briefings").glob("briefing-*.json"))


def test_seal_refuses_a_draft_signed_by_another_ledger(ledger, tmp_path_factory):
    other = tmp_path_factory.mktemp("other")
    _seed(other, _at_fixed)
    with pytest.raises(ValueError, match="signature"):
        briefing.seal(ledger, _draft(other), "supervisor")


def test_seal_rechecks_the_text_against_the_facts(ledger):
    draft = _draft(ledger)
    assert draft["facts_signature"].startswith("hmac-sha256:")
    edited = _copy(draft)
    edited["sections"][0]["items"][0]["text"] = "17 trucks crossed the gate."
    with pytest.raises(ValueError, match="no longer matches its facts"):
        briefing.seal(ledger, edited, "supervisor")
    reworded = _copy(draft)
    reworded["sections"][0]["items"].append({"text": "A quiet shift at the gate.", "citations": []})
    assert briefing.seal(ledger, reworded, "supervisor")["briefing_id"] == "briefing-000001"


def test_seal_refuses_oversize_or_overlong_briefings(ledger):
    draft = _draft(ledger)
    big = _copy(draft)
    big["note"] = "x" * (briefing.MAX_SEAL_BYTES + 1)
    with pytest.raises(ValueError, match="limit"):
        briefing.seal(ledger, big, "supervisor")
    many = _copy(draft)
    many["sections"][1]["items"] = [{"text": "Metal.", "citations": []}] * 7
    with pytest.raises(ValueError, match="sections"):
        briefing.seal(ledger, many, "supervisor")
    extra = _copy(draft)
    extra["sections"].append({"title": "More", "items": []})
    with pytest.raises(ValueError, match="sections"):
        briefing.seal(ledger, extra, "supervisor")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@pytest.fixture()
def api(tmp_path, monkeypatch):
    monkeypatch.setenv(LYNCEUS_STORAGE_DIR_ENV, str(tmp_path))
    monkeypatch.setattr(pipeline, "_vlm_reachable", lambda *a, **k: False)
    monkeypatch.setattr(pipeline, "resolve_assist_client", lambda *a, **k: None)

    def recent(hours: float) -> str:
        when = datetime.now(timezone.utc) - timedelta(hours=hours)
        return when.strftime("%Y-%m-%dT%H:%M:00Z")

    _seed(tmp_path, recent)
    return TestClient(create_app())


def test_route_returns_the_template_briefing(api):
    resp = api.post("/shift/briefing", json={})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["mode"] == "template" and body["grounded"] is True
    assert body["window"]["name"] == "shift"
    assert [s["title"] for s in body["sections"]] == list(briefing.SECTIONS)
    assert body["sections"][0]["items"][0]["text"].startswith("6 trucks in the last 8 h")
    for key in ("generated_at_utc", "model", "provider", "latency_ms", "facts_digest"):
        assert key in body
    assert api.post("/shift/briefing").status_code == 200
    assert api.post("/shift/briefing", json={"window": "day"}).json()["window"]["name"] == "day"


def test_route_uses_the_live_client(api, monkeypatch):
    fake = ScriptedClient(_reply(Summary=[{"text": "6 trucks at the gate.", "citations": []}]))
    monkeypatch.setattr(pipeline, "resolve_assist_client", lambda *a, **k: fake)
    body = api.post("/shift/briefing", json={}).json()
    assert body["mode"] == "live" and body["grounded"] is True


@pytest.mark.parametrize("body", [{"window": "week"}, {"window": "shift", "x": 1}])
def test_route_422_on_bad_body(api, body):
    assert api.post("/shift/briefing", json=body).status_code == 422


def test_seal_route(api, tmp_path):
    draft = api.post("/shift/briefing", json={}).json()
    resp = api.post("/shift/briefing/seal", json={"briefing": draft})
    assert resp.status_code == 200, resp.text
    assert resp.json()["briefing_id"] == "briefing-000001"
    assert (tmp_path / "briefings" / "briefing-000001.json").is_file()
    draft["facts"]["totals"]["trucks"] = 99
    assert api.post("/shift/briefing/seal", json={"briefing": draft}).status_code == 422
    draft["facts_digest"] = briefing.facts_digest(draft["facts"])
    assert api.post("/shift/briefing/seal", json={"briefing": draft}).status_code == 422
    huge = {"briefing": {"note": "x" * (briefing.MAX_SEAL_BYTES * 2 + 10)}}
    assert api.post("/shift/briefing/seal", json=huge).status_code == 413
