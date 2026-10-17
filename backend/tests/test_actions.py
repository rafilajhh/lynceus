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


_SUPERVISOR = (
    "Supervisor reviews the load and records the call on this record: accept, sort "
    "then accept, or reject."
)


def test_escalate_low_vlm_confidence_retakes_then_supervisor():
    steps = actions.next_steps(
        D.ESCALATE_HUMAN, _gates(vlm_confidence="failed"), _detected(), [], "r1"
    )
    assert _refs(steps) == ["SOP-RDF-2.1", "SOP-RDF-5.2"]
    assert _texts(steps) == [
        "Photo unreadable: retake the load photo from the top platform.",
        _SUPERVISOR,
    ]


def test_escalate_weight_ticket_correction():
    steps = actions.next_steps(
        D.ESCALATE_HUMAN, _gates(weight_plausibility="failed"), _detected(), [], "r1"
    )
    assert _refs(steps) == ["SOP-RDF-3.2", "SOP-RDF-3.3", "SOP-RDF-5.2"]
    assert _texts(steps)[0].startswith("Ticket correction: re-weigh the truck")


def test_escalate_uncertain_waybill_read():
    steps = actions.next_steps(
        D.ESCALATE_HUMAN, _gates(ocr_confidence="failed"), _detected(), [], "r1"
    )
    assert _refs(steps) == ["SOP-RDF-3.3", "SOP-RDF-5.2"]
    assert _texts(steps)[0] == (
        "Waybill read uncertain: check the highlighted fields against the paper waybill."
    )


def test_reject_declared_sorted_adds_contract_breach_notice():
    gates = _gates()
    gates["manifest_crosscheck"] = {
        "state": "failed", "value": None, "threshold": None,
        "reason": "Waybill declares sorted RDF (RDF fluff); the camera sees metal.",
    }
    steps = actions.next_steps(D.REJECT, gates, _detected(hard=["metal"]), [], "inspection-000009")
    assert _refs(steps) == ["SOP-RDF-4.1", "SOP-RDF-4.2", "SOP-RDF-4.3", "SOP-RDF-4.5"]
    assert "record inspection-000009" in steps[3]["text"]
    assert "breach fee per contract" in steps[3]["text"]


def test_reject_without_declaration_has_no_breach_notice():
    steps = actions.next_steps(D.REJECT, _gates(), _detected(hard=["metal"]), [], "r1")
    assert "SOP-RDF-4.5" not in _refs(steps)


@pytest.mark.parametrize("verdict,expected", [
    (D.ACCEPT, ["SOP-RDF-6.1", "SOP-RDF-5.4"]),
    (D.ESCALATE_HUMAN, ["SOP-RDF-4.4", "SOP-RDF-5.2", "SOP-RDF-5.4"]),
    (D.REJECT, ["SOP-RDF-4.1", "SOP-RDF-4.2", "SOP-RDF-4.3"]),
    (D.REFUSE_INSUFFICIENT_INPUT, ["SOP-RDF-2.2"]),
])
def test_risk_based_lab_sample_step(verdict, expected):
    detected = _detected(hard=["metal"]) if verdict == D.REJECT else _detected(light=["glass"])
    steps = actions.next_steps(
        verdict, _gates(), detected, ["photo"], "r1", sampling={"sample_this_truck": True}
    )
    assert _refs(steps) == expected
    if "SOP-RDF-5.4" in expected:
        assert "risk-based lab sample" in steps[-1]["text"]


@pytest.mark.parametrize("sampling", [None, {}, {"sample_this_truck": False},
                                      {"sample_this_truck": "yes"}])
def test_no_lab_sample_step_unless_sampling_says_so(sampling):
    steps = actions.next_steps(D.ACCEPT, _gates(), _detected(), [], "r1", sampling=sampling)
    assert _refs(steps) == ["SOP-RDF-6.1"]


def test_lab_sample_comes_before_the_gas_row():
    steps = actions.next_steps(
        D.ACCEPT, _gates(gas_plausibility="failed"), _detected(), [], "r1",
        sampling={"sample_this_truck": True},
    )
    assert _refs(steps) == ["SOP-RDF-6.1", "SOP-RDF-5.4", "SOP-RDF-7.1"]


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
    # glass, not plastic_film: plastic film is RDF feedstock since the
    # 2026-10-14 policy fix, so it no longer selects the pre-sort step.
    steps = actions.next_steps(
        D.ESCALATE_HUMAN, _gates(), _detected(light=["glass"]), [], "r1"
    )
    assert _refs(steps) == ["SOP-RDF-4.4", "SOP-RDF-5.2"]
    assert _texts(steps) == ["Tip to the pre-sort line, not direct feed.", _SUPERVISOR]


@pytest.mark.parametrize("feedstock", [["plastic_film"], ["textile"], ["plastic_film", "textile"]])
def test_rdf_feedstock_listed_as_light_does_not_select_pre_sort(feedstock):
    """Plastic film / textile in the VLM's light list are RDF feedstock: no pre-sort step."""
    steps = actions.next_steps(
        D.ESCALATE_HUMAN, _gates(manifest_crosscheck="failed"), _detected(light=feedstock), [], "r1"
    )
    assert _refs(steps) == ["SOP-RDF-3.3", "SOP-RDF-5.2"]
    assert not any("contamina" in t.lower() for t in _texts(steps))


def test_rdf_feedstock_load_accepts_and_tips_to_storage_via_real_decide():
    """A clean plastic-film / textile load: decide() accepts, the card tips it to storage."""
    inputs = {
        "photo_filename": "p.jpg",
        "manifest_text": "Waste: mixed RDF feedstock. Declared weight: 5,200 kg",
        "weight_kg": 5200.0,
    }
    vlm = {"detected": {"contamination": "textile strip and plastic film", "moisture": 0.05,
                        "hard_contaminants": [], "light_contaminants": ["plastic_film", "textile"]},
           "confidence": 0.95}
    verdict, gates, reasons = decision.decide(inputs, vlm, {"confidence": 0.9}, None)
    assert verdict == D.ACCEPT
    joined = " ".join(reasons).lower()
    assert "plastic_film" not in joined and "textile" not in joined
    steps = actions.next_steps(verdict, gates, vlm["detected"], [], "r1")
    assert _refs(steps) == ["SOP-RDF-6.1"]


def test_escalate_manifest_crosscheck_failed():
    steps = actions.next_steps(
        D.ESCALATE_HUMAN, _gates(manifest_crosscheck="failed"), _detected(), [], "r1"
    )
    assert _refs(steps) == ["SOP-RDF-3.3", "SOP-RDF-5.2"]
    assert _texts(steps) == [
        "Verify the waybill with the driver; correct or void the ticket.", _SUPERVISOR,
    ]


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


@pytest.mark.parametrize("verdict,text", [
    (D.REJECT, "Hold the ticket; supervisor performs a manual visual check."),
    (D.ESCALATE_HUMAN, _SUPERVISOR),
])
def test_unmatched_reject_or_escalate_falls_back_to_supervisor(verdict, text):
    steps = actions.next_steps(verdict, _gates(), _detected(), [], "r1")
    assert steps == [{"order": 1, "text": text, "sop_ref": "SOP-RDF-5.2"}]


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
    assert _refs(steps) == [
        "SOP-RDF-5.1", "SOP-RDF-5.3", "SOP-RDF-4.4", "SOP-RDF-3.3", "SOP-RDF-5.2",
    ]


def test_escalate_every_row_in_table_order():
    gates = _gates(vlm_confidence="failed", manifest_crosscheck="failed",
                   weight_plausibility="failed", ocr_confidence="failed")
    gates["manifest_crosscheck"]["reason"] = "Moisture conflict: x"
    steps = actions.next_steps(
        D.ESCALATE_HUMAN, gates, _detected(light=["glass"]), [], "r1",
        sampling={"sample_this_truck": True},
    )
    assert _refs(steps) == [
        "SOP-RDF-2.1", "SOP-RDF-5.1", "SOP-RDF-5.3", "SOP-RDF-4.4", "SOP-RDF-3.2",
        "SOP-RDF-3.3", "SOP-RDF-5.2", "SOP-RDF-5.4",
    ]
    # 3.3 is cited once: the ticket-correction wording (first row) wins.
    assert steps[5]["text"].startswith("Confirm the corrected net weight")


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
    "SOP-RDF-4.1", "SOP-RDF-4.2", "SOP-RDF-4.3", "SOP-RDF-4.4", "SOP-RDF-4.5",
    "SOP-RDF-5.1", "SOP-RDF-5.2", "SOP-RDF-5.3", "SOP-RDF-5.4", "SOP-RDF-6.1",
    "SOP-RDF-7.1",
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
            ocr_confidence="failed",
        )
        gates["manifest_crosscheck"]["reason"] = (
            "Waybill declares sorted RDF (RDF fluff); the camera sees metal. Moisture conflict: x"
        )
        all_step_refs |= set(_refs(actions.next_steps(
            verdict, gates, _detected(hard=["metal"], light=["glass"]), ["photo"], "r1",
            sampling={"sample_this_truck": True},
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


# ---------------------------------------------------------------------------
# Hard-contaminant steps follow decide()'s own rule (confident_hard_contaminants)
# ---------------------------------------------------------------------------


def _decide_and_steps(inputs, vlm, llm):
    verdict, gates, _ = decision.decide(inputs, vlm, llm, None)
    detected = dict(vlm.get("detected") or {})
    detected["hard_contaminants"] = decision.confident_hard_contaminants(inputs, vlm, llm)
    return verdict, actions.next_steps(verdict, gates, detected, [], "r1")


def test_structured_metal_reject_gets_do_not_tip():
    inputs = {
        "photo_filename": "p.jpg",
        "manifest_text": "Waste: RDF. Driver note: scrap metal loaded on top.",
        "weight_kg": 5000.0,
        "declared_weight_kg": 5000.0,
    }
    vlm = {"detected": {"contamination": "mixed fluff", "moisture": 0.1,
                        "hard_contaminants": ["metal"], "light_contaminants": []},
           "confidence": 0.8}
    verdict, steps = _decide_and_steps(inputs, vlm, {"confidence": 0.9})
    assert verdict == D.REJECT
    assert _refs(steps)[0] == "SOP-RDF-4.1"
    assert "remove: metal." in steps[1]["text"]


def test_weight_mismatch_with_unconfident_hard_list_is_a_ticket_correction():
    inputs = {
        "photo_filename": "p.jpg",
        "manifest_text": "Waste: RDF. Declared weight: 10,000 kg",
        "weight_kg": 14000.0,
    }
    vlm = {"detected": {"contamination": "possible metal", "moisture": 0.1,
                        "hard_contaminants": ["metal"], "light_contaminants": []},
           "confidence": 0.45}
    verdict, steps = _decide_and_steps(inputs, vlm, {"confidence": 0.9})
    assert verdict == D.ESCALATE_HUMAN  # a weight gap never rejects
    assert not any(r.startswith("SOP-RDF-4.1") or r.startswith("SOP-RDF-4.2") for r in _refs(steps))
    # The metal listed below the bar is checked by hand first (SOP 5.2).
    assert _refs(steps) == ["SOP-RDF-5.2", "SOP-RDF-3.2", "SOP-RDF-3.3"]
    assert steps[0]["text"].startswith("Hard item listed below the confidence bar")


def test_declared_sorted_metal_from_real_decide_gets_breach_notice():
    inputs = {
        "photo_filename": "p.jpg",
        "manifest_text": "SURAT JALAN 007842",
        "waybill_fields": {"load_type": "RDF fluff", "net_kg": 16340},
        "weight_kg": 16340.0,
    }
    vlm = {"detected": {"contamination": "steel pipe", "moisture": 0.2,
                        "hard_contaminants": ["metal"], "light_contaminants": []},
           "confidence": 0.85}
    verdict, steps = _decide_and_steps(inputs, vlm, {"confidence": 0.9})
    assert verdict == D.REJECT
    assert _refs(steps) == ["SOP-RDF-4.1", "SOP-RDF-4.2", "SOP-RDF-4.3", "SOP-RDF-4.5"]


def test_wetter_than_declared_from_real_decide_gets_grab_sample():
    inputs = {
        "photo_filename": "p.jpg",
        "manifest_text": "SURAT JALAN 007842",
        "waybill_fields": {"load_type": "RDF fluff", "moisture_pct": 28},
    }
    vlm = {"detected": {"contamination": "none", "moisture": 0.45,
                        "hard_contaminants": [], "light_contaminants": []},
           "confidence": 0.85}
    verdict, steps = _decide_and_steps(inputs, vlm, {"confidence": 0.9})
    assert verdict == D.ESCALATE_HUMAN
    assert _refs(steps) == ["SOP-RDF-5.1", "SOP-RDF-5.3", "SOP-RDF-3.3", "SOP-RDF-5.2"]


def test_confident_hard_contaminants_unit():
    vlm = {"detected": {"contamination": "tire and rock",
                        "hard_contaminants": ["tire", "rock"]}, "confidence": 0.6}
    assert decision.confident_hard_contaminants({}, vlm, {}) == ["rock", "tire"]
    vlm["confidence"] = 0.59
    assert decision.confident_hard_contaminants({}, vlm, {}) == []
    assert decision.confident_hard_contaminants(
        {"manifest_text": "contains Metal"}, {"detected": {}, "confidence": 0.9}, {}
    ) == []
    assert decision.confident_hard_contaminants(None, None, None) == []


# ---------------------------------------------------------------------------
# Wave 2: plate (R3), photo quality (R2), vote split (R1), sampling reason
# ---------------------------------------------------------------------------

_WAVE2_INPUTS = {
    "photo_filename": "p.jpg",
    "manifest_text": "SURAT JALAN 007842",
    "weight_kg": 16340.0,
    "waybill_fields": {"plate": "B 9723 KXW", "net_kg": 16340, "load_type": "RDF fluff"},
}
_CLEAN_VLM = {"detected": {"contamination": "none", "moisture": 0.2,
                           "hard_contaminants": [], "light_contaminants": []},
              "confidence": 0.85}


def _obs(kind, status, value=None, note=None):
    return {"kind": kind, "status": status, "value": value, "note": note}


def test_plate_mismatch_from_real_decide_verifies_the_truck_first():
    inputs = dict(_WAVE2_INPUTS, observations=[_obs("plate", "mismatch", "B 9406 KXW")])
    verdict, steps = _decide_and_steps(inputs, _CLEAN_VLM, None)
    assert verdict == D.ESCALATE_HUMAN
    assert steps[0]["text"] == (
        "Plate does not match the waybill: verify the truck and its papers first.")
    # The weight itself is fine: no ticket-correction rows.
    assert _refs(steps) == ["SOP-RDF-3.3", "SOP-RDF-5.2"]


def test_plate_mismatch_and_weight_gap_keep_the_ticket_correction():
    inputs = dict(_WAVE2_INPUTS, weight_kg=20000.0,
                  observations=[_obs("plate", "mismatch", "B 9406 KXW")])
    verdict, steps = _decide_and_steps(inputs, _CLEAN_VLM, None)
    assert verdict == D.ESCALATE_HUMAN
    assert _refs(steps) == ["SOP-RDF-3.3", "SOP-RDF-3.2", "SOP-RDF-5.2"]


def test_plate_mismatch_on_a_reject_follows_the_do_not_tip_rows():
    inputs = dict(_WAVE2_INPUTS, observations=[_obs("plate", "mismatch", "B 9406 KXW")])
    vlm = {**_CLEAN_VLM, "detected": {**_CLEAN_VLM["detected"], "hard_contaminants": ["metal"]}}
    verdict, steps = _decide_and_steps(inputs, vlm, None)
    assert verdict == D.REJECT
    assert _refs(steps) == ["SOP-RDF-4.1", "SOP-RDF-4.2", "SOP-RDF-4.3", "SOP-RDF-4.5",
                            "SOP-RDF-3.3"]


def test_poor_photo_from_real_decide_retakes():
    inputs = dict(_WAVE2_INPUTS, observations=[_obs("image_quality", "poor", note="Blurred.")])
    verdict, steps = _decide_and_steps(inputs, _CLEAN_VLM, None)
    assert verdict == D.ESCALATE_HUMAN
    assert steps[0] == {"order": 1, "sop_ref": "SOP-RDF-2.1",
                        "text": "Photo quality poor: retake the load photo from the top platform."}


def test_vote_split_from_real_decide_is_a_hand_check():
    vlm = {**_CLEAN_VLM, "votes": [{"hard": ["metal"]}, {"hard": []}, {"hard": []}]}
    verdict, steps = _decide_and_steps(dict(_WAVE2_INPUTS), vlm, None)
    assert verdict == D.ESCALATE_HUMAN
    assert _texts(steps) == [(
        "Vision reads disagree on a hard item: the supervisor checks the load by hand and "
        "records the call.")]
    assert _refs(steps) == ["SOP-RDF-5.2"]


def test_unchecked_early_majority_from_real_decide_is_a_hand_check():
    vlm = {**_CLEAN_VLM, "votes": [{"hard": []}, {"hard": []}], "third_read": "late"}
    verdict, steps = _decide_and_steps(dict(_WAVE2_INPUTS), vlm, None)
    assert verdict == D.ESCALATE_HUMAN
    assert _texts(steps) == [(
        "Vision decided on two of three reads with no second look: the supervisor checks "
        "the load by hand and records the call.")]


def test_lab_sample_step_quotes_the_sampling_reason():
    reason = "Declared moisture 28 % is above the 20 % spec."
    steps = actions.next_steps(D.ACCEPT, _gates(), _detected(), [],
                               sampling={"sample_this_truck": True, "reason": reason})
    assert steps[-1] == {
        "order": 2, "sop_ref": "SOP-RDF-5.4",
        "text": "Take a lab sample as the load is tipped (moisture, NCV, chlorine): " + reason}
