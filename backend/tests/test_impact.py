"""Tests for the measurable-impact layer (lynceus.impact).

Covers: REJECT + hard contaminant → prevented loss > 0 with sourced basis,
ACCEPT → positive RDF load value, ESCALATE without contaminant → combustion
penalty, and determinism (same inputs → identical output).  All figures
must trace to docs/research/realcase-indonesia.md.
"""

from __future__ import annotations

import copy

from lynceus import impact
from lynceus.audit import Decision


def _vlm(hard=None, light=None, moisture=0.14) -> dict:
    return {
        "detected": {
            "contamination": "scripted",
            "moisture": moisture,
            "hard_contaminants": list(hard or []),
            "light_contaminants": list(light or []),
        },
        "confidence": 0.85,
    }


# ---------------------------------------------------------------------------
# REJECT + metal → prevented loss > 0, basis carries source URLs.
# ---------------------------------------------------------------------------


def test_reject_with_metal_has_positive_prevented_loss():
    vlm = _vlm(hard=["metal"])
    out = impact.estimate_prevented_loss("reject", vlm, 5200.0)
    assert out["prevented_loss_idr"] > 0
    assert out["prevented_loss_usd"] > 0
    # Shredder Rp 350 juta + 1 h downtime US$28k × Rp 16.000 = Rp 350jt + 448jt
    expected = impact.SHREDDER_COST_IDR + 28_000.0 * impact.USD_IDR_RATE
    assert out["prevented_loss_idr"] == round(expected)
    assert out["prevented_loss_usd"] == round(expected / impact.USD_IDR_RATE)


def test_reject_basis_rows_have_source_urls():
    vlm = _vlm(hard=["metal"])
    out = impact.estimate_prevented_loss("reject", vlm, 5200.0)
    assert len(out["basis"]) >= 2
    for row in out["basis"]:
        assert row["source_url"], row
        assert row["label"]
        assert row["value"]
    urls = " ".join(row["source_url"] for row in out["basis"])
    assert "https://" in urls
    # The two headline research numbers must be attributed.
    assert "rdiglobal" in urls          # shredder Rp 350 juta (RDI Lampiran 2)
    assert "oxmaint" in urls            # kiln downtime US$28k/jam


def test_reject_without_hard_contaminant_reports_zero():
    # A reject driven e.g. by weight mismatch alone has no impact number.
    out = impact.estimate_prevented_loss("reject", _vlm(), 5200.0)
    assert out["prevented_loss_idr"] == 0
    assert "note" in out


# ---------------------------------------------------------------------------
# ACCEPT → positive RDF load value (Rp 300–450rb/ton × tonnage).
# ---------------------------------------------------------------------------


def test_accept_gives_positive_rdf_value():
    out = impact.estimate_prevented_loss("accept", _vlm(), 5200.0)
    assert out["prevented_loss_idr"] > 0
    low = 5.2 * 300_000
    high = 5.2 * 450_000
    assert low <= out["prevented_loss_idr"] <= high
    assert out["prevented_loss_usd"] == round(
        out["prevented_loss_idr"] / impact.USD_IDR_RATE
    )
    assert any("asi.or.id" in r["source_url"] or "switch-asia" in r["source_url"]
               for r in out["basis"])


def test_accept_defaults_weight_to_arm_roll_trip():
    out = impact.estimate_prevented_loss("accept", _vlm(), None)
    assert out["prevented_loss_idr"] == round(5.2 * impact.RDF_PRICE_IDR_PER_TONNE)
    # The defaulted weight is disclosed in the basis with its own source.
    assert any("arm roll" in r["label"].lower() for r in out["basis"])


# ---------------------------------------------------------------------------
# ESCALATE without contaminant → combustion-efficiency penalty.
# ---------------------------------------------------------------------------


def test_escalate_without_contaminant_prices_combustion_penalty():
    vlm = _vlm(light=["wet_mix"], moisture=0.55)
    out = impact.estimate_prevented_loss("escalate_human", vlm, 5200.0)
    assert out["prevented_loss_idr"] > 0
    # Water mass × latent heat → MJ → RDF-equivalent tonnes × price.
    water_kg = 5200.0 * 0.55
    energy_mj = water_kg * impact.WATER_LATENT_HEAT_MJ_PER_KG
    rdf_eq_t = energy_mj / (impact.RDF_CALORIFIC_MJ_PER_KG * 1000.0)
    assert out["prevented_loss_idr"] == round(rdf_eq_t * impact.RDF_PRICE_IDR_PER_TONNE)
    assert out["prevented_loss_usd"] > 0
    urls = " ".join(r["source_url"] for r in out["basis"])
    assert "switch-asia" in urls  # RDF calorific value source


def test_escalate_without_moisture_reports_zero_honestly():
    vlm = _vlm(light=["plastic_film"], moisture=None)
    out = impact.estimate_prevented_loss("escalate_human", vlm, 5200.0)
    assert out["prevented_loss_idr"] == 0
    assert "cannot be estimated" in out["note"]


def test_refuse_insufficient_input_never_invents_a_number():
    out = impact.estimate_prevented_loss("refuse_insufficient_input", None, None)
    assert out["prevented_loss_idr"] == 0
    assert out["prevented_loss_usd"] == 0
    assert out["note"]


# ---------------------------------------------------------------------------
# Determinism: identical inputs → identical output.
# ---------------------------------------------------------------------------


def test_deterministic_output():
    cases = [
        ("reject", _vlm(hard=["metal"]), 5200.0),
        ("escalate_human", _vlm(light=["wet_mix"], moisture=0.55), 7400.0),
        ("accept", _vlm(), 5200.0),
    ]
    for verdict, vlm, weight in cases:
        first = impact.estimate_prevented_loss(verdict, vlm, weight)
        second = impact.estimate_prevented_loss(
            verdict, copy.deepcopy(vlm), weight
        )
        assert first == second, verdict


# ---------------------------------------------------------------------------
# Presentation language: notes and basis labels are English (finding 3 —
# Indonesian stays only in cited source names/places, never in UI copy).
# ---------------------------------------------------------------------------


def test_notes_and_labels_are_english_not_indonesian():
    cases = [
        ("reject", _vlm(hard=["metal"]), 5200.0),
        ("escalate_human", _vlm(light=["wet_mix"], moisture=0.55), 5200.0),
        ("escalate_human", _vlm(light=["plastic_film"], moisture=None), 5200.0),
        ("accept", _vlm(), 5200.0),
        ("accept", _vlm(), None),  # exercises the defaulted-weight basis row
        ("refuse_insufficient_input", None, None),
    ]
    indonesian_markers = (
        "dengan", "yang", "tidak", "adalah", "diteruskan", "muatan",
        "kadar air", "kerugian", "jam ", " ton ", "ribu", "dicegah",
        "konservatif", "harga", "nilai",
    )
    for verdict, vlm, weight in cases:
        out = impact.estimate_prevented_loss(verdict, vlm, weight)
        blob = out["note"] + " " + " ".join(
            f"{row['label']} {row['value']}" for row in out["basis"]
        ).lower()
        for marker in indonesian_markers:
            assert marker not in blob.lower(), (verdict, marker, blob)
