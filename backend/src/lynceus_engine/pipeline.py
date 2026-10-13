"""End-to-end batch assessment: waste in, decision out.

One entry point that runs the whole chain — composition → phase → generation →
mass balance → suitability → recommendation — so callers cannot accidentally
skip a stage or read a later result without the earlier one.

The chain is deliberately linear and pure: no Qt, no solver, no I/O. That makes
it testable against hand-checked numbers, which is the only way the output can be
claimed accurate.
"""

from __future__ import annotations

from dataclasses import dataclass

from lynceus_engine import generation as gen
from lynceus_engine import massbalance as mb
from lynceus_engine import recommend as rec
from lynceus_engine import suitability as suit
from lynceus_engine.composition import WasteComposition, phase_for


@dataclass(frozen=True)
class BatchAssessment:
    """Every stage's result for one batch, in order."""

    tonnage_t: float
    moisture: float
    age_h: float
    phase: str
    composition: WasteComposition
    generation: gen.Generation
    balance: mb.BatchResult
    suitability: suit.Suitability
    recommendation: rec.Recommendation

    def summary_lines(self) -> list[str]:
        """A readable digest, in the order a reviewer reads it."""
        lines = [
            f"Batch: {self.tonnage_t:.2f} t, moisture {self.moisture:.0%}, "
            f"age {self.age_h:.1f} h -> phase {self.phase}",
            f"  DOC {self.generation.doc:.3f}, k {self.generation.k_per_year:.4f} /yr, "
            f"decay reached {self.generation.decay_fraction:.4%}",
            f"  CH4 cumulative {self.generation.ch4_cumulative_kg:.3f} kg "
            f"({self.generation.ch4_cumulative_m3:.3f} m3), "
            f"CO2 cumulative {self.generation.co2_cumulative_kg:.3f} kg",
            (
                f"  rate now CH4 {self.generation.ch4_rate_kg_per_h:.4f} kg/h, "
                f"CO2 {self.generation.co2_rate_kg_per_h:.4f} kg/h "
                f"(methane share {self.generation.methane_fraction:.1%})"
            ),
        ]
        for stream in mb.STREAMS:
            tonnes = self.balance.streams[stream].tonnes
            if tonnes:
                lines.append(
                    f"  {stream:11s} {tonnes:6.2f} t  "
                    f"({self.balance.yield_fraction(stream):.1%})"
                )
        for score in self.suitability.ranked():
            lines.append(f"  {score.route:20s} {score.score:.2f}")
        lines.append(f"  => {self.recommendation.headline}")
        for reason in self.recommendation.reasons:
            lines.append(f"     because {reason}")
        for caveat in self.recommendation.caveats:
            lines.append(f"     caveat: {caveat}")
        return lines


def assess_batch(
    composition: WasteComposition,
    *,
    tonnage_t: float,
    moisture: float,
    age_h: float,
    quality: suit.QualityInputs | None = None,
    screening: bool = True,
) -> BatchAssessment:
    """Run the whole chain for one batch.

    ``screening`` propagates the mesh-independence caveat to the recommendation;
    it is ``True`` unless a caller has evidence the transport is converged.
    """
    if tonnage_t < 0.0:
        raise ValueError("tonnage_t must not be negative")
    if not 0.0 <= moisture <= 1.0:
        raise ValueError("moisture must be in [0, 1]")

    generation = gen.generate(
        composition, tonnage_t=tonnage_t, age_h=age_h, moisture=moisture
    )
    balance = mb.balance(composition, tonnage_t=tonnage_t, moisture=moisture)
    suitability = suit.assess(composition, moisture=moisture, quality=quality)
    recommendation = rec.recommend(
        composition,
        tonnage_t=tonnage_t,
        moisture=moisture,
        age_h=age_h,
        quality=quality,
        screening=screening,
    )

    return BatchAssessment(
        tonnage_t=tonnage_t,
        moisture=moisture,
        age_h=age_h,
        phase=phase_for(age_h),
        composition=composition,
        generation=generation,
        balance=balance,
        suitability=suitability,
        recommendation=recommendation,
    )
