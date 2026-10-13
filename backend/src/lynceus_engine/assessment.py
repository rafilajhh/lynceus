"""RDF suitability and exposure-threshold assessment from recorded gas data.

Two outputs, both computed from data the pipeline actually has:

* **Exposure thresholds** — the peak sampled concentration of each gas against a
  published occupational limit. Only gases with a defensible limit are checked;
  a gas with no published limit is reported as unchecked rather than given an
  invented one.
* **Halogen and sulfur loading** — the gas-phase chlorine and sulfur carried by
  the AP-42 Table 2.4-1 trace species, in mg/Nm³. This is the emission potential
  of the waste, not the fuel-basis composition an RDF offtaker buys.

The fuel-basis properties an EN 15359 / ISO 21640 class needs — net calorific
value, ash, and chlorine as a percentage of dry mass — require a laboratory
analysis of the material itself. They are reported as needing that analysis and
never estimated here: the gas phase cannot tell you the mass of the fuel, so any
number derived from it would be a fabrication.

Provenance for every limit and atomic count is in ``docs/references.md``.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from lynceus_engine.gas_defaults import AP42_TRACE_COMPOUNDS

#: Molar volume at 25 °C, 1 atm [L/mol]. The ppmv → mg/m³ conversion is
#: ``ppmv × atoms × atomic_mass / 24.45``: one m³ holds 1000/24.45 mol of air.
MOLAR_VOLUME_L_PER_MOL = 24.45

CL_ATOMIC_MASS = 35.45
S_ATOMIC_MASS = 32.06

#: Chlorine and sulfur atoms per molecule, for every AP-42 Table 2.4-1 trace
#: species that carries one. Counted from the molecular formula implied by each
#: compound name; a species absent from this table contributes nothing to
#: either loading, so an unlisted halogenated compound under-reports rather
#: than being guessed. Mercury is absent by nature, not by omission: it is an
#: element with no molecular formula, so it carries no Cl or S atoms.
HALOGEN_ATOMS: dict[str, tuple[int, int]] = {
    "1,1,1-Trichloroethane (methyl chloroform)a": (3, 0),
    "1,1,2,2-Tetrachloroethanea": (4, 0),
    "1,1-Dichloroethane (ethylidene dichloride)a": (2, 0),
    "1,1-Dichloroethene (vinylidene chloride)a": (2, 0),
    "1,2-Dichloroethane (ethylene dichloride)a": (2, 0),
    "1,2-Dichloropropane (propylene dichloride)a": (2, 0),
    "Bromodichloromethane": (2, 0),
    "Carbon disulfidea": (0, 2),
    "Carbon tetrachloridea": (4, 0),
    "Carbonyl sulfidea": (0, 1),
    "Chlorobenzenea": (1, 0),
    "Chlorodifluoromethane": (1, 0),
    "Chloroethane (ethyl chloride)a": (1, 0),
    "Chloroforma": (3, 0),
    "Chloromethane": (1, 0),
    "Dichlorobenzenec": (2, 0),
    "Dichlorodifluoromethane": (2, 0),
    "Dichlorofluoromethane": (2, 0),
    "Dichloromethane (methylene chloride)a": (2, 0),
    "Dimethyl sulfide (methyl sulfide)": (0, 1),
    "Ethyl mercaptan (ethanethiol)": (0, 1),
    "Fluorotrichloromethane": (3, 0),
    "Hydrogen sulfide": (0, 1),
    "Methyl mercaptan": (0, 1),
    "Perchloroethylene (tetrachloroethylene)a": (4, 0),
    "t-1,2-dichloroethene": (2, 0),
    "Trichloroethylene (trichloroethene)a": (3, 0),
    "Vinyl chloridea": (1, 0),
}


@dataclass(frozen=True)
class ExposureLimit:
    """A published occupational exposure limit for one gas."""

    gas: str
    limit_ppmv: float
    name: str
    citation: str


#: Gases with a published limit. A gas that is sampled but absent here is
#: reported as unchecked — no limit is inferred from a similar compound.
EXPOSURE_LIMITS: dict[str, ExposureLimit] = {
    "H2S": ExposureLimit(
        "H2S", 10.0, "NIOSH REL (10-minute ceiling)", "NIOSH Pocket Guide, hydrogen sulfide"
    ),
    "CO": ExposureLimit(
        "CO", 35.0, "NIOSH REL (8-hour TWA)", "NIOSH Pocket Guide, carbon monoxide"
    ),
    "CH4": ExposureLimit(
        "CH4", 50_000.0, "Lower explosive limit (5 vol% in air)", "Methane LEL, NFPA 69"
    ),
    "VOC": ExposureLimit(
        "VOC",
        50.0,
        "NIOSH REL for n-hexane (8-hour TWA); VOC is solved as a hexane proxy",
        "NIOSH Pocket Guide, hexane",
    ),
    "BENZENE": ExposureLimit(
        "BENZENE", 0.1, "NIOSH REL (8-hour TWA)", "NIOSH Pocket Guide, benzene"
    ),
    "TOLUENE": ExposureLimit(
        "TOLUENE", 100.0, "NIOSH REL (8-hour TWA)", "NIOSH Pocket Guide, toluene"
    ),
    "VINYL_CHLORIDE": ExposureLimit(
        "VINYL_CHLORIDE",
        1.0,
        "NIOSH REL (8-hour TWA)",
        "NIOSH Pocket Guide, vinyl chloride",
    ),
    "METHYL_MERCAPTAN": ExposureLimit(
        "METHYL_MERCAPTAN",
        0.5,
        "NIOSH REL (8-hour TWA)",
        "NIOSH Pocket Guide, methyl mercaptan",
    ),
}


@dataclass(frozen=True)
class ThresholdCheck:
    """One sampled gas against its published limit."""

    gas: str
    peak_ppmv: float
    peak_sensor: str
    limit_ppmv: float
    limit_name: str
    citation: str

    @property
    def ratio(self) -> float:
        """Peak divided by the limit; above 1.0 is an exceedance."""
        return self.peak_ppmv / self.limit_ppmv

    @property
    def exceeds(self) -> bool:
        return self.peak_ppmv > self.limit_ppmv


@dataclass(frozen=True)
class HalogenLoad:
    """Gas-phase chlorine and sulfur carried by the trace species, in mg/Nm³."""

    chlorine_mg_per_nm3: float
    sulfur_mg_per_nm3: float
    chlorine_species: tuple[tuple[str, float], ...]
    sulfur_species: tuple[tuple[str, float], ...]
    unparsed: tuple[str, ...]


@dataclass(frozen=True)
class RdfAssessment:
    """What can be said about RDF suitability from gas data alone."""

    halogen: HalogenLoad
    threshold_checks: tuple[ThresholdCheck, ...]
    unchecked_gases: tuple[str, ...]
    peak_to_mean: dict[str, float]
    moisture_fraction: float | None


def parse_ppmv(value: object) -> float | None:
    """Parse an AP-42 concentration cell, or ``None`` when it is not a number.

    The generated tables carry footnote-marked strings: ``"4.0x10-3"`` and
    ``"3.0x10-2"`` are scientific notation, and a trailing letter such as
    ``"110e"`` is a footnote marker on a plain value.
    """
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None
    text = value.strip().lower().replace(" ", "")
    for marker in ("x10", "×10"):
        text = text.replace(marker, "e")
    while text and text[-1].isalpha():
        text = text[:-1]
    try:
        return float(text)
    except ValueError:
        return None


def halogen_load() -> HalogenLoad:
    """Chlorine and sulfur carried by the AP-42 Table 2.4-1 trace species.

    Concentrations are the cited table defaults: they describe uncontrolled
    landfill gas, and no waste-stream scaling is applied because the chlorinated
    and sulfur species come from manufactured materials rather than from the
    organic fraction that drives CH₄ and NMOC.
    """
    chlorine_total = 0.0
    sulfur_total = 0.0
    chlorine_species: list[tuple[str, float]] = []
    sulfur_species: list[tuple[str, float]] = []
    unparsed: list[str] = []

    for name, (cl_atoms, s_atoms) in HALOGEN_ATOMS.items():
        entry = AP42_TRACE_COMPOUNDS.get(name)
        if not isinstance(entry, dict):
            unparsed.append(name)
            continue
        ppmv = parse_ppmv(entry.get("conc_ppmv"))
        if ppmv is None:
            unparsed.append(name)
            continue
        if cl_atoms:
            mass = ppmv * cl_atoms * CL_ATOMIC_MASS / MOLAR_VOLUME_L_PER_MOL
            chlorine_total += mass
            chlorine_species.append((name, mass))
        if s_atoms:
            mass = ppmv * s_atoms * S_ATOMIC_MASS / MOLAR_VOLUME_L_PER_MOL
            sulfur_total += mass
            sulfur_species.append((name, mass))

    chlorine_species.sort(key=lambda item: item[1], reverse=True)
    sulfur_species.sort(key=lambda item: item[1], reverse=True)
    return HalogenLoad(
        chlorine_mg_per_nm3=chlorine_total,
        sulfur_mg_per_nm3=sulfur_total,
        chlorine_species=tuple(chlorine_species),
        sulfur_species=tuple(sulfur_species),
        unparsed=tuple(unparsed),
    )


def _values_of(reading: object) -> dict[str, float]:
    """The gas→concentration map of a reading, whichever shape it arrives in.

    ``history.ReadingRecord`` carries ``values_ppmv``; the live
    ``results_panel.SensorReading`` carries ``values``. Both are plain dicts.
    """
    values = getattr(reading, "values_ppmv", None)
    if values is None:
        values = getattr(reading, "values", None)
    return values if isinstance(values, dict) else {}


def threshold_checks(readings: Iterable[object]) -> tuple[list[ThresholdCheck], list[str]]:
    """Peak per gas against its published limit, plus the gases with no limit.

    ``readings`` are anything with ``sensor_id`` and a per-gas value mapping, so
    both persisted ``ReadingRecord`` objects and live ``SensorReading`` objects
    work without conversion.
    """
    peaks: dict[str, tuple[float, str]] = {}
    for reading in readings:
        sensor_id = getattr(reading, "sensor_id", "?")
        for gas, value in _values_of(reading).items():
            current = peaks.get(gas)
            if current is None or value > current[0]:
                peaks[gas] = (float(value), sensor_id)
    checks = [
        ThresholdCheck(
            gas=gas,
            peak_ppmv=peak,
            peak_sensor=sensor,
            limit_ppmv=limit.limit_ppmv,
            limit_name=limit.name,
            citation=limit.citation,
        )
        for gas, (peak, sensor) in sorted(peaks.items())
        if (limit := EXPOSURE_LIMITS.get(gas)) is not None
    ]
    unchecked = sorted(gas for gas in peaks if gas not in EXPOSURE_LIMITS)
    return checks, unchecked


def peak_to_mean(readings: Iterable[object]) -> dict[str, float]:
    """Per-gas peak divided by the mean across sensors.

    One is a uniform field; larger values mean the plume reaches only part of the
    placement, which is what a sensor network has to cover.
    """
    samples: dict[str, list[float]] = {}
    for reading in readings:
        for gas, value in _values_of(reading).items():
            samples.setdefault(gas, []).append(float(value))
    ratios: dict[str, float] = {}
    for gas, values in samples.items():
        mean = sum(values) / len(values)
        if mean > 0.0:
            ratios[gas] = max(values) / mean
    return ratios


def evaluate(readings: Iterable[object], *, moisture_fraction: float | None = None) -> RdfAssessment:
    """Everything the gas data supports, in one pass."""
    readings = list(readings)
    checks, unchecked = threshold_checks(readings)
    return RdfAssessment(
        halogen=halogen_load(),
        threshold_checks=tuple(checks),
        unchecked_gases=tuple(unchecked),
        peak_to_mean=peak_to_mean(readings),
        moisture_fraction=moisture_fraction,
    )


def suitability_verdict(assessment: RdfAssessment) -> str:
    """One line on what the gas data does and does not establish.

    The verdict is deliberately about evidence, not about a fuel grade: without a
    laboratory analysis of the material there is no defensible RDF class, and
    saying otherwise would put a fabricated number in front of a decision.
    """
    chlorine = assessment.halogen.chlorine_mg_per_nm3
    sulfur = assessment.halogen.sulfur_mg_per_nm3
    return (
        f"Gas-phase loading Cl {chlorine:.1f} mg/Nm³, S {sulfur:.1f} mg/Nm³. "
        "Fuel-basis class (NCV, Cl %, ash) needs laboratory characterisation."
    )
