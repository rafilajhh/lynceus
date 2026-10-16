"""Lynceus audit record module — immutable, append-only inspection records.

Implements the audit-provenance design from
``docs/research/audit-provenance.md`` §(b).  Each truck inspection
(foto, manifest teks, berat, gas) produces exactly one ``inspection-NNN``
directory holding a single ``audit.json`` written **twice, atomically**:

1. ``begin_record`` writes an honest ``in_progress`` record before any AI
   inference runs — a crash leaves an ``in_progress`` record behind, never a
   missing or falsely-successful one.
2. ``finish_record`` performs single-shot finalization to a terminal status
   (``completed`` / ``failed`` / ``cancelled``).  A terminal record is never
   rewritten; corrections are new records referencing the old one.

The ten invariants from the research doc §(b):

1.  **Ditulis dua kali, atomik** — ``in_progress`` before inference, replaced
    via sibling temp file + ``os.replace()``; a crash leaves an honest
    ``in_progress`` record.
2.  **Finalisasi single-shot** — a terminal record on disk can never be
    finalized again; corrections require a new record.
3.  **Input dibekukan sebelum AI berjalan** — input digests are captured in
    the ``begin`` record; when raw input bytes are re-supplied at
    ``finish_record`` time (``frozen_inputs``), their digests are recomputed
    and compared against the frozen digests — mismatch = hard
    ``INPUT_MISMATCH`` error.
4.  **Refuse-to-answer** — the schema forces ``missing`` fields to be listed
    when ``verdict.decision == refuse_insufficient_input``; a speculative
    suitability is represented by the explicit ``insufficient`` flag rather
    than fabricated numbers.
5.  **``completed`` ≠ benar** — ``execution_status`` is a pure process
    outcome; consumers must read the stated, never-inferred ``gates`` (closed
    enum with explicit ``not_evaluated`` / ``not_run`` states).
6.  **Validasi ulang saat load** — ``load_record`` applies the exact same
    strict validation used at write time (enums, timestamp regex, digest
    regex, finite numbers, extra-key rejection, cross-field consistency);
    hand-edited records are rejected hard with field-level error messages.
7.  **Encode → validate → write** — every payload is round-tripped through
    the strict loader *before* it touches disk, so a written record always
    passes its own reader.
8.  **Path relatif saja** — ``inputs.photo.filename`` must be a relative path
    (no drive letters, absolute paths, or parent traversal), keeping records
    portable with their evidence folders.
9.  **No central index** — ``list_inspections`` scans the filesystem; corrupt
    records are skipped with a recorded error instead of crashing the listing
    (while ``load_record`` on the same path still fails hard).
10. **Angka finite, enum tertutup, unit di nama field** — confidence values
    are closed-range ``0..1`` with NaN/inf rejected, every enum is closed,
    units live in field names (``value_kg``, ``readings_ppm``,
    ``*_at_utc``), and all timestamps are ISO 8601 UTC ``Z`` enforced by
    regex.

Only stdlib + pydantic v2.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

__all__ = [
    "AUDIT_FORMAT_VERSION",
    "SUPPORTED_FORMAT_VERSIONS",
    "AuditError",
    "ExecutionStatus",
    "Decision",
    "GateState",
    "Route",
    "Classification",
    "ApplicationRecord",
    "PhotoInput",
    "ManifestTextInput",
    "WeightInput",
    "GasInput",
    "InspectionInputs",
    "ContaminantBox",
    "ActionStep",
    "VLMOutput",
    "LLMOutput",
    "AIOutputs",
    "SuitabilityOutput",
    "RecommendationOutput",
    "EngineOutputs",
    "Verdict",
    "GateResult",
    "Gates",
    "Digest",
    "AuditRecord",
    "allocate_inspection_id",
    "sha256_hex",
    "sha256_field",
    "begin_record",
    "finish_record",
    "load_record",
    "list_inspections",
    "now_utc",
    "validate_timestamp",
]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Bump on any breaking schema change; older readers must reject, not
#: misinterpret (engine RUN_FORMAT_VERSION pattern, history.py:67-102).
#: The writer always stamps this version.  v2 added supplier, provider /
#: latency provenance, contaminant boxes and SOP-cited actions — all
#: optional with empty defaults, so v1 records still decode.
AUDIT_FORMAT_VERSION = 2

#: Versions the reader accepts; anything else is rejected hard.
SUPPORTED_FORMAT_VERSIONS = (1, 2)

#: Closed enum of how contaminants were localised in the photo.
LOCALISATION_MODES = ("box", "zone")

RECORD_FILENAME = "audit.json"
INSPECTION_DIR_RE = re.compile(r"^inspection-(\d+)$")
RECORD_ID_RE = re.compile(r"^inspection-(\d+)$")
SHA256_FIELD_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z$")
SOP_REF_RE = re.compile(r"^SOP-RDF-\d+\.\d+$", re.ASCII)

#: Digest of the empty byte string — placeholder for fields not yet known at
#: begin time.  Its regex validity keeps the in_progress record decodable.
EMPTY_SHA256_FIELD = "sha256:" + hashlib.sha256(b"").hexdigest()

GATE_NAMES = (
    "vlm_confidence",
    "ocr_confidence",
    "manifest_crosscheck",
    "gas_plausibility",
    "weight_plausibility",
)
#: Gates added after format v1: optional in the schema so records written
#: before them still load, always written by the current API.
OPTIONAL_GATE_NAMES = ("detector_second_opinion",)

#: Consistent error prefixes so failures are greppable (engine
#: NO_READINGS_ERROR pattern — prefixed-error rule).
_ERR_FORMAT = "FORMAT_ERROR"
_ERR_STATE = "STATE_ERROR"
_ERR_IO = "IO_ERROR"
_ERR_INPUT_MISMATCH = "INPUT_MISMATCH"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class AuditError(Exception):
    """Raised for any audit-record validation / state violation.

    The message always carries a stable class prefix plus the offending
    field name(s), e.g. ``FORMAT_ERROR: gates.vlm_confidence.value: ...``.
    """


def _err(prefix: str, field: str, detail: str) -> AuditError:
    return AuditError(f"{prefix}: {field}: {detail}")


# ---------------------------------------------------------------------------
# Scalar validators (shared by pydantic field validators and public helpers)
# ---------------------------------------------------------------------------


def now_utc() -> str:
    """Current UTC time as ISO 8601 with trailing ``Z``."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def validate_timestamp(value: str, field: str = "timestamp") -> str:
    """Validate strict ISO 8601 UTC ``Z`` format (invariants 10 & 12)."""
    if not isinstance(value, str) or not TIMESTAMP_RE.match(value):
        raise _err(
            _ERR_FORMAT,
            field,
            "must be ISO 8601 UTC with trailing 'Z', e.g. "
            f"'2026-10-13T02:15:00Z' (got {value!r})",
        )
    try:
        fmt = "%Y-%m-%dT%H:%M:%S.%f" if "." in value else "%Y-%m-%dT%H:%M:%S"
        datetime.strptime(value[:-1], fmt)
    except ValueError as exc:  # pragma: no cover - regex pre-guards most
        raise _err(_ERR_FORMAT, field, f"invalid calendar datetime: {value!r}") from exc
    return value


def sha256_hex(data: bytes) -> str:
    """Raw SHA-256 hex digest (64 lowercase hex chars) of ``data``."""
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise _err(
            _ERR_FORMAT,
            "sha256_hex(data)",
            f"expected bytes, got {type(data).__name__}",
        )
    return hashlib.sha256(bytes(data)).hexdigest()


def sha256_field(data: bytes) -> str:
    """Digest in canonical persisted form: ``sha256:<64 hex>``.

    Validated against the digest regex — a malformed digest can never enter a
    record (invariant 10).
    """
    value = "sha256:" + sha256_hex(data)
    if not SHA256_FIELD_RE.match(value):  # pragma: no cover - cannot happen
        raise _err(_ERR_FORMAT, "digest", f"malformed digest field: {value!r}")
    return value


def safe_filename(name: str) -> str:
    """Reduce any incoming photo path to a portable bare filename.

    Demo clients may send site URLs ("/demo/red-1.jpg") or absolute paths;
    the audit record's portability invariant allows neither. Keep only the
    final path component and strip directory markers.
    """
    candidate = name.replace("\\", "/").rsplit("/", 1)[-1].strip()
    return candidate or "photo.jpg"


def _validate_sha256_field(value: str, field: str) -> str:
    if not isinstance(value, str) or not SHA256_FIELD_RE.match(value):
        raise _err(
            _ERR_FORMAT,
            field,
            f"must match 'sha256:<64 lowercase hex>' (got {value!r})",
        )
    return value


def _validate_relative_filename(value: str, field: str) -> str:
    """Records must stay portable: relative paths inside the inspection
    folder only (invariant 8; frozen-history pattern)."""
    if not isinstance(value, str) or not value:
        raise _err(_ERR_FORMAT, field, f"must be a non-empty string (got {value!r})")
    if os.path.isabs(value) or re.match(r"^[A-Za-z]:", value) or value.startswith("\\"):
        raise _err(_ERR_FORMAT, field, f"absolute/workstation path not allowed (got {value!r})")
    if any(part == ".." for part in Path(value).parts):
        raise _err(_ERR_FORMAT, field, f"parent traversal not allowed (got {value!r})")
    return value


def _validate_confidence(value: float, field: str) -> float:
    """Confidence numbers must be finite and within closed range 0..1
    (invariant 10)."""
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _err(_ERR_FORMAT, field, f"must be a number (got {value!r})")
    value = float(value)
    if math.isnan(value) or math.isinf(value):
        raise _err(_ERR_FORMAT, field, f"must be finite (got {value!r})")
    if not 0.0 <= value <= 1.0:
        raise _err(_ERR_FORMAT, field, f"must be within 0..1 (got {value!r})")
    return value


def _validate_finite_number(value: float, field: str) -> float:
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _err(_ERR_FORMAT, field, f"must be a number (got {value!r})")
    value = float(value)
    if math.isnan(value) or math.isinf(value):
        raise _err(_ERR_FORMAT, field, f"must be finite (got {value!r})")
    return value


def _validate_closed_enum(value: str, allowed: tuple, field: str) -> str:
    if value not in allowed:
        raise _err(
            _ERR_FORMAT,
            field,
            f"must be one of {'|'.join(allowed)} (got {value!r})",
        )
    return value


# ---------------------------------------------------------------------------
# Closed enums (invariant 10 / engine pattern 11)
# ---------------------------------------------------------------------------


class ExecutionStatus:
    """Closed enum: process outcome only — ``completed`` means the pipeline
    finished cleanly, **never** a claim that the AI was correct (invariant
    5)."""

    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    ALL = (IN_PROGRESS, COMPLETED, FAILED, CANCELLED)
    TERMINAL = (COMPLETED, FAILED, CANCELLED)


class Decision:
    """Closed enum for the final verdict."""

    ACCEPT = "accept"
    REJECT = "reject"
    REFUSE_INSUFFICIENT_INPUT = "refuse_insufficient_input"
    ESCALATE_HUMAN = "escalate_human"
    ALL = (ACCEPT, REJECT, REFUSE_INSUFFICIENT_INPUT, ESCALATE_HUMAN)


class GateState:
    """Closed enum per gate, stated — never inferred from exit codes."""

    NOT_EVALUATED = "not_evaluated"
    NOT_RUN = "not_run"
    PASSED = "passed"
    FAILED = "failed"
    ALL = (NOT_EVALUATED, NOT_RUN, PASSED, FAILED)


class Route:
    """Closed enum of engine recommendation routes."""

    ACCEPT_PROCESSING = "accept_processing"
    REJECT = "reject"
    SEGREGATE = "segregate"
    HOLD_FOR_REVIEW = "hold_for_review"
    ALL = (ACCEPT_PROCESSING, REJECT, SEGREGATE, HOLD_FOR_REVIEW)


class Classification:
    """Screening vs validated, stated (empty never means passed)."""

    SCREENING_ESTIMATE = "screening_estimate"
    VALIDATED = "validated"
    ALL = (SCREENING_ESTIMATE, VALIDATED)


# ---------------------------------------------------------------------------
# Pydantic models (v2 style, extra="forbid" → strict decode)
# ---------------------------------------------------------------------------


class _StrictModel(BaseModel):
    """Base model: extra fields forbidden so hand-added keys are rejected
    (strict-decode pattern, closed-schema rule)."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class ApplicationRecord(_StrictModel):
    name: str
    version: str


class PhotoInput(_StrictModel):
    filename: str
    sha256: str
    captured_at_utc: str
    provenance: str

    @field_validator("sha256")
    @classmethod
    def _v_sha256(cls, v: str) -> str:
        return _validate_sha256_field(v, "inputs.photo.sha256")

    @field_validator("captured_at_utc")
    @classmethod
    def _v_captured(cls, v: str) -> str:
        return validate_timestamp(v, "inputs.photo.captured_at_utc")

    @field_validator("filename")
    @classmethod
    def _v_filename(cls, v: str) -> str:
        return _validate_relative_filename(v, "inputs.photo.filename")


class ManifestTextInput(_StrictModel):
    source: str
    raw_text_sha256: str
    extracted_fields: Dict[str, Any]
    ocr_confidence: float

    @field_validator("raw_text_sha256")
    @classmethod
    def _v_sha256(cls, v: str) -> str:
        return _validate_sha256_field(v, "inputs.manifest_text.raw_text_sha256")

    @field_validator("ocr_confidence")
    @classmethod
    def _v_conf(cls, v: float) -> float:
        return _validate_confidence(v, "inputs.manifest_text.ocr_confidence")

    @field_validator("extracted_fields")
    @classmethod
    def _v_fields(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(v, dict):
            raise _err(_ERR_FORMAT, "inputs.manifest_text.extracted_fields", "must be an object")
        return v


class WeightInput(_StrictModel):
    value_kg: float
    source: str
    measured_at_utc: str

    @field_validator("value_kg")
    @classmethod
    def _v_value(cls, v: float) -> float:
        v = _validate_finite_number(v, "inputs.weight.value_kg")
        if v < 0:
            raise _err(_ERR_FORMAT, "inputs.weight.value_kg", f"must be non-negative (got {v!r})")
        return v

    @field_validator("measured_at_utc")
    @classmethod
    def _v_ts(cls, v: str) -> str:
        return validate_timestamp(v, "inputs.weight.measured_at_utc")


class GasInput(_StrictModel):
    readings_ppm: Dict[str, float]
    source: str
    measured_at_utc: str

    @field_validator("readings_ppm")
    @classmethod
    def _v_readings(cls, v: Dict[str, float]) -> Dict[str, float]:
        if not isinstance(v, dict):
            raise _err(_ERR_FORMAT, "inputs.gas.readings_ppm", "must be an object")
        for key, val in v.items():
            if not isinstance(key, str) or not key:
                raise _err(
                    _ERR_FORMAT,
                    "inputs.gas.readings_ppm",
                    f"gas key must be a non-empty string (got {key!r})",
                )
            if val is None or isinstance(val, bool) or not isinstance(val, (int, float)):
                raise _err(
                    _ERR_FORMAT,
                    f"inputs.gas.readings_ppm.{key}",
                    f"must be a number (got {val!r})",
                )
            val = float(val)
            if math.isnan(val) or math.isinf(val):
                raise _err(_ERR_FORMAT, f"inputs.gas.readings_ppm.{key}", f"must be finite (got {val!r})")
            if val < 0:
                raise _err(_ERR_FORMAT, f"inputs.gas.readings_ppm.{key}", f"must be non-negative (got {val!r})")
            v[key] = val
        return v

    @field_validator("measured_at_utc")
    @classmethod
    def _v_ts(cls, v: str) -> str:
        return validate_timestamp(v, "inputs.gas.measured_at_utc")


class InspectionInputs(_StrictModel):
    truck_id: str
    photo: PhotoInput
    manifest_text: ManifestTextInput
    weight: WeightInput
    gas: GasInput
    supplier: Optional[str] = None

    @field_validator("truck_id")
    @classmethod
    def _v_truck(cls, v: str) -> str:
        if not isinstance(v, str) or not v.strip():
            raise _err(_ERR_FORMAT, "inputs.truck_id", f"must be a non-empty string (got {v!r})")
        return v


def _validate_latency_ms(value: Optional[float], field: str) -> Optional[float]:
    """Latency is optional (stub results carry none); when present it must
    be finite and non-negative (invariant 10: unit in the field name)."""
    if value is None:
        return value
    value = _validate_finite_number(value, field)
    if value < 0:
        raise _err(_ERR_FORMAT, field, f"must be non-negative (got {value!r})")
    return value


class ContaminantBox(_StrictModel):
    """One localised contaminant: normalised image coordinates in 0..1,
    top-left ``(x0, y0)`` strictly before bottom-right ``(x1, y1)``."""

    label: str
    x0: float
    y0: float
    x1: float
    y1: float

    @field_validator("x0", "y0", "x1", "y1")
    @classmethod
    def _v_coord(cls, v: float, info: Any) -> float:
        return _validate_confidence(v, f"ai_outputs.vlm.boxes[].{info.field_name}")

    @model_validator(mode="after")
    def _v_order(self) -> "ContaminantBox":
        if not self.x0 < self.x1:
            raise _err(
                _ERR_FORMAT,
                "ai_outputs.vlm.boxes[].x0",
                f"must be less than x1 (got x0={self.x0!r}, x1={self.x1!r})",
            )
        if not self.y0 < self.y1:
            raise _err(
                _ERR_FORMAT,
                "ai_outputs.vlm.boxes[].y0",
                f"must be less than y1 (got y0={self.y0!r}, y1={self.y1!r})",
            )
        return self


class ActionStep(_StrictModel):
    """One ordered recommended action, cited to an SOP clause."""

    order: int
    text: str
    sop_ref: str

    @field_validator("order")
    @classmethod
    def _v_order(cls, v: int) -> int:
        if v < 1:
            raise _err(
                _ERR_FORMAT,
                "engine_outputs.recommendation.actions[].order",
                f"must be >= 1 (got {v!r})",
            )
        return v

    @field_validator("text")
    @classmethod
    def _v_text(cls, v: str) -> str:
        if not v.strip():
            raise _err(
                _ERR_FORMAT,
                "engine_outputs.recommendation.actions[].text",
                "must be a non-empty string",
            )
        return v

    @field_validator("sop_ref")
    @classmethod
    def _v_sop_ref(cls, v: str) -> str:
        if not SOP_REF_RE.fullmatch(v):
            raise _err(
                _ERR_FORMAT,
                "engine_outputs.recommendation.actions[].sop_ref",
                f"must match 'SOP-RDF-<n>.<n>' (got {v!r})",
            )
        return v


class VLMOutput(_StrictModel):
    model: str
    model_version: str
    raw_output_sha256: str
    detected: Dict[str, Any]
    confidence: float
    provider: Optional[str] = None
    latency_ms: Optional[float] = None
    boxes: List[ContaminantBox] = []
    localisation: Optional[str] = None
    #: The vision models that failed before ``model`` answered (each
    #: "<model>: <error> after <s> s"); absent when the primary answered and
    #: on records written before the fallback chain existed.
    fallback_from: Optional[List[str]] = None

    @field_validator("latency_ms")
    @classmethod
    def _v_latency(cls, v: Optional[float]) -> Optional[float]:
        return _validate_latency_ms(v, "ai_outputs.vlm.latency_ms")

    @field_validator("localisation")
    @classmethod
    def _v_localisation(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        return _validate_closed_enum(v, LOCALISATION_MODES, "ai_outputs.vlm.localisation")

    @field_validator("raw_output_sha256")
    @classmethod
    def _v_sha256(cls, v: str) -> str:
        return _validate_sha256_field(v, "ai_outputs.vlm.raw_output_sha256")

    @field_validator("confidence")
    @classmethod
    def _v_conf(cls, v: float) -> float:
        return _validate_confidence(v, "ai_outputs.vlm.confidence")


class LLMOutput(_StrictModel):
    model: str
    model_version: str
    prompt_sha256: str
    raw_output_sha256: str
    reasoning: str
    confidence: float
    provider: Optional[str] = None
    latency_ms: Optional[float] = None

    @field_validator("latency_ms")
    @classmethod
    def _v_latency(cls, v: Optional[float]) -> Optional[float]:
        return _validate_latency_ms(v, "ai_outputs.llm.latency_ms")

    @field_validator("prompt_sha256")
    @classmethod
    def _v_prompt(cls, v: str) -> str:
        return _validate_sha256_field(v, "ai_outputs.llm.prompt_sha256")

    @field_validator("raw_output_sha256")
    @classmethod
    def _v_raw(cls, v: str) -> str:
        return _validate_sha256_field(v, "ai_outputs.llm.raw_output_sha256")

    @field_validator("confidence")
    @classmethod
    def _v_conf(cls, v: float) -> float:
        return _validate_confidence(v, "ai_outputs.llm.confidence")


class GasOutput(_StrictModel):
    """Gate-gas channel provenance: which instrument class produced the
    readings (a live gate sensor or the physics digital twin)
    and the regulatory basis of the twin's generation stage."""

    source: str
    instrument: Optional[Dict[str, Any]] = None
    model_basis: Optional[str] = None


class DetectorBox(_StrictModel):
    """One detector box: class label, its confidence, and ``[x0, y0, x1, y1]``
    normalised 0..1 from the top-left with x0 < x1 and y0 < y1."""

    label: str
    confidence: float
    box: List[float]

    @field_validator("confidence")
    @classmethod
    def _v_conf(cls, v: float) -> float:
        return _validate_confidence(v, "ai_outputs.detector.boxes[].confidence")

    @field_validator("box")
    @classmethod
    def _v_box(cls, v: List[float]) -> List[float]:
        field = "ai_outputs.detector.boxes[].box"
        if len(v) != 4:
            raise _err(_ERR_FORMAT, field, f"must have 4 coordinates (got {len(v)})")
        for coord in v:
            _validate_confidence(coord, field)
        if not (v[0] < v[2] and v[1] < v[3]):
            raise _err(_ERR_FORMAT, field, f"must satisfy x0 < x1 and y0 < y1 (got {v!r})")
        return v


class DetectorThresholds(_StrictModel):
    """The gate settings a detector result was judged with."""

    hard: float
    light: float
    escalate_light: bool

    @field_validator("hard", "light")
    @classmethod
    def _v_conf(cls, v: float) -> float:
        return _validate_confidence(v, "ai_outputs.detector.thresholds")


class DetectorOutput(_StrictModel):
    """The CPU object detector's second opinion (absent on older records).

    ``model_sha256`` (the ONNX file's digest) and ``thresholds`` are optional
    so detector blocks written before them still load.
    """

    model: str
    runtime: str
    latency_ms: Optional[float] = None
    boxes: List[DetectorBox] = []
    hard_contaminants: List[str] = []
    light_contaminants: List[str] = []
    model_sha256: Optional[str] = None
    thresholds: Optional[DetectorThresholds] = None

    @field_validator("latency_ms")
    @classmethod
    def _v_latency(cls, v: Optional[float]) -> Optional[float]:
        return _validate_latency_ms(v, "ai_outputs.detector.latency_ms")

    @field_validator("model_sha256")
    @classmethod
    def _v_model_sha(cls, v: Optional[str]) -> Optional[str]:
        return None if v is None else _validate_sha256_field(v, "ai_outputs.detector.model_sha256")


class AIOutputs(_StrictModel):
    vlm: VLMOutput
    llm: LLMOutput
    gas: Optional[GasOutput] = None
    detector: Optional[DetectorOutput] = None


class SuitabilityOutput(_StrictModel):
    classification: str
    score: float
    rule: str

    @field_validator("score")
    @classmethod
    def _v_score(cls, v: float) -> float:
        return _validate_confidence(v, "engine_outputs.suitability.score")


class RecommendationOutput(_StrictModel):
    actionable: bool
    route: str
    headline: str
    insufficient: bool
    missing: List[str]
    caveats: List[str]
    alternative: str
    actions: List[ActionStep] = []

    @field_validator("route")
    @classmethod
    def _v_route(cls, v: str) -> str:
        return _validate_closed_enum(v, Route.ALL, "engine_outputs.recommendation.route")

    @field_validator("missing", "caveats")
    @classmethod
    def _v_lists(cls, v: List[str], info: Any) -> List[str]:
        field = f"engine_outputs.recommendation.{info.field_name}"
        if not isinstance(v, list) or any(not isinstance(item, str) for item in v):
            raise _err(_ERR_FORMAT, field, "must be a list of strings")
        return v


class EngineOutputs(_StrictModel):
    suitability: SuitabilityOutput
    recommendation: RecommendationOutput


class Verdict(_StrictModel):
    decision: str
    decided_at_utc: str
    classification: str
    uncertainty: str

    @field_validator("decision")
    @classmethod
    def _v_decision(cls, v: str) -> str:
        return _validate_closed_enum(v, Decision.ALL, "verdict.decision")

    @field_validator("classification")
    @classmethod
    def _v_classification(cls, v: str) -> str:
        return _validate_closed_enum(v, Classification.ALL, "verdict.classification")

    @field_validator("decided_at_utc")
    @classmethod
    def _v_ts(cls, v: str) -> str:
        return validate_timestamp(v, "verdict.decided_at_utc")


class GateResult(_StrictModel):
    """One quality gate: stated, never inferred (invariant 5)."""

    state: str
    value: Optional[float] = None
    threshold: Optional[float] = None
    reason: Optional[str] = None

    @field_validator("state")
    @classmethod
    def _v_state(cls, v: str) -> str:
        return _validate_closed_enum(v, GateState.ALL, "gates.<gate>.state")

    @field_validator("value", "threshold")
    @classmethod
    def _v_numbers(cls, v: Optional[float], info: Any) -> Optional[float]:
        if v is None:
            return v
        return _validate_finite_number(v, f"gates.<gate>.{info.field_name}")


class Gates(_StrictModel):
    vlm_confidence: GateResult
    ocr_confidence: GateResult
    manifest_crosscheck: GateResult
    gas_plausibility: GateResult
    weight_plausibility: GateResult
    detector_second_opinion: Optional[GateResult] = None


class Digest(_StrictModel):
    record_sha256: str
    input_digests: Dict[str, str]
    algorithm: str

    @field_validator("record_sha256")
    @classmethod
    def _v_record(cls, v: str) -> str:
        return _validate_sha256_field(v, "digest.record_sha256")

    @field_validator("input_digests")
    @classmethod
    def _v_inputs(cls, v: Dict[str, str]) -> Dict[str, str]:
        if not isinstance(v, dict):
            raise _err(_ERR_FORMAT, "digest.input_digests", "must be an object")
        for key, val in v.items():
            if not isinstance(key, str) or not key:
                raise _err(
                    _ERR_FORMAT,
                    "digest.input_digests",
                    f"digest key must be a non-empty string (got {key!r})",
                )
            _validate_sha256_field(val, f"digest.input_digests.{key}")
        return v

    @field_validator("algorithm")
    @classmethod
    def _v_algorithm(cls, v: str) -> str:
        if v != "sha256":
            raise _err(_ERR_FORMAT, "digest.algorithm", f"must be 'sha256' (got {v!r})")
        return v


class AuditRecord(_StrictModel):
    """The full audit record — frozen snapshot of inputs, AI outputs, engine
    outputs, verdict, stated gates, and digests."""

    format_version: int
    record_id: str
    execution_status: str
    started_at_utc: str
    finished_at_utc: Optional[str] = None
    application: ApplicationRecord
    inputs: InspectionInputs
    ai_outputs: AIOutputs
    engine_outputs: EngineOutputs
    verdict: Verdict
    gates: Gates
    digest: Digest

    @field_validator("format_version")
    @classmethod
    def _v_version(cls, v: int) -> int:
        if v not in SUPPORTED_FORMAT_VERSIONS:
            supported = ", ".join(str(n) for n in SUPPORTED_FORMAT_VERSIONS)
            raise _err(
                _ERR_FORMAT,
                "format_version",
                f"unsupported audit format version {v!r}; this reader "
                f"supports {supported}",
            )
        return v

    @field_validator("record_id")
    @classmethod
    def _v_record_id(cls, v: str) -> str:
        if not isinstance(v, str) or not RECORD_ID_RE.match(v):
            raise _err(
                _ERR_FORMAT,
                "record_id",
                f"must match 'inspection-NNN' (e.g. 'inspection-000123'; got {v!r})",
            )
        return v

    @field_validator("execution_status")
    @classmethod
    def _v_status(cls, v: str) -> str:
        return _validate_closed_enum(v, ExecutionStatus.ALL, "execution_status")

    @field_validator("started_at_utc")
    @classmethod
    def _v_started(cls, v: str) -> str:
        return validate_timestamp(v, "started_at_utc")

    @field_validator("finished_at_utc")
    @classmethod
    def _v_finished(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        return validate_timestamp(v, "finished_at_utc")

    @model_validator(mode="after")
    def _v_cross_field(self) -> "AuditRecord":
        # finished_at mandatory at terminal, forbidden while in_progress
        # (invariants 1 & 2; frozen-schema rules).
        if self.execution_status == ExecutionStatus.IN_PROGRESS:
            if self.finished_at_utc is not None:
                raise _err(
                    _ERR_STATE,
                    "finished_at_utc",
                    "must be null while execution_status is 'in_progress'",
                )
        else:
            if self.finished_at_utc is None:
                raise _err(
                    _ERR_STATE,
                    "finished_at_utc",
                    f"is required when execution_status is {self.execution_status!r}",
                )
            if self.finished_at_utc < self.started_at_utc:
                raise _err(
                    _ERR_STATE,
                    "finished_at_utc",
                    f"finished_at_utc {self.finished_at_utc!r} precedes "
                    f"started_at_utc {self.started_at_utc!r}",
                )
        # Refuse-to-answer coherence (invariant 4): refusing without listing
        # what is missing would be an opaque refusal.
        if (
            self.verdict.decision == Decision.REFUSE_INSUFFICIENT_INPUT
            and not self.engine_outputs.recommendation.missing
        ):
            raise _err(
                _ERR_STATE,
                "engine_outputs.recommendation.missing",
                "must list the missing fields when verdict.decision is "
                "'refuse_insufficient_input'",
            )
        return self


# ---------------------------------------------------------------------------
# Canonical encoding & strict decode
# ---------------------------------------------------------------------------


def _canonical_bytes(payload: Dict[str, Any]) -> bytes:
    """Deterministic JSON encoding (sorted keys, compact separators, no NaN)
    so record digests are stable across platforms."""
    try:
        text = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except ValueError as exc:
        # NaN/inf in the payload would be non-JSON-compliant; reject hard
        # with the audit error type (invariant 10).
        raise _err(_ERR_FORMAT, "digest", f"non-finite number in payload: {exc}") from exc
    return text.encode("utf-8")


def _stamp_record_digest(payload: Dict[str, Any]) -> None:
    """Set ``digest.record_sha256`` over the canonical serialization of the
    record *without* the digest field itself."""
    digestless = {k: v for k, v in payload.items() if k != "digest"}
    payload["digest"]["record_sha256"] = sha256_field(_canonical_bytes(digestless))


def _decode_strict(data: Dict[str, Any], source: str) -> AuditRecord:
    """Strict decode: any validation failure becomes an ``AuditError``
    naming the field (invariant 6)."""
    try:
        return AuditRecord.model_validate(data)
    except Exception as exc:
        raise _normalize_validation_error(exc, source) from exc


def _normalize_validation_error(exc: Exception, source: str) -> AuditError:
    """Convert pydantic exceptions into a field-naming AuditError.

    Our own validators raise ``AuditError``; pydantic wraps them inside
    ``ValidationError`` items (``ctx.error``), so we unwrap and preserve the
    original field-naming message whenever possible.
    """
    if isinstance(exc, AuditError):
        return exc
    lines: List[str] = []
    get_errors = getattr(exc, "errors", None)
    if callable(get_errors):
        for item in get_errors():
            inner = (item.get("ctx") or {}).get("error")
            if isinstance(inner, AuditError):
                lines.append(str(inner))
                continue
            loc = ".".join(str(part) for part in item.get("loc", ()))
            msg = item.get("msg", "invalid value")
            lines.append(f"{loc or '<root>'}: {msg}")
    if not lines:
        lines.append(str(exc))
    return AuditError(f"{_ERR_FORMAT} [{source}]: " + "; ".join(lines))


def _atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
    """Write JSON atomically: unique sibling temp file → ``os.replace()``.

    A failed replace leaves any previously valid record intact
    (invariant 1; atomic-write rule).  The temp name is unique per call so
    two concurrent writers can never clobber each other's staging file.
    """
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{uuid4().hex}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(payload, fh, sort_keys=True, ensure_ascii=False, allow_nan=False, indent=2)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except OSError as exc:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise _err(_ERR_IO, str(path), f"atomic write failed: {exc}") from exc


def _cleanup_empty_dir(path: Path) -> None:
    """Best-effort removal of a freshly reserved, still-empty inspection
    folder (engine pattern 29: no inspection without a record)."""
    try:
        if path.is_dir() and not any(path.iterdir()):
            path.rmdir()
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Filesystem ID allocation — record_id is never reused
# ---------------------------------------------------------------------------


#: Rescans allowed when concurrent inspections race for the same number.
_ALLOCATION_ATTEMPTS = 20


def allocate_inspection_id(storage_dir: "str | os.PathLike[str]") -> "tuple[str, Path]":
    """Reserve the next ``inspection-NNN`` directory and return
    ``(record_id, inspection_path)``.

    IDs are allocated from the *filesystem*, not memory (engine
    allocation rule, history.py:104-110): directories matching ``inspection-NNN``
    are counted even when their record is corrupt or missing, so an ID is
    never reused even after a crash or application restart.  The directory is
    created with ``mkdir(exist_ok=False)``, which is atomic: when two
    concurrent inspections pick the same number, exactly one wins and the
    loser rescans and takes the next free number (bounded retries; running out
    is a hard error).
    """
    storage = Path(storage_dir)
    storage.mkdir(parents=True, exist_ok=True)
    for _attempt in range(_ALLOCATION_ATTEMPTS):
        next_n = 1
        for entry in storage.iterdir():
            if not entry.is_dir():
                continue
            m = INSPECTION_DIR_RE.match(entry.name)
            if m:
                next_n = max(next_n, int(m.group(1)) + 1)
        record_id = f"inspection-{next_n:06d}"
        inspection_path = storage / record_id
        try:
            inspection_path.mkdir(exist_ok=False)
        except FileExistsError:
            continue  # lost the race for this number; rescan
        return record_id, inspection_path
    raise _err(
        _ERR_STATE,
        record_id,
        "inspection directory already exists — ID allocation race lost "
        f"{_ALLOCATION_ATTEMPTS} times",
    )


# ---------------------------------------------------------------------------
# begin_record — in_progress, atomic, inputs frozen
# ---------------------------------------------------------------------------


def begin_record(
    storage_dir: "str | os.PathLike[str]",
    application: Dict[str, str],
    inputs: Dict[str, Any],
    input_digests: Dict[str, str],
    *,
    reserved_record_id: Optional[str] = None,
) -> AuditRecord:
    """Write an honest ``in_progress`` record before AI inference starts.

    Inputs are frozen here (digests recorded; engine snapshot pattern
    pattern, history.py:559-595): live input changes after this point cannot
    alter a running record's claims — ``finish_record`` re-verifies raw input
    bytes against these frozen digests.  If the initial write fails and the
    freshly reserved folder is still empty, it is cleaned up best-effort —
    no inspection without a record (pattern 29).

    ``reserved_record_id`` lets the caller reserve the ID first (so an input
    collector seeded by the record identity — the gate gas channel — can run
    before the record is begun) and then begin into that same directory.  It
    must already exist as an empty ``inspection-NNN`` directory reserved by
    :func:`allocate_inspection_id`; a directory with an existing record, or a
    missing directory, is rejected.

    Returns the in-progress ``AuditRecord``.
    """
    if reserved_record_id is not None:
        if not RECORD_ID_RE.match(reserved_record_id):
            raise _err(
                _ERR_FORMAT,
                "record_id",
                f"reserved_record_id must match 'inspection-NNN' "
                f"(got {reserved_record_id!r})",
            )
        inspection_path = Path(storage_dir) / reserved_record_id
        if not inspection_path.is_dir():
            raise _err(
                _ERR_STATE,
                reserved_record_id,
                "reserved inspection directory does not exist — reserve it "
                "with allocate_inspection_id first",
            )
        if (inspection_path / RECORD_FILENAME).is_file():
            raise _err(
                _ERR_STATE,
                reserved_record_id,
                "reserved inspection directory already has a record — "
                "a reserved ID is begun into exactly once",
            )
        record_id = reserved_record_id
    else:
        record_id, inspection_path = allocate_inspection_id(storage_dir)
    record_path = inspection_path / RECORD_FILENAME
    started = now_utc()
    payload: Dict[str, Any] = {
        "format_version": AUDIT_FORMAT_VERSION,
        "record_id": record_id,
        "execution_status": ExecutionStatus.IN_PROGRESS,
        "started_at_utc": started,
        "finished_at_utc": None,
        "application": dict(application),
        "inputs": dict(inputs),
        # AI has not run yet: outputs are explicitly empty/zero, never
        # fabricated (refuse-to-answer starts at begin time).
        "ai_outputs": {
            "vlm": {
                "model": "",
                "model_version": "",
                "raw_output_sha256": EMPTY_SHA256_FIELD,
                "detected": {},
                "confidence": 0.0,
            },
            "llm": {
                "model": "",
                "model_version": "",
                "prompt_sha256": EMPTY_SHA256_FIELD,
                "raw_output_sha256": EMPTY_SHA256_FIELD,
                "reasoning": "",
                "confidence": 0.0,
            },
            "gas": None,
        },
        "engine_outputs": {
            "suitability": {"classification": "", "score": 0.0, "rule": ""},
            "recommendation": {
                "actionable": False,
                "route": Route.HOLD_FOR_REVIEW,
                "headline": "Inspection in progress.",
                "insufficient": False,
                "missing": [],
                "caveats": [],
                "alternative": "",
            },
        },
        "verdict": {
            "decision": Decision.ESCALATE_HUMAN,
            "decided_at_utc": started,
            "classification": Classification.SCREENING_ESTIMATE,
            "uncertainty": "Record not finalized; no verdict has been reached yet.",
        },
        "gates": {
            gate: {"state": GateState.NOT_EVALUATED, "value": None, "threshold": None, "reason": None}
            for gate in GATE_NAMES
        },
        "digest": {
            "record_sha256": EMPTY_SHA256_FIELD,
            "input_digests": dict(input_digests),
            "algorithm": "sha256",
        },
    }
    # Encode → stamp digest → strict-validate → write (invariants 6 & 7:
    # a written record must always pass its own reader).
    try:
        _stamp_record_digest(payload)
        record = _decode_strict(payload, f"begin_record:{record_id}")
        _atomic_write_json(record_path, payload)
    except AuditError:
        _cleanup_empty_dir(inspection_path)
        raise
    return record


# ---------------------------------------------------------------------------
# finish_record — single-shot terminal finalization
# ---------------------------------------------------------------------------


def finish_record(
    storage_dir: "str | os.PathLike[str]",
    record_id: str,
    execution_status: str,
    finished_at_utc: str,
    application: Dict[str, str],
    inputs: Dict[str, Any],
    ai_outputs: Dict[str, Any],
    engine_outputs: Dict[str, Any],
    verdict: Dict[str, Any],
    gates: Dict[str, Any],
    input_digests: Optional[Dict[str, str]] = None,
    *,
    frozen_inputs: Optional[Dict[str, bytes]] = None,
) -> AuditRecord:
    """Single-shot finalization of a record to a terminal status.

    * ``execution_status`` must be terminal (``completed`` / ``failed`` /
      ``cancelled``) and ``finished_at_utc`` is mandatory (validated).
    * The on-disk record must currently be ``in_progress`` — a terminal
      record can never be finalized again (invariant 2); corrections are new
      records referencing the old.
    * If ``frozen_inputs`` maps input names to raw bytes (e.g.
      ``{"photo": b"...", "manifest_text": b"..."}``), each digest is
      recomputed and compared against the digests frozen at ``begin_record``
      time — a mismatch is a hard ``INPUT_MISMATCH`` error (invariant 3).
    * The payload is encoded → strict-validated → written atomically
      (invariants 1, 6 & 7).

    Returns the finalized terminal ``AuditRecord``.
    """
    if execution_status not in ExecutionStatus.TERMINAL:
        raise _err(
            _ERR_STATE,
            "execution_status",
            "finish_record requires a terminal status "
            f"({'|'.join(ExecutionStatus.TERMINAL)}); got {execution_status!r}",
        )
    validate_timestamp(finished_at_utc, "finished_at_utc")

    storage = Path(storage_dir)
    record_path = storage / record_id / RECORD_FILENAME
    if not record_path.is_file():
        raise _err(
            _ERR_IO,
            str(record_path),
            "audit record not found — cannot finish a record that was never begun",
        )

    # Single-shot finalization is claimed with an exclusive lock file so two
    # concurrent finalizers cannot both pass the in_progress check and both
    # write (invariant 2).  O_CREAT|O_EXCL fails for the loser; the winner
    # removes the lock in `finally`.  record_id is unique per inspection, so
    # a stale lock from a crash only blocks re-finishing that one record —
    # acceptable, since a terminal transition is by definition one-shot.
    lock_path = record_path.with_name(record_path.name + ".finish.lock")
    lock_fd = None
    try:
        lock_fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise _err(
            _ERR_STATE,
            "execution_status",
            f"record {record_id!r} is already being finalized by another "
            "process (finish lock held); terminal records are never "
            "finalized twice",
        ) from exc
    try:
        return _finish_record_locked(
            record_path,
            record_id,
            execution_status,
            finished_at_utc,
            application,
            inputs,
            ai_outputs,
            engine_outputs,
            verdict,
            gates,
            input_digests,
            frozen_inputs=frozen_inputs,
        )
    finally:
        if lock_fd is not None:
            os.close(lock_fd)
        try:
            lock_path.unlink()
        except OSError:
            pass


def _finish_record_locked(
    record_path: Path,
    record_id: str,
    execution_status: str,
    finished_at_utc: str,
    application: Dict[str, str],
    inputs: Dict[str, Any],
    ai_outputs: Dict[str, Any],
    engine_outputs: Dict[str, Any],
    verdict: Dict[str, Any],
    gates: Dict[str, Any],
    input_digests: Optional[Dict[str, str]] = None,
    *,
    frozen_inputs: Optional[Dict[str, bytes]] = None,
) -> AuditRecord:

    # Single-shot: terminal records are immutable (invariant 2).
    current = load_record(record_path)
    if current.execution_status != ExecutionStatus.IN_PROGRESS:
        raise _err(
            _ERR_STATE,
            "execution_status",
            f"record {record_id!r} is already terminal "
            f"({current.execution_status!r}); terminal records are never "
            "finalized twice — write a new record instead",
        )
    if current.record_id != record_id:
        raise _err(
            _ERR_STATE,
            "record_id",
            f"on-disk record_id {current.record_id!r} does not match {record_id!r}",
        )

    # The begin-time digest map is authoritative (invariant 3): a caller may
    # never substitute a different map at finish time.
    if input_digests is not None and dict(input_digests) != dict(current.digest.input_digests):
        raise _err(
            _ERR_INPUT_MISMATCH,
            "digest.input_digests",
            "finish was given an input-digest map that differs from the one "
            "frozen at begin time — inputs are frozen at begin, never re-negotiated",
        )
    digests: Dict[str, str] = dict(current.digest.input_digests)

    # Invariant 3: outputs must answer the same inputs frozen at begin time.
    if frozen_inputs:
        for name, raw in frozen_inputs.items():
            expected = digests.get(name)
            if expected is None:
                raise _err(
                    _ERR_INPUT_MISMATCH,
                    f"digest.input_digests.{name}",
                    "input was provided at finish time but has no digest "
                    "frozen at begin time",
                )
            actual = sha256_field(raw)
            if actual != expected:
                raise _err(
                    _ERR_INPUT_MISMATCH,
                    f"digest.input_digests.{name}",
                    f"frozen digest {expected} does not match current input "
                    f"digest {actual} — input changed after being frozen",
                )

    payload: Dict[str, Any] = {
        "format_version": AUDIT_FORMAT_VERSION,
        "record_id": record_id,
        "execution_status": execution_status,
        "started_at_utc": current.started_at_utc,
        "finished_at_utc": finished_at_utc,
        "application": dict(application),
        "inputs": dict(inputs),
        "ai_outputs": dict(ai_outputs),
        "engine_outputs": dict(engine_outputs),
        "verdict": dict(verdict),
        "gates": dict(gates),
        "digest": {
            "record_sha256": EMPTY_SHA256_FIELD,
            "input_digests": digests,
            "algorithm": "sha256",
        },
    }

    # Encode → stamp digest → strict-validate → write (dual-write, pattern
    # 30: the writer can never write what its own reader would reject).
    _stamp_record_digest(payload)
    record = _decode_strict(payload, f"finish_record:{record_id}")
    _atomic_write_json(record_path, payload)
    return record


# ---------------------------------------------------------------------------
# load_record (strict) & list_inspections (skip corrupt)
# ---------------------------------------------------------------------------


def load_record(path: "str | os.PathLike[str]") -> AuditRecord:
    """Strictly decode an audit record from disk.

    Applies the same validation used at write time — closed enums, timestamp
    regex, digest regex, finite numbers, extra-key rejection, cross-field
    consistency — so a hand-edited record can never smuggle in foreign
    values (invariant 6).  Any violation raises ``AuditError`` naming the
    offending field.
    """
    record_path = Path(path)
    try:
        raw = record_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise _err(_ERR_IO, str(record_path), f"cannot read audit record: {exc}") from exc
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise _err(_ERR_FORMAT, str(record_path), f"invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise _err(
            _ERR_FORMAT,
            str(record_path),
            f"record must be a JSON object (got {type(data).__name__})",
        )

    # Schema first: a structurally invalid record must fail with its specific
    # error (enum, timestamp, format_version, ...), not a digest complaint.
    record = _decode_strict(data, str(record_path))

    # Tamper evidence (invariant 6): a record that is schema-valid but whose
    # body no longer matches its stored digest was edited after writing.
    # Recompute over the canonical digestless serialization with the writer's
    # exact canonicalization and compare in constant time.
    digest = data["digest"]
    stored = digest["record_sha256"]
    recomputed_payload = dict(data)
    recomputed = dict(digest)
    recomputed["record_sha256"] = EMPTY_SHA256_FIELD
    recomputed_payload["digest"] = recomputed
    _stamp_record_digest(recomputed_payload)
    expected = recomputed_payload["digest"]["record_sha256"]
    if not isinstance(stored, str) or not hmac.compare_digest(stored, expected):
        raise _err(
            _ERR_FORMAT,
            str(record_path),
            "digest.record_sha256 mismatch: record body does not match its stored digest",
        )

    return record


def list_inspections(storage_dir: "str | os.PathLike[str]") -> List[Dict[str, Any]]:
    """List inspection summaries; corrupt records are skipped, not fatal.

    There is no central index (invariant 9): the listing is a filesystem
    scan of ``inspection-NNN`` directories.  A corrupt or missing record
    appears in the result with ``"ok": False`` and the recorded ``"error"``
    instead of crashing the listing; ``load_record`` on the same path still
    fails hard (engine list_runs pattern, history.py:810-822).

    Returns a list of dicts sorted by inspection number:
    ``{"record_id", "execution_status", "ok", "error"}`` — ``error`` is
    omitted when ``ok`` is True.
    """
    storage = Path(storage_dir)
    if not storage.is_dir():
        return []
    entries: List[tuple] = []
    for entry in storage.iterdir():
        if not entry.is_dir():
            continue
        m = INSPECTION_DIR_RE.match(entry.name)
        if not m:
            continue
        num = int(m.group(1))
        record_path = entry / RECORD_FILENAME
        if not record_path.is_file():
            entries.append(
                (
                    num,
                    {
                        "record_id": entry.name,
                        "execution_status": None,
                        "ok": False,
                        "error": f"{_ERR_IO}: {record_path}: audit record file missing",
                    },
                )
            )
            continue
        try:
            record = load_record(record_path)
            entries.append(
                (num, {"record_id": record.record_id, "execution_status": record.execution_status, "ok": True})
            )
        except AuditError as exc:
            entries.append(
                (num, {"record_id": entry.name, "execution_status": None, "ok": False, "error": str(exc)})
            )
    entries.sort(key=lambda item: item[0])
    return [payload for _, payload in entries]
