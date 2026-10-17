"""The shift report's ``improvement`` block (``shift.improvement``).

Every expected figure is counted by hand from the scripted records below and
the plan's definitions; money comes from the research constants in
``lynceus.impact`` and the example contract terms.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from lynceus import followups, impact, pipeline, shift
from lynceus.api import create_app
from lynceus.config import LYNCEUS_STORAGE_DIR_ENV
from _ops_records import load, write_record


@pytest.fixture
def shift_dir(tmp_path):
    s = tmp_path
    ids = [
        write_record(s, 1, duration_s=14),                                    # accept, no check
        write_record(s, 2, duration_s=10),                                    # accept, spot-checked
        write_record(s, 3, decision="reject", hard=["metal"], conflict=True, duration_s=20),
        write_record(s, 4, decision="reject", hard=["metal"], duration_s=30),
        write_record(s, 5, decision="escalate_human", light=["wet_mix"], duration_s=40),
        write_record(s, 6, decision="escalate_human", duration_s=50),
        write_record(s, 7, decision="refuse_insufficient_input", duration_s=12),
    ]
    followups.append_resolution(s, ids[1], "accept", actor="s", hand_check_minutes=3)
    followups.append_resolution(s, ids[2], "reject", actor="s")
    followups.append_resolution(s, ids[3], "accept", actor="s")  # tipped anyway
    followups.append_resolution(s, ids[4], "sort_then_accept", actor="s")
    followups.append_lab(s, ids[4], moisture_pct=25, ncv_mj_kg=14, chlorine_pct=0.5, actor="lab")
    followups.append_notice(s, ids[2], actor="s", client=None)
    return s, ids


def _report(storage, ids):
    records = [load(storage, record_id) for record_id in ids]
    return shift.build_report(records, None, None, followups.load_many(storage, ids))


def test_improvement_is_measured_from_records_and_followups(shift_dir):
    storage, ids = shift_dir
    block = _report(storage, ids)["improvement"]
    worst_case = round(
        impact.SHREDDER_COST_IDR
        + impact.KILN_DOWNTIME_USD_PER_HOUR * impact.KILN_DOWNTIME_HOURS * impact.USD_IDR_RATE
    )
    expected = {
        "trucks": 7, "auto_cleared": 2, "held": 2, "rejected": 2, "refused": 1,
        # Truck 2 was hand-checked after an ACCEPT: only truck 1 avoided a check.
        "hand_checks_avoided": 1, "manual_check_minutes_assumed": 3.0,
        "staff_minutes_freed": 3.0,
        # Durations 10, 12, 14, 20, 30, 40, 50 s: median 20, nearest-rank p95 50.
        "median_decision_s": 20.0, "p95_decision_s": 50.0,
        "hazardous_loads_stopped": 2, "declaration_conflicts": 1,
        "supervisor_reviews": 4, "ai_confirmed": 2, "ai_overridden": 1,
        # 10 t at 360,000 minus 10 % (5 moisture points) -> 360,000 deducted.
        "lab_samples": 1, "spec_breaches": 1, "deductions_idr": 360_000,
        "breach_fees_idr": 1_500_000, "notices": 1,
        # Truck 4's metal load was accepted unsorted: its worst-case exposure.
        "exposure_if_tipped_idr": worst_case,
    }
    assert {k: block[k] for k in expected} == expected
    assert block["manual_check_minutes_assumed"] == impact.MANUAL_CHECK_MINUTES_BASE
    notes = " ".join(block["notes"])
    assert "assumption" in notes and "3 min" in notes
    assert "started_at_utc to finished_at_utc" in notes
    assert "SOP-RDF-5.3" in notes
    assert "not loaded" not in notes


def test_existing_fields_are_kept(shift_dir):
    storage, ids = shift_dir
    report = _report(storage, ids)
    for key in ("window", "trucks", "by_verdict", "contaminants", "prevented_loss_idr",
                "loss_exposure_idr", "value_model", "median_seconds_per_truck",
                "suppliers", "sample", "sample_records"):
        assert key in report
    assert report["median_seconds_per_truck"] == report["improvement"]["median_decision_s"]


def test_without_followups_the_block_says_so(shift_dir):
    storage, ids = shift_dir
    records = [load(storage, record_id) for record_id in ids]
    block = shift.build_report(records, None, None)["improvement"]
    assert block["supervisor_reviews"] == 0
    assert block["hand_checks_avoided"] == 2
    assert any("not loaded" in note for note in block["notes"])


def test_window_limits_the_block(shift_dir):
    storage, ids = shift_dir
    records = [load(storage, record_id) for record_id in ids]
    block = shift.build_report(
        records, "2026-10-14T01:03:00Z", "2026-10-14T01:05:00Z",
        followups.load_many(storage, ids),
    )["improvement"]
    assert block["trucks"] == 2  # records 3 and 4
    assert block["breach_fees_idr"] == 1_500_000
    assert block["lab_samples"] == 0


def test_p95_nearest_rank():
    assert shift._p95([]) is None
    assert shift._p95([5.0]) == 5.0
    assert shift._p95([float(i) for i in range(1, 21)]) == 19.0


def test_shift_report_endpoint_carries_improvement(shift_dir, monkeypatch):
    storage, _ids = shift_dir
    monkeypatch.setenv(LYNCEUS_STORAGE_DIR_ENV, str(storage))
    monkeypatch.setattr(pipeline, "resolve_explain_client", lambda *a, **k: None)
    data = TestClient(create_app()).get("/shift-report").json()
    assert data["improvement"]["supervisor_reviews"] == 4
    assert data["improvement"]["deductions_idr"] == 360_000
    assert data["trucks"] == 7
