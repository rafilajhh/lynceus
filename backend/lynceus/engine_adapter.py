"""Adapter between the Lynceus API and the Scentinel engine.

Scentinel (:mod:`scentinel.core`) is the physics; Lynceus is the service.
This module is the only place the two meet, so the rest of the backend never
imports Scentinel directly and the engine can evolve behind this seam.

Design notes:

* ``scentinel`` is imported lazily inside :func:`_load_engine`, never at
  module import time. A missing engine therefore degrades into a clear
  runtime error (surfaced by ``/health`` and ``/assess``) instead of
  breaking every import of Lynceus.
* All serialisation helpers are pure functions over dataclasses, so they are
  trivially unit-testable without the engine installed.
* ``screening=False`` is passed to :func:`scentinel.core.pipeline.assess_batch`
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
    """Scentinel is not importable in this process."""

    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


class UnknownWasteStreamError(ValueError):
    """The requested waste stream is not a known Scentinel preset (HTTP 422)."""

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
    """Import ``scentinel.core`` (plus the submodules we use) or fail clearly.

    ``scentinel.core``'s ``__init__`` does not re-export its submodules, so
    the pieces Lynceus needs — ``composition`` and ``pipeline`` — are
    imported explicitly. Import stays lazy: it happens on first request, not
    at module load, so a missing engine degrades into a clear runtime error
    instead of breaking every import of Lynceus, and tests can monkeypatch
    this function to simulate failures.
    """
    try:
        import scentinel.core as engine  # type: ignore[import-untyped]
        import scentinel.core.composition  # noqa: F401  (registers submodule)
        import scentinel.core.pipeline  # noqa: F401  (registers submodule)
    except ImportError as exc:
        raise EngineUnavailableError(
            "the Scentinel engine package 'scentinel' is not installed or "
            f"not importable in this process ({exc}); the Lynceus /assess "
            "endpoint requires it — install Scentinel or add its src/ "
            "directory to PYTHONPATH"
        ) from exc
    return engine


def engine_available() -> bool:
    """True when ``scentinel.core`` can be imported (used by ``/health``)."""
    try:
        _load_engine()
    except EngineUnavailableError:
        return False
    return True


def _resolve_waste_stream(engine: Any, waste_stream: str) -> Any:
    """Map a waste-stream name onto its Scentinel composition preset."""
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
#: access (PEP 562) so that importing this module never imports Scentinel.
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
    """Flatten a Scentinel ``BatchAssessment`` into the API response shape.

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
        "recommendation": as_jsonable(assessment.recommendation),
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
    """Run the full Scentinel chain for one batch and serialise the result.

    Args:
        waste_stream: a Scentinel preset name (e.g. ``"mixed-msw"``);
            unknown names raise :class:`UnknownWasteStreamError`.
        tonnage_t: wet-basis batch tonnage in tonnes (>= 0).
        moisture: wet-basis moisture fraction in [0, 1].
        age_h: elapsed time since disposal, in hours.

    Returns:
        A JSON-friendly dict with every stage's output plus a summary.

    Raises:
        UnknownWasteStreamError: ``waste_stream`` is not a known preset.
        InvalidBatchError: numeric inputs are outside the engine's domain.
        EngineUnavailableError: Scentinel could not be imported.
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
