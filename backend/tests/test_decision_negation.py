"""Hard rejection uses structured detections, never contaminant prose."""

import pytest

from lynceus import decision
from lynceus.audit import Decision


def _decide(contamination, hard_contaminants, confidence):
    inputs = {
        "photo_filename": "load.jpg",
        "manifest_text": "Waste: RDF. No metal contamination declared.",
        "weight_kg": 5000.0,
        "declared_weight_kg": 5000.0,
    }
    vlm = {
        "detected": {
            "contamination": contamination,
            "hard_contaminants": hard_contaminants,
            "moisture": 0.1,
        },
        "confidence": confidence,
    }
    llm = {"confidence": 0.9, "crosscheck_notes": "No metal found."}
    engine = {"recommendation": {"actionable": True, "tied": False, "route": "rdf"}}
    return decision.decide(inputs, vlm, llm, engine)


def test_negated_metal_prose_does_not_hard_reject():
    verdict, _, reasons = _decide("no metal contamination visible", [], 0.9)
    assert verdict != Decision.REJECT
    assert not any("metal" in reason.lower() for reason in reasons)


def test_structured_metal_at_confidence_threshold_rejects():
    verdict, _, reasons = _decide("metal visible", ["metal"], 0.6)
    assert verdict == Decision.REJECT
    assert "Hard contamination detected in the load: metal" in " ".join(reasons)


def test_structured_metal_below_confidence_threshold_does_not_hard_reject():
    verdict, _, reasons = _decide("possible metal", ["metal"], 0.59)
    assert verdict != Decision.REJECT
    assert not any("metal" in reason.lower() for reason in reasons)


@pytest.mark.parametrize("hard_contaminants", [None, "metal", {"metal": True}, ["no metal", 7, "tyre"]])
def test_invalid_structured_contaminants_do_not_hard_reject(hard_contaminants):
    verdict, _, reasons = _decide("metal visible", hard_contaminants, 0.9)
    assert verdict != Decision.REJECT
    assert not any("metal" in reason.lower() for reason in reasons)
