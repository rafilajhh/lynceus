"""Sealed follow-ups (``lynceus.followups``): chain, tamper evidence, notices."""

from __future__ import annotations

import json
import re

import pytest

from lynceus import audit, followups
from _ops_records import load, write_record

FIELDS = {
    "document_no": "007842", "plate": "B 9723 KXW", "carrier": "PT. Hijau Lestari Transport",
    "net_kg": 16340, "load_type": "RDF fluff", "moisture_pct": 28,
}


@pytest.fixture
def rejected(tmp_path):
    """A completed REJECT: metal in a load declared as sorted RDF."""
    record_id = write_record(
        tmp_path, 1, decision="reject", hard=["metal"], conflict=True,
        supplier="PT. Hijau Lestari Transport", weight_kg=16340, fields=FIELDS,
        sop_refs=("SOP-RDF-4.1", "SOP-RDF-4.5"),
    )
    return tmp_path, record_id


def _file(storage, record_id, name):
    return storage / record_id / followups.FOLLOWUPS_DIRNAME / name


def _rewrite(path, mutate, *, restamp=False):
    data = json.loads(path.read_text(encoding="utf-8"))
    mutate(data)
    if restamp:
        data["digest"] = followups._digest(data)
    path.write_text(json.dumps(data), encoding="utf-8")


# ---------------------------------------------------------------------------
# Chain
# ---------------------------------------------------------------------------


def test_followups_are_sealed_and_hash_chained(rejected):
    storage, record_id = rejected
    parent = load(storage, record_id).digest.record_sha256

    first = followups.append_resolution(storage, record_id, "reject", actor="supervisor", note="Confirmed")
    second = followups.append_lab(storage, record_id, moisture_pct=18, ncv_mj_kg=14,
                                  chlorine_pct=0.5, actor="lab")
    third = followups.append_notice(storage, record_id, actor="procurement", client=None)

    assert [f["seq"] for f in (first, second, third)] == [1, 2, 3]
    assert {f["parent_record_digest"] for f in (first, second, third)} == {parent}
    assert first["previous_digest"] is None
    assert second["previous_digest"] == first["digest"]
    assert third["previous_digest"] == second["digest"]
    assert [first["actor"], second["actor"], third["actor"]] == ["supervisor", "lab", "procurement"]
    assert all(re.fullmatch(r"sha256:[0-9a-f]{64}", f["digest"]) for f in (first, second, third))
    assert sorted(p.name for p in (storage / record_id / "followups").iterdir()) == [
        "001-resolution.json", "002-lab_result.json", "003-notice.json"]

    chain, problems = followups.read_chain(storage, record_id)
    assert problems == []
    assert chain == [first, second, third]
    assert followups.verify_chain(storage, record_id) == {"ok": True, "problems": []}
    # The parent record itself is untouched (a terminal record is never rewritten).
    assert load(storage, record_id).digest.record_sha256 == parent


def test_digest_is_sha256_of_canonical_json_without_digest(rejected):
    storage, record_id = rejected
    sealed = followups.append_resolution(storage, record_id, "reject", actor="s")
    body = {k: v for k, v in sealed.items() if k != "digest"}
    expected = audit.sha256_field(
        json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    assert sealed["digest"] == expected


def test_edit_after_sealing_is_detected_and_blocks_appends(rejected):
    storage, record_id = rejected
    followups.append_resolution(storage, record_id, "reject", actor="s", note="ok")
    _rewrite(_file(storage, record_id, "001-resolution.json"),
             lambda d: d["body"].update(note="changed later"))

    state = followups.verify_chain(storage, record_id)
    assert state["ok"] is False
    assert any("digest mismatch" in p for p in state["problems"])
    with pytest.raises(followups.ChainBroken):
        followups.append_resolution(storage, record_id, "accept", actor="s")


def test_restamped_edit_breaks_the_link_to_the_next_followup(rejected):
    storage, record_id = rejected
    followups.append_resolution(storage, record_id, "reject", actor="s", note="ok")
    followups.append_lab(storage, record_id, moisture_pct=18, ncv_mj_kg=14, chlorine_pct=0.5, actor="s")
    # An editor who recomputes the edited file's own digest still breaks the chain.
    _rewrite(_file(storage, record_id, "001-resolution.json"),
             lambda d: d["body"].update(decision="accept"), restamp=True)
    state = followups.verify_chain(storage, record_id)
    assert state["ok"] is False
    assert any("previous_digest" in p for p in state["problems"])


def test_deleted_followup_is_detected(rejected):
    storage, record_id = rejected
    followups.append_resolution(storage, record_id, "reject", actor="s")
    followups.append_lab(storage, record_id, moisture_pct=18, ncv_mj_kg=14, chlorine_pct=0.5, actor="s")
    _file(storage, record_id, "001-resolution.json").unlink()
    state = followups.verify_chain(storage, record_id)
    assert state["ok"] is False
    assert any("missing" in p for p in state["problems"])


def test_parent_mismatch_is_detected(rejected):
    storage, record_id = rejected
    followups.append_resolution(storage, record_id, "reject", actor="s")
    # Re-seal the inspection record with a different verdict (a valid digest,
    # but not the record the follow-up answered).
    path = storage / record_id / audit.RECORD_FILENAME
    data = json.loads(path.read_text(encoding="utf-8"))
    data["verdict"]["decision"] = "accept"
    audit._stamp_record_digest(data)
    path.write_text(json.dumps(data), encoding="utf-8")

    state = followups.verify_chain(storage, record_id)
    assert state["ok"] is False
    assert any("parent_record_digest" in p for p in state["problems"])


def test_extra_key_is_rejected_by_the_strict_reader(rejected):
    storage, record_id = rejected
    followups.append_resolution(storage, record_id, "reject", actor="s")
    _rewrite(_file(storage, record_id, "001-resolution.json"),
             lambda d: d.update(smuggled=True), restamp=True)
    chain, problems = followups.read_chain(storage, record_id)
    assert chain == []
    assert any("schema" in p for p in problems)


def test_only_completed_records_take_followups(tmp_path):
    record_id = write_record(tmp_path, 1, status="in_progress", decision="escalate_human")
    with pytest.raises(followups.RecordNotCompleted):
        followups.append_resolution(tmp_path, record_id, "accept", actor="s")
    assert not (tmp_path / record_id / "followups").exists()


def test_unknown_and_malformed_record_ids(tmp_path):
    with pytest.raises(followups.RecordNotFound):
        followups.append_resolution(tmp_path, "inspection-000042", "accept", actor="s")
    with pytest.raises(followups.InvalidRecordId):
        followups.append_resolution(tmp_path, "../etc", "accept", actor="s")


def test_bad_body_and_actor_raise_value_error(rejected):
    storage, record_id = rejected
    with pytest.raises(ValueError):
        followups.append_resolution(storage, record_id, "approve", actor="s")
    with pytest.raises(ValueError):
        followups.append_resolution(storage, record_id, "reject", actor="s", note="x" * 501)
    with pytest.raises(ValueError):
        followups.append_resolution(storage, record_id, "reject", actor="  ")
    assert followups.read_chain(storage, record_id) == ([], [])


# ---------------------------------------------------------------------------
# Resolution: agreement with the AI
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("ai, human, agrees", [
    ("reject", "reject", True),
    ("reject", "sort_then_accept", False),
    ("reject", "accept", False),
    ("accept", "accept", True),
    ("accept", "reject", False),
    ("accept", "sort_then_accept", False),
    ("escalate_human", "accept", None),
    ("escalate_human", "reject", None),
    ("refuse_insufficient_input", "retake", None),
])
def test_agrees_with_ai(tmp_path, ai, human, agrees):
    record_id = write_record(tmp_path, 1, decision=ai)
    sealed = followups.append_resolution(tmp_path, record_id, human, actor="s", hand_check_minutes=4)
    assert sealed["body"]["ai_decision"] == ai
    assert sealed["body"]["agrees_with_ai"] is agrees
    assert sealed["body"]["hand_check_minutes"] == 4.0


# ---------------------------------------------------------------------------
# Lab result
# ---------------------------------------------------------------------------


def test_lab_result_carries_the_contract_effect_on_the_weighed_load(rejected):
    storage, record_id = rejected
    sealed = followups.append_lab(storage, record_id, moisture_pct=25, ncv_mj_kg=14,
                                  chlorine_pct=0.5, actor="lab")
    body = sealed["body"]
    assert body["sample_id"] == "S-000001-1"
    assert body["lab"] == "Site laboratory"
    assert body["ash_pct"] is None
    # 16.34 t at Rp 360,000 minus 10 % (5 moisture points) -> deduction 588,240.
    assert body["contract_eval"]["net_t"] == 16.34
    assert body["contract_eval"]["adjusted_price_idr_per_t"] == 324_000
    assert body["contract_eval"]["deduction_idr"] == 588_240
    second = followups.append_lab(storage, record_id, moisture_pct=18, ncv_mj_kg=14,
                                  chlorine_pct=0.5, actor="lab", sample_id="LAB-7", lab="Sucofindo")
    assert (second["body"]["sample_id"], second["body"]["lab"]) == ("LAB-7", "Sucofindo")


# ---------------------------------------------------------------------------
# Notice
# ---------------------------------------------------------------------------


class FakeClient:
    def __init__(self, reply=None, error=None, latency=1234.5):
        self.reply, self.error, self.latency = reply, error, latency
        self.messages = None

    def assist(self, messages, max_tokens=700):
        self.messages = messages
        if self.error:
            raise self.error
        return self.reply, self.latency


def _numbers(text):
    return set(followups._numbers_in(text))


def test_notice_facts_come_from_the_sealed_record(rejected):
    storage, record_id = rejected
    facts = followups.notice_facts(load(storage, record_id), [])
    joined = "\n".join(facts)
    assert f"Inspection record {record_id}" in joined
    assert "Truck B 9723 KXW" in joined
    assert "Supplier PT. Hijau Lestari Transport" in joined
    assert "Waybill 007842 declares RDF fluff at 28 % moisture" in joined
    assert "saw metal on the load (confidence 0.83)" in joined
    assert "Weighbridge net 16,340 kg against 16,340 kg declared (+0.0 %)" in joined
    assert "REJECT" in joined
    assert "Declaration check failed" in joined
    assert "SOP-RDF-4.1, SOP-RDF-4.5" in joined
    assert "Contract breach fee Rp 1,500,000" in joined


def test_template_notice_without_a_client(rejected):
    storage, record_id = rejected
    sealed = followups.append_notice(storage, record_id, actor="s", client=None)
    body = sealed["body"]
    assert body["provenance"] == "template"
    assert body["model"] is None and body["provider"] is None and body["latency_ms"] is None
    assert body["to"] == "PT. Hijau Lestari Transport"
    assert record_id in body["subject"] and "refused" in body["subject"]
    assert record_id in body["text"]
    # The template is grounded by construction.
    assert _numbers(body["subject"] + body["text"]) <= _numbers("\n".join(body["facts"]))


def test_live_notice_when_every_number_is_grounded(rejected):
    storage, record_id = rejected
    text = (f"Truck B 9723 KXW (record {record_id}) declared RDF fluff at 28 % moisture, "
            "but the camera saw metal. The load was refused and a breach fee of "
            "Rp 1,500,000 applies under SOP-RDF-4.5.")
    client = FakeClient({"subject": f"Load refused: {record_id}", "text": text})
    sealed = followups.append_notice(storage, record_id, actor="s", client=client)
    body = sealed["body"]
    assert body["provenance"] == "live"
    assert body["text"] == text
    assert body["model"] and body["provider"]
    assert body["latency_ms"] == 1234.5
    # The prompt carried the facts and nothing else from the record.
    assert "Truck B 9723 KXW" in client.messages[1]["content"]


@pytest.mark.parametrize("reply", [
    {"subject": "Load refused", "text": "Record inspection-000001: fee Rp 2,000,000 applies."},
    {"subject": "Load refused", "text": "Truck B 9723 KXW carried 9 tonnes of metal. inspection-000001"},
    {"subject": "Load refused", "text": "Truck B 9723 KXW carried metal."},  # no record id
    {"subject": "", "text": "inspection-000001"},
    {"text": "inspection-000001"},
    "not a dict",
    None,
])
def test_ungrounded_or_malformed_model_output_falls_back_to_template(rejected, reply):
    storage, record_id = rejected
    sealed = followups.append_notice(storage, record_id, actor="s", client=FakeClient(reply))
    assert sealed["body"]["provenance"] == "template"
    assert sealed["body"]["model"] is None


def test_model_error_falls_back_to_template(rejected):
    storage, record_id = rejected
    sealed = followups.append_notice(
        storage, record_id, actor="s", client=FakeClient(error=RuntimeError("429")))
    assert sealed["body"]["provenance"] == "template"


def test_notice_facts_include_sealed_resolution_and_lab(rejected):
    storage, record_id = rejected
    followups.append_resolution(storage, record_id, "sort_then_accept", actor="s")
    followups.append_lab(storage, record_id, moisture_pct=25, ncv_mj_kg=14, chlorine_pct=0.5, actor="s")
    chain, _ = followups.read_chain(storage, record_id)
    facts = "\n".join(followups.notice_facts(load(storage, record_id), chain))
    assert "Supervisor decision: sort then accept" in facts
    assert "contract deduction Rp 588,240" in facts


# ---------------------------------------------------------------------------
# Ledger row
# ---------------------------------------------------------------------------


def test_ledger_row_counts(rejected):
    storage, record_id = rejected
    followups.append_resolution(storage, record_id, "sort_then_accept", actor="s")
    followups.append_lab(storage, record_id, moisture_pct=25, ncv_mj_kg=14, chlorine_pct=0.9, actor="s")
    followups.append_lab(storage, record_id, moisture_pct=18, ncv_mj_kg=14, chlorine_pct=0.9, actor="s")
    chain, _ = followups.read_chain(storage, record_id)
    row = followups.ledger_row(load(storage, record_id), chain)
    assert row["hard_contaminant_load"] is True
    assert row["declaration_conflict"] is True
    assert row["breach_fee_idr"] == 1_500_000
    assert row["reviewed"] and row["overridden"] and not row["confirmed"]
    assert len(row["labs"]) == 2
    assert row["spec_breach_samples"] == 1  # the chlorine warning alone is not a breach
    assert row["deductions_idr"] == 588_240
    assert row["supplier"] == "PT. Hijau Lestari Transport"
