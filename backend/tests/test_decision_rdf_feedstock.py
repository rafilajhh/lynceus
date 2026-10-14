"""Plastic film and textile are RDF feedstock, not light contaminants.

Policy fix motivated by the 2026-10-13 live benchmark: 26 of 40 clean
paper / cardboard / plastic / textile loads were escalated, almost all on
``plastic_film`` / ``textile`` detections.  Glass, organic residue and wet mix
still escalate; hard contaminants still reject.
"""

import pytest

from lynceus import decision
from lynceus.audit import Decision


def _decide(contamination, light, hard=(), confidence=0.95):
    inputs = {
        "photo_filename": "load.jpg",
        "manifest_text": "Waste type: mixed RDF feedstock load. Declared weight: 5,200 kg",
        "weight_kg": 5200.0,
        "declared_weight_kg": 5200.0,
    }
    vlm = {
        "detected": {
            "contamination": contamination,
            "moisture": 0.05,
            "hard_contaminants": list(hard),
            "light_contaminants": list(light),
        },
        "confidence": confidence,
    }
    return decision.decide(inputs, vlm, {"confidence": 0.9}, None)


def test_plastic_film_and_textile_are_not_light_contaminants():
    assert "plastic_film" not in decision.LIGHT_CONTAMINANTS
    assert "textile" not in decision.LIGHT_CONTAMINANTS
    assert set(decision.LIGHT_CONTAMINANTS) == {"glass", "organic_residue", "wet_mix"}


@pytest.mark.parametrize(
    "contamination, light",
    [
        ("textile strip with frayed edges", ["textile"]),
        ("plastic bottle with blue cap", ["plastic_film"]),
        ("paper and plastic film visible", ["plastic_film", "textile"]),
    ],
)
def test_feedstock_only_load_is_accepted(contamination, light):
    verdict, _, reasons = _decide(contamination, light)
    assert verdict == Decision.ACCEPT
    joined = " ".join(reasons).lower()
    assert "plastic_film" not in joined and "textile" not in joined
    assert "light or ambiguous contamination" not in joined


@pytest.mark.parametrize("light", [["glass"], ["organic_residue"], ["wet_mix"]])
def test_remaining_light_contaminants_still_escalate(light):
    verdict, _, reasons = _decide("visible " + light[0], light)
    assert verdict == Decision.ESCALATE_HUMAN
    assert reasons == [f"Light or ambiguous contamination detected: {light[0]}."]


def test_escalate_reason_names_only_true_contaminants():
    verdict, _, reasons = _decide(
        "plastic film with food residue", ["plastic_film", "textile", "organic_residue"]
    )
    assert verdict == Decision.ESCALATE_HUMAN
    assert reasons == ["Light or ambiguous contamination detected: organic_residue."]


def test_hard_contaminant_still_rejects_alongside_feedstock():
    verdict, _, _ = _decide("metal can among textiles", ["textile"], hard=["metal"])
    assert verdict == Decision.REJECT
