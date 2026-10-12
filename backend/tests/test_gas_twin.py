"""Unit tests for the gas digital twin and its decision-layer integration.

Covers the assignment's acceptance criteria:

* determinism — the same inputs (truck + record) produce identical
  readings, twice in a row;
* physical ordering — an old, wet, organic load reads higher CH4 than a
  dry, young load of the same stream family;
* the ``gas_plausibility`` gate — active when data exists, ``failed``
  for an old organic load claimed dry, honest ``not_run`` when absent,
  and never able to change the verdict on its own.

The Scentinel engine is required; these tests are skipped cleanly when
it is not importable (mirroring the e2e suite's treatment of the
engine-dependent paths).
"""

from __future__ import annotations

import pytest

from lynceus import decision, gas_twin, pipeline
from lynceus.audit import Decision, GateState

pytest.importorskip("scentinel.core", reason="gas twin requires the Scentinel engine")


#: A waybill claiming a dry load (the conflict trigger).
_DRY_MANIFEST = (
    "DUTY OF CARE — WASTE TRANSFER NOTE\n"
    "Producer: Eco RDF Processing Plant 2\n"
    "Waste type: SRF / RDF fluff, pre-sorted, baled\n"
    "Declared weight: 12,000 kg\n"
    "Moisture declared: 10% (dry, stored under cover)\n"
    "Collected: 2026-10-09 08:00 UTC"
)

#: A waybill declaring a wet organic mix (no conflict).
_WET_MANIFEST = (
    "DUTY OF CARE — WASTE TRANSFER NOTE\n"
    "Producer: TPA Suwung transfer station\n"
    "Waste type: organic-rich source-separated biowaste\n"
    "Declared weight: 11,200 kg\n"
    "Moisture declared: 45%\n"
    "Collected: 2026-10-09 08:00 UTC"
)


# ---------------------------------------------------------------------------
# 1. Determinism: same inputs -> byte-identical readings, twice.
# ---------------------------------------------------------------------------


def test_gas_twin_is_deterministic_for_same_inputs():
    first = gas_twin.simulate_gate_readings(
        "organic-rich", 10.0, 0.60, 96.0, truck_id="B-9174-KT", record_id="inspection-000001"
    )
    second = gas_twin.simulate_gate_readings(
        "organic-rich", 10.0, 0.60, 96.0, truck_id="B-9174-KT", record_id="inspection-000001"
    )
    assert first == second, "same truck + record must reproduce identical twin output"
    assert first["readings_ppm"] == second["readings_ppm"]
    assert first["readings_ppm"]["ch4"] > 0.0


def test_gas_twin_noise_seed_depends_on_record_identity():
    """Different records legitimately differ (per-sample noise), but the
    *ground truth* — the physics — must be identical for the same load."""
    first = gas_twin.simulate_gate_readings(
        "organic-rich", 10.0, 0.60, 96.0, truck_id="B-9174-KT", record_id="inspection-000001"
    )
    second = gas_twin.simulate_gate_readings(
        "organic-rich", 10.0, 0.60, 96.0, truck_id="B-9174-KT", record_id="inspection-000002"
    )
    assert first["ground_truth_ppm"] == second["ground_truth_ppm"]
    assert first["readings_ppm"] != second["readings_ppm"], (
        "the deterministic noise should differ once the seed (record) changes"
    )


def test_gas_twin_result_shape_and_provenance():
    result = gas_twin.simulate_gate_readings(
        "mixed-msw", 12.0, 0.40, 48.0, truck_id="T-1", record_id="inspection-000003"
    )
    assert result["source"] == "digital_twin"
    assert result["model_basis"] == "Eq. HH-1 40 CFR 98"
    assert set(result["readings_ppm"]) == {"ch4", "co2", "tvoc", "h2s"}
    assert all(value >= 0.0 for value in result["readings_ppm"].values())
    # Sensor families: NDIR for CH4/CO2, PID for TVOC, electrochemical for H2S.
    assert result["sensor_families"]["ch4"] == "NDIR"
    assert result["sensor_families"]["co2"] == "NDIR"
    assert result["sensor_families"]["tvoc"] == "PID"
    assert result["sensor_families"]["h2s"] == "Electrochemical"
    # The dilution assumption is stated, labelled 'model assumption'.
    names = {a["name"] for a in result["assumptions"]}
    assert "dilution_air_flow" in names
    for assumption in result["assumptions"]:
        assert assumption["provenance"]


# ---------------------------------------------------------------------------
# 2. Physical ordering: old wet organic > dry young load.
# ---------------------------------------------------------------------------


def test_old_organic_load_reads_higher_ch4_than_dry_young_load():
    old_organic = gas_twin.simulate_gate_readings(
        "organic-rich", 10.0, 0.60, 96.0, truck_id="T-1", record_id="inspection-000010"
    )
    young_dry = gas_twin.simulate_gate_readings(
        "rdf-feedstock", 10.0, 0.095, 5.0, truck_id="T-2", record_id="inspection-000011"
    )
    assert (
        old_organic["readings_ppm"]["ch4"]
        > young_dry["readings_ppm"]["ch4"]
    ), (
        "an old wet organic load must read higher CH4 than a dry young one: "
        f"got {old_organic['readings_ppm']['ch4']} vs {young_dry['readings_ppm']['ch4']}"
    )
    # And the old organic load must actually be strongly anaerobic so the
    # gas gate's 100 ppm threshold is exercised by this scenario.
    assert old_organic["readings_ppm"]["ch4"] > gas_twin_threshold()


def gas_twin_threshold() -> float:
    """The decision layer's CH4 anaerobicity threshold (ppmv)."""
    return decision.GAS_CH4_ANAEROBIC_THRESHOLD_PPM


# ---------------------------------------------------------------------------
# 3. The gas_plausibility gate in the decision layer.
# ---------------------------------------------------------------------------


def _decide(gas: object, manifest: str, moisture: float):
    """Run the fusion layer with a clean VLM/LLM pair and the given gas."""
    inputs = {
        "truck_id": "T-1",
        "photo_base64": "c3R1Yi1waG90bw==",
        "manifest_text": manifest,
        "moisture": moisture,
        "gas": gas,
    }
    vlm = {"detected": {"contamination": "none detected", "moisture": 0.10}, "confidence": 0.9}
    llm = {"reasoning": "consistent", "confidence": 0.9, "crosscheck_failed": False}
    verdict, gates, _reasons = decision.decide(inputs, vlm, llm, None)
    return verdict, gates


def test_gas_gate_fails_for_old_organic_load_claimed_dry():
    """Acceptance scenario: old + wet organic load with a dry waybill —
    the twin reads strongly anaerobic CH4, the gate must fail."""
    twin = pipeline._simulate_gas_readings(
        {
            "truck_id": "F-7702-TS",
            "weight_kg": 12000,
            "waste_stream": "organic-rich",
            "moisture": 0.62,  # the load is actually wet and old
            "age_h": 96,
        },
        "inspection-000042",
    )
    assert twin is not None, "the twin must run for a complete batch description"
    assert twin["readings_ppm"]["ch4"] > gas_twin_threshold()

    verdict, gates = _decide(
        {"readings_ppm": twin["readings_ppm"]}, _DRY_MANIFEST, 0.10
    )
    assert gates["gas_plausibility"]["state"] == GateState.FAILED
    assert gates["gas_plausibility"]["value"] == pytest.approx(
        twin["readings_ppm"]["ch4"]
    )


def test_gas_gate_passes_when_reading_matches_wet_claim():
    twin = gas_twin.simulate_gate_readings(
        "organic-rich", 11.45, 0.57, 76.0, truck_id="DK-4418-WR", record_id="r-1"
    )
    verdict, gates = _decide(
        {"readings_ppm": twin["readings_ppm"]}, _WET_MANIFEST, 0.57
    )
    assert twin["readings_ppm"]["ch4"] > gas_twin_threshold()
    assert gates["gas_plausibility"]["state"] == GateState.PASSED


def test_gas_gate_not_run_without_gas_data():
    for absent in (None, {}, {"readings_ppm": {}}):
        _verdict, gates = _decide(absent, _DRY_MANIFEST, 0.10)
        assert gates["gas_plausibility"]["state"] == GateState.NOT_RUN


def test_gas_gate_never_overrides_the_verdict():
    """Supporting gate only: identical inputs must yield an identical
    verdict whether the gas channel failed, passed or was absent."""
    verdicts = set()
    for gas in (
        None,
        {"readings_ppm": {"ch4": 54.0}},
        {"readings_ppm": {"ch4": 234.0}},  # failed gate, same verdict
    ):
        verdict, gates = _decide(gas, _DRY_MANIFEST, 0.10)
        verdicts.add(verdict)
    assert len(verdicts) == 1, (
        f"the gas channel must not change the verdict; got {verdicts!r}"
    )
    assert verdicts.pop() == Decision.ACCEPT
