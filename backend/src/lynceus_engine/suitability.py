"""Route suitability scoring and RDF quality.

Scores answer *"how suitable is this batch for route X?"*. The discipline that
makes them trustworthy is that **every score is a stated rule over named inputs,
and a score missing an input is not a number**.

Fuel-basis quality — net calorific value, ash, chlorine as a fraction of dry
mass — is what an RDF offtaker actually buys, and it cannot be derived from the
gas phase: the gas does not know the mass of the fuel. Those values therefore
come from one of two places, never a guess:

* a **laboratory measurement** the user enters, or
* a **cited correlation** from composition, if one exists.

No correlation is currently in the repository, so the code offers the laboratory
path and reports the correlated path as unavailable. That is a deliberate gap,
not an oversight: see ``docs/gas-composition-basis.md`` section 6.4.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from lynceus_engine.composition import WasteComposition

#: Routes a batch can be scored for.
ROUTES = ("rdf", "recycling", "composting", "anaerobic_digestion", "landfill")

#: Provenance labels for a quality input.
LABORATORY = "laboratory"
CORRELATED = "correlated"
USER_INPUT = "user input"
UNAVAILABLE = "unavailable"

#: A route score is withheld rather than guessed when its inputs are missing.
INSUFFICIENT = "insufficient_data"


@dataclass(frozen=True)
class QualityInputs:
    """Fuel-basis values. Every field is either measured or absent.

    ``None`` means *not measured*. It never means zero, and no default is
    substituted: a missing value must stay visibly missing all the way to the UI.
    """

    ncv_mj_per_kg: float | None = None
    ash_fraction: float | None = None
    chlorine_fraction: float | None = None
    moisture_fraction: float | None = None
    source: str = UNAVAILABLE

    def missing(self) -> tuple[str, ...]:
        """Names of the values still needed for a fuel grade."""
        names = []
        if self.ncv_mj_per_kg is None:
            names.append("ncv_mj_per_kg")
        if self.ash_fraction is None:
            names.append("ash_fraction")
        if self.chlorine_fraction is None:
            names.append("chlorine_fraction")
        return tuple(names)

    @property
    def complete(self) -> bool:
        return not self.missing()


@dataclass(frozen=True)
class RouteScore:
    """One route's suitability, with the rule and inputs behind it."""

    route: str
    score: float | None
    rule: str
    inputs: dict[str, float]
    withheld_reason: str | None = None

    @property
    def available(self) -> bool:
        return self.score is not None


@dataclass(frozen=True)
class Suitability:
    """Every route's score for one batch, plus what could not be scored."""

    scores: dict[str, RouteScore]
    quality: QualityInputs
    notes: tuple[str, ...] = ()

    def ranked(self) -> list[RouteScore]:
        """Available scores, best first. Withheld routes are excluded."""
        available = [s for s in self.scores.values() if s.available]
        return sorted(available, key=lambda s: s.score, reverse=True)

    def best(self) -> RouteScore | None:
        ranked = self.ranked()
        return ranked[0] if ranked else None


def _clamp(value: float) -> float:
    """Scores are fractions in [0, 1]; a rule may not leave that range."""
    return max(0.0, min(1.0, value))


def score_rdf(composition: WasteComposition, moisture: float) -> RouteScore:
    """RDF suitability from the dry, combustible, paper-rich fraction.

    The rule rewards what makes refuse-derived fuel burn: dry mass, paper and
    textiles (the high-calorific materials), and penalises moisture, which has to
    be driven off before the fuel is worth anything.

    This is a *stated heuristic*, not a standard. It is reported with its rule
    text so a reviewer can disagree with the rule rather than with a number.
    """
    dry = 1.0 - moisture
    fuel_materials = composition.paper + composition.textile + composition.wood
    rule = (
        "0.55*dry + 0.45*(paper+textile+wood), clamped to [0,1]"
    )
    inputs = {
        "dry_fraction": dry,
        "fuel_materials": fuel_materials,
        "moisture": moisture,
    }
    return RouteScore(
        route="rdf",
        score=_clamp(0.55 * dry + 0.45 * fuel_materials),
        rule=rule,
        inputs=inputs,
    )


def score_recycling(composition: WasteComposition, moisture: float) -> RouteScore:
    """Recycling suitability from clean, dry, source-separated material.

    High moisture contaminates recyclables, so it penalises; inerts are what
    recycling actually recovers, so they count positively here.
    """
    rule = "0.60*inert + 0.40*(1 - moisture), clamped to [0,1]"
    inputs = {
        "inert": composition.inert,
        "moisture": moisture,
    }
    return RouteScore(
        route="recycling",
        score=_clamp(0.60 * composition.inert + 0.40 * (1.0 - moisture)),
        rule=rule,
        inputs=inputs,
    )


def score_composting(composition: WasteComposition, moisture: float) -> RouteScore:
    """Composting suitability from putrescible content at working moisture.

    Composting needs food and garden material *and* moisture — but not saturation.
    The rule peaks around 0.5 moisture, which is the working range for aerobic
    decomposition, and falls off on both sides.
    """
    putrescible = composition.food + composition.garden
    # 1.0 at 0.5 moisture, 0.0 at 0.0 and 1.0.
    moisture_factor = 1.0 - abs(moisture - 0.5) * 2.0
    rule = "0.75*(food+garden) + 0.25*moisture_factor, moisture_factor peaks at 0.5"
    inputs = {
        "putrescible": putrescible,
        "moisture": moisture,
        "moisture_factor": moisture_factor,
    }
    return RouteScore(
        route="composting",
        score=_clamp(0.75 * putrescible + 0.25 * moisture_factor),
        rule=rule,
        inputs=inputs,
    )


def score_anaerobic_digestion(
    composition: WasteComposition, moisture: float
) -> RouteScore:
    """Digestion suitability from wet putrescibles.

    Unlike composting, digestion *wants* high moisture: the reactor is a slurry.
    """
    putrescible = composition.food + composition.garden + composition.sludge
    rule = "0.70*(food+garden+sludge) + 0.30*moisture, clamped to [0,1]"
    inputs = {"putrescible": putrescible, "moisture": moisture}
    return RouteScore(
        route="anaerobic_digestion",
        score=_clamp(0.70 * putrescible + 0.30 * moisture),
        rule=rule,
        inputs=inputs,
    )


def score_landfill(composition: WasteComposition, moisture: float) -> RouteScore:
    """Landfill suitability as the residual option: whatever nothing else wants.

    This scores *how much of the load would have to be landfilled*, so it rises
    with inert content and falls as recoverable material rises. It is a
    disposition score, not an endorsement.
    """
    recoverable = (
        composition.paper
        + composition.food
        + composition.garden
        + composition.textile
        + composition.wood
    )
    rule = "0.50*inert + 0.50*(1 - recoverable), clamped to [0,1]"
    inputs = {"inert": composition.inert, "recoverable": recoverable}
    return RouteScore(
        route="landfill",
        score=_clamp(0.50 * composition.inert + 0.50 * (1.0 - recoverable)),
        rule=rule,
        inputs=inputs,
    )


_RULES = {
    "rdf": score_rdf,
    "recycling": score_recycling,
    "composting": score_composting,
    "anaerobic_digestion": score_anaerobic_digestion,
    "landfill": score_landfill,
}


def assess(
    composition: WasteComposition,
    *,
    moisture: float,
    quality: QualityInputs | None = None,
) -> Suitability:
    """Score every route for a batch.

    Route scores are heuristics over composition and are always available. The
    fuel-grade fields are separate: they are reported from ``quality`` and stay
    missing when nothing measured them.
    """
    if not 0.0 <= moisture <= 1.0:
        raise ValueError("moisture must be in [0, 1]")

    scores = {
        route: rule(composition, moisture) for route, rule in _RULES.items()
    }
    quality = quality or QualityInputs()

    notes: list[str] = []
    notes.append(
        "route scores are stated heuristics over composition, not standard classifications"
    )
    if not quality.complete:
        notes.append(
            "fuel grade needs " + ", ".join(quality.missing()) + " from laboratory analysis"
        )
    if quality.source == CORRELATED:
        notes.append("correlated quality values: confirm the citation applies to this material")

    return Suitability(scores=scores, quality=quality, notes=tuple(notes))


def fuel_grade(quality: QualityInputs) -> tuple[str | None, str]:
    """EN 15359-style class from measured NCV/Cl/ash, or why it cannot be given.

    Returns ``(class_or_None, reason)``. The class is withheld unless all three
    parameters are present: a grade computed from two of three inputs would be a
    fabrication, and it is the number a procurement decision would rest on.
    """
    missing = quality.missing()
    if missing:
        return None, (
            "cannot assign a fuel class without " + ", ".join(missing)
        )
    if quality.source == UNAVAILABLE:
        return None, "values are present but their provenance is unknown; no class assigned"

    # The class boundaries themselves are a standard lookup that is not in this
    # repository. Rather than invent thresholds, the parameters are reported and
    # the class is withheld until the standard's table is cited here.
    return None, (
        "EN 15359 / ISO 21640 class boundaries are not yet cited in this repository; "
        "report the three parameters instead of a class"
    )
