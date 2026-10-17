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


def test_subscription_cost_hand_computed():
    scenarios = impact.value_model(_SUMMARY, "fixture.summary.json")["scenarios"]
    # Fee per day: Rp 6M × 12 / 365 = Rp 197,260.27.
    # Base: 1,000 trucks × 5.2 t / 75 t/day (Cilacap) = 69.333 days
    # → Rp 13,676,712.33; net 120,549,118.84 − 13,676,712.33 = 106,872,406.51.
    base = scenarios["base"]
    assert base["days_per_1000_trucks"] == pytest.approx(69.3)
    assert base["subscription_cost_idr"] == 13_676_712
    assert base["net_after_subscription_idr"] == 106_872_407
    assert base["net_value_idr"] == 120_549_119  # pre-fee figure unchanged
    # Low: 5,200 / 35 t/day (Banyumas) = 148.571 days → Rp 29,307,240.60.
    assert scenarios["low"]["days_per_1000_trucks"] == pytest.approx(148.6)
    assert scenarios["low"]["subscription_cost_idr"] == 29_307_241
    # High: 5,200 / 400 t/day (Bantargebang) = 13 days → Rp 2,564,383.56.
    assert scenarios["high"]["days_per_1000_trucks"] == pytest.approx(13.0)
    assert scenarios["high"]["subscription_cost_idr"] == 2_564_384
    nets = [scenarios[k]["net_after_subscription_idr"] for k in ("low", "base", "high")]
    assert nets == sorted(nets)


def test_subscription_is_a_labelled_proposal():
    params = {row["key"]: row
              for row in impact.value_model(_SUMMARY, "fixture.summary.json")["parameters"]}
    fee = params["subscription_idr_per_month"]
    assert fee["low"] == fee["base"] == fee["high"] == 6_000_000
    assert fee["assumption"] and fee["sources"] == []
    assert "Proposal" in fee["rationale"] and "BUSINESS.md" in fee["rationale"]
    gate = params["gate_rdf_tonnes_per_day"]
    assert (gate["low"], gate["base"], gate["high"]) == (35.0, 75.0, 400.0)
    assert "Table III.2" in gate["rationale"]


def test_wilson_interval_hand_computed():
    # z = 1.96, z² = 3.8416.  p = 0.9, n = 20: denom 1.19208,
    # centre (0.9 + 0.09604) / 1.19208 = 0.83555,
    # half 1.96 × √(0.0045 + 0.002401) / 1.19208 = 0.13659.
    lo, hi = impact._wilson(0.9, 20)
    assert lo == pytest.approx(0.69896, abs=1e-4)
    assert hi == pytest.approx(0.97213, abs=1e-4)
    # p = 0.05, n = 40: denom 1.09604, centre 0.09802 / 1.09604 = 0.08943,
    # half 1.96 × √(0.0011875 + 0.00060025) / 1.09604 = 0.07561.
    lo, hi = impact._wilson(0.05, 40)
    assert lo == pytest.approx(0.01382, abs=1e-4)
    assert hi == pytest.approx(0.16504, abs=1e-4)
    assert impact._wilson(0.3, None) == (0.3, 0.3)


def test_measured_rates_span_their_wilson_interval():
    params = {row["key"]: row
              for row in impact.value_model(_SUMMARY, "fixture.summary.json")["parameters"]}
    # Low is least favourable to Lynceus: lower reject recall, upper clean rates.
    assert params["hard_reject_rate"]["low"] == pytest.approx(0.69896, abs=1e-4)
    assert params["hard_reject_rate"]["base"] == pytest.approx(0.9)
    assert params["hard_reject_rate"]["high"] == pytest.approx(0.97213, abs=1e-4)
    assert params["clean_reject_rate"]["low"] == pytest.approx(0.16504, abs=1e-4)
    assert params["clean_reject_rate"]["high"] == pytest.approx(0.01382, abs=1e-4)
    # p = 0.2, n = 40: centre 0.24802 / 1.09604 = 0.22629,
    # half 1.96 × √(0.004 + 0.00060025) / 1.09604 = 0.12129.
    assert params["clean_escalate_rate"]["low"] == pytest.approx(0.34758, abs=1e-4)
    assert params["clean_escalate_rate"]["high"] == pytest.approx(0.10500, abs=1e-4)
    # Metal escalate 0.1 is held except at high: 1 − 0.97213 = 0.02787 caps it.
    assert params["hard_escalate_rate"]["low"] == pytest.approx(0.1)
    assert params["hard_escalate_rate"]["high"] == pytest.approx(0.02787, abs=1e-4)
    assert "Wilson" in params["hard_reject_rate"]["rationale"]


def test_low_scenario_hand_computed_can_be_negative():
    low = impact.value_model(_SUMMARY, "fixture.summary.json")["scenarios"]["low"]
    # 5 hard loads; harm per escape 2% × 798M = Rp 15.96M.
    # Without 5 × 0.1 = 0.5 escape → Rp 7.98M.  With 5 × (0.69896 + 0.1 × 0.9)
    # = 3.9448 caught → 1.0552 escape → Rp 16.841M.  Avoided ≈ −Rp 8.861M.
    assert low["with"]["escaped_hard_loads"] == pytest.approx(1.06, abs=0.01)
    assert low["expected_loss_avoided_idr"] == pytest.approx(-8_861_000, abs=2_000)
    # False rejects 995 × 0.16504 = 164.22 × 5.2 t × Rp 450,000 ≈ Rp 384.27M.
    assert low["false_reject_cost_idr"] == pytest.approx(384_270_000, abs=50_000)
    assert low["net_value_idr"] < 0


def test_replay_rates_say_they_are_not_held_out():
    replay = {**_SUMMARY, "kind": "replay", "disclosure": "Fixture disclosure."}
    model = impact.value_model(replay, "2026-10-13.rescore.summary.json")
    measured = [row for row in model["parameters"] if row["key"].endswith("_rate")
                and not row["assumption"]]
    assert len(measured) == 4
    for row in measured:
        assert "replay of the recorded live model outputs" in row["rationale"]
        assert "not a held-out" in row["rationale"]
        assert "Fixture disclosure." in row["rationale"]
    live = impact.value_model(_SUMMARY, "2026-10-13.summary.json")
    assert all("replay" not in row["rationale"] for row in live["parameters"])


def test_benchmark_rates_count_errored_clean_loads_as_flagged():
    # Clean class 40: 2 reject, 6 escalate, 30 accept, 2 errors.  The errors
    # go to the manual check: escalate share (6 + 2) / 40 = 0.2, whether the
    # rate comes from the confusion matrix or the summary's key (6 / 40).
    confusion = {**_SUMMARY["confusion"],
                 "accept": {"reject": 2, "escalate": 6, "accept": 30, "error": 2}}
    from_matrix = impact.benchmark_rates({**_SUMMARY, "confusion": confusion})
    assert from_matrix["clean_escalate_rate"] == pytest.approx(0.2)
    from_keys = impact.benchmark_rates({**_SUMMARY, "confusion": confusion,
                                        "clean_reject_rate": 0.05,
                                        "clean_escalate_rate": 0.15})
    assert from_keys["clean_escalate_rate"] == pytest.approx(0.2)
    assert from_keys["clean_reject_rate"] == pytest.approx(0.05)


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


def _hybrid_summary(source_run: str, metal_accepted: int = 0) -> dict:
    """Shipped-gate re-score: metal 8 rejected, the rest held (or accepted)."""
    held = 12 - metal_accepted
    return {
        "kind": "hybrid_replay",
        "source_run": source_run,
        "vlm_model": "DeepSeek-V4-Flash-Vision-Exp",
        "detector": {"model": "yolo26m-realwaste-taco", "runtime": "onnxruntime-cpu"},
        "disclosure": "Hybrid fixture disclosure.",
        "variants": {
            "vlm_only": {"confusion": _SUMMARY["confusion"], "metal_reject": {"recall": 0.9}},
            "hybrid_light_escalation_on": {
                "metal_reject": {"precision": 1.0, "recall": 0.4, "tp": 8, "fp": 0, "fn": 12},
                "metal_accepted": metal_accepted,
                "confusion": {
                    "reject": {"reject": 8, "escalate": held, "accept": metal_accepted, "error": 0},
                    "escalate": {"reject": 0, "escalate": 20, "accept": 0, "error": 0},
                    "accept": {"reject": 0, "escalate": 3, "accept": 37, "error": 0},
                },
            },
        },
    }


def test_hybrid_rates_hold_unrejected_metal_instead_of_accepting_it():
    rates = impact.benchmark_rates(_hybrid_summary("run"))
    assert rates["hard_reject_rate"] == pytest.approx(0.4)
    # metal_accepted 0 of 20: every unrejected metal load goes to an operator.
    assert rates["hard_escalate_rate"] == pytest.approx(0.6)
    assert rates["clean_reject_rate"] == 0.0
    assert rates["clean_escalate_rate"] == pytest.approx(3 / 40)
    leaky = impact.benchmark_rates(_hybrid_summary("run", metal_accepted=2))
    assert 1 - leaky["hard_reject_rate"] - leaky["hard_escalate_rate"] == pytest.approx(2 / 20)


def test_hybrid_escape_is_only_the_manual_misses_of_held_metal():
    model = impact.value_model(_hybrid_summary("run"), "x.hybrid-rescore.summary.json")
    base = model["scenarios"]["base"]
    # 20 hard loads per 1,000; 40% rejected, 60% held, manual check misses 30%:
    # escaped = 20 × 0.6 × 0.3, not 20 × (1 − 0.4).
    assert base["with"]["escaped_hard_loads"] == pytest.approx(3.6)
    assert model["benchmark_source"].startswith(
        "DeepSeek-V4-Flash-Vision-Exp + yolo26m-realwaste-taco CPU detector")
    measured = [row for row in model["parameters"] if row["key"] == "hard_reject_rate"][0]
    assert "shipped gate" in measured["rationale"]
    assert "held for an operator, not accepted" in measured["rationale"]
    assert "Hybrid fixture disclosure." in measured["rationale"]


def test_value_model_prefers_the_newest_live_runs_hybrid(tmp_path):
    import json

    def write(name, body):
        (tmp_path / name).write_text(json.dumps(body), encoding="utf-8")

    write("2026-10-13.summary.json", {**_SUMMARY, "date": "2026-10-13"})
    # A hybrid of the old run only: the fallback list still wins.
    write("2026-10-16.hybrid-rescore.summary.json", _hybrid_summary("2026-10-13"))
    write("2026-10-17.x.summary.json", {**_SUMMARY, "kind": "live", "date": "2026-10-17.x"})
    model = impact.value_model_from_benchmark(tmp_path)
    assert model["benchmark_file"] == "2026-10-13.summary.json"

    write("2026-10-17.x.hybrid-rescore.summary.json", _hybrid_summary("2026-10-17.x"))
    model = impact.value_model_from_benchmark(tmp_path)
    assert model["benchmark_file"] == "2026-10-17.x.hybrid-rescore.summary.json"
    assert model["scenarios"]["base"]["with"]["escaped_hard_loads"] == pytest.approx(3.6)


def test_committed_value_model_runs_on_the_shipped_gate():
    model = impact.value_model_from_benchmark()
    assert model["benchmark_file"].endswith(".hybrid-rescore.summary.json")
    assert "yolo26m" in model["benchmark_source"]
