"""Tests for the deterministic next-step card (lynceus.actions) and its SOP.

Every step must cite a clause that exists in the reference gate SOP
(``knowledge/sop-rdf-gate.md``); the rule table is the one in the Task 5
brief, with controller ruling 16 for combined / unmatched / gas semantics.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import lynceus
from lynceus import actions, audit, decision, pipeline
from lynceus.api import create_app
from lynceus.config import LYNCEUS_STORAGE_DIR_ENV

SOP_PATH = Path(lynceus.__file__).resolve().parent / "knowledge" / "sop-rdf-gate.md"

D = audit.Decision


def _gates(**states: str) -> dict:
    """Gate dict with every gate passed, overridden by ``name=state``."""
    base = {name: {"state": "passed", "value": None, "threshold": None, "reason": None}
            for name in audit.GATE_NAMES}
    for name, state in states.items():
        base[name] = dict(base[name], state=state)
    return base


def _detected(hard=(), light=()) -> dict:
    return {"hard_contaminants": list(hard), "light_contaminants": list(light)}


def _refs(steps) -> list[str]:
    return [s["sop_ref"] for s in steps]


def _texts(steps) -> list[str]:
    return [s["text"] for s in steps]


# ---------------------------------------------------------------------------
# One test per table row
# ---------------------------------------------------------------------------


def test_reject_hard_contaminant():
    steps = actions.next_steps(
        D.REJECT, _gates(), _detected(hard=["metal", "concrete"]), [], "inspection-000007"
    )
    assert _refs(steps) == ["SOP-RDF-4.1", "SOP-RDF-4.2", "SOP-RDF-4.3"]
    assert [s["order"] for s in steps] == [1, 2, 3]
    assert _texts(steps) == [
        "Do not tip. Keep the truck on the weighbridge.",
        "Send the load to the sorting bay to remove: metal, concrete.",
        "Photograph the load and notify the supplier with record inspection-000007.",
    ]


def test_reject_weight_mismatch():
    steps = actions.next_steps(
        D.REJECT, _gates(weight_plausibility="failed"), _detected(), [], "r1"
    )
    assert _refs(steps) == ["SOP-RDF-3.2", "SOP-RDF-4.3"]
    assert _texts(steps) == [
        "Hold the ticket and re-weigh the truck.",
        "Ask the driver for the original waybill and notify the supplier.",
    ]


def test_reject_low_vlm_confidence():
    steps = actions.next_steps(
        D.REJECT, _gates(vlm_confidence="failed"), _detected(), [], "r1"
    )
    assert _refs(steps) == ["SOP-RDF-2.1", "SOP-RDF-5.2"]
    assert _texts(steps) == [
        "Retake the load photo from the top platform.",
        "Supervisor performs a manual visual check.",
    ]


def test_escalate_moisture_conflict():
    gates = _gates()
    gates["manifest_crosscheck"] = {
        "state": "failed", "value": None, "threshold": None,
        "reason": "Moisture conflict: the waybill declares a dry load (<15%) but ...",
    }
    steps = actions.next_steps(D.ESCALATE_HUMAN, gates, _detected(), [], "r1")
    assert _refs(steps)[:2] == ["SOP-RDF-5.1", "SOP-RDF-5.3"]
    assert _texts(steps)[:2] == [
        "Hold the ticket; supervisor takes a grab sample for moisture.",
        "If confirmed wet, apply the contract moisture penalty.",
    ]


def test_escalate_moisture_conflict_from_real_decide():
    """Guard against drift in decision.py's moisture-conflict gate reason."""
    inputs = {
        "photo_filename": "p.jpg",
        "manifest_text": "Waste: RDF. Moisture declared: 10%. Declared weight: 5,000 kg",
        "weight_kg": 5000.0,
    }
    vlm = {"detected": {"contamination": "none", "moisture": 0.5,
                        "hard_contaminants": [], "light_contaminants": []},
           "confidence": 0.8}
    llm = {"confidence": 0.9, "crosscheck_failed": False}
    verdict, gates, _ = decision.decide(inputs, vlm, llm, None)
    assert verdict == D.ESCALATE_HUMAN
    steps = actions.next_steps(verdict, gates, vlm["detected"], [], "r1")
    assert _refs(steps)[:2] == ["SOP-RDF-5.1", "SOP-RDF-5.3"]


def test_escalate_light_contaminant():
    steps = actions.next_steps(
        D.ESCALATE_HUMAN, _gates(), _detected(light=["plastic_film"]), [], "r1"
    )
    assert _refs(steps) == ["SOP-RDF-4.4"]
    assert _texts(steps) == ["Tip to the pre-sort line, not direct feed."]


def test_escalate_manifest_crosscheck_failed():
    steps = actions.next_steps(
        D.ESCALATE_HUMAN, _gates(manifest_crosscheck="failed"), _detected(), [], "r1"
    )
    assert _refs(steps) == ["SOP-RDF-3.3"]
    assert _texts(steps) == ["Verify the waybill with the driver; correct or void the ticket."]


def test_accept():
    steps = actions.next_steps(D.ACCEPT, _gates(), _detected(), [], "r1")
    assert steps == [{
        "order": 1,
        "text": "Tip to the RDF storage bay and release the ticket.",
        "sop_ref": "SOP-RDF-6.1",
    }]


def test_refuse_insufficient_input():
    steps = actions.next_steps(
        D.REFUSE_INSUFFICIENT_INPUT, _gates(), {}, ["photo", "manifest_text"], "r1"
    )
    assert steps == [{
        "order": 1,
        "text": "Collect the missing inputs (photo, manifest_text) and re-run the inspection.",
        "sop_ref": "SOP-RDF-2.2",
    }]


def test_gas_failed_appended_last_for_any_verdict():
    gas = "Gas alert: ventilate the tipping area before unloading; keep the cab closed."
    accept = actions.next_steps(D.ACCEPT, _gates(gas_plausibility="failed"), _detected(), [], "r1")
    assert _refs(accept) == ["SOP-RDF-6.1", "SOP-RDF-7.1"]
    assert accept[-1]["text"] == gas
    reject = actions.next_steps(
        D.REJECT,
        _gates(gas_plausibility="failed"),
        _detected(hard=["metal"]),
        [],
        "r1",
    )
    assert _refs(reject) == ["SOP-RDF-4.1", "SOP-RDF-4.2", "SOP-RDF-4.3", "SOP-RDF-7.1"]
    assert [s["order"] for s in reject] == [1, 2, 3, 4]


# ---------------------------------------------------------------------------
# Ruling 16: combined, unmatched, dedupe
# ---------------------------------------------------------------------------


def test_combined_reject_hard_plus_weight_dedupes_4_3():
    steps = actions.next_steps(
        D.REJECT,
        _gates(weight_plausibility="failed"),
        _detected(hard=["metal"]),
        [],
        "r1",
    )
    assert _refs(steps) == ["SOP-RDF-4.1", "SOP-RDF-4.2", "SOP-RDF-4.3", "SOP-RDF-3.2"]
    assert [s["order"] for s in steps] == [1, 2, 3, 4]
    assert len({s["sop_ref"] for s in steps}) == len(steps)


@pytest.mark.parametrize("verdict", [D.REJECT, D.ESCALATE_HUMAN])
def test_unmatched_reject_or_escalate_falls_back_to_manual_check(verdict):
    steps = actions.next_steps(verdict, _gates(), _detected(), [], "r1")
    assert steps == [{
        "order": 1,
        "text": "Hold the ticket; supervisor performs a manual visual check.",
        "sop_ref": "SOP-RDF-5.2",
    }]


def test_unmatched_fallback_still_gets_gas_appended():
    steps = actions.next_steps(
        D.ESCALATE_HUMAN, _gates(gas_plausibility="failed"), _detected(), [], "r1"
    )
    assert _refs(steps) == ["SOP-RDF-5.2", "SOP-RDF-7.1"]


def test_escalate_all_rows_in_table_order():
    gates = _gates(manifest_crosscheck="failed")
    gates["manifest_crosscheck"]["reason"] = "Moisture conflict: x"
    steps = actions.next_steps(
        D.ESCALATE_HUMAN, gates, _detected(light=["glass"]), [], "r1"
    )
    assert _refs(steps) == ["SOP-RDF-5.1", "SOP-RDF-5.3", "SOP-RDF-4.4", "SOP-RDF-3.3"]


def test_tolerates_missing_or_malformed_inputs():
    steps = actions.next_steps(D.REJECT, {}, {"hard_contaminants": None}, [], "")
    assert _refs(steps) == ["SOP-RDF-5.2"]
    steps = actions.next_steps(D.REJECT, _gates(), _detected(hard=["metal"]), [], "")
    assert "with record" not in steps[2]["text"]


def test_steps_validate_as_action_steps():
    steps = actions.next_steps(
        D.REJECT, _gates(weight_plausibility="failed"), _detected(hard=["tire"]), [], "r1"
    )
    for s in steps:
        audit.ActionStep(**s)


# ---------------------------------------------------------------------------
# Reference SOP document
# ---------------------------------------------------------------------------

_ALL_REFS = {
    "SOP-RDF-2.1", "SOP-RDF-2.2", "SOP-RDF-3.2", "SOP-RDF-3.3",
    "SOP-RDF-4.1", "SOP-RDF-4.2", "SOP-RDF-4.3", "SOP-RDF-4.4",
    "SOP-RDF-5.1", "SOP-RDF-5.2", "SOP-RDF-5.3", "SOP-RDF-6.1", "SOP-RDF-7.1",
}


def _sop_sections() -> dict[str, str]:
    text = SOP_PATH.read_text(encoding="utf-8")
    parts = re.split(r"^## (SOP-RDF-\d+\.\d+) — (.+)$", text, flags=re.M)
    # parts: [preamble, id, title, body, id, title, body, ...]
    return {parts[i]: parts[i + 2].strip() for i in range(1, len(parts), 3)}


def test_sop_first_line_exact():
    first = SOP_PATH.read_text(encoding="utf-8").splitlines()[0]
    assert first == (
        "# Reference gate SOP — RDF receiving (reference SOP, not a real plant's document)"
    )


def test_every_sop_ref_exists_in_sop_doc():
    sections = _sop_sections()
    assert set(sections) == _ALL_REFS
    all_step_refs = set()
    for verdict in (D.ACCEPT, D.REJECT, D.ESCALATE_HUMAN, D.REFUSE_INSUFFICIENT_INPUT):
        gates = _gates(
            weight_plausibility="failed",
            vlm_confidence="failed",
            manifest_crosscheck="failed",
            gas_plausibility="failed",
        )
        gates["manifest_crosscheck"]["reason"] = "Moisture conflict: x"
        all_step_refs |= set(_refs(actions.next_steps(
            verdict, gates, _detected(hard=["metal"], light=["glass"]), ["photo"], "r1"
        )))
    assert all_step_refs == _ALL_REFS
    assert all_step_refs <= set(sections)


def test_sop_sections_have_3_to_6_sentences_each():
    for ref, body in _sop_sections().items():
        sentences = [s for s in re.split(r"(?<=[.!?])\s+", body) if s.strip()]
        assert 3 <= len(sentences) <= 6, (ref, len(sentences))


def test_sop_sections_name_a_research_source():
    markers = ("RDI", "SIPSN", "SWITCH-Asia", "ITATS", "PUPR", "Kompas", "oxmaint",
               "Damanhuri", "PP 55", "UU 22", "SIG", "SBI")
    for ref, body in _sop_sections().items():
        assert any(m in body for m in markers), ref


# ---------------------------------------------------------------------------
# End to end: /inspect carries the actions into the audit record
# ---------------------------------------------------------------------------


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv(LYNCEUS_STORAGE_DIR_ENV, str(tmp_path))
    monkeypatch.setattr(pipeline, "_vlm_reachable", lambda *a, **k: False)
    return TestClient(create_app())


def test_actions_in_audit_record(client):
    resp = client.post("/inspect", json={
        "truck_id": "F-7702-TS",
        "demo_case": "red",
        "manifest_text": "Waste type: clean RDF fluff\nDeclared weight: 15,500 kg\n"
                         "Moisture declared: 12%",
        "weight_kg": 19300,
        "waste_stream": "mixed-msw",
        "moisture": 0.14,
        "age_h": 8,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["verdict"]["decision"] == D.REJECT
    assert body["actions"][0]["sop_ref"] == "SOP-RDF-4.1"
    assert "with record " + body["record_id"] in body["actions"][2]["text"]
    recorded = body["audit_record"]["engine_outputs"]["recommendation"]["actions"]
    assert recorded == body["actions"] == body["engine_outputs"]["recommendation"]["actions"]
    for step in recorded:
        audit.ActionStep(**step)
