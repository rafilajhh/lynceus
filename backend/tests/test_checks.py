"""Operator checks and the "why" sentence (lynceus.checks, plan section 5).

Each scenario runs the real ``decision.decide`` and reads the outcome in
both shapes the checks accept: an ``/inspect`` response dict and an audit
record ``model_dump()``.  Older records (LLM cross-check, gas twin, no
waybill fields) must still read sensibly.
"""

from __future__ import annotations

import copy

import pytest

from lynceus import audit, checks, decision, detector

D = audit.Decision

WAYBILL = {
    "document_no": "007842", "plate": "B 9723 KXW", "date": "2025-05-14",
    "origin": "TPST Bantargebang, Bekasi", "destination": "PLTSa Rorotan, Jakarta Utara",
    "carrier": "PT. Hijau Lestari Transport", "shipper": "TPST Bantargebang",
    "driver": "Slamet Riyadi", "reference_no": "DO-250514-0198",
    "gross_kg": 32580, "tare_kg": 16240, "net_kg": 16340, "load_type": "RDF fluff",
    "moisture_pct": 28,
    "remarks": "Muatan RDF fluff dari hasil proses pemilahan sampah. Pastikan terpal tertutup.",
}
ENGINE = {"recommendation": {"actionable": True, "route": "rdf", "tied": False}}
KEYS = ["vision", "second_look", "waybill_read", "declaration", "weight", "supplier"]


def _inputs(**over):
    base = {
        "photo_base64": "x",
        "manifest_text": "SURAT JALAN 007842",
        "weight_kg": 16340.0,
        "declared_weight_kg": 16340.0,
        "supplier": "PT. Hijau Lestari Transport",
        "waybill_fields": dict(WAYBILL),
        "waybill_read": {"confidence": 0.88, "edited_fields": []},
        "weight_source": "weighbridge_simulated",
    }
    base.update(over)
    return base


def _vlm(hard=(), light=(), confidence=0.85, moisture=0.25):
    return {
        "detected": {"contamination": "mixed fluff", "moisture": moisture,
                     "hard_contaminants": list(hard), "light_contaminants": list(light)},
        "confidence": confidence,
    }


def _det(*boxes):
    return detector.summarize(
        [{"label": label, "confidence": conf, "box": [0.1, 0.1, 0.5, 0.5]}
         for label, conf in boxes],
        5.0, decision.DETECTOR_HARD_CONFIDENCE, decision.DETECTOR_LIGHT_CONFIDENCE,
    )


def _response(inputs=None, vlm=None, det=None, engine=ENGINE, **extra):
    """An /inspect-like response from the real decide()."""
    inputs = inputs if inputs is not None else _inputs()
    vlm = vlm or _vlm()
    verdict, gates, reasons = decision.decide(inputs, vlm, {"confidence": 0.9}, engine, det)
    return {
        "verdict": {"decision": verdict},
        "gates": gates,
        "reasons": reasons,
        "ai_outputs": {"vlm": vlm, "detector": det},
        "inputs": inputs,
        **extra,
    }


def _as_record(response):
    """The same inspection in the audit record ``model_dump()`` shape."""
    inputs = response["inputs"]
    read = inputs.get("waybill_read")
    edited = bool(read and read.get("edited_fields"))
    record_inputs = {
        "truck_id": "B 9723 KXW",
        "supplier": inputs.get("supplier"),
        "manifest_text": {
            "source": ("waybill_photo_ai_read" + ("_operator_edited" if edited else ""))
            if read else "manual_text",
            "raw_text_sha256": "0" * 64,
            "extracted_fields": dict(inputs.get("waybill_fields") or {}),
            "ocr_confidence": read["confidence"] if read else 0.95,
        },
        "weight": {"value_kg": inputs.get("weight_kg") or 0.0,
                   "source": inputs.get("weight_source", "weighbridge"),
                   "measured_at_utc": "2026-10-17T08:00:00Z"},
        "gas": {"readings_ppm": {}, "source": "not_measured",
                "measured_at_utc": "2026-10-17T08:00:00Z"},
    }
    if "observations" in inputs:
        record_inputs["observations"] = inputs["observations"]
    gates = {k: v for k, v in response["gates"].items() if k != "missing"}
    return {
        "format_version": 2,
        "record_id": "inspection-000061",
        "inputs": record_inputs,
        "ai_outputs": {"vlm": {**response["ai_outputs"]["vlm"], "model": "m"},
                       "llm": {"reasoning": "", "confidence": 0.9},
                       "detector": response["ai_outputs"]["detector"]},
        "engine_outputs": {"recommendation": {"missing": list(response["gates"].get("missing") or [])}},
        "verdict": {"decision": response["verdict"]["decision"],
                    "decided_at_utc": "2026-10-17T08:00:00Z"},
        "gates": gates,
    }


def _by_key(result):
    return {c["key"]: c for c in result["checks"]}


def _both(response, profile=None):
    """build_checks on both shapes; the checks and why must be the same (the
    receipt may not: a record keeps the waybill text only as a digest)."""
    a = checks.build_checks(response, profile)
    b = checks.build_checks(_as_record(response), profile)
    assert (a["why"], a["checks"]) == (b["why"], b["checks"])
    return a


# ---------------------------------------------------------------------------
# Shape and invariants
# ---------------------------------------------------------------------------


def test_six_checks_in_order_with_the_contract_shape():
    result = _both(_response())
    assert [c["key"] for c in result["checks"]] == KEYS
    assert [c["label"] for c in result["checks"]] == [
        "Load photo", "Second look", "Waybill read", "Waybill vs load", "Weighbridge",
        "Supplier record"]
    assert [c["gate"] for c in result["checks"]] == [
        "vlm_confidence", "detector_second_opinion", "ocr_confidence",
        "manifest_crosscheck", "weight_plausibility", None]
    for c in result["checks"]:
        extra = {"agreement"} if c["key"] == "vision" else set()
        assert set(c) == {"key", "label", "status", "finding", "detail", "gate"} | extra
        assert c["status"] in {"pass", "warn", "fail", "info", "skipped"}
        assert len(c["finding"]) <= checks.FINDING_MAX


def test_pure_and_deterministic():
    response = _response(vlm=_vlm(hard=["metal"]), det=_det(("paper", 0.9)))
    before = copy.deepcopy(response)
    assert checks.build_checks(response) == checks.build_checks(response)
    assert response == before  # the input is not mutated


@pytest.mark.parametrize("garbage", [{}, None, {"verdict": None, "gates": "x"},
                                     {"verdict": "accept", "ai_outputs": {"vlm": None}}])
def test_robust_to_missing_pieces(garbage):
    result = checks.build_checks(garbage)
    assert [c["key"] for c in result["checks"]] == KEYS
    assert len(result["why"]) <= checks.WHY_MAX


# ---------------------------------------------------------------------------
# The three demo stories
# ---------------------------------------------------------------------------


def test_accept_clean_rdf():
    dry = dict(WAYBILL, moisture_pct=18)
    result = _both(_response(_inputs(waybill_fields=dry), det=_det(("paper", 0.8))))
    c = _by_key(result)
    assert result["why"] == (
        "Clean RDF: nothing hard seen, weight within 5 %, waybill matches the load.")
    assert (c["vision"]["status"], c["vision"]["finding"]) == ("pass", "Nothing hard seen")
    assert (c["second_look"]["status"], c["second_look"]["finding"]) == ("pass", "Agrees")
    assert (c["waybill_read"]["status"], c["waybill_read"]["finding"]) == (
        "pass", "15/15 fields · 0.88")
    assert (c["declaration"]["status"], c["declaration"]["finding"]) == ("pass", "Matches")
    assert (c["weight"]["status"], c["weight"]["finding"]) == ("pass", "+0.0 % vs waybill")
    assert "simulated scale feed" in c["weight"]["detail"]


def test_reject_metal_declared_sorted_never_green_for_the_cause():
    result = _both(_response(vlm=_vlm(hard=["metal"]), det=_det(("paper", 0.9))))
    c = _by_key(result)
    assert result["why"] == (
        "Metal seen in a load declared as sorted RDF: risk to the shredder and kiln. "
        "Do not tip.")
    assert (c["vision"]["status"], c["vision"]["finding"]) == ("fail", "Metal · 0.85")
    assert (c["declaration"]["status"], c["declaration"]["finding"]) == (
        "fail", "Declared sorted · metal")
    # The detector did not see it: info, never a green pass, never a veto.
    assert (c["second_look"]["status"], c["second_look"]["finding"]) == ("info", "Did not see it")
    assert "vision finding stands" in c["second_look"]["detail"]


def test_reject_without_declaration():
    inputs = _inputs(waybill_fields={"net_kg": 16340}, waybill_read=None)
    result = _both(_response(inputs, _vlm(hard=["metal", "tire"])))
    assert result["why"] == "Metal and tire seen in the load: risk to the shredder and kiln. Do not tip."
    c = _by_key(result)
    assert c["vision"]["finding"] == "Metal, tire · 0.85"
    assert c["declaration"]["status"] == "skipped"
    assert c["second_look"]["status"] == "skipped"  # detector did not run


def test_hold_wetter_than_declared():
    result = _both(_response(vlm=_vlm(moisture=0.5)))
    c = _by_key(result)
    assert result["why"] == (
        "Load looks wetter than the declared 28 %: take a grab sample before tipping.")
    assert (c["declaration"]["status"], c["declaration"]["finding"]) == (
        "fail", "Wetter than declared")


# ---------------------------------------------------------------------------
# Every check status
# ---------------------------------------------------------------------------


def test_vision_unreadable_and_light_and_possible_hard():
    c = _by_key(_both(_response(vlm=_vlm(confidence=0.2))))
    assert (c["vision"]["status"], c["vision"]["finding"]) == ("warn", "Unreadable · retake")
    c = _by_key(_both(_response(vlm=_vlm(light=["glass", "organic_residue"]))))
    assert (c["vision"]["status"], c["vision"]["finding"]) == ("warn", "Glass, organic")
    c = _by_key(_both(_response(vlm=_vlm(hard=["metal"], confidence=0.5))))
    assert (c["vision"]["status"], c["vision"]["finding"]) == ("warn", "Possible metal · 0.50")


def test_second_look_flags_unconfirmed_metal():
    result = _both(_response(det=_det(("metal", 0.41))))
    c = _by_key(result)
    assert (c["second_look"]["status"], c["second_look"]["finding"]) == ("warn", "Flags metal 0.41")
    assert result["why"] == (
        "Second look flags metal the vision model did not confirm: the supervisor checks "
        "the load.")


def test_second_look_light_flag_not_acted_on_is_info():
    response = _response()
    response["gates"]["detector_second_opinion"] = {
        "state": "passed", "value": 0.88, "threshold": 0.5,
        "reason": "Detector (YOLO26m) flagged glass (0.88) that the vision model did not "
                  "report; light detector findings are set not to escalate.",
    }
    c = _by_key(checks.build_checks(response))
    assert (c["second_look"]["status"], c["second_look"]["finding"]) == (
        "info", "Flags glass · not acted on")


def test_waybill_read_warn_and_typed():
    response = _response(_inputs(waybill_read={"confidence": 0.5, "edited_fields": ["net_kg"]}))
    result = checks.build_checks(response)
    c = _by_key(result)
    assert (c["waybill_read"]["status"], c["waybill_read"]["finding"]) == ("warn", "Unsure · 0.50")
    assert "operator edited: net_kg" in c["waybill_read"]["detail"]
    assert result["why"] == (
        "Waybill read is uncertain: check the fields against the paper before tipping.")
    c = _by_key(_both(_response(_inputs(waybill_read=None))))
    assert (c["waybill_read"]["status"], c["waybill_read"]["finding"]) == (
        "skipped", "Typed by operator")


def test_waybill_read_counts_unsure_fields_when_confidences_are_given():
    fields = {k: {"value": v, "confidence": 0.9} for k, v in WAYBILL.items()}
    for name in ("shipper", "remarks", "date"):
        fields[name]["confidence"] = 0.4
    response = _response(_inputs(waybill_read={"confidence": 0.5}))
    response["inputs"]["waybill_fields"] = fields
    c = _by_key(checks.build_checks(response))
    assert c["waybill_read"]["finding"] == "3 fields unsure"
    assert "unsure: date, remarks, shipper" in c["waybill_read"]["detail"]


def test_declaration_arithmetic_and_nothing_declared():
    fields = dict(WAYBILL, net_kg=15000)
    result = _both(_response(_inputs(waybill_fields=fields, declared_weight_kg=15000.0,
                                     weight_kg=15000.0)))
    c = _by_key(result)
    assert (c["declaration"]["status"], c["declaration"]["finding"]) == (
        "fail", "Net does not add up")
    assert result["why"].startswith("Waybill gross minus tare does not give the net")
    # The payload only: a record without a waybill net keeps no declared weight.
    c = _by_key(checks.build_checks(_response(_inputs(waybill_fields={"plate": "B 1 X"}))))
    assert (c["declaration"]["status"], c["declaration"]["finding"]) == (
        "skipped", "Nothing declared")


def test_weight_ticket_correction_and_missing():
    result = _both(_response(_inputs(weight_kg=17516.0)))
    c = _by_key(result)
    assert (c["weight"]["status"], c["weight"]["finding"]) == ("warn", "+7.2 % · correct ticket")
    assert result["why"] == (
        "Scale reads +7.2 % vs the waybill: re-weigh or correct the ticket before tipping.")
    no_scale = _inputs()
    del no_scale["weight_kg"]
    c = _by_key(checks.build_checks(_response(no_scale)))
    assert (c["weight"]["status"], c["weight"]["finding"]) == ("skipped", "No scale reading")
    no_declared = _inputs(waybill_fields={}, waybill_read=None)
    del no_declared["declared_weight_kg"]
    c = _by_key(checks.build_checks(_response(no_declared)))
    assert (c["weight"]["status"], c["weight"]["finding"]) == ("skipped", "No declared weight")


@pytest.mark.parametrize("profile,sampling,status,finding", [
    ({"tier": "low", "sampling": {"every_n": 10, "label": "1 in 10"}, "trucks": 40},
     None, "pass", "Low risk · 1 in 10 sampled"),
    ({"tier": "medium", "sampling": {"every_n": 3}, "trucks": 12},
     {"sample_this_truck": False}, "warn", "Medium risk · 1 in 3 sampled"),
    ({"tier": "medium", "sampling": {"every_n": 3}, "trucks": 11},
     {"sample_this_truck": True}, "warn", "Sample this truck"),
    ({"tier": "high", "sampling": {"every_n": 1}, "trucks": 9},
     None, "warn", "High risk · lab sample"),
    ({"tier": "new", "sampling": {"every_n": 3}, "trucks": 2},
     {"sample_this_truck": True}, "warn", "Sample this truck"),
    ({"tier": "new", "sampling": {"every_n": 3}, "trucks": 1},
     None, "skipped", "New supplier"),
])
def test_supplier_record(profile, sampling, status, finding):
    response = _response(sampling=sampling) if sampling else _response()
    c = _by_key(checks.build_checks(response, profile))
    assert (c["supplier"]["status"], c["supplier"]["finding"]) == (status, finding)
    assert len(c["supplier"]["finding"]) <= checks.FINDING_MAX


def test_supplier_without_profile():
    c = _by_key(_both(_response()))
    assert (c["supplier"]["status"], c["supplier"]["finding"]) == ("skipped", "New supplier")
    assert "PT. Hijau Lestari Transport" in c["supplier"]["detail"]
    nameless = _inputs(waybill_fields={}, waybill_read=None)
    del nameless["supplier"]
    c = _by_key(checks.build_checks(_response(nameless)))
    assert (c["supplier"]["status"], c["supplier"]["finding"]) == ("skipped", "No supplier named")


# ---------------------------------------------------------------------------
# why: refuse, degraded, light, other holds
# ---------------------------------------------------------------------------


def test_why_refuse_names_the_missing_inputs():
    inputs = {"manifest_text": "  "}
    result = _both(_response(inputs))
    assert result["why"] == (
        "Missing photo, waybill: collect it and re-run; no verdict without it.")
    c = _by_key(result)
    assert c["vision"]["status"] == "skipped"


def test_why_degraded_mode():
    verdict, gates, reasons = decision.decide_degraded(_det(("metal", 0.9)), "ReadTimeout",
                                                       inputs=_inputs())
    response = {"verdict": {"decision": verdict}, "gates": gates, "reasons": reasons,
                "ai_outputs": {"vlm": {}, "detector": _det(("metal", 0.9))}, "inputs": _inputs()}
    result = checks.build_checks(response)
    assert result["why"] == (
        "Vision model unavailable; the second look flags metal: inspect the load before "
        "tipping.")
    c = _by_key(result)
    assert c["vision"]["status"] == "skipped"
    assert (c["second_look"]["status"], c["second_look"]["finding"]) == ("warn", "Flags metal 0.90")


def test_why_light_and_retake_and_tie():
    assert checks.build_checks(_response(vlm=_vlm(light=["glass"])))["why"] == (
        "Glass seen in the load: tip to the pre-sort line, not direct feed.")
    assert checks.build_checks(_response(vlm=_vlm(confidence=0.1)))["why"] == (
        "Photo unreadable: retake it from the top platform before deciding.")
    tied = {"recommendation": {"actionable": True, "route": "rdf", "tied": True}}
    assert checks.build_checks(_response(engine=tied))["why"] == (
        "Engine routes tied: the supervisor picks the route before tipping.")


def test_why_unbenchmarked_fallback_with_metal():
    vlm = {**_vlm(hard=["metal"]), "model": "Other-VL", "fallback_from": ["primary: timeout"]}
    response = _response(vlm=vlm)
    assert response["verdict"]["decision"] == D.ESCALATE_HUMAN
    assert checks.build_checks(response)["why"] == (
        "Metal seen by a fallback vision model: the supervisor checks the load before tipping.")


@pytest.mark.parametrize("scenario", [
    {"vlm": _vlm(hard=["metal"])},
    {"vlm": _vlm(moisture=0.6)},
    {"vlm": _vlm(confidence=0.1)},
    {"inputs": _inputs(weight_kg=30000.0)},
    {},
])
def test_why_is_short_and_starts_with_the_cause(scenario):
    result = checks.build_checks(_response(**scenario))
    assert len(result["why"]) <= checks.WHY_MAX
    assert result["why"][0].isupper() and result["why"].endswith(".")


# ---------------------------------------------------------------------------
# Old records (format v1/v2: LLM cross-check, gas twin, no waybill fields)
# ---------------------------------------------------------------------------


def _old_record(decision_, gates, detected, confidence=0.9, weight=19300.0):
    base_gates = {
        "vlm_confidence": {"state": "passed", "value": confidence, "threshold": 0.3,
                           "reason": "VLM confidence within the safe range."},
        "ocr_confidence": {"state": "passed", "value": 0.9, "threshold": None,
                           "reason": "Manifest analysis confidence 0.90."},
        "manifest_crosscheck": {"state": "passed", "value": None, "threshold": None,
                                "reason": "Manifest cross-check passed."},
        "gas_plausibility": {"state": "passed", "value": 54.0, "threshold": 100.0,
                             "reason": "CH4 reading 54 ppm is consistent."},
        "weight_plausibility": {"state": "passed", "value": 0.01, "threshold": 0.1,
                                "reason": "Weighbridge weight is consistent with the declared weight."},
    }
    base_gates.update(gates)
    return {
        "format_version": 1,
        "inputs": {
            "truck_id": "F-7702-TS",
            "manifest_text": {"source": "manual_text", "raw_text_sha256": "0" * 64,
                              "extracted_fields": {}, "ocr_confidence": 0.95},
            "weight": {"value_kg": weight, "source": "weighbridge",
                       "measured_at_utc": "2026-10-12T08:00:00Z"},
            "gas": {"readings_ppm": {"ch4": 54.0}, "source": "digital_twin",
                    "measured_at_utc": "2026-10-12T08:00:00Z"},
        },
        "ai_outputs": {"vlm": {"detected": detected, "confidence": confidence},
                       "llm": {"reasoning": "ok", "confidence": 0.9},
                       "gas": {"source": "digital_twin"}},
        "engine_outputs": {"recommendation": {"missing": []}},
        "verdict": {"decision": decision_},
        "gates": base_gates,
    }


def test_old_reject_by_weight_fails_the_weight_check():
    record = _old_record("reject", {"weight_plausibility": {
        "state": "failed", "value": 0.245, "threshold": 0.1,
        "reason": "Weighbridge weight deviates 24.5% from the declared weight (threshold 10%)."}},
        {"contamination": "none", "hard_contaminants": []})
    result = checks.build_checks(record)
    c = _by_key(result)
    assert (c["weight"]["status"], c["weight"]["finding"]) == ("fail", "24.5 % vs waybill")
    assert c["vision"]["status"] == "pass"  # not the cause
    assert result["why"].startswith("Weight 24.5 % off the waybill (older 10 % rule)")
    assert (c["waybill_read"]["status"], c["waybill_read"]["finding"]) == (
        "skipped", "Typed by operator")
    assert c["supplier"]["finding"] == "No supplier named"


def test_old_reject_by_low_confidence_fails_the_vision_check():
    record = _old_record("reject", {"vlm_confidence": {
        "state": "failed", "value": 0.2, "threshold": 0.3, "reason": "below"}},
        {"contamination": "unclear"}, confidence=0.2)
    result = checks.build_checks(record)
    c = _by_key(result)
    assert (c["vision"]["status"], c["vision"]["finding"]) == ("fail", "Unreadable · retake")
    assert result["why"] == "Photo unreadable (older rule): retake it before deciding."


def test_old_reject_by_prose_is_never_a_green_vision_pass():
    record = _old_record("reject", {}, {"contamination": "a concrete block"})
    result = checks.build_checks(record)
    c = _by_key(result)
    assert c["vision"]["status"] == "fail"
    assert all(ch["status"] != "pass" or ch["key"] != "vision" for ch in result["checks"])
    assert result["why"].startswith("Rejected under an older rule")


def test_old_escalate_by_llm_crosscheck_is_a_warning():
    record = _old_record("escalate_human", {"manifest_crosscheck": {
        "state": "failed", "value": None, "threshold": None,
        "reason": "The manifest cross-check failed on one or more fields."}},
        {"contamination": "none", "hard_contaminants": []})
    result = checks.build_checks(record)
    c = _by_key(result)
    assert (c["declaration"]["status"], c["declaration"]["finding"]) == ("warn", "Fields disagree")
    assert c["second_look"]["status"] == "skipped"  # no detector in old records
    assert result["why"] == (
        "Waybill fields disagree with the load: verify with the driver before tipping.")


def test_old_accept_record():
    record = _old_record("accept", {}, {"contamination": "none", "hard_contaminants": []})
    result = checks.build_checks(record)
    assert result["why"] == (
        "Clean RDF: nothing hard seen, weight within 5 %, waybill matches the load.")
    assert _by_key(result)["weight"]["finding"] == "1.0 % vs waybill"


def test_response_with_embedded_audit_record_reads_its_inputs():
    response = _response(vlm=_vlm(hard=["metal"]))
    embedded = {k: v for k, v in response.items() if k != "inputs"}
    embedded["audit_record"] = _as_record(response)
    a, b = checks.build_checks(embedded), checks.build_checks(response)
    assert (a["why"], a["checks"]) == (b["why"], b["checks"])


# ---------------------------------------------------------------------------
# Wave 2: vote agreement, poor photo, plate, moisture spec, sampling
# ---------------------------------------------------------------------------


def _voted(votes, hard=()):
    return {**_vlm(hard=hard), "votes": [{"hard": list(v), "light": []} for v in votes]}


def _obs(kind, status, value=None, note=None):
    return {"kind": kind, "status": status, "value": value, "note": note, "simulated": True}


def test_load_photo_shows_the_vote_agreement():
    c = _by_key(_both(_response(vlm=_voted([[], [], []]))))
    assert (c["vision"]["status"], c["vision"]["finding"]) == ("pass", "Reads 3/3 agree")
    assert c["vision"]["agreement"] == "Reads 3/3 agree"
    result = _both(_response(vlm=_voted([["metal"], [], []])))
    c = _by_key(result)
    assert (c["vision"]["status"], c["vision"]["finding"]) == ("warn", "Reads split 1/3")
    assert result["why"] == "1 of 3 vision reads saw metal: check the load by hand before tipping."
    assert _by_key(_both(_response()))["vision"]["agreement"] is None


def test_poor_photo_is_on_the_load_photo_tile():
    inputs = _inputs(observations=[_obs("image_quality", "poor", note="Too dark.")])
    result = _both(_response(inputs))
    c = _by_key(result)
    assert (c["vision"]["status"], c["vision"]["finding"]) == ("warn", "Poor photo · retake")
    assert result["why"] == "Photo quality is poor: retake it from the top platform before deciding."
    assert [ch["key"] for ch in result["checks"]] == KEYS  # no new tile


def test_plate_mismatch_is_on_the_weighbridge_tile():
    inputs = _inputs(observations=[_obs("plate", "mismatch", "B 9406 KXW")])
    result = _both(_response(inputs))
    c = _by_key(result)
    assert c["weight"]["status"] == "fail"
    assert c["weight"]["finding"] == "Plate B 9406 KXW ≠ waybill"
    assert len(c["weight"]["finding"]) <= checks.FINDING_MAX
    assert "verify the truck" in c["weight"]["detail"]
    assert result["why"] == (
        "Plate B 9406 KXW does not match the waybill (B 9723 KXW): verify the truck before "
        "tipping.")
    assert [ch["key"] for ch in result["checks"]] == KEYS


def test_declared_moisture_above_spec_warns_and_does_not_hold():
    result = _both(_response(det=_det(("paper", 0.8))))
    assert result["receipt"][-1]["id"] == "accept"
    c = _by_key(result)
    assert (c["declaration"]["status"], c["declaration"]["finding"]) == (
        "warn", "Declared 28 % > 20 % spec")
    assert "priced on the lab sample" in c["declaration"]["detail"]
    assert result["why"] == (
        "Accept for tipping: nothing hard seen; declared moisture 28 % is above the 20 % "
        "spec, so sample it to settle the price.")
    assert len(result["why"]) <= checks.WHY_MAX


def test_wetter_than_declared_outranks_the_spec_warning():
    c = _by_key(_both(_response(vlm=_vlm(moisture=0.5))))
    assert (c["declaration"]["status"], c["declaration"]["finding"]) == (
        "fail", "Wetter than declared")


def test_sampling_argument_or_response_field_sets_the_supplier_warn():
    sampling = {"sample_this_truck": True, "tier": "low", "reason": "Every 10th truck."}
    profile = {"tier": "low", "sampling": {"every_n": 10}, "trucks": 40}
    via_arg = _by_key(checks.build_checks(_response(), profile, sampling))["supplier"]
    via_response = _by_key(checks.build_checks(_response(sampling=sampling), profile))["supplier"]
    assert via_arg == via_response
    assert (via_arg["status"], via_arg["finding"], via_arg["detail"]) == (
        "warn", "Sample this truck", "Every 10th truck.")
    # The argument wins over the response field.
    not_now = checks.build_checks(_response(sampling=sampling), profile,
                                  {"sample_this_truck": False})
    assert _by_key(not_now)["supplier"]["finding"] == "Low risk · 1 in 10 sampled"


@pytest.mark.parametrize("trucks,words", [(1, "1 truck on record"), (2, "2 trucks on record")])
def test_supplier_truck_count_grammar(trucks, words):
    profile = {"tier": "low", "sampling": {"every_n": 10}, "trucks": trucks}
    assert words in _by_key(checks.build_checks(_response(), profile))["supplier"]["detail"]


# ---------------------------------------------------------------------------
# The decision receipt
# ---------------------------------------------------------------------------


def test_receipt_from_the_response_is_passed_through():
    rows = [{"id": "accept", "rule": "r", "fired": True, "evidence": "e", "effect": "accept"}]
    assert checks.build_checks(_response(receipt=rows))["receipt"] == rows


def test_receipt_rebuilt_for_a_live_response_matches_rule_trace():
    inputs, vlm = _inputs(), _vlm(hard=["metal"])
    expected = decision.rule_trace(inputs, vlm, None, ENGINE, None)
    response = _response(inputs, vlm, engine_outputs=ENGINE)
    assert checks.build_checks(response)["receipt"] == expected


def test_receipt_rebuilt_for_a_record_keeps_the_sealed_verdict():
    record = _as_record(_response(vlm=_vlm(hard=["metal"])))
    rows = checks.build_checks(record)["receipt"]
    assert [row["id"] for row in rows] == [rule_id for rule_id, _, _ in decision.RULES]
    assert next(row for row in rows if row["id"] == "hard_contaminant")["fired"]


def test_old_record_receipt_notes_when_todays_rules_disagree():
    record = _old_record("reject", {"weight_plausibility": {
        "state": "failed", "value": 0.245, "threshold": 0.1,
        "reason": "Weighbridge weight deviates 24.5% from the declared weight (threshold 10%)."}},
        {"contamination": "none", "hard_contaminants": []})
    rows = checks.build_checks(record)["receipt"]
    last = rows[-1]
    assert last["id"] == "recorded_verdict"
    assert (last["fired"], last["effect"]) == (True, "reject")
    assert last["evidence"].startswith("Recorded reject; today's rules on the stored outputs give")


def test_degraded_record_receipt_says_the_vision_model_was_unavailable():
    verdict, gates, reasons = decision.decide_degraded(_det(("metal", 0.9)), "ReadTimeout",
                                                       inputs=_inputs())
    response = {"verdict": {"decision": verdict}, "gates": gates, "reasons": reasons,
                "ai_outputs": {"vlm": {}, "detector": _det(("metal", 0.9))}, "inputs": _inputs()}
    last = checks.build_checks(response)["receipt"][-1]
    assert (last["id"], last["effect"]) == ("recorded_verdict", "hold")
    assert "degraded mode: the vision model was unavailable" in last["evidence"]


@pytest.mark.parametrize("third,finding", [
    ("late", "2 of 3 reads (third late)"),
    ("failed", "2 of 3 reads (third failed)"),
    ("arrived", "Reads 2/2 agree"),
    (None, "Reads 2/2 agree"),
])
def test_early_majority_names_the_third_read(third, finding):
    vlm = {**_voted([[], []]), "votes_used": 2, "third_read": third}
    c = _by_key(_both(_response(vlm=vlm)))
    assert (c["vision"]["status"], c["vision"]["finding"]) == ("pass", finding)
    assert len(finding) <= checks.FINDING_MAX


def test_early_majority_third_read_arrived_with_metal_still_holds():
    vlm = {**_voted([[], [], ["metal"]]), "votes_used": 3, "third_read": "arrived"}
    response = _response(vlm=vlm)
    assert response["verdict"]["decision"] == D.ESCALATE_HUMAN
    assert _by_key(_both(response))["vision"]["finding"] == "Reads split 1/3"


@pytest.mark.parametrize("garbage", [{}, None, {"verdict": None, "gates": "x"},
                                     {"verdict": "accept", "ai_outputs": {"vlm": None}},
                                     {"receipt": "x"}])
def test_receipt_is_robust_to_missing_pieces(garbage):
    rows = checks.build_checks(garbage)["receipt"]
    assert isinstance(rows, list) and rows
    assert all(set(row) == {"id", "rule", "fired", "evidence", "effect"} for row in rows)
