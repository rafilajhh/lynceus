"""Batch mass balance: what a load becomes, in tonnes.

The user's expected output is tonnage per stream ("10 t in -> 6.4 t RDF"). This
module is that arithmetic and nothing more: it routes each material to a process
by an explicit split fraction, and it accounts for every kilogram.

Two disciplines are load-bearing:

* **Mass closes.** Every stream is reported, including moisture and residue, and
  the sum equals the input. A balance that quietly loses mass is worse than no
  balance.
* **Every split fraction carries its provenance.** Routing is a *process*
  property, not a physical constant. Where no citation exists the fraction is
  labelled a user assumption, exactly as manual gas sources already are.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from lynceus_engine.composition import MATERIAL_KEYS, WasteComposition

#: Streams a batch can leave as. ``moisture`` and ``residue`` are not products:
#: one is water that was in the load, the other is what no route accepted.
STREAMS = ("rdf", "recyclable", "organic", "compost", "residue", "moisture")

#: Provenance labels. A fraction is either taken from a source or it is the
#: user's assumption; there is no third state that could pass for a citation.
CITED = "cited"
USER_ASSUMPTION = "user assumption"

#: Default routing per material: the fraction of that material's dry mass that
#: each process takes. These are **starting assumptions for the UI**, not
#: measurements — no source in the repository supports a specific split, so they
#: are labelled as assumptions and are meant to be edited per facility.
#:
#: The one property that *is* defensible is ordering: paper and textiles are the
#: RDF feedstock, food and garden the organic/compost streams, and inerts go to
#: residue. The numbers below encode that ordering and nothing finer.
DEFAULT_ROUTING: dict[str, dict[str, float]] = {
    "food": {"organic": 0.85, "compost": 0.10, "residue": 0.05},
    "garden": {"compost": 0.60, "organic": 0.25, "rdf": 0.05, "residue": 0.10},
    "paper": {"rdf": 0.70, "recyclable": 0.25, "residue": 0.05},
    "wood": {"rdf": 0.60, "compost": 0.15, "residue": 0.25},
    "textile": {"rdf": 0.75, "recyclable": 0.10, "residue": 0.15},
    "diaper": {"rdf": 0.50, "residue": 0.50},
    "sludge": {"compost": 0.50, "organic": 0.30, "residue": 0.20},
    "inert": {"recyclable": 0.30, "residue": 0.70},
}


@dataclass(frozen=True)
class StreamResult:
    """One output stream and where its mass came from."""

    stream: str
    tonnes: float
    by_material: dict[str, float]


@dataclass(frozen=True)
class BatchResult:
    """The balance for one batch."""

    tonnage_t: float
    dry_tonnage_t: float
    moisture_tonnes: float
    streams: dict[str, StreamResult]
    routing: dict[str, dict[str, float]]
    routing_provenance: dict[str, str]
    notes: tuple[str, ...]

    @property
    def accounted_tonnes(self) -> float:
        """Every kilogram that left the batch, products and losses alike."""
        return sum(result.tonnes for result in self.streams.values())

    def yield_fraction(self, stream: str) -> float:
        """A stream's share of the input, as a fraction."""
        if stream not in self.streams:
            raise KeyError(f"unknown stream {stream!r}; expected one of {STREAMS}")
        if self.tonnage_t <= 0.0:
            return 0.0
        return self.streams[stream].tonnes / self.tonnage_t


def _validate_routing(routing: dict[str, dict[str, float]]) -> None:
    """Every material's split must exist and sum to one, or mass leaks."""
    for material in MATERIAL_KEYS:
        if material not in routing:
            raise ValueError(f"routing is missing material {material!r}")
        splits = routing[material]
        unknown = set(splits) - set(STREAMS)
        if unknown:
            raise ValueError(f"routing for {material!r} names unknown streams {sorted(unknown)}")
        total = sum(splits.values())
        if abs(total - 1.0) > 1e-9:
            raise ValueError(
                f"routing for {material!r} must sum to 1.0, got {total:.9f}"
            )
        for stream, value in splits.items():
            if not 0.0 <= value <= 1.0:
                raise ValueError(
                    f"routing for {material!r} -> {stream!r} must be in [0, 1], got {value}"
                )


def balance(
    composition: WasteComposition,
    *,
    tonnage_t: float,
    moisture: float,
    routing: dict[str, dict[str, float]] | None = None,
    provenance: dict[str, str] | None = None,
) -> BatchResult:
    """Route a batch's dry mass through the process and account for all of it.

    Moisture is removed first and reported as its own stream: it was water in the
    load, not a product of any route. The remaining dry mass is split by each
    material's routing.
    """
    if tonnage_t < 0.0:
        raise ValueError("tonnage_t must not be negative")
    if not 0.0 <= moisture <= 1.0:
        raise ValueError("moisture must be in [0, 1]")

    table = routing if routing is not None else DEFAULT_ROUTING
    _validate_routing(table)

    # A routing table is a *process* property. Passing one is not evidence that
    # anyone published it, so the default label is the user's assumption in
    # every case; ``provenance`` is the only way a material may be marked
    # ``cited``, and it has to be stated explicitly by the caller.
    labels = dict(provenance or {})
    for material in MATERIAL_KEYS:
        labels.setdefault(material, USER_ASSUMPTION)

    moisture_tonnes = tonnage_t * moisture
    dry_tonnage = tonnage_t - moisture_tonnes

    accumulated: dict[str, dict[str, float]] = {stream: {} for stream in STREAMS}
    accumulated["moisture"]["water"] = moisture_tonnes

    for material in MATERIAL_KEYS:
        mass = dry_tonnage * getattr(composition, material)
        if mass == 0.0:
            continue
        for stream, fraction in table[material].items():
            share = mass * fraction
            if share:
                accumulated[stream][material] = accumulated[stream].get(material, 0.0) + share

    streams = {
        stream: StreamResult(
            stream=stream,
            tonnes=sum(parts.values()),
            by_material=dict(parts),
        )
        for stream, parts in accumulated.items()
    }

    notes: list[str] = []
    if USER_ASSUMPTION in labels.values():
        notes.append(
            "routing fractions are model assumptions, not measurements; edit them per facility"
        )
    if moisture >= 0.5:
        notes.append(f"{moisture:.0%} moisture: drying is a prerequisite for most routes")
    if composition.inert >= 0.5:
        notes.append("over half the load is inert: little is recoverable")

    result = BatchResult(
        tonnage_t=tonnage_t,
        dry_tonnage_t=dry_tonnage,
        moisture_tonnes=moisture_tonnes,
        streams=streams,
        routing={material: dict(table[material]) for material in MATERIAL_KEYS},
        routing_provenance=labels,
        notes=tuple(notes),
    )

    # Mass must close. A tolerance of 1e-9 relative is arithmetic slack, not a
    # licence to lose a kilogram.
    if abs(result.accounted_tonnes - tonnage_t) > max(1e-9, tonnage_t * 1e-9):
        raise AssertionError(
            f"mass balance does not close: in {tonnage_t}, out {result.accounted_tonnes}"
        )
    return result
