"""FastAPI application for the Lynceus backend.

Routes:
    GET  /health   — liveness plus engine availability.
    POST /assess   — one batch assessment through the Lynceus decision engine.
    POST /inspect  — full AI gate inspection (VLM + LLM + engine + fusion verdict).
    POST /inspect/stream — the same inspection as NDJSON stage events + result.
    POST /warmup   — wake the vision model and the CPU detector (≤ once a minute).
    POST /waybill/read — read a waybill photo into confirmed-able fields.
    GET  /weighbridge/reading — simulated scale ticket for a plate.
    POST /assist   — Pythia: cited answers over plant documents and an audit record.
    GET  /shift-report — shift aggregation with supplier risk and explanations.
    GET  /benchmark/latest — newest committed validation summary (+ framing,
                             + its replay, + its hybrid VLM + detector re-score).
    GET  /benchmark/replay — newest replay re-score of a recorded run (current rules).
"""

from __future__ import annotations

import base64
import binascii
import importlib
import inspect as pyinspect
import json
import logging
import os
import queue
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from types import ModuleType
from typing import Any, AsyncIterator, Iterator, Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator
from lynceus import __version__
from lynceus import actions
from lynceus import assist
from lynceus import audit
from lynceus import auth
from lynceus import decision
from lynceus import detector
from lynceus import engine_adapter
from lynceus import gas_twin
from lynceus import impact
from lynceus import pipeline
from lynceus import shift
from lynceus import waybill
from lynceus import observations
from lynceus import weighbridge
from lynceus.config import get_settings, provider_for_url

_log = logging.getLogger(__name__)


def _optional_module(name: str) -> ModuleType | None:
    """``lynceus.<name>`` when it is installed, else ``None``.

    Only the module itself being absent counts: an import error inside it
    still raises, so a broken module is never silently skipped.
    """
    qualified = f"lynceus.{name}"
    try:
        return importlib.import_module(qualified)
    except ModuleNotFoundError as exc:
        if exc.name != qualified:
            raise
        return None

def _dir_from_env(name: str, default: Path) -> Path:
    """A directory from environment variable ``name``, else the source-tree ``default``.

    The defaults resolve relative to this file, which is only right for a
    source checkout or an editable install.  A regular ``pip install`` puts the
    package under site-packages, so the container sets ``LYNCEUS_WEB_DIR`` /
    ``LYNCEUS_BENCHMARK_DIR`` to where it staged those assets.
    """
    value = os.environ.get(name, "").strip()
    return Path(value) if value else default


#: Static web export served at ``/`` (``LYNCEUS_WEB_DIR`` overrides the source-tree path).
_WEB_DIR = _dir_from_env(
    "LYNCEUS_WEB_DIR", Path(__file__).resolve().parents[3] / "web" / "out"
)
#: Validation benchmark assets (manifest + committed result files);
#: ``LYNCEUS_BENCHMARK_DIR`` overrides the source-tree path.
_BENCHMARK_DIR = _dir_from_env(
    "LYNCEUS_BENCHMARK_DIR", Path(__file__).resolve().parents[2] / "benchmark"
)
#: What the benchmark is, stated with every result so no page can overstate it.
BENCHMARK_FRAMING = (
    "component validation on public RealWaste images — not field data from a plant"
)

#: Sent with every response.  No page of the app is meant to be framed, so
#: framing is refused outright (clickjacking); MIME sniffing is off; other
#: sites receive only the origin as referrer.
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "X-Frame-Options": "DENY",
}

# No OCR is performed on the waybill; this is the fixed confidence attached
# to operator-typed manifest text, not an OCR score.
_MANUAL_TEXT_CONFIDENCE = 0.95
#: Most sensor readings one inspection request may carry.
MAX_SUPPLIED_OBSERVATIONS = 20
#: Waste age the engine assumes when none was entered (stated as a caveat).
DEFAULT_AGE_H = 24.0

#: Largest accepted load photo, measured on the decoded bytes.
MAX_PHOTO_BYTES = 8 * 1024 * 1024
#: Accepted image formats, by magic bytes (the data: URI's claim is not trusted).
_PHOTO_MAGIC = (bytes([0xFF, 0xD8, 0xFF]), bytes([0x89, 0x50, 0x4E, 0x47]))  # JPEG, PNG


class PhotoError(ValueError):
    """An uploaded photo failed validation; maps to a 4xx before any record."""

    def __init__(self, status_code: int, error: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error = error


def decode_photo(photo_base64: str | None) -> bytes:
    """Decode and validate an uploaded photo; ``b""`` when none was sent.

    Accepts raw base64 or a ``data:image/...;base64,`` URI.  Only JPEG and PNG
    pass (by magic bytes), up to :data:`MAX_PHOTO_BYTES` decoded.  Called
    before ``audit.begin_record`` so a rejected upload leaves no record.
    """
    if not photo_base64:
        return b""
    text = photo_base64.strip()
    if text[:5].lower() == "data:":
        header, comma, rest = text.partition(",")
        if not comma or not header.lower().startswith("data:image/"):
            raise PhotoError(422, "invalid_photo", "photo is not an image data URI.")
        text = rest
    text = "".join(text.split())
    # Exact for well-formed base64; avoids decoding a huge payload just to refuse it.
    if len(text) * 3 // 4 - text.count("=", -2) > MAX_PHOTO_BYTES:
        raise PhotoError(
            413,
            "photo_too_large",
            f"photo exceeds the {MAX_PHOTO_BYTES // (1024 * 1024)} MB limit.",
        )
    try:
        raw = base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise PhotoError(422, "invalid_photo", "photo is not valid base64.") from exc
    if len(raw) > MAX_PHOTO_BYTES:
        raise PhotoError(
            413,
            "photo_too_large",
            f"photo exceeds the {MAX_PHOTO_BYTES // (1024 * 1024)} MB limit.",
        )
    if not raw.startswith(_PHOTO_MAGIC):
        raise PhotoError(422, "invalid_photo", "photo must be a JPEG or PNG image.")
    return raw

def _web_file(filename: str) -> Path:
    """Absolute path of a static-export page inside ``web/out``."""
    return _WEB_DIR / filename


def _wants_html(request: Request) -> bool:
    """Content negotiation for the pages that share a path with the API.

    A browser navigation sends ``Accept: text/html,application/xhtml+xml,…``
    (no ``application/json``); ``fetch`` from the demo frontend explicitly
    sends ``Accept: application/json`` and a bare ``fetch`` defaults to
    ``*/*``.  Rule: serve HTML only when ``text/html`` is offered AND
    ``application/json`` is not explicitly preferred — the JSON API keeps
    the path for every programmatic caller.
    """
    accept = request.headers.get("accept", "")
    wants_html = "text/html" in accept.lower()
    wants_json = "application/json" in accept.lower()
    return wants_html and not wants_json

class AssessRequest(BaseModel):
    """One waste batch, as the demo UI submits it."""

    waste_stream: str = Field(
        description="engine preset name, e.g. 'mixed-msw'.",
        examples=["mixed-msw"],
    )
    tonnage_t: float = Field(
        gt=0.0,
        description="Wet-basis batch tonnage in tonnes.",
        examples=[100.0],
    )
    moisture: float = Field(
        ge=0.0,
        le=1.0,
        description="Wet-basis moisture fraction in [0, 1].",
        examples=[0.40],
    )
    age_h: float = Field(
        ge=0.0,
        description="Elapsed time since disposal, in hours.",
        examples=[48.0],
    )


class WaybillReadRequest(BaseModel):
    """One waybill photo to read (``POST /waybill/read``)."""

    model_config = ConfigDict(extra="forbid")

    image_base64: str = Field(min_length=1, description="JPEG/PNG base64 or data URI.")
    filename: str | None = Field(default=None, max_length=200)
    demo_case: str | None = Field(
        default=None, description="Any value forces the offline reader (sample waybill only)."
    )


class ObservationIn(BaseModel):
    """One reading a site's own sensor gateway sends with the inspection
    (lynceus.observations record shape; the digest is computed here)."""

    model_config = ConfigDict(extra="forbid")

    source: str = Field(min_length=1, max_length=120)
    kind: str = Field(min_length=1, max_length=40)
    value: Any = None
    unit: str | None = Field(default=None, max_length=20)
    uncertainty: float | None = None
    status: Literal["ok", "poor", "mismatch", "not_installed", "unavailable"] = "ok"
    measured_at_utc: str | None = None
    simulated: bool = False
    note: str | None = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def _valid_time(self) -> "ObservationIn":
        if self.measured_at_utc is not None:
            try:
                audit.validate_timestamp(self.measured_at_utc, "observations[].measured_at_utc")
            except audit.AuditError as exc:  # a 422, not a 500
                raise ValueError(str(exc)) from exc
        return self


class WaybillReadMeta(BaseModel):
    """How the confirmed waybill fields were read (``/inspect`` input)."""

    model_config = ConfigDict(extra="ignore")

    confidence: float = Field(ge=0.0, le=1.0)
    model: str | None = None
    provenance: str | None = None
    latency_ms: float | None = Field(default=None, ge=0.0)
    edited_fields: list[str] = Field(default_factory=list)
    #: Optional per-field read confidences (the read's ``fields.*.confidence``):
    #: lets the "Waybill read" check count the unsure fields.
    field_confidences: dict[str, float] | None = None


class InspectRequest(BaseModel):
    """One truck inspection, as the demo UI submits it.

    Field aliases accept the manual-mode shape of ``web/app.js``
    (``stream``, ``moisture_pct``, ``photo_filename``) alongside the
    canonical names.  Everything except a usable payload is optional at the
    request layer: missing mandatory inputs produce an honest
    ``refuse_insufficient_input`` verdict (HTTP 200), never a 422.
    """

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    truck_id: str | None = Field(
        default=None, description="Truck / vehicle ID at the weighbridge."
    )
    supplier: str | None = Field(
        default=None,
        max_length=120,
        description="Supplier / hauler named on the waybill (shift report grouping).",
    )
    demo_case: str | None = Field(
        default=None,
        description="Scripted demo case (green | amber | red); forces the offline stub.",
    )
    photo_base64: str | None = Field(
        default=None,
        description="Base64 JPEG of the truck load (live VLM input).",
    )
    photo_filename: str | None = Field(
        default=None,
        description="Photo filename when no image bytes are available (stub mode).",
    )
    waybill_image_base64: str | None = Field(
        default=None,
        description="Base64 JPEG/PNG of the waybill document — archived as "
        "evidence in the audit record; no OCR is performed on it.",
    )
    waybill_photo_filename: str | None = Field(
        default=None,
        description="Filename of the uploaded waybill document photo.",
    )
    manifest_text: str | None = Field(
        default=None,
        description="Waybill / transfer-note text (LLM cross-check input).",
    )
    weight_kg: float | None = Field(
        default=None, gt=0.0, description="Actual weighbridge weight in kg."
    )
    declared_weight_kg: float | None = Field(
        default=None,
        description="Weight declared on the waybill, in kg.",
    )
    waste_stream: str | None = Field(
        default=None,
        validation_alias=AliasChoices("waste_stream", "stream"),
        description="engine preset name, e.g. 'mixed-msw' or 'rdf-feedstock'.",
    )
    moisture: float | None = Field(
        default=None,
        ge=0.0,
        le=100.0,
        validation_alias=AliasChoices("moisture", "moisture_pct"),
        description="Wet-basis moisture: fraction [0,1] or percent 0..100 "
        "(percent values are normalised to a fraction).",
    )
    age_h: float | None = Field(
        default=None,
        ge=0.0,
        description="Elapsed time since disposal, in hours (default 24 h, "
        "stated as a caveat).",
    )
    waybill_fields: dict[str, Any] | None = Field(
        default=None,
        description="The operator-confirmed waybill fields as plain values "
        "(POST /waybill/read field names), e.g. {'plate': 'B 9723 KXW', "
        "'net_kg': 16340}. Defaults truck, supplier, declared weight, waste "
        "stream, moisture and the manifest text.",
    )
    waybill_read: WaybillReadMeta | None = Field(
        default=None,
        description="How the waybill fields were read (absent: typed by the operator).",
    )
    weight_source: Literal["weighbridge_simulated", "weighbridge", "manual_entry"] | None = Field(
        default=None, description="Where weight_kg came from (audit inputs.weight.source)."
    )
    extra_photos_base64: list[str] | None = Field(
        default=None,
        max_length=audit.MAX_FRAMES - 1,
        description="Up to two extra camera angles of the load (JPEG/PNG base64).",
    )
    extra_photo_filenames: list[str] | None = Field(
        default=None,
        max_length=audit.MAX_FRAMES - 1,
        description="Filenames of the extra camera angles, in the same order.",
    )
    observations: list[ObservationIn] | None = Field(
        default=None,
        max_length=MAX_SUPPLIED_OBSERVATIONS,
        description="Readings from the site's own gate sensors (ANPR, radiation "
        "portal, analysers, ...). A kind sent here replaces the computed or "
        "simulated one.",
    )

    @model_validator(mode="after")
    def _normalize_moisture(self) -> "InspectRequest":
        """``moisture_pct`` arrives as percent (0..100) — normalise to a
        fraction so both shapes meet the engine's [0, 1] domain."""
        if self.moisture is not None and self.moisture > 1.0:
            object.__setattr__(self, "moisture", self.moisture / 100.0)
        return self


class AssistRequest(BaseModel):
    """One question to Pythia, optionally about a stored inspection."""

    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=500)
    record_id: str | None = None

    @model_validator(mode="after")
    def _question_not_blank(self) -> "AssistRequest":
        if not self.question.strip():
            raise ValueError("question must not be blank")
        return self


def _load_record_or_http(record_id: str) -> audit.AuditRecord:
    """Validate ``record_id`` (422) and strict-load its record (404)."""
    if not audit.RECORD_ID_RE.match(record_id):
        raise HTTPException(
            status_code=422,
            detail={
                "error": "invalid_record_id",
                "message": (
                    "record_id must match 'inspection-NNN' "
                    f"(got {record_id!r})"
                ),
            },
        )
    settings = get_settings()
    record_path = Path(settings.storage_dir) / record_id / audit.RECORD_FILENAME
    try:
        return audit.load_record(record_path)
    except audit.AuditError as exc:
        # Missing file (IO_ERROR) and strict-decode failures both mean
        # "no servable record here" — 404, not a 500 crash.
        raise HTTPException(
            status_code=404,
            detail={"error": "record_not_found", "message": str(exc)},
        ) from exc


#: Process-wide cap on concurrent LIVE inspections (non-demo ``/inspect``).
#: The AMD endpoint is a shared, rate-limited key and the public URL is open:
#: a third concurrent live request gets a fast 503 instead of queueing behind
#: 90 s model calls.  Scripted ``demo_case`` requests never take a slot.
MAX_LIVE_INSPECTIONS = 2
_LIVE_SLOTS = threading.BoundedSemaphore(MAX_LIVE_INSPECTIONS)


def _inspect_payload(request: InspectRequest) -> dict[str, Any]:
    """Request model → the single effective payload used by everything.

    When only ``demo_case`` is supplied (no manual data), research-backed
    defaults fill the gaps so the demo tells a true story (see
    docs/research/realcase-indonesia.md): an arm-roll truck carries
    ≈ 5,2 ton/trip (jurnal ITATS Surabaya §3a) and Indonesian MSW runs
    55–60 % moisture (SBI Cilacap §2c).  The InspectRequest contract
    itself is untouched — only the demo defaults are realistic.

    With ``waybill_fields`` (the operator-confirmed waybill) the waybill
    fills what the operator did not type: truck = plate, supplier =
    carrier, declared weight = net, waste stream from the load type,
    moisture from the declared moisture.  The manifest text is then the
    deterministic transcript of the fields (:func:`waybill.transcript`).
    A missing ``age_h`` defaults to :data:`DEFAULT_AGE_H` (``age_defaulted``,
    stated as an engine caveat).

    This is the canonical object: the audit record, the AI prompts, the
    engine assessment, the decision, and the impact estimate all derive
    from it, so what the verdict used is exactly what gets recorded.
    ``weight_defaulted`` / ``manifest_defaulted`` mark injected defaults so
    their audit provenance is honest rather than claimed as measured.
    """
    weight_kg = request.weight_kg
    moisture = request.moisture
    waste_stream = request.waste_stream
    age_h = request.age_h
    manifest_text = request.manifest_text
    truck_id = request.truck_id
    supplier = (request.supplier or "").strip() or None
    declared_weight_kg = request.declared_weight_kg
    weight_defaulted = False
    manifest_defaulted = False
    age_defaulted = False
    fields = (
        waybill.clean_values(request.waybill_fields)
        if request.waybill_fields is not None
        else None
    )
    if fields is not None:
        truck_id = truck_id or fields.get("plate")
        supplier = supplier or (str(fields.get("carrier") or "").strip()[:120] or None)
        if declared_weight_kg is None:
            declared_weight_kg = fields.get("net_kg")
        if waste_stream is None:
            waste_stream = waybill.waste_stream_for(fields.get("load_type"))[0]
        if moisture is None and fields.get("moisture_pct") is not None:
            moisture = float(fields["moisture_pct"]) / 100.0
        manifest_text = waybill.transcript(fields)
    if request.demo_case:
        if weight_kg is None:
            weight_kg = impact.ARM_ROLL_TRIP_KG  # ≈ 5,2 t/trip (ITATS §3a)
            weight_defaulted = True
        if moisture is None:
            moisture = 0.55  # MSW Indonesia 55–60 % (SBI Cilacap §2c)
        if waste_stream is None:
            waste_stream = "mixed-msw"
        if age_h is None:
            age_h = 48.0
        if not (manifest_text or "").strip():
            # Waybill skeleton per SOP PUPR §4a / praktik jembatan timbang
            # (docs/research/realcase-indonesia.md §4d) — a demo_case-only
            # payload still carries an honest scripted waybill.
            manifest_text = (
                "SURAT JALAN / TIKET TIMBANG (RDF-MSW)\n"
                "Jenis muatan: MSW\n"
                f"Netto (kg): {int(weight_kg)} (bruto - tarra, jembatan timbang)\n"
                "Verifikasi: non-B3, non-medis; kadar air sesuai deklarasi."
            )
            manifest_defaulted = True
    if age_h is None:
        age_h = DEFAULT_AGE_H
        age_defaulted = True
    return {
        "truck_id": truck_id or f"demo-{request.demo_case or 'truck'}",
        "demo_case": request.demo_case,
        "photo_base64": request.photo_base64,
        "photo_filename": request.photo_filename,
        "extra_photos_base64": [p for p in request.extra_photos_base64 or [] if p],
        "extra_photo_filenames": list(request.extra_photo_filenames or []),
        "waybill_image_base64": request.waybill_image_base64,
        "waybill_photo_filename": request.waybill_photo_filename,
        "manifest_text": manifest_text,
        "weight_kg": weight_kg,
        "declared_weight_kg": declared_weight_kg,
        "waste_stream": waste_stream,
        "moisture": moisture,
        "age_h": age_h,
        "supplier": supplier,
        "waybill_fields": fields,
        "waybill_read": request.waybill_read.model_dump() if request.waybill_read else None,
        "weight_source": request.weight_source,
        "weight_defaulted": weight_defaulted,
        "manifest_defaulted": manifest_defaulted,
        "age_defaulted": age_defaulted,
    }


def _manifest_input(payload: dict[str, Any], manifest_text: str) -> dict[str, Any]:
    """``inputs.manifest_text`` of the audit record: where the waybill text
    came from, its digest, the confirmed fields and the read confidence."""
    fields = payload["waybill_fields"]
    read = payload["waybill_read"]
    if fields is not None and read is not None:
        source = (
            "waybill_photo_ai_read_operator_edited"
            if read.get("edited_fields")
            else "waybill_photo_ai_read"
        )
        confidence = float(read["confidence"])
    elif fields is not None:
        source, confidence = "operator_typed_fields", _MANUAL_TEXT_CONFIDENCE
    elif payload["manifest_defaulted"]:
        source, confidence = "scripted_demo_default", _MANUAL_TEXT_CONFIDENCE
    else:
        source, confidence = "manual_text", _MANUAL_TEXT_CONFIDENCE
    return {
        "source": source,
        "raw_text_sha256": audit.sha256_field(manifest_text.encode("utf-8")),
        "extracted_fields": dict(fields or {}),
        "ocr_confidence": confidence,
    }


def _supplier_profile(
    storage_dir: Any, supplier: str | None, *, exclude_record_id: str | None = None
) -> dict[str, Any] | None:
    """The supplier's scorecard (``suppliers.profile``), when there is one."""
    suppliers = _optional_module("suppliers")
    if suppliers is None or not supplier:
        return None
    try:
        return suppliers.profile(storage_dir, supplier, exclude_record_id=exclude_record_id)
    except Exception as exc:  # noqa: BLE001 — a scorecard never fails an inspection
        _log.warning("supplier profile skipped: %s: %s", type(exc).__name__, exc)
        return None


def _sampling_for(
    storage_dir: Any,
    supplier: str | None,
    declared: dict[str, Any] | None = None,
    *,
    exclude_record_id: str | None = None,
) -> dict[str, Any] | None:
    """Risk-based lab-sampling call for this truck (``suppliers.sampling_for``);
    ``declared`` (the confirmed waybill fields) lets a declared moisture above
    the contract spec call for a sample."""
    suppliers = _optional_module("suppliers")
    if suppliers is None or not supplier:
        return None
    try:
        return suppliers.sampling_for(
            storage_dir, supplier, declared, exclude_record_id=exclude_record_id
        )
    except Exception as exc:  # noqa: BLE001 — sampling never fails an inspection
        _log.warning("sampling skipped: %s: %s", type(exc).__name__, exc)
        return None


def _checks_for(record_like: dict[str, Any], profile: dict[str, Any] | None) -> dict[str, Any]:
    """``{"checks", "why"}`` from :func:`checks.build_checks` (empty when the
    module is absent; ``None`` values when it failed on this record)."""
    checks = _optional_module("checks")
    if checks is None:
        return {}
    try:
        built = checks.build_checks(record_like, profile)
    except Exception as exc:  # noqa: BLE001 — the sealed verdict still answers
        _log.warning("operator checks skipped: %s: %s", type(exc).__name__, exc)
        return {"checks": None, "why": None}
    return {"checks": built.get("checks"), "why": built.get("why")}


def _vlm_block(vlm_result: dict[str, Any], no_model: str) -> dict[str, Any]:
    """``ai_outputs.vlm`` (or one ``vlm_frames`` entry) of the audit record."""
    return {
        "model": str(vlm_result.get("model", no_model)),
        "model_version": str(vlm_result.get("model_version", no_model)),
        "raw_output_sha256": audit.sha256_field(
            str(vlm_result.get("raw_output", "")).encode("utf-8")
        ),
        "detected": vlm_result.get("detected", {}),
        "confidence": float(vlm_result.get("confidence", 0.0)),
        # Live clients stamp provider + latency; stub results carry
        # neither, and the record then honestly says None.
        "provider": vlm_result.get("provider"),
        "latency_ms": vlm_result.get("latency_ms"),
        # Validated contaminant regions; older/stub results without
        # them stay valid as an empty list / unspecified mode.
        "boxes": vlm_result.get("boxes", []),
        "localisation": vlm_result.get("localisation"),
        # The vision models that failed before this one answered.
        "fallback_from": vlm_result.get("fallback_from"),
        # Each read's own answer (absent on results that kept none).
        **({"votes": vlm_result["votes"]} if vlm_result.get("votes") is not None else {}),
    }


def _run_inspection_with_audit(
    request: InspectRequest,
    settings: Any,
    *,
    photo_provenance: str | None = None,
    on_progress: pipeline.ProgressFn | None = None,
) -> dict[str, Any]:
    """Full inspection: audit begin → AI + engine + decision → audit finish.

    ``photo_provenance`` overrides the recorded photo provenance; only the
    seeding script uses it (``"sample"`` for the scripted sample shift).
    ``on_progress`` hears every stage (``POST /inspect/stream``).
    """
    emit = pipeline.progress_emitter(on_progress)
    # Validate the uploads first: a rejected photo must not leave an
    # ``inspection-*`` record behind (audit.begin_record is below).
    photo_bytes = decode_photo(request.photo_base64)
    waybill_bytes = decode_photo(request.waybill_image_base64)
    extra_names = list(request.extra_photo_filenames or [])
    extra_photos: list[tuple[bytes, str | None]] = []
    for index, raw in enumerate(p for p in request.extra_photos_base64 or [] if p):
        extra_photos.append(
            (decode_photo(raw), extra_names[index] if index < len(extra_names) else None)
        )
    if extra_photos and not photo_bytes:
        raise PhotoError(
            422, "invalid_photo", "Extra camera angles need the main load photo."
        )
    # One effective payload: demo defaults applied here flow identically to
    # the AI, the engine, the decision, the impact estimate, and the audit
    # record — the record reflects what the verdict actually used.
    payload = _inspect_payload(request)

    manifest_text = payload["manifest_text"] or ""
    # Demo photos arrive as site URLs ("/demo/t-metal-1.jpg"); the audit record
    # stores a portable relative filename (invariant: no absolute paths),
    # so keep only the basename. Real uploads already send bare names.
    photo_filename = audit.safe_filename(
        payload["photo_filename"] or "photo.jpg"
    )
    provenance = photo_provenance or payload["demo_case"] or "user_upload"
    now = audit.now_utc()
    gas_input: dict[str, Any] = {"readings_ppm": {}, "source": "not_measured", "measured_at_utc": now}
    inputs = {
        "truck_id": payload["truck_id"],
        "photo": {
            "filename": photo_filename,
            "sha256": audit.sha256_field(photo_bytes),
            "captured_at_utc": now,
            "provenance": provenance,
        },
        "manifest_text": _manifest_input(payload, manifest_text),
        "weight": {
            "value_kg": payload["weight_kg"] if payload["weight_kg"] is not None else 0.0,
            "source": "scripted_demo_default"
            if payload["weight_defaulted"]
            else payload["weight_source"] or "weighbridge",
            "measured_at_utc": now,
        },
        "gas": gas_input,
        "supplier": payload["supplier"],
    }
    # The waybill document photo is evidence: digest it into the audit
    # record when one was uploaded.
    if waybill_bytes:
        inputs["waybill_photo"] = {
            "filename": audit.safe_filename(
                payload["waybill_photo_filename"] or "waybill.jpg"
            ),
            "sha256": audit.sha256_field(waybill_bytes),
            "captured_at_utc": now,
            # A demo_case names the load story, not where the waybill came from.
            "provenance": photo_provenance or "user_upload",
        }
    input_digests = {
        "photo": audit.sha256_field(photo_bytes),
        "manifest_text": audit.sha256_field(manifest_text.encode("utf-8")),
    }
    if waybill_bytes:
        input_digests["waybill_photo"] = audit.sha256_field(waybill_bytes)
    frozen_inputs = {
        "photo": photo_bytes,
        "manifest_text": manifest_text.encode("utf-8"),
    }
    if extra_photos:
        # Extra angles are frozen like the main photo: digest at begin,
        # re-verified at finish (keys photo_2 / photo_3).
        inputs["extra_photos"] = []
        for number, (data, name) in enumerate(extra_photos, start=2):
            inputs["extra_photos"].append(
                {
                    "filename": audit.safe_filename(name or f"photo-{number}.jpg"),
                    "sha256": audit.sha256_field(data),
                    "captured_at_utc": now,
                    "provenance": provenance,
                }
            )
            input_digests[f"photo_{number}"] = audit.sha256_field(data)
            frozen_inputs[f"photo_{number}"] = data
    # Gate sensors: what the site sent, plus the photo quality computed here
    # and the simulated scale / plate camera.  Frozen with the inputs and
    # read by the rules (decide's inputs["observations"]).
    gate_observations = observations.collect(
        supplied=[
            observations.supplied_record(o.model_dump(), now)
            for o in request.observations or []
        ],
        frames=[photo_bytes, *(data for data, _name in extra_photos)],
        weight_kg=payload["weight_kg"],
        weight_source=None if payload["weight_defaulted"] else payload["weight_source"],
        registered_plate=request.truck_id,
        waybill_plate=(payload["waybill_fields"] or {}).get("plate"),
        measured_at_utc=now,
    )
    payload["observations"] = gate_observations
    inputs["observations"] = gate_observations
    application = {"name": "lynceus", "version": __version__}

    # Resolve the AI clients before the record is begun: an unreachable live
    # endpoint with stub fallback disabled raises LiveAIUnavailableError here
    # (HTTP 503) and leaves no ``inspection-*`` shell behind.
    detector_kwargs: dict[str, Any] = {}
    try:
        ai_clients = pipeline.resolve_clients(payload, settings)
    except pipeline.LiveAIUnavailableError as exc:
        # Degraded, not dark: when the CPU detector can read this photo the
        # truck is held for a human on its findings instead of a 503.  It
        # runs before the record is begun, so a photo it cannot read still
        # leaves no record shell behind.
        # Never a demo payload: resolve_clients gives those the stub clients.
        early = pipeline.safe_detect(photo_bytes, settings) if photo_bytes else None
        if early is None:
            raise
        ai_clients = pipeline.UnavailableAIClients(str(exc))
        detector_kwargs["precomputed_detector"] = early

    # Reserve the record identity first so the gate gas channel can run
    # BEFORE the record is begun.  The readings are then frozen into the
    # begin-time inputs, so what the verdict answers to is exactly what the
    # record froze (invariant 3).  The sensor is read exactly once here,
    # not again in run_inspection.
    reserved_id, reserved_path = audit.allocate_inspection_id(settings.storage_dir)

    # The supplier's record and this truck's lab-sampling call, from the
    # completed records before this one.
    sampling = _sampling_for(
        settings.storage_dir,
        payload["supplier"],
        payload["waybill_fields"],
        exclude_record_id=reserved_id,
    )
    supplier_profile = _supplier_profile(
        settings.storage_dir, payload["supplier"], exclude_record_id=reserved_id
    )

    # Persist the evidence bytes inside the reserved record folder so the
    # audit trail can show the photo the verdict answered to (record sha256
    # identifies it; the file makes it inspectable). A storage failure must
    # not kill the inspection: the record keeps hash-only evidence.
    def _persist(name: str, data: bytes) -> str | None:
        if not data:
            return None
        try:
            target = reserved_path / name
            target.write_bytes(data)
            return name
        except OSError:
            return None

    photo_path = _persist("photo.jpg", photo_bytes)
    if photo_path:
        inputs["photo"]["path"] = photo_path
    waybill_path = _persist("waybill.jpg", waybill_bytes)
    if waybill_path:
        inputs["waybill_photo"]["path"] = waybill_path
    for number, (data, _name) in enumerate(extra_photos, start=2):
        extra_path = _persist(f"photo-{number}.jpg", data)
        if extra_path:
            inputs["extra_photos"][number - 2]["path"] = extra_path

    # Gas comes from a live gate sensor only (no sensor: not_measured).
    gas_result = pipeline.collect_gate_gas(payload, reserved_id)
    gas_ai_output: dict[str, Any] | None = None
    if gas_result and gas_result.get("readings_ppm"):
        gas_source = gas_result.get("source") or gas_twin.GAS_SOURCE
        gas_input["readings_ppm"] = gas_result["readings_ppm"]
        gas_input["source"] = gas_source
        # A live gateway's own measurement time (already validated by
        # gas_ingest) beats the time the inspection happened to run.
        gas_input["measured_at_utc"] = gas_result.get("measured_at_utc") or now
        payload["gas"] = gas_input
        gas_ai_output = {
            "source": gas_source,
            "instrument": gas_result.get("instrument"),
            "model_basis": gas_result.get("model_basis"),
        }

    # Invariant 1: an honest in_progress record exists before AI runs.
    begin = audit.begin_record(
        settings.storage_dir,
        application,
        inputs,
        input_digests,
        reserved_record_id=reserved_id,
    )
    record_id = begin.record_id

    ai = pipeline.run_inspection(
        payload,
        ai_clients,
        record_id,
        allow_stub_fallback=settings.allow_stub_fallback,
        precomputed_gas=gas_result,
        settings=settings,
        on_progress=on_progress,
        **detector_kwargs,
    )
    vlm_result = ai.get("vlm") or {}
    llm_result = ai.get("llm") or {}
    detector_result = ai.get("detector")
    degraded = ai.get("provenance") == pipeline.DEGRADED_PROVENANCE
    # Which live call failed in a degraded run: "vlm" (vision) or "llm" (waybill).
    failed_stage = str(ai.get("failed_stage") or "vlm")
    vision_label = (
        "AMD vision model"
        if provider_for_url(settings.vllm_vlm_url) == "amd-token-factory"
        else "live vision model"
    )

    engine_result = None
    if (
        payload["waste_stream"]
        and payload["weight_kg"] is not None
        and payload["moisture"] is not None
        and payload["age_h"] is not None
    ):
        try:
            engine_result = engine_adapter.run_assessment(
                waste_stream=payload["waste_stream"],
                tonnage_t=payload["weight_kg"] / 1000.0,
                moisture=payload["moisture"],
                age_h=payload["age_h"],
            )
        except (
            engine_adapter.EngineUnavailableError,
            engine_adapter.UnknownWasteStreamError,
            engine_adapter.InvalidBatchError,
        ):
            engine_result = None

    if degraded:
        verdict, gates, reasons = decision.decide_degraded(
            detector_result,
            str(ai.get("fallback_reason") or "live AI failed"),
            detector_hard_conf=settings.detector_hard_conf,
            detector_light_conf=settings.detector_light_conf,
            vision_label=vision_label,
            inputs=payload,
            failed_stage=failed_stage,
        )
    else:
        verdict, gates, reasons = decision.decide(
            payload,
            ai.get("vlm"),
            llm_result,
            engine_result,
            detector_result,
            detector_hard_conf=settings.detector_hard_conf,
            detector_light_conf=settings.detector_light_conf,
            detector_escalate_light=settings.detector_escalate_light,
            benchmarked_vlm_models=settings.vlm_benchmarked_models,
        )

    # No engine run (missing batch inputs): the audit record states so with a
    # hold-for-review route rather than a guessed one.
    engine_recommendation = {
        "actionable": True,
        "route": audit.Route.HOLD_FOR_REVIEW,
        "headline": "Engine assessment completed.",
        "insufficient": False,
        "missing": [],
        "caveats": [],
        "alternative": "",
    }
    if engine_result and "recommendation" in engine_result:
        rec = engine_result["recommendation"]
        route_name = rec.get("route")
        # Engine routes (rdf/recycling/composting/anaerobic_digestion/landfill)
        # collapse onto the audit's closed Route enum.  No route, or a tie
        # between the top two, is held for a human rather than guessed.
        if not route_name or rec.get("tied"):
            route_name = audit.Route.HOLD_FOR_REVIEW
        elif route_name in ("rdf", "recycling"):
            route_name = audit.Route.ACCEPT_PROCESSING
        else:
            route_name = audit.Route.SEGREGATE
        engine_recommendation = {
            # Read from the engine, never assumed.
            "actionable": bool(rec.get("actionable", True)),
            "route": route_name,
            "headline": rec.get("headline", ""),
            "insufficient": bool(rec.get("insufficient", False)),
            "missing": list(rec.get("missing") or []),
            "caveats": list(rec.get("caveats") or []),
            "alternative": rec.get("alternative") or "",
        }
        if payload["age_defaulted"]:
            engine_recommendation["caveats"].append(
                f"Waste age was not entered: the engine assumed {DEFAULT_AGE_H:g} h (defaulted)."
            )
    if verdict == audit.Decision.REFUSE_INSUFFICIENT_INPUT:
        # The gate-level refusal (no photo, no weight, ...) also makes the
        # recommendation unusable; keep whatever the engine itself listed.
        engine_recommendation["actionable"] = False
        engine_recommendation["insufficient"] = True
        engine_recommendation["missing"] = list(
            gates.get("missing") or engine_recommendation["missing"]
        )

    # Deterministic next-step card; every step cites a clause of the
    # reference gate SOP (knowledge/sop-rdf-gate.md).
    missing_inputs = list(gates.get("missing") or [])
    if not missing_inputs and verdict == audit.Decision.REFUSE_INSUFFICIENT_INPUT:
        missing_inputs = list(
            ((engine_result or {}).get("recommendation") or {}).get("missing") or []
        )
    step_kwargs: dict[str, Any] = {}
    if "sampling" in pyinspect.signature(actions.next_steps).parameters:
        step_kwargs["sampling"] = sampling
    next_steps = actions.next_steps(
        verdict,
        gates,
        {
            **(vlm_result.get("detected") or {}),
            # The hard-contaminant rule decide() itself applied (one source
            # of truth): empty when the VLM was not confident enough.
            "hard_contaminants": decision.confident_hard_contaminants(
                payload, vlm_result, llm_result
            ),
        },
        missing_inputs,
        record_id,
        **step_kwargs,
    )
    engine_recommendation["actions"] = next_steps
    emit("rules", "done", {"decision": verdict})

    suitability = {
        "classification": audit.Classification.SCREENING_ESTIMATE,
        "score": float(vlm_result.get("confidence", 0.0)),
        "rule": (
            "detector-only degraded mode: "
            + (
                "the waybill analysis failed, so the vision answer was discarded"
                if failed_stage == "llm"
                else "no VLM or LLM analysis ran"
            )
            + " and nothing was fused; the CPU detector's findings only hold the"
            " truck for a human"
            if degraded
            else "fusion of VLM visual analysis, LLM cross-check and engine assessment"
        ),
    }
    engine_outputs = {"suitability": suitability, "recommendation": engine_recommendation}

    uncertainty = f"AI provenance: {ai.get('provenance', 'unknown')}."
    if degraded:
        uncertainty += (
            f" The waybill model was unavailable ({ai.get('fallback_reason')}); the"
            " vision answer was not fused and is discarded."
            if failed_stage == "llm"
            else f" The {vision_label} was unavailable ({ai.get('fallback_reason')});"
            " no vision-language or waybill analysis ran."
        )
        uncertainty += (
            " A mandatory input was missing, so the inspection was refused."
            if verdict == audit.Decision.REFUSE_INSUFFICIENT_INPUT
            else " The truck is held for a human on the CPU detector (YOLO26m,"
            " trained on RealWaste and TACO photos, not gate imagery) alone."
        )
    elif ai.get("fallback_reason"):
        uncertainty += f" Live AI failed ({ai['fallback_reason']}); stub used."
    if vlm_result.get("fallback_from"):
        uncertainty += (
            f" Vision model fallback: {'; '.join(vlm_result['fallback_from'])} failed,"
            f" {vlm_result.get('model', 'unknown')} answered."
        )
    uncertainty += " Verdict is a screening estimate, not a validated classification."

    llm_raw = str(llm_result.get("raw_output", ""))
    # Degraded runs got no model output: the record names the models
    # "unavailable" with zero confidence and the digest of an empty output,
    # never a fabricated reading.
    no_model = "unavailable" if degraded else ""
    ai_outputs = {
        "vlm": _vlm_block(vlm_result, no_model),
        "llm": {
            "model": str(llm_result.get("model", no_model)),
            "model_version": str(llm_result.get("model_version", no_model)),
            "prompt_sha256": audit.sha256_field(manifest_text.encode("utf-8")),
            "raw_output_sha256": audit.sha256_field(llm_raw.encode("utf-8")),
            "reasoning": str(llm_result.get("reasoning", "")),
            "confidence": float(llm_result.get("confidence", 0.0)),
            "provider": llm_result.get("provider"),
            "latency_ms": llm_result.get("latency_ms"),
        },
        "gas": gas_ai_output,
        # The CPU detector's second opinion (None when it did not run).
        "detector": detector_result,
    }
    if ai.get("vlm_frames"):
        # Each camera angle's own answer; ``vlm`` above is their merge.
        ai_outputs["vlm_frames"] = [_vlm_block(frame, no_model) for frame in ai["vlm_frames"]]
    audit_gates = {
        k: v
        for k, v in gates.items()
        if k in audit.GATE_NAMES or k in audit.OPTIONAL_GATE_NAMES
    }
    verdict_payload = {
        "decision": verdict,
        "decided_at_utc": audit.now_utc(),
        "classification": audit.Classification.SCREENING_ESTIMATE,
        "uncertainty": uncertainty,
    }

    record = None
    if record_id:
        record = audit.finish_record(
            settings.storage_dir,
            record_id,
            audit.ExecutionStatus.COMPLETED,
            audit.now_utc(),
            application,
            inputs,
            ai_outputs,
            engine_outputs,
            verdict_payload,
            audit_gates,
            frozen_inputs=frozen_inputs,
        )
        emit(
            "sealed",
            "done",
            {"record_id": record_id, "record_sha256": record.digest.record_sha256},
        )

    # Presentation-layer measurable impact — NOT part of the audit schema:
    # it derives from the verdict + VLM result with explicit research
    # provenance (docs/research/realcase-indonesia.md) and sits in the
    # response JSON parallel to the frozen audit_record.
    impact_estimate = impact.estimate_prevented_loss(
        verdict, vlm_result, payload["weight_kg"]
    )
    impact_estimate["provenance"] = (
        "docs/research/realcase-indonesia.md (dampak Rp, §5) — "
        "every basis row carries its source URL"
    )
    waybill_block = None
    if payload["waybill_fields"] is not None:
        derived, derived_warnings = waybill.derive(payload["waybill_fields"])
        waybill_block = {
            "fields": payload["waybill_fields"],
            "read": payload["waybill_read"],
            "derived": derived,
            "transcript": manifest_text,
            "warnings": derived_warnings,
        }
    response = {
        "record_id": record_id,
        "verdict": verdict_payload,
        "impact": impact_estimate,
        "gates": audit_gates,
        "reasons": reasons,
        "actions": next_steps,
        "provenance": ai.get("provenance"),
        # Degraded runs only: which live call failed ("vlm" or "llm").
        "failed_stage": failed_stage if degraded else None,
        "ai_outputs": ai_outputs,
        "engine_outputs": engine_outputs,
        # Declared vs observed: the confirmed waybill and what it implies.
        "waybill": waybill_block,
        "sampling": sampling,
        "supplier_profile": supplier_profile,
    }
    if record is not None:
        response["audit_record"] = record.model_dump()

    # The operator's checks read the sealed record plus what the request
    # knew that the record keeps only in digest form (per-field read
    # confidences, the scale's own provenance).
    check_inputs = dict((response.get("audit_record") or {}).get("inputs") or inputs)
    check_inputs.update(
        {
            "waybill_read": payload["waybill_read"],
            "weight_kg": payload["weight_kg"],
            "declared_weight_kg": payload["declared_weight_kg"],
            "weight_source": inputs["weight"]["source"],
        }
    )
    if payload["waybill_fields"] is not None:
        confidences = (payload["waybill_read"] or {}).get("field_confidences") or {}
        check_inputs["waybill_fields"] = {
            name: {"value": value, "confidence": confidences[name]}
            if name in confidences
            else value
            for name, value in payload["waybill_fields"].items()
        }
    response.update(_checks_for({**response, "inputs": check_inputs}, supplier_profile))
    return response


def _busy_error() -> HTTPException:
    return HTTPException(
        status_code=503,
        detail={
            "error": "busy",
            "message": (
                "The live AMD pipeline is busy — try again in a "
                "moment or use a scripted case."
            ),
        },
    )


#: Errors an inspection maps to an HTTP answer (:func:`_inspect_http_error`).
_INSPECT_ERRORS = (
    PhotoError,
    engine_adapter.UnknownWasteStreamError,
    engine_adapter.InvalidBatchError,
    audit.AuditError,
    pipeline.LiveAIUnavailableError,
)


def _inspect_http_error(exc: Exception) -> HTTPException:
    """The HTTP answer for one of :data:`_INSPECT_ERRORS` (``/inspect`` and
    the stream's error line use the same mapping)."""
    if isinstance(exc, PhotoError):
        return HTTPException(
            status_code=exc.status_code,
            detail={"error": exc.error, "message": str(exc)},
        )
    if isinstance(exc, engine_adapter.UnknownWasteStreamError):
        return HTTPException(
            status_code=422,
            detail={
                "error": "unknown_waste_stream",
                "message": str(exc),
                "waste_stream": exc.waste_stream,
                "available": list(exc.available),
            },
        )
    if isinstance(exc, engine_adapter.InvalidBatchError):
        return HTTPException(
            status_code=422,
            detail={"error": "invalid_batch", "message": str(exc)},
        )
    if isinstance(exc, audit.AuditError):
        return HTTPException(
            status_code=500,
            detail={"error": "audit_error", "message": str(exc)},
        )
    # Fail-closed (LYNCEUS_ALLOW_STUB_FALLBACK=0): never return a stub
    # verdict as if the live model answered.
    return HTTPException(
        status_code=503,
        detail={"error": "live_ai_unavailable", "message": str(exc)},
    )


def _error_event(error: HTTPException) -> dict[str, Any]:
    """An HTTP error as the stream's ``{"event": "error", ...}`` line."""
    detail = error.detail if isinstance(error.detail, dict) else {"message": str(error.detail)}
    return {"event": "error", "status": error.status_code, **detail}


NDJSON_MEDIA_TYPE = "application/x-ndjson"


def _ndjson(event: dict[str, Any]) -> bytes:
    return (json.dumps(event, default=str) + "\n").encode("utf-8")


#: ``POST /warmup`` wakes the models at most once per this many seconds.
WARMUP_INTERVAL_S = 60.0
_WARMUP_LOCK = threading.Lock()
_WARMUP_STATE: dict[str, float | None] = {"last": None}


def _warm_backends(settings: Any) -> None:
    """Load the CPU detector and send the vision model a one-token chat.

    Runs on a background thread; every failure is logged, never raised.
    """
    try:
        detector.warm(settings)
    except Exception as exc:  # noqa: BLE001 — warm-up is best-effort
        _log.warning("detector warm-up failed: %s: %s", type(exc).__name__, exc)
    try:
        pipeline.VLLMClient(settings=settings).warm()
    except Exception as exc:  # noqa: BLE001 — warm-up is best-effort
        _log.info("vision warm-up ping failed: %s", type(exc).__name__)


def create_app() -> FastAPI:
    """Build the application; kept as a factory for clean test clients."""

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        # Load the CPU detector before the first truck instead of on it
        # (logs once when it is disabled).
        detector.warm()
        yield

    app = FastAPI(
        title="Lynceus backend",
        version=__version__,
        description="Assessment service wrapping the Lynceus decision engine.",
        lifespan=lifespan,
    )

    # Dev-friendly: the demo UI may be served from any origin.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next: Any) -> Any:
        """Add :data:`SECURITY_HEADERS` to every response (route-set values win)."""
        response = await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        return response

    # Session auth (demo-open when LYNCEUS_ADMIN_* are unset; see auth.py).
    auth.register_auth_routes(app)

    def _guard_console_page(request: Request) -> RedirectResponse | None:
        """303 → /login.html when auth is on and the session is missing.

        The HTML pages are browser navigations, so a redirect beats a 401;
        the JSON API below answers 401 instead (``auth.require_auth``).
        """
        if auth.get_auth_settings().enabled and auth.current_user(request) is None:
            return RedirectResponse("/login.html", status_code=303)
        return None

    def _user_is_blocked(request: Request) -> bool:
        """True when auth is on and the request carries no valid session."""
        return auth.get_auth_settings().enabled and auth.current_user(request) is None

    @app.get("/login", include_in_schema=False)
    def redirect_login() -> RedirectResponse:
        """Canonical /login redirects to the static login page."""
        return RedirectResponse("/login.html", status_code=308)

    @app.get("/login.html", include_in_schema=False)
    def serve_login_page() -> FileResponse:
        """Public sign-in page (the one page the console guard never gates)."""
        page = _web_file("login.html")
        if not page.is_file():
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "login_page_not_found",
                    "message": "web/out/login.html is missing — build the web export.",
                },
            )
        return FileResponse(page, media_type="text/html")

    @app.get("/health")
    def health() -> dict[str, Any]:
        settings = get_settings()
        return {
            "status": "ok",
            "version": settings.version,
            "engine_available": engine_adapter.engine_available(),
            # Consumed by the status chip's one-shot VLM liveness probe:
            # the browser cannot read the backend's environment, so the
            # configured endpoint is disclosed here (finding 5).
            "vllm_vlm_url": settings.vllm_vlm_url,
        }

    @app.get("/app", include_in_schema=False, response_model=None)
    def serve_app_page(request: Request) -> FileResponse | RedirectResponse:
        """Demo-day hard-reload fix: ``/app`` must serve the workspace page.

        ``StaticFiles(html=True)`` only maps ``/app`` → ``app/index.html``,
        but the static export is a flat ``app.html`` — a refresh or a
        direct URL previously hit the API 404 instead.  This explicit
        route serves the file.  Auth on + no session → 303 to /login.html.
        """
        if (redirect := _guard_console_page(request)) is not None:
            return redirect
        page = _web_file("app.html")
        if not page.is_file():
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "app_page_not_found",
                    "message": "web/out/app.html is missing — build the web export.",
                },
            )
        return FileResponse(page, media_type="text/html")

    @app.post("/assess")
    def assess(
        request: AssessRequest, _user: str | None = Depends(auth.require_auth)
    ) -> dict[str, Any]:
        try:
            return engine_adapter.run_assessment(
                waste_stream=request.waste_stream,
                tonnage_t=request.tonnage_t,
                moisture=request.moisture,
                age_h=request.age_h,
            )
        except engine_adapter.UnknownWasteStreamError as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "unknown_waste_stream",
                    "message": str(exc),
                    "waste_stream": exc.waste_stream,
                    "available": list(exc.available),
                },
            ) from exc
        except engine_adapter.InvalidBatchError as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "invalid_batch",
                    "message": str(exc),
                },
            ) from exc
        except engine_adapter.EngineUnavailableError as exc:
            # Not the caller's fault; a 503 says "backend broken", not "you
            # sent a bad request".
            raise HTTPException(
                status_code=503,
                detail={"error": "engine_unavailable", "message": exc.detail},
            ) from exc

    @app.post("/inspect")
    def inspect(
        request: InspectRequest, _user: str | None = Depends(auth.require_auth)
    ) -> dict[str, Any]:
        settings = get_settings()
        # Ruling 40: cap concurrent live pipelines (before any record exists).
        live = not request.demo_case
        if live and not _LIVE_SLOTS.acquire(blocking=False):
            raise _busy_error()
        try:
            return _run_inspection_with_audit(request, settings)
        except _INSPECT_ERRORS as exc:
            raise _inspect_http_error(exc) from exc
        finally:
            if live:
                _LIVE_SLOTS.release()

    @app.post("/inspect/stream", response_model=None)
    def inspect_stream(
        request: InspectRequest, _user: str | None = Depends(auth.require_auth)
    ) -> StreamingResponse:
        """The ``/inspect`` inspection as NDJSON, one event per line.

        ``{"event": "stage", "stage", "status", "t", "data"?}`` lines as the
        stages happen (queued, detector, vision, vision_read, waybill_audit,
        rules, sealed), then ``{"event": "result", "data": <the /inspect
        response>}``, or ``{"event": "error", "status", "error", "message"}``
        with /inspect's own error mapping.  The inspection runs on a worker
        thread holding the same live slot as /inspect; a client that hangs
        up does not stop it, so its record is still sealed.
        """
        settings = get_settings()
        started = time.monotonic()
        events: queue.Queue = queue.Queue()

        def on_progress(stage: str, status: str, data: dict[str, Any] | None = None) -> None:
            event: dict[str, Any] = {
                "event": "stage",
                "stage": stage,
                "status": status,
                "t": round(time.monotonic() - started, 2),
            }
            if data:
                event["data"] = data
            events.put(event)

        live = not request.demo_case
        headers = {"Cache-Control": "no-store", "X-Accel-Buffering": "no"}
        if live and not _LIVE_SLOTS.acquire(blocking=False):
            return StreamingResponse(
                iter([_ndjson(_error_event(_busy_error()))]),
                media_type=NDJSON_MEDIA_TYPE,
                headers=headers,
            )

        def work() -> None:
            try:
                on_progress("queued", "done")
                result = _run_inspection_with_audit(request, settings, on_progress=on_progress)
                events.put({"event": "result", "data": result})
            except _INSPECT_ERRORS as exc:
                events.put(_error_event(_inspect_http_error(exc)))
            except Exception:  # noqa: BLE001 — reported as a line, logged in full
                _log.exception("streamed inspection failed")
                events.put(
                    {
                        "event": "error",
                        "status": 500,
                        "error": "internal_error",
                        "message": "The inspection failed unexpectedly.",
                    }
                )
            finally:
                if live:
                    _LIVE_SLOTS.release()
                events.put(None)

        threading.Thread(target=work, name="lynceus-inspect-stream", daemon=True).start()

        def lines() -> Iterator[bytes]:
            while (event := events.get()) is not None:
                yield _ndjson(event)

        return StreamingResponse(lines(), media_type=NDJSON_MEDIA_TYPE, headers=headers)

    @app.post("/warmup")
    def warmup(_user: str | None = Depends(auth.require_auth)) -> dict[str, Any]:
        """Wake the vision model (a one-token chat) and load the detector.

        At most once per :data:`WARMUP_INTERVAL_S` process-wide; returns at
        once and never fails the caller (the work runs on a thread).
        """
        now = time.monotonic()
        with _WARMUP_LOCK:
            last = _WARMUP_STATE["last"]
            if last is not None and now - last < WARMUP_INTERVAL_S:
                return {"warmed": False, "reason": "recent"}
            _WARMUP_STATE["last"] = now
        threading.Thread(
            target=_warm_backends, args=(get_settings(),), name="lynceus-warmup", daemon=True
        ).start()
        return {"warmed": True}

    @app.post("/waybill/read")
    def read_waybill(
        request: WaybillReadRequest, _user: str | None = Depends(auth.require_auth)
    ) -> dict[str, Any]:
        """Read a waybill photo into fields the operator confirms.

        503 ``waybill_reader_offline`` when no reader can answer for this
        photo (offline, only the bundled sample waybill is "read"), 503
        ``busy`` when every read slot stays taken, 429 ``rate_limited`` when
        the shared endpoint throttles every retry.
        """
        try:
            image = decode_photo(request.image_base64)
        except PhotoError as exc:
            raise _inspect_http_error(exc) from exc
        try:
            return waybill.read(image, get_settings(), demo=bool(request.demo_case))
        except waybill.WaybillRateLimited as exc:
            raise HTTPException(
                status_code=429, detail={"error": "rate_limited", "message": str(exc)}
            ) from exc
        except waybill.WaybillReaderBusy as exc:
            raise HTTPException(
                status_code=503, detail={"error": "busy", "message": str(exc)}
            ) from exc
        except waybill.WaybillReaderOffline as exc:
            raise HTTPException(
                status_code=503,
                detail={"error": "waybill_reader_offline", "message": str(exc)},
            ) from exc

    @app.get("/sensors")
    def list_sensors(_user: str | None = Depends(auth.require_auth)) -> dict[str, Any]:
        """The gate sensor plug-ins (installed / simulated / not_installed)
        and how a site connects its own (:mod:`lynceus.observations`)."""
        return observations.sensors()

    @app.get("/weighbridge/reading")
    def weighbridge_reading(
        plate: str = Query(min_length=1, max_length=20),
        declared_net_kg: float | None = Query(default=None, gt=0.0, le=200_000.0),
        _user: str | None = Depends(auth.require_auth),
    ) -> dict[str, Any]:
        """A simulated, deterministic scale ticket for ``plate`` (see
        :mod:`lynceus.weighbridge`); ``source`` is always ``"simulated"``."""
        try:
            return weighbridge.reading(plate, declared_net_kg)
        except ValueError as exc:
            raise HTTPException(
                status_code=422, detail={"error": "invalid_plate", "message": str(exc)}
            ) from exc

    @app.get("/inspections", response_model=None)
    def list_inspections(request: Request) -> dict[str, Any] | FileResponse | RedirectResponse:
        """Ledger view: one summary row per inspection, newest first.

        ``list_inspections`` (audit) scans the filesystem and skips corrupt
        records with ``ok: False`` — the listing never crashes.  For healthy
        rows the verdict fields are read from the full record so the summary
        stays consistent with what a strict decode would return.

        Direct browser navigation (``Accept: text/html`` without an explicit
        JSON preference) gets the static-export ledger page; the JSON API —
        used by the frontend ``fetch`` (explicit ``application/json`` or the
        ``*/*`` default) — is unchanged.  Auth on + no session: browsers are
        redirected to /login.html, API callers get 401 JSON.
        """
        if _wants_html(request):
            if (redirect := _guard_console_page(request)) is not None:
                return redirect
            page = _web_file("inspections.html")
            if page.is_file():
                return FileResponse(page, media_type="text/html")
            # No export to serve — fall through to the JSON API so a
            # browser never gets a 404 where the API still works.
        if _user_is_blocked(request):
            raise HTTPException(
                status_code=401,
                detail={"error": "authentication_required", "message": "Sign in first."},
            )
        settings = get_settings()
        rows: list[dict[str, Any]] = []
        for entry in audit.list_inspections(settings.storage_dir):
            if not entry.get("ok"):
                continue
            record_path = (
                Path(settings.storage_dir) / entry["record_id"] / audit.RECORD_FILENAME
            )
            try:
                record = audit.load_record(record_path)
            except audit.AuditError:
                # Listed ok but unreadable a moment later — skip, stay honest.
                continue
            states = {
                gate: getattr(record.gates, gate).state for gate in audit.GATE_NAMES
            }
            # Optional gates appear only on records that carry them.
            for gate in audit.OPTIONAL_GATE_NAMES:
                result = getattr(record.gates, gate, None)
                if result is not None:
                    states[gate] = result.state
            estimate_idr = impact.estimate_prevented_loss(
                record.verdict.decision,
                {"detected": record.ai_outputs.vlm.detected},
                record.inputs.weight.value_kg,
            )["prevented_loss_idr"]
            # An accepted load's estimate is its market value, not a loss
            # that was prevented: report it as admitted value so the
            # ledger's "prevented" total matches the shift report's.
            admitted = record.verdict.decision == audit.Decision.ACCEPT
            rows.append(
                {
                    "record_id": record.record_id,
                    "truck_id": record.inputs.truck_id,
                    "supplier": (record.inputs.supplier or "").strip() or None,
                    "decision": record.verdict.decision,
                    "decided_at_utc": record.verdict.decided_at_utc,
                    "prevented_loss_idr": 0 if admitted else estimate_idr,
                    "admitted_value_idr": estimate_idr if admitted else 0,
                    "gate_states": states,
                }
            )
        # Newest inspection first: record_id is zero-padded, so a plain
        # string sort matches numeric order.
        rows.sort(key=lambda row: row["record_id"], reverse=True)
        return {"inspections": rows}

    @app.post("/assist")
    def post_assist(
        request: AssistRequest, _user: str | None = Depends(auth.require_auth)
    ) -> dict[str, Any]:
        """Pythia: a cited answer from plant documents and, optionally, a record.

        Bad ``record_id`` is 422, an unknown one 404 (same rules as
        ``GET /inspections/{record_id}``).
        """
        record = None
        if request.record_id is not None:
            record = _load_record_or_http(request.record_id).model_dump()
        client = pipeline.resolve_assist_client(get_settings())
        return assist.answer(request.question, record, client)

    @app.get("/shift", include_in_schema=False, response_model=None)
    def serve_shift_page(request: Request) -> FileResponse | RedirectResponse:
        """The static export is a flat ``shift.html``; serve it on ``/shift``
        (same hard-reload fix as ``/app``)."""
        if (redirect := _guard_console_page(request)) is not None:
            return redirect
        page = _web_file("shift.html")
        if not page.is_file():
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "shift_page_not_found",
                    "message": "web/out/shift.html is missing — build the web export.",
                },
            )
        return FileResponse(page, media_type="text/html")

    @app.get("/validation", include_in_schema=False, response_model=None)
    def serve_validation_page(request: Request) -> FileResponse | RedirectResponse:
        """Flat ``validation.html`` on ``/validation`` (same fix as ``/shift``)."""
        if (redirect := _guard_console_page(request)) is not None:
            return redirect
        page = _web_file("validation.html")
        if not page.is_file():
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "validation_page_not_found",
                    "message": "web/out/validation.html is missing — build the web export.",
                },
            )
        return FileResponse(page, media_type="text/html")

    def _benchmark_summaries(kind: str) -> Iterator[dict[str, Any]]:
        """Readable summaries of ``kind``, newest first (allow-listed by the
        summary's own ``kind``; see :func:`impact.benchmark_summaries`), so a
        hybrid what-if is never served as a live run.  A live run that
        stopped early is still served: its summary says ``complete: false``
        and the validation page flags it as partial."""
        for summary, _name in impact.benchmark_summaries(_BENCHMARK_DIR / "results", kind):
            yield summary

    @app.get("/benchmark/latest")
    def benchmark_latest(
        _user: str | None = Depends(auth.require_auth),
    ) -> dict[str, Any]:
        """Newest live ``*.summary.json``, plus framing, its replay and its hybrid.

        ``replay`` is the newest re-score of *this* run (its ``source_run``
        equals the run's ``date``) through the current rules, else ``None``.
        ``hybrid`` is the newest ``hybrid_replay`` of this run, else ``None``:
        its recorded VLM outputs fused with the CPU detector, whose
        ``hybrid_light_escalation_on`` variant is the gate that ships
        (``DETECTOR_ESCALATE_LIGHT=1``).
        """
        results = _BENCHMARK_DIR / "results"
        for summary in _benchmark_summaries("live"):
            replay = impact.matching_summary(results, "replay", summary)
            hybrid = impact.matching_summary(results, "hybrid_replay", summary)
            return {
                **summary,
                "framing": BENCHMARK_FRAMING,
                "replay": replay[0] if replay else None,
                "hybrid": hybrid[0] if hybrid else None,
            }
        raise HTTPException(
            status_code=404,
            detail={
                "error": "no_benchmark",
                "message": "No benchmark summary has been committed yet.",
            },
        )

    @app.get("/benchmark/replay")
    def benchmark_replay(
        _user: str | None = Depends(auth.require_auth),
    ) -> dict[str, Any]:
        """Newest offline replay re-score (recorded model outputs, current rules)."""
        for summary in _benchmark_summaries("replay"):
            return summary
        raise HTTPException(
            status_code=404,
            detail={
                "error": "no_replay",
                "message": "No replay re-score has been committed yet.",
            },
        )

    @app.get("/benchmark/manifest.csv", include_in_schema=False)
    def benchmark_manifest(
        _user: str | None = Depends(auth.require_auth),
    ) -> FileResponse:
        """The benchmark's image list with expected verdicts."""
        path = _BENCHMARK_DIR / "manifest.csv"
        if not path.is_file():
            raise HTTPException(
                status_code=404,
                detail={"error": "no_manifest", "message": "manifest.csv is missing."},
            )
        return FileResponse(path, media_type="text/csv")

    @app.get("/shift-report")
    def shift_report(
        since: str | None = None,
        until: str | None = None,
        _user: str | None = Depends(auth.require_auth),
    ) -> dict[str, Any]:
        """Shift aggregation over completed records started in ``[since, until)``.

        Both bounds are optional ISO 8601 UTC ``Z`` timestamps (422 otherwise).
        Flagged supplier rows carry ``explanation`` plus ``explanation_source``:
        ``"model"`` when the assist model's text passed the number check,
        ``"rule"`` for the deterministic sentence.
        """
        settings = get_settings()
        records: list[audit.AuditRecord] = []
        for entry in audit.list_inspections(settings.storage_dir):
            if not entry.get("ok"):
                continue
            try:
                records.append(
                    audit.load_record(
                        Path(settings.storage_dir) / entry["record_id"] / audit.RECORD_FILENAME
                    )
                )
            except audit.AuditError:
                continue
        from lynceus import followups  # BE-OPS: follow-ups feed report["improvement"]

        chains = followups.load_many(settings.storage_dir, [r.record_id for r in records])
        try:
            report = shift.build_report(records, since, until, chains)
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail={"error": "invalid_window", "message": str(exc)},
            ) from exc

        flagged = [row for row in report["suppliers"] if row["flagged"]]
        # Probe the explain endpoint only when some row still needs the model:
        # cached explanations must not cost a request per page load.
        client = (
            pipeline.resolve_explain_client(settings)
            if any(shift.needs_model(row) for row in flagged)
            else None
        )
        model_used = False
        for row in flagged:
            text = shift.explain_supplier(row, client)
            row["explanation"] = text
            row["explanation_source"] = (
                "rule" if text == shift.fallback_explanation(row) else "model"
            )
            model_used = model_used or row["explanation_source"] == "model"
        report["explanation_model"] = settings.explain_model if model_used else None
        report["explanation_provider"] = (
            provider_for_url(settings.explain_url) if model_used else None
        )
        return report

    @app.get("/inspections/{record_id}")
    def get_inspection(
        record_id: str, _user: str | None = Depends(auth.require_auth)
    ) -> dict[str, Any]:
        """Full audit record for one inspection (strict decode).

        The record_id is validated against the audit's own closed pattern
        before it ever reaches the filesystem — ``../etc/passwd`` and
        friends are rejected with 422, not probed on disk.

        The record's fields stay at the top level; ``checks``, ``why`` and
        ``supplier_profile`` (the supplier's current scorecard) are added
        beside them.
        """
        record = _load_record_or_http(record_id)
        body = record.model_dump()
        profile = _supplier_profile(get_settings().storage_dir, record.inputs.supplier)
        body.update(_checks_for(body, profile))
        body["supplier_profile"] = profile
        return body

    @app.get("/inspections/{record_id}/evidence/{slot}")
    def get_evidence_photo(
        record_id: str,
        slot: str,
        _user: str | None = Depends(auth.require_auth),
    ) -> FileResponse:
        """Serve one stored evidence photo for an inspection.

        ``slot`` is "photo" for the load, "waybill_photo" for the waybill, and
        "photo-2" / "photo-3" for the extra camera angles
        (``inputs.extra_photos``). Only files the record itself names in the
        slot's ``path`` are served — the record is the allow-list, so nothing
        else inside the inspection folder is reachable. The stored bytes'
        sha256 is checked against the recorded digest: a tampered or missing
        file is a 410, never a quiet substitution.
        """
        extra_slots = {f"photo-{n}": n - 2 for n in range(2, audit.MAX_FRAMES + 1)}
        if slot not in ("photo", "waybill_photo") and slot not in extra_slots:
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "invalid_slot",
                    "message": "slot must be 'photo', 'waybill_photo', 'photo-2' or 'photo-3'.",
                },
            )
        record = _load_record_or_http(record_id)
        if slot in extra_slots:
            extras = record.inputs.extra_photos or []
            index = extra_slots[slot]
            photo_input = extras[index] if index < len(extras) else None
        else:
            photo_input = getattr(record.inputs, slot, None) if record.inputs else None
        rel_path = getattr(photo_input, "path", None) if photo_input else None
        if not rel_path:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "no_stored_photo",
                    "message": f"This record stored no {slot} file (hash-only evidence).",
                },
            )
        # _validate_relative_filename ran at strict-decode time; resolve and
        # confine to the inspection folder anyway (defence in depth).
        record_dir = (Path(get_settings().storage_dir) / record_id).resolve()
        file_path = (record_dir / rel_path).resolve()
        if file_path.parent != record_dir:
            raise HTTPException(
                status_code=422,
                detail={"error": "invalid_path", "message": "evidence path escapes the inspection folder."},
            )
        if not file_path.is_file():
            raise HTTPException(
                status_code=410,
                detail={"error": "evidence_missing", "message": "The stored evidence file is gone."},
            )
        if audit.sha256_field(file_path.read_bytes()) != getattr(
            photo_input, "sha256", ""
        ):
            raise HTTPException(
                status_code=410,
                detail={
                    "error": "evidence_tampered",
                    "message": "Stored file hash does not match the audit record.",
                },
            )
        return FileResponse(
            file_path,
            media_type="image/jpeg",
            headers={"Cache-Control": "private, max-age=3600"},
        )

    # BE-OPS: ops-loop routes (follow-ups, suppliers, contract), before the static mount.
    from lynceus import api_ops
    app.include_router(api_ops.router)
    if (api_amd := _optional_module("api_amd")) is not None: app.include_router(api_amd.router)  # AMD-BENCH: GET /benchmark/amd
    if (api_assist := _optional_module("api_assist")) is not None: app.include_router(api_assist.router)  # AI-AGENT: POST /assist/stream

    if _WEB_DIR.is_dir():
        app.mount("/", StaticFiles(directory=str(_WEB_DIR), html=True), name="web")

    return app


app = create_app()
