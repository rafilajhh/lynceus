"""Lynceus gas digital twin — simulated gate readings above the waste bin.

The chain is assembled from the Lynceus engine; this module only wires
it into the Lynceus inspection pipeline:

1. ``composition.preset(waste_stream)`` — the stream's mass fractions
   (Table HH-1 wet-basis materials).
2. ``generation.generate()`` — instantaneous CH4 / CO2 mass rates [kg/h]
   from the regulatory first-order decay model (Eq. HH-1, 40 CFR 98).
3. A *simple dilution* converts each mass rate into a plausible ppmv
   concentration in the air sweeping the open bin.  The dilution is not
   measured physics: it is stated as a ``model assumption`` in the
   returned payload (engine provenance pattern — assumptions are
   labelled, never silently embedded).
4. ``virtual_sensor.step_response()`` — each concentration is read
   through a virtual sensor of the matching family (NDIR for CH4 and
   CO2, PID for TVOC, electrochemical for H2S), adding realistic lag and
   noise so the output looks like an instrument, not a formula.

Determinism: the pseudo-noise depends only on the sample index, which is
seeded from ``truck_id`` + ``record_id`` — the same truck and record
always produce identical readings, while different records differ.  The
returned dict contains no timestamps, so two calls with the same inputs
compare equal.

The Lynceus engine is imported lazily (on first call, not at module import)
so a process without the engine degrades into an honest "gas not measured"
inspection instead of an import failure.
"""

from __future__ import annotations

import hashlib
import math
from typing import Any, Dict

__all__ = [
    "GAS_SOURCE",
    "MODEL_BASIS",
    "ASSUMPTIONS",
    "GasTwinUnavailableError",
    "simulate_gate_readings",
]

#: Provenance tag stamped on every twin result (the source is stated,
#: never inferred — engine pattern 11).
GAS_SOURCE = "digital_twin"

#: Regulatory basis of the generation stage (engine generation.py).
MODEL_BASIS = "Eq. HH-1 40 CFR 98"

#: Ideal-gas molar volume at 25 °C, 1 atm [m3/kmol] (CRC Handbook).
MOLAR_VOLUME_M3_PER_KMOL = 24.465

#: Molar masses for the mass -> volume conversion [g/mol], mirroring the
#: constants the Lynceus engine generation module itself uses.
MOLAR_MASS_G_PER_MOL = {"CH4": 16.043, "CO2": 44.009}

#: model assumption — dilution air sweeping the open bin, per wet tonne
#: of load.  Chosen so a fresh dry RDF bale reads tens of ppm CH4 while
#: an old wet organic load reads hundreds of ppm, straddling the
#: decision layer's 100 ppm anaerobicity threshold.
DILUTION_AIR_FLOW_M3_PER_H_PER_TONNE = 6.0

#: AP-42 Table 2.4-2 default NMOC concentration in landfill gas, as the
#: hexane proxy [ppmv of LFG].
LFG_TVOC_FRACTION = 550.0e-6

#: AP-42 Table 2.4-1 default H2S concentration in landfill gas [ppmv of LFG].
LFG_H2S_FRACTION = 36.0e-6

#: The virtual sensor board: one channel per reported reading.
#: (family, range_ppm, detection_limit_ppm, response_time_s,
#:  recovery_time_s, noise_ppm, reading_decimals)
SENSOR_SPECS: Dict[str, tuple] = {
    "ch4": ("NDIR", 50_000.0, 0.5, 2.0, 5.0, 1.0, 2),
    "co2": ("NDIR", 50_000.0, 1.0, 2.0, 5.0, 3.0, 1),
    "tvoc": ("PID", 100.0, 0.005, 3.0, 8.0, 0.01, 3),
"h2s": ("Electrochemical", 100.0, 0.0005, 15.0, 30.0, 0.0002, 4),
}

#: Sampling cadence of the warm-up run [s].
STEP_S = 2.0

#: Warm-up length in response-time constants (5 tau -> 99.3 % settled).
SETTLING_TAUS = 5.0

#: Stated assumptions carried by every twin result.  The dilution is the
#: load-bearing simplification: a real bin has wind, depth gradients and
#: surface crusting, none of which a gate-side screening model can
#: resolve — so the assumption is stated instead of hidden.
ASSUMPTIONS: tuple = (
    {
        "name": "dilution_air_flow",
        "statement": (
            "Generated gas is instantly and uniformly diluted into an air "
            f"flow of {DILUTION_AIR_FLOW_M3_PER_H_PER_TONNE:.1f} m3/h per wet "
            "tonne of load sweeping the open bin surface."
        ),
        "provenance": "model assumption",
    },
    {
        "name": "trace_gas_scaling",
        "statement": (
            "TVOC (as the AP-42 hexane proxy) and H2S ride the generated "
            "landfill-gas stream at their AP-42 default concentrations "
            f"({LFG_TVOC_FRACTION * 1e6:.0f} ppmv and "
            f"{LFG_H2S_FRACTION * 1e6:.0f} ppmv of LFG)."
        ),
        "provenance": "model assumption",
    },
    {
        "name": "ambient_conditions",
        "statement": (
            "Sensor environment fixed at 25 °C and 50 % RH; sensors are "
            "freshly calibrated (no drift, no cross-sensitivity)."
        ),
        "provenance": "model assumption",
    },
    {
        "name": "molar_volume",
        "statement": (
            f"Ideal-gas molar volume {MOLAR_VOLUME_M3_PER_KMOL} m3/kmol "
            "at 25 °C, 1 atm."
        ),
        "provenance": "CRC Handbook of Chemistry and Physics, 97th ed.",
    },
)


class GasTwinUnavailableError(RuntimeError):
    """The Lynceus engine package is not importable in this process."""

    def __init__(self, detail: str) -> None:
        super().__init__(
            "the Lynceus engine package 'lynceus_engine' is not installed "
            f"or not importable in this process ({detail}); the gas digital "
            "twin requires it"
        )
        self.detail = detail


def _load_core() -> Any:
    """Lazily import the Lynceus engine core modules the twin needs.

    Importing this module must never import the engine: a deployment
    without the engine keeps a working Lynceus that simply reports gas
    as ``not_measured``.
    """
    try:
        import lynceus_engine as core  # type: ignore[import-untyped]
        import lynceus_engine.composition  # noqa: F401  (registers submodule)
        import lynceus_engine.generation  # noqa: F401
        import lynceus_engine.virtual_sensor  # noqa: F401
    except ImportError as exc:
        raise GasTwinUnavailableError(str(exc)) from exc
    return core


def _ppmv(
    rate_kg_per_h: float, molar_mass_g_per_mol: float, dilution_air_m3_per_h: float
) -> float:
    """Volume fraction [ppmv] of a gas emitted at ``rate_kg_per_h`` into a
    sweeping air flow of ``dilution_air_m3_per_h``.

    kg / (g/mol) is numerically kmol, so the volume flow is
    ``rate / molar_mass * molar_volume`` [m3/h]; the ppmv is that volume
    share of the dilution air times 1e6.
    """
    if rate_kg_per_h <= 0.0 or dilution_air_m3_per_h <= 0.0:
        return 0.0
    volume_m3_per_h = rate_kg_per_h / molar_mass_g_per_mol * MOLAR_VOLUME_M3_PER_KMOL
    return volume_m3_per_h / dilution_air_m3_per_h * 1e6


def _seed_sample_index(truck_id: str, record_id: str) -> int:
    """Deterministic noise seed from the truck and record identity."""
    digest = hashlib.sha256(f"{truck_id}|{record_id}".encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big")


def simulate_gate_readings(
    waste_stream: str,
    tonnage_t: float,
    moisture: float,
    age_h: float,
    *,
    truck_id: str = "",
    record_id: str = "",
) -> Dict[str, Any]:
    """Simulate one set of gas readings above the bin for a truck load.

    Args:
        waste_stream: an engine preset name (e.g. ``"mixed-msw"``);
            unknown names raise ``ValueError`` (from ``composition.preset``).
        tonnage_t: wet-basis batch tonnage in tonnes (>= 0).
        moisture: wet-basis moisture fraction in [0, 1].
        age_h: elapsed time since disposal, in hours.
        truck_id: truck identity, part of the deterministic noise seed.
        record_id: inspection record identity, part of the same seed —
            the same truck + record always reproduce the same readings.

    Returns:
        A JSON-friendly dict carrying ``readings_ppm`` (simulated sensor
        indications, one key per channel), ``source`` (:data:`GAS_SOURCE`)
        and ``model_basis`` (:data:`MODEL_BASIS`), plus the ground-truth
        concentrations, the generation-stage rates and the stated
        assumptions.  No timestamps: the dict is a pure function of its
        arguments.

    Raises:
        GasTwinUnavailableError: the Lynceus engine is not importable.
        ValueError: unknown preset, or numeric inputs outside the
            engine's domain (negative tonnage/age, moisture outside
            [0, 1]).
    """
    core = _load_core()
    composition, _preset_moisture = core.composition.preset(waste_stream)
    generation = core.generation.generate(
        composition, tonnage_t=tonnage_t, age_h=age_h, moisture=moisture
    )

    # --- model assumption: simple dilution into sweeping air ------------
    dilution_air_m3_per_h = (
        DILUTION_AIR_FLOW_M3_PER_H_PER_TONNE * max(float(tonnage_t), 0.0)
    )
    ch4_truth = _ppmv(
        generation.ch4_rate_kg_per_h, MOLAR_MASS_G_PER_MOL["CH4"], dilution_air_m3_per_h
    )
    co2_truth = _ppmv(
        generation.co2_rate_kg_per_h, MOLAR_MASS_G_PER_MOL["CO2"], dilution_air_m3_per_h
    )
    landfill_gas_ppm = ch4_truth + co2_truth
    ground_truth = {
        "ch4": ch4_truth,
        "co2": co2_truth,
        "tvoc": landfill_gas_ppm * LFG_TVOC_FRACTION,
        "h2s": landfill_gas_ppm * LFG_H2S_FRACTION,
    }

    # --- virtual sensors: deterministic lag + noise ----------------------
    seed = _seed_sample_index(truck_id, record_id)
    readings: Dict[str, float] = {}
    sensor_families: Dict[str, str] = {}
    for ordinal, (channel, spec) in enumerate(SENSOR_SPECS.items()):
        (
            family,
            range_ppm,
            detection_limit_ppm,
            response_time_s,
            recovery_time_s,
            noise_ppm,
            decimals,
        ) = spec
        config = core.virtual_sensor.VirtualSensorConfig(
            family=family,
            range_ppm=range_ppm,
            detection_limit_ppm=detection_limit_ppm,
            response_time_s=response_time_s,
            recovery_time_s=recovery_time_s,
            noise_ppm=noise_ppm,
        )
        steps = max(1, math.ceil(SETTLING_TAUS * response_time_s / STEP_S))
        previous_ppm = 0.0
        reading = None
        for step in range(steps):
            reading = core.virtual_sensor.step_response(
                config,
                ground_truth_ppm=ground_truth[channel],
                previous_ppm=previous_ppm,
                elapsed_s=step * STEP_S,
                step_s=STEP_S,
                sample_index=seed + ordinal * 997 + step,
            )
            previous_ppm = reading.indicated_ppm
        assert reading is not None  # steps >= 1, kept for type checkers
        readings[channel] = round(reading.indicated_ppm, decimals)
        sensor_families[channel] = family

    return {
        "readings_ppm": readings,
        "ground_truth_ppm": {key: round(value, 3) for key, value in ground_truth.items()},
        "source": GAS_SOURCE,
        "model_basis": MODEL_BASIS,
        "waste_stream": waste_stream,
        "tonnage_t": float(tonnage_t),
        "moisture": float(moisture),
        "age_h": float(age_h),
        "phase": generation.phase,
        "ch4_rate_kg_per_h": generation.ch4_rate_kg_per_h,
        "co2_rate_kg_per_h": generation.co2_rate_kg_per_h,
        "dilution_air_m3_per_h": round(dilution_air_m3_per_h, 3),
        "sensor_families": sensor_families,
        "assumptions": [dict(assumption) for assumption in ASSUMPTIONS],
    }
