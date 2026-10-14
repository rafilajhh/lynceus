"""Tests for the measurable-impact layer (lynceus.impact).

Covers: REJECT + hard contaminant → prevented loss > 0 with sourced basis,
ACCEPT → positive RDF load value, ESCALATE without contaminant → combustion
penalty, and determinism (same inputs → identical output).  All figures
must trace to docs/research/realcase-indonesia.md.
"""

from __future__ import annotations

import copy

import pytest

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


def test_reject_note_calls_the_figure_worst_case_exposure():
    out = impact.estimate_prevented_loss("reject", _vlm(hard=["metal"]), 5200.0)
    assert "worst-case loss exposure" in out["note"]
    assert "certainly" in out["note"]


# ---------------------------------------------------------------------------
# Expected-value model (with vs without Lynceus, per 1,000 trucks).
# Expected numbers are worked by hand in the comments, never from the code.
# ---------------------------------------------------------------------------

#: Hard class 20 images: 18 reject, 2 escalate → reject 0.9, escalate 0.1.
#: Clean class 40 images: 2 reject, 8 escalate, 30 accept → 0.05 / 0.20.
_SUMMARY = {
    "confusion": {
        "reject": {"reject": 18, "escalate": 2, "accept": 0, "error": 0},
        "escalate": {"reject": 0, "escalate": 20, "accept": 0, "error": 0},
        "accept": {"reject": 2, "escalate": 8, "accept": 30, "error": 0},
    },
    "reject": {"precision": 0.9, "recall": 0.9},
}


def test_benchmark_rates_from_confusion():
    rates = impact.benchmark_rates(_SUMMARY)
    assert rates["hard_reject_rate"] == pytest.approx(0.9)
    assert rates["hard_escalate_rate"] == pytest.approx(0.1)
    assert rates["clean_reject_rate"] == pytest.approx(0.05)
    assert rates["clean_escalate_rate"] == pytest.approx(0.2)
    assert rates["n_hard"] == 20 and rates["n_clean"] == 40


def test_benchmark_rates_prefer_rescore_clean_keys():
    summary = {**_SUMMARY, "clean_reject_rate": 0.0, "clean_escalate_rate": 0.1,
               "clean_accept_rate": 0.9}
    rates = impact.benchmark_rates(summary)
    assert rates["clean_reject_rate"] == 0.0
    assert rates["clean_escalate_rate"] == 0.1


def test_benchmark_rates_none_when_unusable():
    assert impact.benchmark_rates({}) is None
    assert impact.benchmark_rates({"reject": {"recall": 0.9}}) is None


def test_base_scenario_hand_computed():
    model = impact.value_model(_SUMMARY, "fixture.summary.json")
    base = model["scenarios"]["base"]
    # 1,000 trucks × 2% = 20 hard loads, 980 clean.
    # One escape that does damage: 5% × (Rp 350M + US$28k × 16,000) = Rp 39.9M.
    # Without: 20 × (1 − 0.7) = 6 escape → 6 × 39.9M = Rp 239.4M; 1,000 × 3 min.
    assert base["without"]["escaped_hard_loads"] == pytest.approx(6.0)
    assert base["without"]["expected_damage_idr"] == 239_400_000
    assert base["without"]["operator_minutes"] == pytest.approx(3000.0)
    assert base["without"]["false_reject_cost_idr"] == 0
    # With: caught 20 × (0.9 + 0.1 × 0.7) = 19.4 → 0.6 escape → Rp 23.94M.
    assert base["with"]["escaped_hard_loads"] == pytest.approx(0.6)
    assert base["with"]["expected_damage_idr"] == 23_940_000
    # Flagged 20 × 1.0 + 980 × 0.25 = 265; minutes 1,000 × 0.5 + 265 × 3 = 1,295.
    assert base["with"]["trucks_checked_by_hand"] == pytest.approx(265.0)
    assert base["with"]["operator_minutes"] == pytest.approx(1295.0)
    # False rejects 980 × 0.05 = 49 × 5.2 t × Rp 375,000 = Rp 95.55M.
    assert base["with"]["false_rejects"] == pytest.approx(49.0)
    assert base["false_reject_cost_idr"] == 95_550_000
    assert base["expected_loss_avoided_idr"] == 215_460_000
    # 1,705 min × (Rp 1.497B / 32 / 2,080 h / 60) = Rp 639,118.84.
    assert base["operator_minutes_saved"] == pytest.approx(1705.0)
    assert base["operator_time_value_idr"] == 639_119
    # 215.46M − 95.55M + 0.639M.
    assert base["net_value_idr"] == 120_549_119


def test_low_scenario_hand_computed_can_be_negative():
    low = impact.value_model(_SUMMARY, "fixture.summary.json")["scenarios"]["low"]
    # 5 hard loads; harm per escape 2% × 798M = Rp 15.96M.
    # Without 5 × 0.1 = 0.5 escape → Rp 7.98M.  With 5 × (0.9 + 0.1 × 0.9)
    # = 4.95 caught → 0.05 escape → Rp 0.798M.  Avoided Rp 7.182M.
    assert low["expected_loss_avoided_idr"] == 7_182_000
    # False rejects 995 × 0.05 = 49.75 × 5.2 × Rp 450,000 = Rp 116.415M.
    assert low["false_reject_cost_idr"] == 116_415_000
    assert low["net_value_idr"] < 0


def test_scenarios_ordered_and_parameters_honest():
    model = impact.value_model(_SUMMARY, "fixture.summary.json")
    nets = [model["scenarios"][k]["net_value_idr"] for k in ("low", "base", "high")]
    assert nets == sorted(nets)
    assert model["trucks"] == 1000
    assert model["worst_case_per_incident_idr"] == 798_000_000
    for row in model["parameters"]:
        assert row["sources"] or row["assumption"], row["key"]
        assert row["rationale"], row["key"]
        assert all(url.startswith("https://") for url in row["sources"]), row["key"]
    assumed = {row["key"] for row in model["parameters"] if row["assumption"]}
    assert {"hard_load_rate", "manual_catch_rate", "damage_probability",
            "manual_check_minutes", "capture_minutes"} <= assumed
    assert model["eur_idr_rate"] == 20_004.87
    assert "ecb.europa.eu" in model["eur_idr_source_url"]


def test_value_model_prefers_rescore_file_and_falls_back(tmp_path):
    import json

    live = tmp_path / "2026-10-13.summary.json"
    live.write_text(json.dumps(_SUMMARY), encoding="utf-8")
    model = impact.value_model_from_benchmark(tmp_path)
    assert model["benchmark_file"] == "2026-10-13.summary.json"

    rescore = {**_SUMMARY, "clean_reject_rate": 0.0, "clean_escalate_rate": 0.1}
    (tmp_path / "2026-10-13.rescore.summary.json").write_text(
        json.dumps(rescore), encoding="utf-8"
    )
    model = impact.value_model_from_benchmark(tmp_path)
    assert model["benchmark_file"] == "2026-10-13.rescore.summary.json"
    assert model["scenarios"]["base"]["false_reject_cost_idr"] == 0


def test_value_model_none_without_benchmark(tmp_path):
    assert impact.value_model_from_benchmark(tmp_path) is None
