"""Gas generation from waste composition, by the EPA's own regulatory model.

Implements Equation HH-1 of 40 CFR §98.343(a)(1):

    G_CH4 = Σ_x W_x · MCF · DOC · DOC_F · F · (16/12)
            · ( e^(-k(T-x-1)) - e^(-k(T-x)) )

That equation describes annual generation from waste placed in year ``x``. This
module applies the same first-order decay to a single batch of known mass and
known age, which is the question the app actually asks: *what is this load
producing, and how fast?*

Three quantities are kept distinct, because conflating them is what made a
fresh load read like a landfill:

* **Ultimate potential** — what the batch could produce if every degradable
  tonne decayed: :func:`ultimate_methane_yield` and :func:`ultimate_carbon_kg`.
  A property of the composition and the tonnage, not of the age.
* **Cumulative generated** — what has been produced by ``age_h``:
  ``Generation.ch4_cumulative_kg``. Monotone in age, zero at zero age.
* **Instantaneous rate** — what is being produced *now*:
  ``Generation.ch4_rate_kg_per_h``. The exact derivative of the cumulative
  curve, so the two can never disagree.

The methane term uses the regulation's measurement-replaceable default fraction
``F = 0.5`` (Table HH-1 to Subpart HH) at every age. Assigning the remaining
degraded carbon to CO2 is a model assumption, not a stoichiometric split stated
by the regulation. The AP-42 p.2.4-3 steady-state mix (55% CH4 / 40% CO2 /
5% N2) remains a measured mature-landfill comparison, never the generated mix.

Because the split does not depend on age, the generation curve is continuous:
no phase boundary switches methane on or off. The phase label
(:func:`composition.phase_for`) is recorded as an interpretation of the curve
and gates no number.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from lynceus_engine.composition import (
    CARBON_MOLAR_MASS,
    DISSIMILATED_DOC_FRACTION,
    LANDFILL_GAS_METHANE_FRACTION,
    METHANE_CORRECTION_FACTOR,
    METHANE_DENSITY_KG_PER_M3,
    METHANE_MOLAR_MASS,
    PhaseInterpretation,
    WasteComposition,
    interpret_phase,
    phase_for,
)

HOURS_PER_YEAR = 24.0 * 365.25

#: Stoichiometric CH4/C mass ratio. The regulation writes it as exactly 16/12,
#: so the exact ratio is used rather than a ratio of precise molar masses: the
#: point of this module is to reproduce the regulatory equation, and using
#: 16.043/12.011 would silently disagree with it by 0.2%.
STOICHIOMETRIC_RATIO = 16.0 / 12.0

#: Molar masses for converting a mass of gas to its molar (volume) share.
CO2_MOLAR_MASS = 44.009
MOLAR_MASS_G_PER_MOL = {"CH4": METHANE_MOLAR_MASS, "CO2": CO2_MOLAR_MASS}

#: Internal alias kept so the module's own arithmetic reads unchanged.
_MOLAR_MASS = MOLAR_MASS_G_PER_MOL

#: CO2/C mass ratio for the carbon that does not leave as methane. The
#: regulation fixes only the CH4 conversion (16/12); CO2 uses molar masses.
CO2_CARBON_RATIO = CO2_MOLAR_MASS / CARBON_MOLAR_MASS

#: AP-42 p.2.4-3 steady-state composition, by volume: 55% CH4, 40% CO2, 5% N2.
#: Kept as a measured mature-landfill ceiling for interpretation and comparison;
#: it is **not** the mixture this model produces (that is F = 0.5).
STEADY_STATE_MIX = {"CH4": 55.0, "CO2": 40.0, "N2": 5.0}


@dataclass(frozen=True)
class Generation:
    """Gas produced by one batch at a given age.

    ``phase`` is an interpretation of ``age_h`` and gates no number here.
    """

    phase: str
    age_h: float
    tonnage_t: float
    doc: float
    k_per_year: float
    decay_fraction: float
    ultimate_ch4_kg_per_t: float
    ultimate_ch4_m3_per_t: float
    ultimate_ch4_kg: float
    ch4_cumulative_kg: float
    ch4_cumulative_m3: float
    co2_cumulative_kg: float
    ch4_rate_kg_per_h: float
    co2_rate_kg_per_h: float
    methane_fraction: float
    gases: tuple[str, ...]
    notes: tuple[str, ...]
    phase_interpretation: PhaseInterpretation


def ultimate_methane_yield(composition: WasteComposition) -> tuple[float, float]:
    """Ultimate CH4 per tonne of waste [kg/t, m3/t], with all carbon degraded.

    The HH-1 sum with the decay factors omitted, which is the ceiling a batch
    approaches as ``age`` grows without bound.
    """
    doc = composition.weighted_doc()
    kg_per_t = (
        1000.0
        * METHANE_CORRECTION_FACTOR
        * doc
        * DISSIMILATED_DOC_FRACTION
        * LANDFILL_GAS_METHANE_FRACTION
        * STOICHIOMETRIC_RATIO
    )
    return kg_per_t, kg_per_t / METHANE_DENSITY_KG_PER_M3


def ultimate_carbon_kg(composition: WasteComposition, tonnage_t: float) -> float:
    """Dissimilated carbon in the batch once every degradable tonne has decayed."""
    return (
        1000.0
        * composition.weighted_doc()
        * DISSIMILATED_DOC_FRACTION
        * tonnage_t
    )


def decay_fraction(k_per_year: float, age_h: float) -> float:
    """Fraction of the ultimate yield reached by ``age_h``.

    ``1 - e^(-k·Δt)``: the same first-order form as HH-1, evaluated for a single
    batch instead of summed over disposal years.
    """
    if k_per_year < 0.0:
        raise ValueError("k_per_year must not be negative")
    if age_h < 0.0:
        raise ValueError("age_h must not be negative")
    return 1.0 - math.exp(-k_per_year * (age_h / HOURS_PER_YEAR))


def co2_from_carbon(carbon_kg: float) -> float:
    """CO2 mass from the carbon share the methane fraction leaves behind.

    ``(1 - F)`` of the degraded carbon is oxidised to CO2; the rest leaves as
    CH4. CO2 carries the carbon at ``44.009 / 12.011`` by mass.
    """
    if carbon_kg < 0.0:
        raise ValueError("carbon_kg must not be negative")
    return carbon_kg * (1.0 - LANDFILL_GAS_METHANE_FRACTION) * CO2_CARBON_RATIO


def carbon_rate_kg_per_h(
    composition: WasteComposition,
    tonnage_t: float,
    *,
    k_per_year: float,
    age_h: float,
) -> float:
    """Instantaneous degraded-carbon rate: the derivative of the decay curve.

    ``d/dt [ C_ult · (1 - e^(-k·t)) ] = C_ult · k · e^(-k·t)``. This is what
    makes the rate the same model as the cumulative mass rather than a second,
    independently-tuned one.
    """
    if age_h < 0.0:
        raise ValueError("age_h must not be negative")
    return (
        ultimate_carbon_kg(composition, tonnage_t)
        * k_per_year
        / HOURS_PER_YEAR
        * math.exp(-k_per_year * age_h / HOURS_PER_YEAR)
    )


def generate(
    composition: WasteComposition,
    *,
    tonnage_t: float,
    age_h: float,
    moisture: float,
    gases: tuple[str, ...] | None = None,
) -> Generation:
    """Gas produced by ``tonnage_t`` tonnes of ``composition`` at ``age_h``.

    ``gases`` is the phase's allowable set; when omitted it is derived from the
    phase. The *amounts* do not consult the phase: methane exists from the first
    hour, in the regulation's ``F`` share, and grows continuously with age.
    """
    if tonnage_t < 0.0:
        raise ValueError("tonnage_t must not be negative")
    if not 0.0 <= moisture <= 1.0:
        raise ValueError("moisture must be in [0, 1]")
    if age_h < 0.0:
        raise ValueError("age_h must not be negative")

    phase = phase_for(age_h)
    interpretation = interpret_phase(age_h)
    doc = composition.weighted_doc()
    k = composition.weighted_decay(moisture)
    fraction = decay_fraction(k, age_h)
    kg_per_t, m3_per_t = ultimate_methane_yield(composition)

    carbon_kg = ultimate_carbon_kg(composition, tonnage_t) * fraction
    ch4_cumulative_kg = (
        carbon_kg * LANDFILL_GAS_METHANE_FRACTION * STOICHIOMETRIC_RATIO
    )
    co2_cumulative_kg = co2_from_carbon(carbon_kg)
    ch4_cumulative_m3 = ch4_cumulative_kg / METHANE_DENSITY_KG_PER_M3
    ultimate_ch4_kg = kg_per_t * tonnage_t

    carbon_rate = carbon_rate_kg_per_h(
        composition, tonnage_t, k_per_year=k, age_h=age_h
    )
    ch4_rate_kg_per_h = (
        carbon_rate * LANDFILL_GAS_METHANE_FRACTION * STOICHIOMETRIC_RATIO
    )
    co2_rate_kg_per_h = co2_from_carbon(carbon_rate)

    # The methane volume share over the produced gas. With F = 0.5 the two
    # species carry the same molar carbon, so this sits at ~0.5; the exact value
    # differs slightly because the regulation's 16/12 is not the molar-mass
    # ratio. The AP-42 55% steady state is a ceiling, not a target.
    moles_ch4 = ch4_cumulative_kg / (_MOLAR_MASS["CH4"] / 1000.0)
    moles_co2 = co2_cumulative_kg / (_MOLAR_MASS["CO2"] / 1000.0)
    total_moles = moles_ch4 + moles_co2
    methane_fraction = moles_ch4 / total_moles if total_moles > 0.0 else 0.0

    notes: list[str] = []
    if methane_fraction > STEADY_STATE_MIX["CH4"] / 100.0 + 1e-9:
        # Unreachable while the split is F-based; kept as an assertion of the
        # ceiling rather than a silent clamp.
        raise AssertionError(
            f"methane volume fraction {methane_fraction:.4f} exceeds the AP-42 "
            f"measured ceiling {STEADY_STATE_MIX['CH4'] / 100.0}"
        )
    if composition.inert >= 1.0:
        notes.append("composition is entirely inert: no gas is produced")
    if moisture < 0.15:
        notes.append("dry load: decay rate is at the low end of the cited range")

    allowed = gases if gases is not None else PHASE_GASES_FOR(phase)
    return Generation(
        phase=phase,
        age_h=age_h,
        tonnage_t=tonnage_t,
        doc=doc,
        k_per_year=k,
        decay_fraction=fraction,
        ultimate_ch4_kg_per_t=kg_per_t,
        ultimate_ch4_m3_per_t=m3_per_t,
        ultimate_ch4_kg=ultimate_ch4_kg,
        ch4_cumulative_kg=ch4_cumulative_kg,
        ch4_cumulative_m3=ch4_cumulative_m3,
        co2_cumulative_kg=co2_cumulative_kg,
        ch4_rate_kg_per_h=ch4_rate_kg_per_h,
        co2_rate_kg_per_h=co2_rate_kg_per_h,
        methane_fraction=methane_fraction,
        gases=allowed,
        notes=tuple(notes),
        phase_interpretation=interpretation,
    )


def PHASE_GASES_FOR(phase: str) -> tuple[str, ...]:  # noqa: N802 - mirrors the constant
    """Gases a phase can produce, from :data:`composition.PHASE_GASES`."""
    from lynceus_engine.composition import PHASE_GASES

    if phase not in PHASE_GASES:
        raise ValueError(f"unknown phase {phase!r}")
    return PHASE_GASES[phase]
