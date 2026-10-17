"""Example supply contract (``lynceus.contracts``).

Expected prices are worked by hand from the example terms (base Rp 360,000/t;
moisture minus 2 % per point above 20 %; NCV price x actual/12.6; chlorine
above 1.0 % dry refused) and ISO 21640 class limits, never from the code
under test.
"""

from __future__ import annotations

import math

import pytest

from lynceus import contracts, impact

GOOD = {"moisture_pct": 18.0, "ncv_mj_kg": 14.0, "chlorine_pct": 0.5}


def _lab(**overrides):
    return {**GOOD, **overrides}


def test_no_breach_pays_full_price():
    result = contracts.evaluate(GOOD, 10_000)
    assert result["breaches"] == []
    assert result["base_price_idr_per_t"] == 360_000
    assert result["adjusted_price_idr_per_t"] == 360_000
    assert result["adjustment_pct"] == 0.0
    assert result["net_t"] == 10.0
    assert result["payable_idr"] == 3_600_000
    assert result["deduction_idr"] == 0
    assert result["refused"] is False


def test_moisture_penalty_two_percent_per_point():
    # 25 % is 5 points over 20 %: minus 10 % -> Rp 324,000/t; 10 t -> 3,240,000.
    result = contracts.evaluate(_lab(moisture_pct=25.0), 10_000)
    assert [b["param"] for b in result["breaches"]] == ["moisture_pct"]
    assert result["breaches"][0]["severity"] == "penalty"
    assert result["breaches"][0]["limit"] == 20.0
    assert result["adjusted_price_idr_per_t"] == 324_000
    assert result["adjustment_pct"] == -10.0
    assert result["payable_idr"] == 3_240_000
    assert result["deduction_idr"] == 360_000


def test_fractional_moisture_points_count_pro_rata():
    # SBI Cilacap's typical 23.4 % -> 3.4 points -> minus 6.8 % -> Rp 335,520/t.
    result = contracts.evaluate(_lab(moisture_pct=23.4), 1_000)
    assert result["adjusted_price_idr_per_t"] == 335_520


def test_ncv_penalty_scales_price_by_actual_over_minimum():
    # 11.34 / 12.6 = 0.9 -> Rp 324,000/t.
    result = contracts.evaluate(_lab(ncv_mj_kg=11.34), 10_000)
    assert [b["param"] for b in result["breaches"]] == ["ncv_mj_kg"]
    assert result["adjusted_price_idr_per_t"] == 324_000
    assert result["deduction_idr"] == 360_000


def test_moisture_and_ncv_penalties_multiply():
    # 360,000 x 0.90 x 0.90 = 291,600.
    result = contracts.evaluate(_lab(moisture_pct=25.0, ncv_mj_kg=11.34), 10_000)
    assert result["adjusted_price_idr_per_t"] == 291_600
    assert result["payable_idr"] == 2_916_000
    assert result["deduction_idr"] == 684_000


def test_chlorine_above_limit_refuses_the_load_and_nothing_else_applies():
    result = contracts.evaluate(_lab(chlorine_pct=1.2, moisture_pct=40.0), 16_340)
    assert result["refused"] is True
    assert [(b["param"], b["severity"]) for b in result["breaches"]] == [
        ("chlorine_pct", "refusal")]
    assert "supplier's cost" in result["breaches"][0]["effect"]
    assert result["adjusted_price_idr_per_t"] == 0
    assert result["adjustment_pct"] == -100.0
    assert result["payable_idr"] == 0
    # The whole load's value: 16.34 t x 360,000.
    assert result["deduction_idr"] == 5_882_400


@pytest.mark.parametrize("chlorine", [0.81, 0.9, 1.0])
def test_chlorine_between_warn_and_limit_is_warning_only(chlorine):
    result = contracts.evaluate(_lab(chlorine_pct=chlorine), 10_000)
    assert [(b["param"], b["severity"]) for b in result["breaches"]] == [
        ("chlorine_pct", "warning")]
    assert result["refused"] is False
    assert result["payable_idr"] == 3_600_000
    assert result["deduction_idr"] == 0


def test_values_on_the_spec_line_do_not_breach():
    result = contracts.evaluate(
        {"moisture_pct": 20.0, "ncv_mj_kg": 12.6, "chlorine_pct": 0.8}, 10_000)
    assert result["breaches"] == []


@pytest.mark.parametrize("lab, net", [
    ({**GOOD, "moisture_pct": math.nan}, 1000),
    ({**GOOD, "ncv_mj_kg": None}, 1000),
    ({"moisture_pct": 20, "ncv_mj_kg": 14}, 1000),
    ({**GOOD, "hg_mg_mj": math.inf}, 1000),
    (GOOD, -5),
])
def test_bad_input_raises_value_error(lab, net):
    with pytest.raises(ValueError):
        contracts.evaluate(lab, net)


# ---------------------------------------------------------------------------
# Settlement tiers
# ---------------------------------------------------------------------------


def test_tier_a_pays_ten_percent_premium():
    # 15 MJ/kg, 15 % moisture, 0.6 % Cl: tier A -> 396,000/t; 10 t -> 3,960,000.
    result = contracts.evaluate(
        {"moisture_pct": 15.0, "ncv_mj_kg": 15.0, "chlorine_pct": 0.6}, 10_000)
    assert result["tier"] == "A"
    assert result["settlement_price_idr_per_t"] == 396_000
    assert result["settlement_idr"] == 3_960_000
    assert result["payable_idr"] == 3_600_000
    assert result["premium_idr"] == 360_000


@pytest.mark.parametrize("lab", [
    GOOD,  # 18 % moisture: in spec, not 5 points under
    {"moisture_pct": 15.0, "ncv_mj_kg": 14.9, "chlorine_pct": 0.5},
    {"moisture_pct": 15.0, "ncv_mj_kg": 15.0, "chlorine_pct": 0.61},
    {"moisture_pct": 15.0, "ncv_mj_kg": 15.0, "chlorine_pct": 0.9},  # warning
])
def test_tier_b_pays_base(lab):
    result = contracts.evaluate(lab, 10_000)
    assert result["tier"] == "B"
    assert result["settlement_idr"] == 3_600_000
    assert result["premium_idr"] == 0


def test_tier_c_settles_at_the_adjusted_price():
    result = contracts.evaluate(_lab(moisture_pct=25.0), 10_000)
    assert (result["tier"], result["settlement_idr"], result["premium_idr"]) == (
        "C", 3_240_000, 0)
    assert result["tier_reason"] == "Out of spec: moisture_pct."
    refused = contracts.evaluate(_lab(chlorine_pct=1.2), 10_000)
    assert (refused["tier"], refused["settlement_idr"]) == ("C", 0)
    assert refused["tier_reason"].startswith("Refused")


def test_contract_lists_the_example_tiers():
    assert [t["tier"] for t in contracts.DEFAULT_CONTRACT["settlement_tiers"]] == ["A", "B", "C"]


# ---------------------------------------------------------------------------
# ISO 21640 indicative class
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("ncv, cl, hg, code", [
    (14.0, 0.5, None, "NCV 4; Cl 2; Hg n/a"),
    (15.0, 1.0, None, "NCV 3; Cl 3; Hg n/a"),
    (25.0, 0.2, 0.02, "NCV 1; Cl 1; Hg 1"),
    (12.6, 0.61, 0.04, "NCV 4; Cl 3; Hg 3"),
    (2.9, 3.1, 0.2, "NCV out; Cl out; Hg out"),
])
def test_iso21640_class_code(ncv, cl, hg, code):
    result = contracts.iso21640_class(ncv, cl, hg)
    assert result["code"] == code
    assert "indicative" in result["label"] and "lot statistics" in result["label"]


def test_evaluate_carries_the_iso_class_with_optional_mercury():
    assert contracts.evaluate(GOOD, 1000)["iso21640"]["code"] == "NCV 4; Cl 2; Hg n/a"
    with_hg = contracts.evaluate({**GOOD, "hg_mg_mj": 0.03}, 1000)
    assert with_hg["iso21640"]["classes"] == {"ncv": 4, "cl": 2, "hg": 2}


# ---------------------------------------------------------------------------
# Terms and labels
# ---------------------------------------------------------------------------


def test_contract_is_labelled_example_with_public_indonesian_specs():
    contract = contracts.DEFAULT_CONTRACT
    assert contract["example"] is True
    assert "terms are set per contract (SOP-RDF-5.3)" in contract["note"]
    assert contract["base_price_idr_per_t"] == 360_000
    assert contract["specs"] == {
        "moisture_pct_max": 20.0, "ncv_mj_kg_min": 12.6,
        "chlorine_pct_max": 1.0, "chlorine_pct_warn": 0.8,
    }
    assert "indonesiawaterportal.com" in contract["spec_sources"]["moisture_pct_max"]
    assert "whiterose" in contract["spec_sources"]["chlorine_pct_max"]
    assert contract["breach_fee_idr"] == 1_500_000
    # 12.6 MJ/kg / 4.184 kJ/kcal = 3,011 kcal/kg (the spec's "3,000 kcal/kg").
    assert contract["ncv_kcal_kg_min"] == 3011
    band = contract["price_band"]
    assert (band["usd_per_t_min"], band["usd_per_t_max"]) == (24.0, 44.0)
    assert "indocement.co.id" in band["source"]
    assert contract["iso21640"]["limits"]["chlorine_pct_dry_max"] == (0.2, 0.6, 1.0, 1.5, 3.0)
    # Same source string impact.py already cites for the Bantargebang price.
    assert contracts.BASE_PRICE_SOURCE in impact.RDF_PRICE_SOURCE
