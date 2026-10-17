"""Supplier scorecard and risk-based sampling (``lynceus.suppliers``).

Tiers and sampling are worked by hand from the plan's rules: new < 3 trucks
(every 3rd); high = hard contaminant in the last 10 trucks, risk >= 0.34 or
a lab breach in the last 5 samples (every truck); medium (every 3rd); low
(every 10th).
"""

from __future__ import annotations

import pytest

from lynceus import followups, suppliers
from _ops_records import write_record

_n = 0


@pytest.fixture(autouse=True)
def _fresh():
    global _n
    _n = 0
    suppliers.clear_cache()
    yield
    suppliers.clear_cache()


def _add(storage, count=1, **kwargs):
    global _n
    ids = []
    for _ in range(count):
        _n += 1
        ids.append(write_record(storage, _n, **kwargs))
    return ids


def _lab(storage, record_id, moisture=18.0, chlorine=0.5):
    followups.append_lab(storage, record_id, moisture_pct=moisture, ncv_mj_kg=14.0,
                         chlorine_pct=chlorine, actor="lab")


def test_new_supplier_under_three_trucks(tmp_path):
    _add(tmp_path, 2, supplier="CV Baru")
    prof = suppliers.profile(tmp_path, "CV Baru")
    assert prof["tier"] == "new"
    assert prof["sampling"] == {"every_n": 3, "label": "1 in 3 sampled"}


def test_low_risk_clean_supplier(tmp_path):
    _add(tmp_path, 10, supplier="CV Sumber Bersih", weight_kg=18_000)
    prof = suppliers.profile(tmp_path, "CV Sumber Bersih")
    assert prof["tier"] == "low"
    assert prof["sampling"] == {"every_n": 10, "label": "1 in 10 sampled"}
    assert (prof["trucks"], prof["accepted"], prof["rejected"]) == (10, 10, 0)
    assert prof["risk_score"] == 0.0
    assert prof["net_t"] == 180.0
    assert prof["avg_moisture_pct"] is None
    assert prof["last_seen_utc"] == "2026-10-14T01:10:00Z"


def test_medium_on_risk_score(tmp_path):
    # 3 held of 10 -> (0 + 1.5) / 10 = 0.15: medium, below 0.34.
    _add(tmp_path, 7, supplier="UD Timbang")
    _add(tmp_path, 3, supplier="UD Timbang", decision="escalate_human")
    prof = suppliers.profile(tmp_path, "UD Timbang")
    assert prof["risk_score"] == 0.15
    assert prof["tier"] == "medium"
    assert prof["sampling"]["every_n"] == 3


def test_medium_on_declaration_conflict_in_last_ten(tmp_path):
    _add(tmp_path, 1, supplier="CV Basah", conflict=True, conflict_reason="Wetter than declared")
    _add(tmp_path, 9, supplier="CV Basah")
    assert suppliers.profile(tmp_path, "CV Basah")["tier"] == "medium"


def test_high_on_hard_contaminant_in_last_ten_trucks(tmp_path):
    _add(tmp_path, 1, supplier="PT Logam", decision="reject", hard=["metal"], conflict=True)
    _add(tmp_path, 9, supplier="PT Logam")
    prof = suppliers.profile(tmp_path, "PT Logam")
    assert prof["risk_score"] == 0.1
    assert prof["tier"] == "high"
    assert prof["sampling"] == {"every_n": 1, "label": "Every truck sampled"}
    assert prof["hard_contaminant_loads"] == 1
    assert prof["declaration_conflicts"] == 1
    assert prof["breach_fees_idr"] == 1_500_000
    # Ten more clean trucks push the metal load out of the window.
    _add(tmp_path, 10, supplier="PT Logam")
    assert suppliers.profile(tmp_path, "PT Logam")["tier"] == "low"


def test_high_on_risk_score(tmp_path):
    # 1 reject (no hard label) + 1 held of 3 -> 0.5.
    _add(tmp_path, 1, supplier="CV Risiko", decision="reject")
    _add(tmp_path, 1, supplier="CV Risiko", decision="escalate_human")
    _add(tmp_path, 1, supplier="CV Risiko")
    prof = suppliers.profile(tmp_path, "CV Risiko")
    assert prof["risk_score"] == 0.5
    assert prof["tier"] == "high"


def test_lab_breach_in_last_five_samples_is_high_then_older_breach_is_medium(tmp_path):
    ids = _add(tmp_path, 10, supplier="PT Daur Ulang Jaya")
    _lab(tmp_path, ids[0], moisture=26.0)  # penalty breach
    prof = suppliers.profile(tmp_path, "PT Daur Ulang Jaya")
    assert prof["tier"] == "high"
    assert (prof["lab_samples"], prof["spec_breaches"]) == (1, 1)
    assert prof["avg_moisture_pct"] == 26.0
    # 360,000 x 12 % x 10 t = 432,000.
    assert prof["deductions_idr"] == 432_000
    for record_id in ids[1:6]:
        _lab(tmp_path, record_id)
    prof = suppliers.profile(tmp_path, "PT Daur Ulang Jaya")
    assert (prof["lab_samples"], prof["spec_breaches"]) == (6, 1)
    assert prof["tier"] == "medium"
    assert prof["avg_moisture_pct"] == 19.33


def test_chlorine_warning_is_not_a_spec_breach(tmp_path):
    ids = _add(tmp_path, 10, supplier="CV Klorin")
    _lab(tmp_path, ids[0], chlorine=0.9)
    prof = suppliers.profile(tmp_path, "CV Klorin")
    assert prof["spec_breaches"] == 0
    assert prof["tier"] == "low"


def test_reviews_and_overrides(tmp_path):
    reject, accept, held = (
        _add(tmp_path, 1, supplier="CV R", decision="reject", hard=["metal"])[0],
        _add(tmp_path, 1, supplier="CV R")[0],
        _add(tmp_path, 1, supplier="CV R", decision="escalate_human")[0],
    )
    followups.append_resolution(tmp_path, reject, "sort_then_accept", actor="s")
    followups.append_resolution(tmp_path, accept, "accept", actor="s")
    followups.append_resolution(tmp_path, held, "reject", actor="s")
    prof = suppliers.profile(tmp_path, "CV R")
    assert prof["reviews"] == 3
    assert prof["overrides"] == 1


def test_names_match_ignoring_case_and_punctuation_unknown_and_incomplete(tmp_path):
    _add(tmp_path, 2, supplier="PT. Hijau Lestari Transport")
    _add(tmp_path, 1, supplier="pt hijau  lestari transport")
    _add(tmp_path, 1, supplier=None)
    _add(tmp_path, 1, supplier="PT. Hijau Lestari Transport", status="in_progress",
         decision="escalate_human")
    prof = suppliers.profile(tmp_path, "PT Hijau Lestari Transport")
    assert prof["trucks"] == 3
    assert prof["supplier"] == "pt hijau  lestari transport"  # the latest spelling
    names = {p["supplier"] for p in suppliers.profiles(tmp_path)}
    assert names == {"pt hijau  lestari transport", "unknown"}
    assert suppliers.profile(tmp_path, "CV Tidak Ada") is None
    assert suppliers.profile(tmp_path, "") is None


def test_profiles_have_every_contract_field(tmp_path):
    _add(tmp_path, 1, supplier="CV A")
    keys = set(suppliers.profiles(tmp_path)[0])
    assert {
        "supplier", "trucks", "accepted", "escalated", "rejected", "hard_contaminant_loads",
        "declaration_conflicts", "reviews", "overrides", "lab_samples", "avg_moisture_pct",
        "avg_ncv_mj_kg", "avg_chlorine_pct", "spec_breaches", "deductions_idr",
        "breach_fees_idr", "net_t", "risk_score", "tier", "sampling", "last_seen_utc",
    } <= keys


def test_cache_sees_new_followups(tmp_path):
    ids = _add(tmp_path, 10, supplier="CV Cache")
    assert suppliers.profile(tmp_path, "CV Cache")["tier"] == "low"
    _lab(tmp_path, ids[-1], moisture=30.0)
    assert suppliers.profile(tmp_path, "CV Cache")["tier"] == "high"


# ---------------------------------------------------------------------------
# sampling_for
# ---------------------------------------------------------------------------


def test_sampling_low_tier_every_tenth_truck(tmp_path):
    _add(tmp_path, 8, supplier="CV Low")
    # Tiers need 3+ trucks; 8 clean -> low; the next truck is the 9th: no.
    first = suppliers.sampling_for(tmp_path, "CV Low")
    assert first["sample_this_truck"] is False
    assert first["tier"] == "low"
    assert first["label"] == "1 in 10 sampled"
    assert "truck 10" in first["reason"]
    assert suppliers.sampling_for(tmp_path, "CV Low") == first  # deterministic
    _add(tmp_path, 1, supplier="CV Low")
    tenth = suppliers.sampling_for(tmp_path, "CV Low")
    assert tenth["sample_this_truck"] is True
    assert "SOP-RDF-5.4" in tenth["reason"]


def test_sampling_high_tier_samples_every_truck(tmp_path):
    _add(tmp_path, 3, supplier="PT Logam", decision="reject", hard=["metal"])
    for _ in range(3):
        result = suppliers.sampling_for(tmp_path, "PT Logam")
        assert result["sample_this_truck"] is True
        assert result["tier"] == "high"
        assert result["label"] == "Every truck sampled"


def test_sampling_new_supplier_third_truck(tmp_path):
    assert suppliers.sampling_for(tmp_path, "CV Baru")["sample_this_truck"] is False
    assert suppliers.sampling_for(tmp_path, None)["tier"] == "new"
    ids = _add(tmp_path, 2, supplier="CV Baru")
    third = suppliers.sampling_for(tmp_path, "CV Baru")
    assert (third["sample_this_truck"], third["tier"]) == (True, "new")
    # Excluding the current (already sealed) truck counts one fewer.
    again = suppliers.sampling_for(tmp_path, "CV Baru", exclude_record_id=ids[-1])
    assert again["sample_this_truck"] is False


def test_declared_moisture_above_spec_samples_whatever_the_tier(tmp_path):
    _add(tmp_path, 8, supplier="CV Low")  # low tier; the 9th truck is not due
    plain = suppliers.sampling_for(tmp_path, "CV Low", {"moisture_pct": 18})
    assert plain["sample_this_truck"] is False
    wet = suppliers.sampling_for(tmp_path, "CV Low", {"moisture_pct": 28, "net_kg": 16340})
    assert wet["sample_this_truck"] is True
    assert wet["tier"] == "low"
    assert wet["reason"].startswith(
        "Declared moisture 28 % is above the 20 % contract spec: sample to settle the price")
    # A read field ({value, confidence}) works too; at or under spec does not trigger.
    assert suppliers.sampling_for(tmp_path, "CV Low", {"moisture_pct": {"value": 21.5}})[
        "sample_this_truck"] is True
    for value in (None, 20, "28"):
        assert suppliers.sampling_for(tmp_path, "CV Low", {"moisture_pct": value})[
            "sample_this_truck"] is False
