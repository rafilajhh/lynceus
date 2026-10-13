"""Decision recommendation: one actionable line, traceable to its inputs.

This is the output the user called the most important one — *"recommended for RDF
after moisture reduction"*. Two properties make it trustworthy:

* **It cites its reasons.** Every recommendation carries the inputs and the rule
  that produced it, so a reviewer can disagree with the reasoning rather than
  with an assertion.
* **It refuses to answer when it cannot.** A batch missing the inputs a route
  needs yields "not enough information" plus the list of what is missing. A
  recommendation built on absent data would be the most damaging kind of output
  this tool could produce.
"""

from __future__ import annotations

from dataclasses import dataclass

from lynceus_engine import massbalance as mb
from lynceus_engine import suitability as suit
from lynceus_engine.composition import WasteComposition

#: Below this score a route is not worth recommending, however it ranks.
MINIMUM_SCORE = 0.45

#: Moisture above which drying is named as a prerequisite rather than a caveat.
DRYING_THRESHOLD = 0.45

#: Route names as they read in a sentence.
ROUTE_LABELS = {
    "rdf": "RDF processing",
    "recycling": "recycling",
    "composting": "composting",
    "anaerobic_digestion": "anaerobic digestion",
    "landfill": "landfill disposal",
}


@dataclass(frozen=True)
class Recommendation:
    """One decision, with everything it rested on."""

    route: str | None
    headline: str
    reasons: tuple[str, ...]
    caveats: tuple[str, ...]
    inputs: dict[str, float]
    alternative: str | None = None
    insufficient: bool = False
    missing: tuple[str, ...] = ()

    @property
    def actionable(self) -> bool:
        return self.route is not None and not self.insufficient


def recommend(
    composition: WasteComposition,
    *,
    tonnage_t: float,
    moisture: float,
    age_h: float,
    quality: suit.QualityInputs | None = None,
    screening: bool = True,
) -> Recommendation:
    """Recommend a route for one batch.

    ``screening`` carries the mesh-independence caveat: while absolute
    concentrations are not converged, no recommendation may present itself as
    validated. It defaults to ``True`` and is only set ``False`` by a caller that
    has evidence the transport is converged.
    """
    if tonnage_t <= 0.0:
        return Recommendation(
            route=None,
            headline="No batch to assess: tonnage is zero.",
            reasons=(),
            caveats=(),
            inputs={"tonnage_t": tonnage_t},
            insufficient=True,
            missing=("tonnage_t",),
        )

    assessment = suit.assess(composition, moisture=moisture, quality=quality)
    balance = mb.balance(composition, tonnage_t=tonnage_t, moisture=moisture)
    best = assessment.best()

    caveats: list[str] = []
    if moisture > DRYING_THRESHOLD:
        caveats.append(
            f"moisture is {moisture:.0%}: drying below {DRYING_THRESHOLD:.0%} is a "
            "prerequisite for a combustible product"
        )
    if not assessment.quality.complete:
        caveats.append(
            "fuel grade is not established: "
            + ", ".join(assessment.quality.missing())
            + " require laboratory analysis"
        )
    if screening:
        caveats.append(
            "concentrations are screening estimates: mesh independence is not yet met, "
            "so treat any sensor figure as relative"
        )
    caveats.extend(balance.notes)
    caveats.extend(assessment.notes)

    if best is None:
        return Recommendation(
            route=None,
            headline="No route could be scored for this batch.",
            reasons=("every route rule requires inputs this batch did not provide",),
            caveats=tuple(dict.fromkeys(caveats)),
            inputs={"tonnage_t": tonnage_t, "moisture": moisture, "age_h": age_h},
            insufficient=True,
            missing=("a scoreable route",),
        )

    # A route below the threshold is still the best available option — the batch
    # has to go somewhere. It is recommended with the shortfall stated, rather
    # than withheld, because "no recommendation" is not an actionable answer for
    # a load that physically exists.
    label = ROUTE_LABELS[best.route]
    below_threshold = best.score < MINIMUM_SCORE
    if below_threshold:
        caveats.append(
            f"best available score is {best.score:.2f}, below the {MINIMUM_SCORE:.2f} "
            "threshold: this is a least-bad option, not a good one"
        )

    yield_stream = {
        "rdf": "rdf",
        "recycling": "recyclable",
        "composting": "compost",
        "anaerobic_digestion": "organic",
        "landfill": "residue",
    }[best.route]
    yield_t = balance.streams.get(yield_stream)
    reasons = [
        f"{label} scores {best.score:.2f} by the rule: {best.rule}",
    ]
    if yield_t is not None:
        reasons.append(
            f"projected yield {yield_t.tonnes:.2f} t of {yield_t.stream} "
            f"from {tonnage_t:.2f} t input ({yield_t.tonnes / tonnage_t:.0%})"
        )
    reasons.append(
        "inputs: "
        + ", ".join(f"{key}={value:.3g}" for key, value in sorted(best.inputs.items()))
    )

    headline = f"Recommended for {label}."
    if moisture > DRYING_THRESHOLD and best.route == "rdf":
        headline = f"Recommended for {label} after moisture reduction."
    elif below_threshold:
        headline = f"Least-bad option is {label}."

    ranked = assessment.ranked()
    alternative = None
    if len(ranked) > 1:
        runner_up = ranked[1]
        alternative = (
            f"{ROUTE_LABELS[runner_up.route]} scores {runner_up.score:.2f} "
            f"(margin {best.score - runner_up.score:.2f})"
        )

    return Recommendation(
        route=best.route,
        headline=headline,
        reasons=tuple(reasons),
        caveats=tuple(dict.fromkeys(caveats)),
        inputs={"tonnage_t": tonnage_t, "moisture": moisture, "age_h": age_h},
        alternative=alternative,
    )
