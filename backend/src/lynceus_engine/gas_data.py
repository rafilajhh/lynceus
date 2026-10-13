"""Gas table loader: reads the generated AP-42 defaults and exposes them per gas."""

from __future__ import annotations

from dataclasses import dataclass

from lynceus_engine.gas_defaults import GAS_PROPERTIES, SOURCE_DEFAULTS

REGIMES = ("msw-only", "co-disposal")

#: Gas keys offered as scenario sources, in display order: the AP-42 headline
#: gases first, then the added trace species grouped by chemical family
#: (hydrocarbon, aromatics, chlorinated, sulfur).
#: Headline gases, shown first and selected by default on a new project.
HEADLINE_GASES = ("CO", "CH4", "VOC", "H2S")

#: The full cited catalogue from AP-42 Tables 2.4-1 and 2.4-2, grouped by
#: chemical family. Every entry carries a value, a rating, and a basis string
#: read out of the workbook by ``scripts/build_gas_data.py``; none is estimated.
#: Grouping exists so a 47-item list stays navigable in the UI.
GAS_FAMILIES: dict[str, tuple[str, ...]] = {
    "headline": HEADLINE_GASES,
    "sulfur": (
        "METHYL_MERCAPTAN",
        "ETHYL_MERCAPTAN",
        "DIMETHYL_SULFIDE",
        "CARBON_DISULFIDE",
        "CARBONYL_SULFIDE",
    ),
    "aromatic": ("BENZENE", "TOLUENE", "ETHYLBENZENE", "XYLENES", "CHLOROBENZENE", "DICHLOROBENZENE"),
    "alkane": ("ETHANE", "PROPANE", "BUTANE", "PENTANE", "HEXANE"),
    "oxygenate": (
        "ACETONE",
        "METHYL_ETHYL_KETONE",
        "METHYL_ISOBUTYL_KETONE",
        "ETHANOL",
        "PROPANOL_2",
    ),
    "chlorinated": (
        "VINYL_CHLORIDE",
        "DICHLOROMETHANE",
        "CHLOROFORM",
        "CARBON_TETRACHLORIDE",
        "TRICHLOROETHANE_111",
        "TRICHLOROETHYLENE",
        "PERCHLOROETHYLENE",
        "TETRACHLOROETHANE_1122",
        "DICHLOROETHANE_11",
        "DICHLOROETHANE_12",
        "DICHLOROETHENE_11",
        "T_DICHLOROETHENE_12",
        "DICHLOROPROPANE_12",
        "CHLOROMETHANE",
        "CHLOROETHANE",
        "BROMODICHLOROMETHANE",
        "ETHYLENE_DIBROMIDE",
    ),
    "halocarbon": (
        "DICHLORODIFLUOROMETHANE",
        "DICHLOROFLUOROMETHANE",
        "CHLORODIFLUOROMETHANE",
        "FLUOROTRICHLOROMETHANE",
    ),
    "other": ("ACRYLONITRILE",),
}

#: Every selectable gas, headline first, then by family in the order above.
DEFAULT_SOURCE_GASES = tuple(
    dict.fromkeys(gas for family in GAS_FAMILIES.values() for gas in family)
)


@dataclass(frozen=True)
class GasApplicability:
    """Which decomposition phases a gas applies to, and how well we know.

    The AP-42 Table 2.4-1 values are landfill-gas measurements: they describe an
    aged, anaerobic landfill. Offering them for a fresh, aerobic bin would be the
    same basis error the generation model was fixed for, so each gas states the
    phases it applies to and the uncertainty of using it outside them.
    """

    phases: tuple[str, ...]
    source: str
    uncertainty: str


#: Gases that exist in every phase. CO2 and the trace odour species are produced
#: aerobically as well as anaerobically; CO is a combustion/oxidation product
#: present throughout.
_ALL_PHASES = ("I", "II", "III", "IV")
#: Methanogenic phases only. Methane is not produced in a fresh aerobic load.
_METHANOGENIC = ("III", "IV")

_AP42_LANDFILL = "AP-42 Ch.2.4 Table 2.4-1, landfill gas (aged, anaerobic)"
_AP42_PHASE_I_NOTE = (
    "The table value is a landfill measurement; using it for a fresh aerobic "
    "load is an extrapolation, and the true fresh-bin strength is not cited here."
)
_AP42_TRANSITION_NOTE = (
    "The table value is a mature-landfill measurement; the transition phase is "
    "between aerobic and anaerobic and the value applies only approximately."
)
_AP42_APPLIES = "The table value describes this anaerobic phase directly."

#: Gases deliberately offered for a phase-I load. Their catalogue strengths
#: still come from mature-landfill measurements and retain that evidence-gap
#: warning; other catalogue entries are withheld entirely for phase I.
_PHASE_I_OFFERED = frozenset(
    {
        "CO",
        "H2S",
        "METHYL_MERCAPTAN",
        "ETHYL_MERCAPTAN",
        "DIMETHYL_SULFIDE",
        "VOC",
        "CO2",
    }
)

#: Per-gas phase applicability. A gas absent from this map is offered in every
#: phase with the landfill caveat; the map narrows the exceptions.
_GAS_APPLICABILITY: dict[str, GasApplicability] = {
    "CH4": GasApplicability(
        phases=_METHANOGENIC,
        source=_AP42_LANDFILL,
        uncertainty=_AP42_APPLIES,
    ),
    "CO": GasApplicability(
        phases=_ALL_PHASES,
        source=_AP42_LANDFILL,
        uncertainty=_AP42_PHASE_I_NOTE,
    ),
    "VOC": GasApplicability(
        phases=_ALL_PHASES,
        source=_AP42_LANDFILL,
        uncertainty=_AP42_PHASE_I_NOTE,
    ),
    "H2S": GasApplicability(
        phases=_ALL_PHASES,
        source=_AP42_LANDFILL,
        uncertainty=_AP42_PHASE_I_NOTE,
    ),
}

#: Gases produced by the generation model rather than read from a table.
_GENERATED_APPLICABILITY: dict[str, GasApplicability] = {
    "CO2": GasApplicability(
        phases=_ALL_PHASES,
        source="Generation model, 40 CFR 98.343 default F = 0.5 carbon balance",
        uncertainty=(
            "Model assumption: CO2 receives (1 - F) of degraded carbon; the "
            "regulation defines F as a measurement-replaceable methane default."
        ),
    ),
    "CH4": GasApplicability(
        phases=_METHANOGENIC,
        source="Generation model, 40 CFR 98.343(a)(1) Equation HH-1",
        uncertainty=_AP42_APPLIES,
    ),
}



def applicability(gas_key: str) -> GasApplicability:
    """Which phases ``gas_key`` applies to, with its source and uncertainty.

    Covers catalogue and generated gases. Catalogue gases without a cited
    fresh-waste basis are excluded from phase I rather than presenting a
    mature-landfill measurement as an equivalent source.
    """
    if gas_key in _GENERATED_APPLICABILITY:
        return _GENERATED_APPLICABILITY[gas_key]
    if gas_key not in GAS_PROPERTIES:
        raise KeyError(f"Unknown gas: {gas_key}")
    if gas_key in _GAS_APPLICABILITY:
        return _GAS_APPLICABILITY[gas_key]
    fresh = gas_key in _PHASE_I_OFFERED
    return GasApplicability(
        phases=_ALL_PHASES if fresh else ("II", "III", "IV"),
        source=_AP42_LANDFILL,
        uncertainty=(
            _AP42_TRANSITION_NOTE
            if fresh
            else "No cited fresh-waste value exists for this species; the AP-42 "
            "value is a mature-landfill measurement and is not offered for phase I."
        ),
    )


def offered_gases(age_h: float) -> tuple[str, ...]:
    """The selectable catalogue gases whose applicability includes the age's phase.

    The offered set is a function of holding time: a fresh load does not offer
    methane, and an aged one does. Gases are returned in catalogue order. The
    generated gases (CO2, CH4) are not selectable sources here — CO2 is reported
    as a generated mass/share, and CH4 is a catalogue gas — so this covers the
    checkboxes the UI can actually build.
    """
    from lynceus_engine.composition import phase_for

    phase = phase_for(age_h)
    return tuple(
        gas for gas in DEFAULT_SOURCE_GASES if phase in applicability(gas).phases
    )

#: Compact labels for dense rows such as the source list, where the full
#: ``name`` does not fit. The headline gases use the formula engineers write;
#: the rest use a trimmed common name. The full name and its citation belong in
#: a tooltip.
SHORT_LABELS = {
    "CO": "CO",
    "CH4": "CH4",
    "VOC": "VOC",
    "H2S": "H2S",
    "ETHANE": "Ethane",
    "BENZENE": "Benzene",
    "TOLUENE": "Toluene",
    "VINYL_CHLORIDE": "Vinyl chloride",
    "METHYL_MERCAPTAN": "Methyl mercaptan",
    "DIMETHYL_SULFIDE": "Dimethyl sulfide",
    "ETHYL_MERCAPTAN": "Ethyl mercaptan",
    "CARBON_DISULFIDE": "Carbon disulfide",
    "CARBONYL_SULFIDE": "Carbonyl sulfide",
    "ETHYLBENZENE": "Ethylbenzene",
    "XYLENES": "Xylenes",
    "CHLOROBENZENE": "Chlorobenzene",
    "DICHLOROBENZENE": "Dichlorobenzene",
    "PROPANE": "Propane",
    "BUTANE": "Butane",
    "PENTANE": "Pentane",
    "HEXANE": "Hexane",
    "ACETONE": "Acetone",
    "METHYL_ETHYL_KETONE": "MEK",
    "METHYL_ISOBUTYL_KETONE": "MIBK",
    "ETHANOL": "Ethanol",
    "PROPANOL_2": "2-Propanol",
    "DICHLOROMETHANE": "Dichloromethane",
    "CHLOROFORM": "Chloroform",
    "CARBON_TETRACHLORIDE": "Carbon tetrachloride",
    "TRICHLOROETHANE_111": "1,1,1-TCA",
    "TRICHLOROETHYLENE": "Trichloroethylene",
    "PERCHLOROETHYLENE": "Perchloroethylene",
    "TETRACHLOROETHANE_1122": "1,1,2,2-TeCA",
    "DICHLOROETHANE_11": "1,1-DCA",
    "DICHLOROETHANE_12": "1,2-DCA",
    "DICHLOROETHENE_11": "1,1-DCE",
    "T_DICHLOROETHENE_12": "t-1,2-DCE",
    "DICHLOROPROPANE_12": "1,2-DCP",
    "CHLOROMETHANE": "Chloromethane",
    "CHLOROETHANE": "Chloroethane",
    "BROMODICHLOROMETHANE": "Bromodichloromethane",
    "ETHYLENE_DIBROMIDE": "Ethylene dibromide",
    "DICHLORODIFLUOROMETHANE": "CFC-12",
    "DICHLOROFLUOROMETHANE": "HCFC-21",
    "CHLORODIFLUOROMETHANE": "HCFC-22",
    "FLUOROTRICHLOROMETHANE": "CFC-11",
    "ACRYLONITRILE": "Acrylonitrile",
}


def short_label(gas_key: str) -> str:
    """Compact label for a gas, falling back to its full name."""
    if gas_key in SHORT_LABELS:
        return SHORT_LABELS[gas_key]
    return get_gas(gas_key).name


@dataclass(frozen=True)
class GasSpec:
    """Physical properties plus the cited source default for one gas."""

    key: str
    name: str
    mw_g_mol: float
    diffusivity_m2_s: float
    default_conc_ppmv: float
    basis: str
    rating: str = ""
    alternate_conc_ppmv: float | None = None
    alternate_basis: str = ""



def _concentration(value: object, key: str) -> float:
    """Parse an AP-42 concentration cell into ppmv.

    The published cells are not all plain numbers. Some are scientific notation
    written the EPA's way (``"4.0x10-3"``, ``"3.0x10-2"``) and some are a plain
    value with a footnote letter attached (``"110e"``). A bare ``float()``
    rejects both forms, which would silently restrict the catalogue to whichever
    gases happened to be stored numerically.

    Raises ``KeyError`` rather than returning a guess: an unreadable cell means
    the gas has no usable cited value, and inventing one is not an option.
    """
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str):
        text = value.strip().lower().replace(" ", "")
        for marker in ("x10", "\u00d710"):
            text = text.replace(marker, "e")
        while text and text[-1].isalpha():
            text = text[:-1]
        try:
            return float(text)
        except ValueError:
            pass
    raise KeyError(f"unreadable AP-42 concentration for {key}: {value!r}")


def available_gases() -> list[str]:
    """Every gas with a cited AP-42 value, in display order."""
    return [gas for gas in DEFAULT_SOURCE_GASES if gas in GAS_PROPERTIES]


def get_gas(key: str) -> GasSpec:
    if key not in GAS_PROPERTIES:
        raise KeyError(f"Unknown gas: {key}")
    props = GAS_PROPERTIES[key]
    defaults = SOURCE_DEFAULTS.get(key, {})
    if "conc_ppmv" in defaults:
        default_conc = _concentration(defaults["conc_ppmv"], key)
    elif "fraction_by_volume" in defaults:
        default_conc = float(defaults["fraction_by_volume"]) * 1_000_000.0
    else:
        raise KeyError(f"No concentration default for {key}")
    alternate = defaults.get("alternate_conc_ppmv")
    if alternate is None and "alternate_fraction" in defaults:
        alternate = float(defaults["alternate_fraction"]) * 1_000_000.0
    elif alternate is not None:
        alternate = _concentration(alternate, key)
    return GasSpec(
        key=key,
        name=props["name"],
        mw_g_mol=props["mw_g_mol"],
        diffusivity_m2_s=props["diffusivity_m2_s"],
        default_conc_ppmv=default_conc,
        basis=defaults.get("basis", ""),
        rating=defaults.get("rating", ""),
        alternate_conc_ppmv=None if alternate is None else float(alternate),
        alternate_basis=defaults.get("alternate_basis", ""),
    )


def source_concentration(gas_key: str, regime: str = "msw-only") -> float:
    """Cited default source concentration in ppmv for one gas and disposal regime.

    Strict by design: a co-disposal lookup for a gas AP-42 gives no alternate for
    raises rather than guessing. Use :func:`default_sources` (or
    :func:`lynceus_engine.core.scenario.auto_concentration_ppmv`) when the desired
    behaviour is a fallback.
    """
    if regime not in REGIMES:
        raise ValueError(f"regime must be one of {REGIMES}")
    spec = get_gas(gas_key)
    if regime == "co-disposal":
        if spec.alternate_conc_ppmv is None:
            raise KeyError(f"No co-disposal default for {gas_key}")
        return spec.alternate_conc_ppmv
    return spec.default_conc_ppmv


def regime_concentration(gas_key: str, regime: str = "msw-only") -> float:
    """Default concentration for ``gas_key`` under ``regime``, falling back.

    Uses the cited co-disposal alternate where AP-42 publishes one and the base
    default where it does not, so this never raises for a gas in
    :data:`DEFAULT_SOURCE_GASES`. :func:`source_concentration` is the strict
    variant, for callers that need to know whether a cited alternate exists.
    """
    if regime not in REGIMES:
        raise ValueError(f"regime must be one of {REGIMES}")
    spec = get_gas(gas_key)
    if regime == "co-disposal" and spec.alternate_conc_ppmv is not None:
        return spec.alternate_conc_ppmv
    return spec.default_conc_ppmv


def default_sources(regime: str = "msw-only") -> dict[str, float]:
    """Every source gas at its cited default, ready to drop into a scenario.

    Mirrors :func:`lynceus_engine.core.scenario.auto_concentration_ppmv`: a
    co-disposal regime uses each gas's cited alternate where AP-42 has one and
    falls back to the base default where it does not, so this covers every entry
    of :data:`DEFAULT_SOURCE_GASES` under both regimes.
    """
    return {key: regime_concentration(key, regime) for key in DEFAULT_SOURCE_GASES}


def citation(gas_key: str) -> str:
    """One-line provenance string for the given gas, e.g. for a tooltip."""
    spec = get_gas(gas_key)
    parts = [f"{spec.name}: {spec.default_conc_ppmv:g} ppmv", spec.basis]
    if spec.rating:
        parts.append(f"EPA rating {spec.rating}")
    return " — ".join(part for part in parts if part)
