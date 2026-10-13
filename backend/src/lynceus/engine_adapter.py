"""Adapter between the Lynceus API and the Lynceus decision engine.

The engine (:mod:`lynceus_engine`, vendored under ``backend/src``) is the
physics; Lynceus is the service. This module is the only place the two
meet, so the rest of the backend never imports the engine directly and
the engine can evolve behind this seam.

Design notes:

* ``lynceus_engine`` is imported lazily inside :func:`_load_engine`, never
  at module import time. A missing engine therefore degrades into a clear
  runtime error (surfaced by ``/health`` and ``/assess``) instead of
  breaking every import of Lynceus.
* All serialisation helpers are pure functions over dataclasses, so they are
  trivially unit-testable without the engine installed.
* ``screening=False`` is passed to :func:`lynceus_engine.pipeline.assess_batch`
  because the CFD transport mesh was dropped from Lynceus; with it gone there
  is no mesh-independence claim to caveat.
"""

from __future__ import annotations

import dataclasses
from typing import Any

__all__ = [
    "EngineUnavailableError",
    "UnknownWasteStreamError",
    "InvalidBatchError",
    "AVAILABLE_WASTE_STREAMS",
    "list_waste_streams",
    "run_assessment",
]


class EngineUnavailableError(RuntimeError):
    """The Lynceus decision engine is not importable in this process."""

    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


class UnknownWasteStreamError(ValueError):
    """The requested waste stream is not a known engine preset (HTTP 422)."""

    def __init__(self, waste_stream: str, available: tuple[str, ...]):
        self.waste_stream = waste_stream
        self.available = available
        super().__init__(
            f"unknown waste_stream {waste_stream!r}; "
            f"expected one of {list(available)}"
        )


class InvalidBatchError(ValueError):
    """Batch inputs are outside the engine's domain (HTTP 422)."""


def _load_engine() -> Any:
    """Import ``lynceus_engine`` (plus the submodules we use) or fail clearly.

    ``lynceus_engine``'s ``__init__`` does not re-export its submodules, so
    the pieces Lynceus needs — ``composition`` and ``pipeline`` — are
    imported explicitly. Import stays lazy: it happens on first request, not
    at module load, so a missing engine degrades into a clear runtime error
    instead of breaking every import of Lynceus, and tests can monkeypatch
    this function to simulate failures.
    """
    try:
        import lynceus_engine as engine  # type: ignore[import-untyped]
        import lynceus_engine.composition  # noqa: F401  (registers submodule)
        import lynceus_engine.pipeline  # noqa: F401  (registers submodule)
    except ImportError as exc:
        raise EngineUnavailableError(
            "the Lynceus decision engine package 'lynceus_engine' is not "
            f"installed or not importable in this process ({exc}); the "
            "Lynceus /assess endpoint requires it — install the backend "
            "package or add backend/src to PYTHONPATH"
        ) from exc
    return engine


def engine_available() -> bool:
    """True when ``lynceus_engine`` can be imported (used by ``/health``)."""
    try:
        _load_engine()
    except EngineUnavailableError:
        return False
    return True


def _resolve_waste_stream(engine: Any, waste_stream: str) -> Any:
    """Map a waste-stream name onto its engine composition preset."""
    presets = engine.composition.PRESETS
    if waste_stream not in presets:
        raise UnknownWasteStreamError(waste_stream, tuple(presets))
    return presets[waste_stream]


def list_waste_streams() -> list[str]:
    """Names of the waste-stream presets the engine supports."""
    try:
        engine = _load_engine()
    except EngineUnavailableError:
        return []
    return list(engine.composition.PRESETS)


#: Waste streams offered by the current engine, resolved lazily on first
#: access (PEP 562) so that importing this module never imports the engine.
AVAILABLE_WASTE_STREAMS: tuple[str, ...]


def __getattr__(name: str) -> Any:
    if name == "AVAILABLE_WASTE_STREAMS":
        return tuple(list_waste_streams())
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# --------------------------------------------------------------------------
# Pure serialisation helpers (dataclasses in, JSON-friendly dicts out).
# --------------------------------------------------------------------------


def as_jsonable(value: Any) -> Any:
    """Recursively convert a dataclass/tuple/dict tree into JSON types."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: as_jsonable(getattr(value, field.name))
            for field in dataclasses.fields(value)
        }
    if isinstance(value, dict):
        return {str(key): as_jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [as_jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    # Anything exotic (e.g. an enum) falls back to its string form.
    return str(value)


def serialize_assessment(assessment: Any) -> dict[str, Any]:
    """Flatten an engine ``BatchAssessment`` into the API response shape.

    The stage dataclasses are serialised in full (nested), with the two
    summary conveniences — ``summary_lines`` and the recommended route —
    lifted to the top level for easy consumption by the demo UI.
    """
    return {
        "tonnage_t": assessment.tonnage_t,
        "moisture": assessment.moisture,
        "age_h": assessment.age_h,
        "phase": assessment.phase,
        "composition": as_jsonable(assessment.composition),
        "generation": as_jsonable(assessment.generation),
        "balance": as_jsonable(assessment.balance),
        "suitability": as_jsonable(assessment.suitability),
        # ``actionable`` is a derived property, not a dataclass field, so it
        # is lifted explicitly: consumers must read it from the engine.
        "recommendation": {
            **as_jsonable(assessment.recommendation),
            "actionable": assessment.recommendation.actionable,
        },
        "recommended_route": assessment.recommendation.route,
        "headline": assessment.recommendation.headline,
        "summary": assessment.summary_lines(),
    }


# --------------------------------------------------------------------------
# Public entry point.
# --------------------------------------------------------------------------


def run_assessment(
    waste_stream: str,
    tonnage_t: float,
    moisture: float,
    age_h: float,
) -> dict[str, Any]:
    """Run the full assessment chain for one batch and serialise the result.

    Args:
        waste_stream: an engine preset name (e.g. ``"mixed-msw"``);
            unknown names raise :class:`UnknownWasteStreamError`.
        tonnage_t: wet-basis batch tonnage in tonnes (>= 0).
        moisture: wet-basis moisture fraction in [0, 1].
        age_h: elapsed time since disposal, in hours.

    Returns:
        A JSON-friendly dict with every stage's output plus a summary.

    Raises:
        UnknownWasteStreamError: ``waste_stream`` is not a known preset.
        InvalidBatchError: numeric inputs are outside the engine's domain.
        EngineUnavailableError: the engine could not be imported.
    """
    engine = _load_engine()
    composition = _resolve_waste_stream(engine, waste_stream)

    try:
        assessment = engine.pipeline.assess_batch(
            composition,
            tonnage_t=tonnage_t,
            moisture=moisture,
            age_h=age_h,
            # The CFD transport stage was dropped from Lynceus, so there is
            # no mesh whose independence would need a caveat.
            screening=False,
        )
    except ValueError as exc:
        # The engine validates tonnage/moisture; surface that as a 422-shaped
        # error while letting UnknownWasteStreamError (also a ValueError
        # subclass) pass through untouched.
        if isinstance(exc, UnknownWasteStreamError):
            raise
        raise InvalidBatchError(str(exc)) from exc

    return serialize_assessment(assessment)
