"""The product-win decision rules (plan section 4) in ``decision.decide``.

Only a confident hard contaminant rejects.  An unreadable photo, a weight
gap, an uncertain waybill read, a wetter-than-declared load and broken
waybill arithmetic all hold the truck for a person; the LLM's own
cross-check never moves the verdict; the gas gate needs a live sensor.
"""

from __future__ import annotations

import pytest

from lynceus import audit, decision, gas_ingest

D = audit.Decision
G = audit.GateState

#: The demo waybill (plan "Demo waybill"), as the operator confirms it.
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


def _inputs(**over):
    base = {
        "photo_base64": "x",
        "manifest_text": "SURAT JALAN 007842 | Plate B 9723 KXW",
        "weight_kg": 16340.0,
        "declared_weight_kg": 16340.0,
        "waybill_fields": dict(WAYBILL),
        "waybill_read": {"confidence": 0.88, "model": "m", "provenance": "live",
                         "latency_ms": 6100.0, "edited_fields": []},
    }
    base.update(over)
    return base


def _vlm(hard=(), light=(), confidence=0.85, moisture=0.25):
    return {
        "detected": {"contamination": "mixed fluff", "moisture": moisture,
                     "hard_contaminants": list(hard), "light_contaminants": list(light)},
        "confidence": confidence,
    }


_LLM = {"confidence": 0.9, "crosscheck_failed": False}


def _decide(inputs=None, vlm=None, llm=_LLM, engine=ENGINE, detector=None):
    return decision.decide(inputs or _inputs(), vlm or _vlm(), llm, engine, detector)


def test_clean_demo_truck_accepts_with_every_gate_stated():
    verdict, gates, reasons = _decide()
    assert verdict == D.ACCEPT
    assert gates["vlm_confidence"]["state"] == G.PASSED
    assert gates["ocr_confidence"] == {
        "state": G.PASSED, "value": 0.88, "threshold": 0.6,
        "reason": "Waybill read confidence 0.88.",
    }
    assert gates["manifest_crosscheck"]["state"] == G.PASSED
    assert "gross - tare = net" in gates["manifest_crosscheck"]["reason"]
    assert gates["weight_plausibility"]["state"] == G.PASSED
    assert gates["weight_plausibility"]["threshold"] == 0.05
    assert gates["gas_plausibility"] == {
        "state": G.NOT_RUN, "value": None, "threshold": None,
        "reason": "No gas sensor at this gate.",
    }
    assert reasons[0].startswith("No red flags")


# ---------------------------------------------------------------------------
# Reject: only a confident hard contaminant (0.6 bar unchanged)
# ---------------------------------------------------------------------------


def test_threshold_constants():
    assert decision.HARD_CONTAMINANT_CONFIDENCE == 0.6
    assert decision.WEIGHT_TOLERANCE == 0.05
    assert decision.WEIGHT_MISMATCH_THRESHOLD == decision.WEIGHT_TOLERANCE
    assert decision.UNSAFE_VLM_CONFIDENCE == 0.3
    assert decision.WAYBILL_READ_MIN_CONFIDENCE == 0.6


@pytest.mark.parametrize("confidence,expected", [(0.6, D.REJECT), (0.59, D.ACCEPT)])
def test_confident_hard_contaminant_still_rejects_at_0_6(confidence, expected):
    plain = _inputs(waybill_fields={}, waybill_read=None)
    assert _decide(plain, _vlm(hard=["metal"], confidence=confidence))[0] == expected


def test_declared_sorted_rdf_with_metal_fails_declaration_and_adds_breach():
    verdict, gates, reasons = _decide(vlm=_vlm(hard=["metal"]))
    assert verdict == D.REJECT
    gate = gates["manifest_crosscheck"]
    assert gate["state"] == G.FAILED
    assert gate["reason"].startswith(
        "Waybill declares sorted RDF (RDF fluff); the camera sees metal.")
    assert reasons[0] == "Hard contamination detected in the load: metal (VLM confidence 0.85)."
    assert reasons[1].startswith("Contract breach:")
    assert "supplier notice" in reasons[1]


def test_processed_rdf_declared_by_remarks_only():
    fields = {"load_type": "campuran", "remarks": "hasil proses pemilahan"}
    assert decision.declares_processed_rdf(fields)
    assert not decision.declares_processed_rdf({"load_type": "sampah campuran"})
    assert not decision.declares_processed_rdf(None)
    _, gates, _ = _decide(_inputs(waybill_fields=fields), _vlm(hard=["tire"]))
    assert "declares sorted RDF (campuran)" in gates["manifest_crosscheck"]["reason"]


def test_undeclared_load_with_metal_rejects_without_breach():
    verdict, gates, reasons = _decide(
        _inputs(waybill_fields={"load_type": "sampah campuran", "net_kg": 16340}),
        _vlm(hard=["metal"]))
    assert verdict == D.REJECT
    assert gates["manifest_crosscheck"]["state"] == G.NOT_EVALUATED
    assert not any("Contract breach" in r for r in reasons)


# ---------------------------------------------------------------------------
# Escalate, never reject
# ---------------------------------------------------------------------------


def test_low_vlm_confidence_escalates_retake_never_rejects():
    verdict, gates, reasons = _decide(vlm=_vlm(confidence=0.2))
    assert verdict == D.ESCALATE_HUMAN
    assert gates["vlm_confidence"]["state"] == G.FAILED
    assert "retake" in gates["vlm_confidence"]["reason"]
    assert reasons[0] == (
        "Photo unreadable: VLM confidence 0.20 is below the safe minimum of 0.30; "
        "retake the photo.")


@pytest.mark.parametrize("scale,state", [
    (16340 + 817.0, G.PASSED),   # exactly 5.0 %: at the tolerance
    (16340 * 0.951, G.PASSED),
    (16340 * 1.072, G.FAILED),   # the B 9118 TRQ demo scenario
    (16340 * 0.80, G.FAILED),
])
def test_weight_tolerance_5_percent(scale, state):
    verdict, gates, reasons = _decide(_inputs(weight_kg=scale))
    assert gates["weight_plausibility"]["state"] == state
    if state == G.FAILED:
        assert verdict == D.ESCALATE_HUMAN
        assert reasons[0].startswith("Ticket correction: the weighbridge reads")
        assert "re-weigh or correct the waybill" in reasons[0]
    else:
        assert verdict == D.ACCEPT


def test_weight_gap_signed_in_the_reason():
    _, gates, reasons = _decide(_inputs(weight_kg=17516.0))
    assert "+7.2%" in gates["weight_plausibility"]["reason"]
    assert "(+7.2%, tolerance 5%)" in reasons[0]
    assert gates["weight_plausibility"]["value"] == pytest.approx(0.072, abs=1e-3)


def test_declared_weight_falls_back_to_the_waybill_net():
    inputs = _inputs(weight_kg=20000.0)
    del inputs["declared_weight_kg"]
    verdict, gates, _ = _decide(inputs)
    assert verdict == D.ESCALATE_HUMAN
    assert gates["weight_plausibility"]["state"] == G.FAILED
    assert "16,340 kg" in gates["weight_plausibility"]["reason"]


def test_typed_waybill_declared_weight_still_parsed():
    inputs = {"photo_base64": "x", "manifest_text": "Declared weight: 5,200 kg",
              "weight_kg": 5800}
    verdict, gates, _ = _decide(inputs)
    assert gates["weight_plausibility"]["state"] == G.FAILED
    assert verdict == D.ESCALATE_HUMAN


def test_weight_gap_with_confident_metal_still_rejects():
    verdict, gates, reasons = _decide(_inputs(weight_kg=25000.0), _vlm(hard=["metal"]))
    assert verdict == D.REJECT
    assert gates["weight_plausibility"]["state"] == G.FAILED
    assert not any("Ticket correction" in r for r in reasons)


def test_llm_crosscheck_failed_no_longer_moves_the_verdict():
    llm = {"confidence": 0.4, "crosscheck_failed": True, "crosscheck_notes": "vague"}
    verdict, gates, reasons = _decide(llm=llm)
    assert verdict == D.ACCEPT
    assert gates["manifest_crosscheck"]["state"] == G.PASSED
    assert not any("cross-check" in r for r in reasons)
    # Not even without a waybill read: a typed manifest with nothing declared.
    plain = {"photo_base64": "x", "manifest_text": "Mixed RDF feedstock.", "weight_kg": 5200,
             "declared_weight_kg": 5200}
    verdict, gates, _ = _decide(plain, llm=llm)
    assert verdict == D.ACCEPT
    assert gates["manifest_crosscheck"]["state"] == G.NOT_EVALUATED


def test_uncertain_waybill_read_escalates_check_fields():
    read = {"confidence": 0.55, "edited_fields": ["net_kg"]}
    verdict, gates, reasons = _decide(_inputs(waybill_read=read))
    assert verdict == D.ESCALATE_HUMAN
    gate = gates["ocr_confidence"]
    assert (gate["state"], gate["value"], gate["threshold"]) == (G.FAILED, 0.55, 0.6)
    assert "check the fields" in gate["reason"] and "Operator edited: net_kg." in gate["reason"]
    assert reasons == ["Waybill read uncertain (confidence 0.55): check the fields."]


def test_waybill_read_at_0_6_passes():
    verdict, gates, _ = _decide(_inputs(waybill_read={"confidence": 0.6}))
    assert verdict == D.ACCEPT and gates["ocr_confidence"]["state"] == G.PASSED


def test_typed_waybill_ocr_gate_not_run():
    verdict, gates, _ = _decide(_inputs(waybill_read=None))
    assert gates["ocr_confidence"]["state"] == G.NOT_RUN
    assert gates["ocr_confidence"]["reason"] == "No waybill photo; fields typed by the operator."
    assert verdict == D.ACCEPT


def test_waybill_read_without_confidence_is_not_evaluated():
    _, gates, _ = _decide(_inputs(waybill_read={"model": "m"}))
    assert gates["ocr_confidence"]["state"] == G.NOT_EVALUATED


@pytest.mark.parametrize("visual,expected", [
    (0.43, D.ESCALATE_HUMAN),  # declared 28 % + 15 points
    (0.60, D.ESCALATE_HUMAN),
    (0.42, D.ACCEPT),
    (0.10, D.ACCEPT),          # drier than declared is no conflict
])
def test_wetter_than_declared_moisture(visual, expected):
    verdict, gates, reasons = _decide(vlm=_vlm(moisture=visual))
    assert verdict == expected
    gate = gates["manifest_crosscheck"]
    if expected == D.ESCALATE_HUMAN:
        assert gate["state"] == G.FAILED
        assert gate["reason"].startswith("Moisture conflict: the waybill declares 28% moisture")
        assert reasons == ["Load looks wetter than the declared 28%: take a grab sample."]
    else:
        assert gate["state"] == G.PASSED
        assert "declared moisture 28%" in gate["reason"]


def test_moisture_field_as_numeric_string():
    fields = dict(WAYBILL, moisture_pct="28 %")
    verdict, _, _ = _decide(_inputs(waybill_fields=fields), _vlm(moisture=0.5))
    assert verdict == D.ESCALATE_HUMAN


def test_typed_text_dry_claim_rule_kept():
    typed = {"photo_base64": "x", "manifest_text": "Moisture declared: 10% (dry)"}
    verdict, gates, reasons = _decide(typed, _vlm(moisture=0.16))
    assert verdict == D.ESCALATE_HUMAN
    assert gates["manifest_crosscheck"]["reason"].startswith(
        "Moisture conflict: the waybill declares a dry load")
    assert reasons == ["The visual moisture estimate conflicts with the waybill's dry claim."]
    verdict, gates, _ = _decide(typed, _vlm(moisture=0.12))
    assert verdict == D.ACCEPT and gates["manifest_crosscheck"]["state"] == G.PASSED


@pytest.mark.parametrize("net,expected", [
    (16340, D.ACCEPT),
    (16340 + 163, D.ACCEPT),       # within 1 % of net
    (16340 + 400, D.ESCALATE_HUMAN),
    (15000, D.ESCALATE_HUMAN),
])
def test_waybill_arithmetic(net, expected):
    fields = dict(WAYBILL, net_kg=net)
    verdict, gates, reasons = _decide(_inputs(waybill_fields=fields, declared_weight_kg=net,
                                              weight_kg=net))
    assert verdict == expected
    if expected == D.ESCALATE_HUMAN:
        assert gates["manifest_crosscheck"]["state"] == G.FAILED
        assert gates["manifest_crosscheck"]["reason"].startswith("Waybill arithmetic: gross")
        assert reasons[-1].startswith("Waybill arithmetic does not add up")


def test_nothing_declared_is_not_evaluated():
    _, gates, _ = _decide(_inputs(waybill_fields={"plate": "B 1 X"}))
    gate = gates["manifest_crosscheck"]
    assert gate["state"] == G.NOT_EVALUATED
    assert gate["reason"].startswith("Nothing declared on the waybill")


def test_escalate_reasons_in_stated_order():
    fields = dict(WAYBILL, net_kg=10000)  # arithmetic off too
    inputs = _inputs(waybill_fields=fields, weight_kg=20000.0,
                     waybill_read={"confidence": 0.3})
    verdict, _, reasons = _decide(inputs, _vlm(confidence=0.25, moisture=0.9, light=["glass"]))
    assert verdict == D.ESCALATE_HUMAN
    assert [r.split(" ")[0] for r in reasons] == [
        "Photo", "Ticket", "Waybill", "Load", "Waybill", "Light"]


# ---------------------------------------------------------------------------
# Gas: a live sensor only
# ---------------------------------------------------------------------------


def test_gas_gate_runs_only_on_a_live_sensor():
    live = {"readings_ppm": {"ch4": 54.0}, "source": gas_ingest.LIVE_GAS_SOURCE}
    _, gates, _ = _decide(_inputs(gas=live))
    assert gates["gas_plausibility"]["state"] == G.PASSED
    twin = {"readings_ppm": {"ch4": 54.0}, "source": "digital_twin"}
    _, gates, _ = _decide(_inputs(gas=twin))
    assert gates["gas_plausibility"]["reason"] == "No gas sensor at this gate."


# ---------------------------------------------------------------------------
# Detector disagreement wording
# ---------------------------------------------------------------------------


def _det(*boxes):
    from lynceus import detector

    return detector.summarize(
        [{"label": label, "confidence": conf, "box": [0.1, 0.1, 0.5, 0.5]}
         for label, conf in boxes],
        5.0, decision.DETECTOR_HARD_CONFIDENCE, decision.DETECTOR_LIGHT_CONFIDENCE,
    )


def test_detector_missing_a_confident_vision_finding_keeps_the_reject():
    verdict, gates, _ = _decide(vlm=_vlm(hard=["metal"]), detector=_det(("paper", 0.9)))
    assert verdict == D.REJECT
    gate = gates["detector_second_opinion"]
    assert gate["state"] == G.PASSED
    assert gate["reason"].startswith(
        "Second look did not find it; the vision finding stands (the detector is trained "
        "on close-ups, not truck beds).")
    assert "did not flag metal" in gate["reason"]


def test_detector_agreeing_keeps_the_agree_wording():
    _, gates, _ = _decide(vlm=_vlm(hard=["metal"]), detector=_det(("metal", 0.9)))
    assert "agree" in gates["detector_second_opinion"]["reason"]
    assert decision.DETECTOR_MISSED_MARKER not in gates["detector_second_opinion"]["reason"]


# ---------------------------------------------------------------------------
# Refusal and degraded mode keep working
# ---------------------------------------------------------------------------


def test_refusal_states_the_waybill_read_gate():
    verdict, gates, _ = decision.decide(
        {"manifest_text": "x", "waybill_read": {"confidence": 0.9}}, None, None, None)
    assert verdict == D.REFUSE_INSUFFICIENT_INPUT
    assert gates["ocr_confidence"]["state"] == G.NOT_EVALUATED
    assert gates["ocr_confidence"]["value"] == 0.9
    verdict, gates, _ = decision.decide({"manifest_text": "x"}, None, None, None)
    assert gates["ocr_confidence"]["state"] == G.NOT_RUN
    assert sorted(gates["missing"]) == ["photo", "vlm_result"]


def test_decide_degraded_still_holds():
    verdict, gates, _ = decision.decide_degraded(_det(("metal", 0.9)), "ReadTimeout",
                                                 inputs=_inputs())
    assert verdict == D.ESCALATE_HUMAN
    assert gates["detector_second_opinion"]["state"] == G.FAILED
