"""Kiln intake and carbon (``lynceus.fuel``).

Expected figures are worked by hand: energy = net t x NCV, chlorine kg =
dry t x Cl % x 10, IPCC defaults 96.1 (coal) and 91.7 (waste) t CO2/TJ.
"""

from __future__ import annotations

import pytest

from lynceus import followups, fuel, suppliers
from _ops_records import write_record

NOW = "2026-10-14T09:00:00Z"


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    monkeypatch.delenv(fuel.CHLORINE_BUDGET_ENV, raising=False)
    suppliers.clear_cache()
    yield
    suppliers.clear_cache()


@pytest.fixture
def ledger(tmp_path):
    s = tmp_path
    # Supplier A: truck 1 lab-sampled, truck 2 uses A's lab average.
    a1 = write_record(s, 1, supplier="CV A", weight_kg=10_000)
    followups.append_lab(s, a1, moisture_pct=20, ncv_mj_kg=14, chlorine_pct=0.5, actor="lab")
    write_record(s, 2, supplier="CV A", weight_kg=20_000)
    # Supplier B: no lab ever -> contract spec values.
    write_record(s, 3, supplier="CV B", weight_kg=10_000)
    # Not accepted: a reject, an open hold, a refusal.
    write_record(s, 4, supplier="CV B", decision="reject", hard=["metal"])
    write_record(s, 5, supplier="CV B", decision="escalate_human")
    write_record(s, 6, supplier="CV B", decision="refuse_insufficient_input")
    # A hold the supervisor sorted then accepted counts.
    held = write_record(s, 7, supplier="CV A", decision="escalate_human", weight_kg=10_000)
    followups.append_resolution(s, held, "sort_then_accept", actor="s")
    # An ACCEPT the supervisor reversed does not.
    reversed_ = write_record(s, 8, supplier="CV A", weight_kg=10_000)
    followups.append_resolution(s, reversed_, "reject", actor="s")
    return s


def test_kiln_intake_methods_energy_and_chlorine(ledger):
    intake = fuel.kiln_intake(ledger, "all", now=NOW)
    rows = {r["record_id"]: r for r in intake["rows"]}
    assert set(rows) == {"inspection-000001", "inspection-000002", "inspection-000003",
                         "inspection-000007"}
    assert [rows[k]["method"] for k in sorted(rows)] == [
        "lab", "supplier_average", "contract_spec", "supplier_average"]
    # Lab: 10 t x 14 = 140 GJ; dry 8 t x 0.5 % = 40 kg Cl.
    assert (rows["inspection-000001"]["energy_gj"], rows["inspection-000001"]["chlorine_kg"]) == (140.0, 40.0)
    # Supplier average of one sample: 20 t -> 280 GJ, 16 dry t -> 80 kg.
    assert (rows["inspection-000002"]["energy_gj"], rows["inspection-000002"]["chlorine_kg"]) == (280.0, 80.0)
    # Contract spec: 10 t x 12.6 = 126 GJ; dry 8 t x 1.0 % = 80 kg.
    assert (rows["inspection-000003"]["energy_gj"], rows["inspection-000003"]["chlorine_kg"]) == (126.0, 80.0)
    assert intake["trucks_accepted"] == 4
    assert intake["accepted_t"] == 50.0
    assert intake["energy_gj"] == 140 + 280 + 126 + 140
    assert intake["chlorine_kg"] == 40 + 80 + 80 + 40
    assert intake["methods"] == {"lab": 1, "supplier_average": 2, "contract_spec": 1}
    assert intake["method_mix"] == "Cl from lab on 1 load, supplier average on 2, contract limit on 1"
    assert "cl_per_t_clinker" not in intake
    # Weighted: moisture 20 everywhere; NCV (140+280+126+140)/50 = 13.72;
    # Cl by dry t: (8x0.5 + 16x0.5 + 8x1.0 + 8x0.5) / 40 = 0.6.
    assert intake["weighted"] == {"moisture_pct": 20.0, "ncv_mj_kg": 13.72, "chlorine_pct": 0.6}
    assert intake["vs_spec"] == {"moisture_pct": True, "ncv_mj_kg": True, "chlorine_pct": True}
    # No budget for the whole ledger.
    assert intake["chlorine_budget_kg"] is None and intake["chlorine_status"] is None


def test_shift_window_and_budget(ledger, monkeypatch):
    # Records start 01:01..01:08; a shift ending 09:00 starts at 01:00.
    intake = fuel.kiln_intake(ledger, "shift", now=NOW)
    assert intake["window"] == {"name": "shift", "since": "2026-10-14T01:00:00Z", "until": NOW}
    assert intake["chlorine_budget_kg"] == fuel.CHLORINE_BUDGET_KG_PER_SHIFT
    assert intake["chlorine_budget_note"].startswith(
        "Example plant budget; set per kiln (bypass capacity): 3000 kg")
    assert intake["chlorine_status"] == "ok"

    monkeypatch.setenv(fuel.CHLORINE_BUDGET_ENV, "300")
    intake = fuel.kiln_intake(ledger, "shift", now=NOW)
    assert intake["chlorine_budget_pct"] == 80.0  # 240 / 300
    assert intake["chlorine_status"] == "warn"
    monkeypatch.setenv(fuel.CHLORINE_BUDGET_ENV, "200")
    assert fuel.kiln_intake(ledger, "shift", now=NOW)["chlorine_status"] == "over"
    # The day window triples the shift budget.
    assert fuel.kiln_intake(ledger, "day", now=NOW)["chlorine_budget_kg"] == 600.0
    monkeypatch.setenv(fuel.CHLORINE_BUDGET_ENV, "not a number")
    assert fuel.chlorine_budget_kg_per_shift() == fuel.CHLORINE_BUDGET_KG_PER_SHIFT


def test_window_excludes_older_and_later_trucks(ledger):
    assert fuel.kiln_intake(ledger, "shift", now="2026-10-14T20:00:00Z")["trucks_accepted"] == 0
    assert fuel.kiln_intake(ledger, "all", now="2026-10-14T01:02:00Z")["trucks_accepted"] == 1


def test_bad_window_raises(ledger):
    with pytest.raises(ValueError):
        fuel.kiln_intake(ledger, "week", now=NOW)


def test_empty_ledger(tmp_path):
    intake = fuel.kiln_intake(tmp_path, "shift", now=NOW)
    assert intake["trucks_accepted"] == 0
    assert intake["weighted"] == {"moisture_pct": None, "ncv_mj_kg": None, "chlorine_pct": None}
    assert intake["chlorine_status"] == "ok"
    assert intake["method_mix"] == "No accepted loads in this window"


def test_carbon_gross_and_net(ledger):
    result = fuel.carbon(ledger, "all", now=NOW)
    tj = 686.0 / 1000.0
    assert result["af_energy_gj"] == 686.0
    assert result["biogenic_share"] == 0.5
    assert result["coal_co2_displaced_t"] == round(tj * 96.1, 2)
    assert result["af_fossil_co2_t"] == round(tj * 91.7 * 0.5, 2)
    assert result["af_biogenic_co2_t"] == round(tj * 91.7 * 0.5, 2)
    assert result["net_co2_avoided_t"] == round(tj * 96.1 - tj * 91.7 * 0.5, 2)
    assert result["gcca"]["gross_emissions_from_af_t"] == result["af_fossil_co2_t"]
    assert "total kiln heat" in result["tsr"]["note"]
    assert "ghgprotocol.org" in result["sources"]["protocol"]
    assert "Assumption" in result["biogenic_share_note"]


def test_research_worked_example_one_tonne():
    # 1 t RDF at 16.7 GJ: about 1.60 t coal CO2 displaced, 0.77 t fossil, 0.8 net.
    tj = 16.7 / 1000.0
    assert round(tj * fuel.COAL_CO2_T_PER_TJ, 2) == 1.6
    assert round(tj * fuel.AF_CO2_T_PER_TJ * (1 - fuel.BIOGENIC_SHARE), 2) == 0.77
