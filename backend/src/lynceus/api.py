"""FastAPI application for the Lynceus backend.

Routes:
    GET  /health   — liveness plus engine availability.
    POST /assess   — one batch assessment through the Lynceus decision engine.
    POST /inspect  — full AI gate inspection (VLM + LLM + engine + fusion verdict).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator
from lynceus import __version__
from lynceus import audit
from lynceus import decision
from lynceus import engine_adapter
from lynceus import gas_twin
from lynceus import impact
from lynceus import pipeline
from lynceus.config import get_settings

_WEB_DIR = Path(__file__).resolve().parents[3] / "web" / "out"

# No OCR is performed on the waybill; this is the fixed confidence attached
# to operator-typed manifest text, not an OCR score.
_MANUAL_TEXT_CONFIDENCE = 0.95

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
        default=None, ge=0.0, description="Elapsed time since disposal, in hours."
    )

    @model_validator(mode="after")
    def _normalize_moisture(self) -> "InspectRequest":
        """``moisture_pct`` arrives as percent (0..100) — normalise to a
        fraction so both shapes meet the engine's [0, 1] domain."""
        if self.moisture is not None and self.moisture > 1.0:
            object.__setattr__(self, "moisture", self.moisture / 100.0)
        return self


def _inspect_payload(request: InspectRequest) -> dict[str, Any]:
    """Request model → plain pipeline/decision payload dict.

    When only ``demo_case`` is supplied (no manual data), research-backed
    defaults fill the gaps so the demo tells a true story (see
    docs/research/realcase-indonesia.md): an arm-roll truck carries
    ≈ 5,2 ton/trip (jurnal ITATS Surabaya §3a) and Indonesian MSW runs
    55–60 % moisture (SBI Cilacap §2c).  The InspectRequest contract
    itself is untouched — only the demo defaults are realistic.
    """
    weight_kg = request.weight_kg
    moisture = request.moisture
    waste_stream = request.waste_stream
    age_h = request.age_h
    manifest_text = request.manifest_text
    if request.demo_case:
        if weight_kg is None:
            weight_kg = impact.ARM_ROLL_TRIP_KG  # ≈ 5,2 t/trip (ITATS §3a)
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
    return {
        "truck_id": request.truck_id or "",
        "demo_case": request.demo_case,
        "photo_base64": request.photo_base64,
        "photo_filename": request.photo_filename,
        "manifest_text": manifest_text,
        "weight_kg": weight_kg,
        "declared_weight_kg": request.declared_weight_kg,
        "waste_stream": waste_stream,
        "moisture": moisture,
        "age_h": age_h,
    }


def _run_inspection_with_audit(
    request: InspectRequest, settings: Any
) -> dict[str, Any]:
    """Full inspection: audit begin → AI + engine + decision → audit finish."""
    payload = _inspect_payload(request)

    manifest_text = request.manifest_text or ""
    photo_bytes = (
        request.photo_base64.encode("ascii") if request.photo_base64 else b""
    )
    # Demo photos arrive as site URLs ("/demo/red-1.jpg"); the audit record
    # stores a portable relative filename (invariant: no absolute paths),
    # so keep only the basename. Real uploads already send bare names.
    photo_filename = audit.safe_filename(
        request.photo_filename or "photo.jpg"
    )
    now = audit.now_utc()
    gas_input: dict[str, Any] = {"readings_ppm": {}, "source": "not_measured", "measured_at_utc": now}
    inputs = {
        "truck_id": request.truck_id or f"demo-{request.demo_case or 'truck'}",
        "photo": {
            "filename": photo_filename,
            "sha256": audit.sha256_field(photo_bytes),
            "captured_at_utc": now,
            "provenance": request.demo_case or "user_upload",
        },
        "manifest_text": {
            "source": "manual_text",
            "raw_text_sha256": audit.sha256_field(manifest_text.encode("utf-8")),
            "extracted_fields": {},
            "ocr_confidence": _MANUAL_TEXT_CONFIDENCE,
        },
        "weight": {
            "value_kg": request.weight_kg if request.weight_kg is not None else 0.0,
            "source": "weighbridge",
            "measured_at_utc": now,
        },
        "gas": gas_input,
    }
    input_digests = {
        "photo": audit.sha256_field(photo_bytes),
        "manifest_text": audit.sha256_field(manifest_text.encode("utf-8")),
    }
    application = {"name": "lynceus", "version": __version__}

    # Invariant 1: an honest in_progress record exists before AI runs.
    begin = audit.begin_record(
        settings.storage_dir, application, inputs, input_digests
    )
    record_id = begin.record_id

    ai = pipeline.run_inspection(
        payload,
        pipeline.resolve_clients(payload, settings),
        record_id,
        allow_stub_fallback=settings.allow_stub_fallback,
    )
    vlm_result = ai.get("vlm") or {}
    llm_result = ai.get("llm") or {}

    # The gate gas channel (when it ran) feeds both the decision layer
    # and the audit record's frozen inputs — the readings above the bin
    # are part of what the verdict answers to.  The source is whatever
    # the pipeline reported: a live gate sensor (``sentinel_gate_sensor``)
    # or the physics twin (``digital_twin``).
    gas_result = ai.get("gas")
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

    engine_result = None
    if (
        request.waste_stream
        and request.weight_kg is not None
        and request.moisture is not None
        and request.age_h is not None
    ):
        try:
            engine_result = engine_adapter.run_assessment(
                waste_stream=request.waste_stream,
                tonnage_t=request.weight_kg / 1000.0,
                moisture=request.moisture,
                age_h=request.age_h,
            )
        except (
            engine_adapter.EngineUnavailableError,
            engine_adapter.UnknownWasteStreamError,
            engine_adapter.InvalidBatchError,
        ):
            engine_result = None

    verdict, gates, reasons = decision.decide(payload, vlm_result, llm_result, engine_result)

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
        route_name = rec.get("route") or audit.Route.HOLD_FOR_REVIEW
        # Engine routes (rdf/recycling/composting/anaerobic_digestion/landfill)
        # collapse onto the audit's closed Route enum.
        if route_name in ("rdf", "recycling"):
            route_name = audit.Route.ACCEPT_PROCESSING
        else:
            route_name = audit.Route.SEGREGATE
        engine_recommendation = {
            "actionable": True,
            "route": route_name,
            "headline": rec.get("headline", ""),
            "insufficient": False,
            "missing": [],
            "caveats": rec.get("caveats", []),
            "alternative": rec.get("alternative", ""),
        }
    if verdict == audit.Decision.REFUSE_INSUFFICIENT_INPUT:
        engine_recommendation["actionable"] = False
        engine_recommendation["insufficient"] = True
        engine_recommendation["missing"] = gates.get("missing", [])

    suitability = {
        "classification": audit.Classification.SCREENING_ESTIMATE,
        "score": float(vlm_result.get("confidence", 0.0)),
        "rule": "fusion of VLM visual analysis, LLM cross-check and engine assessment",
    }
    engine_outputs = {"suitability": suitability, "recommendation": engine_recommendation}

    uncertainty = f"AI provenance: {ai.get('provenance', 'unknown')}."
    if ai.get("fallback_reason"):
        uncertainty += f" Live AI failed ({ai['fallback_reason']}); stub used."
    uncertainty += " Verdict is a screening estimate, not a validated classification."

    vlm_sha = audit.sha256_field(str(vlm_result.get("raw_output", "")).encode("utf-8"))
    llm_raw = str(llm_result.get("raw_output", ""))
    ai_outputs = {
        "vlm": {
            "model": str(vlm_result.get("model", "")),
            "model_version": str(vlm_result.get("model_version", "")),
            "raw_output_sha256": vlm_sha,
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
        },
        "llm": {
            "model": str(llm_result.get("model", "")),
            "model_version": str(llm_result.get("model_version", "")),
            "prompt_sha256": audit.sha256_field(manifest_text.encode("utf-8")),
            "raw_output_sha256": audit.sha256_field(llm_raw.encode("utf-8")),
            "reasoning": str(llm_result.get("reasoning", "")),
            "confidence": float(llm_result.get("confidence", 0.0)),
            "provider": llm_result.get("provider"),
            "latency_ms": llm_result.get("latency_ms"),
        },
        "gas": gas_ai_output,
    }
    audit_gates = {k: v for k, v in gates.items() if k in audit.GATE_NAMES}
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
        )

    # Presentation-layer measurable impact — NOT part of the audit schema:
    # it derives from the verdict + VLM result with explicit research
    # provenance (docs/research/realcase-indonesia.md) and sits in the
    # response JSON parallel to the frozen audit_record.
    impact_estimate = impact.estimate_prevented_loss(
        verdict, vlm_result, request.weight_kg
    )
    impact_estimate["provenance"] = (
        "docs/research/realcase-indonesia.md (dampak Rp, §5) — "
        "every basis row carries its source URL"
    )
    response = {
        "record_id": record_id,
        "verdict": verdict_payload,
        "impact": impact_estimate,
        "gates": audit_gates,
        "reasons": reasons,
        "provenance": ai.get("provenance"),
        "ai_outputs": ai_outputs,
        "engine_outputs": engine_outputs,
    }
    if record is not None:
        response["audit_record"] = record.model_dump()
    return response


def create_app() -> FastAPI:
    """Build the application; kept as a factory for clean test clients."""
    app = FastAPI(
        title="Lynceus backend",
        version=__version__,
        description="Assessment service wrapping the Lynceus decision engine.",
    )

    # Dev-friendly: the demo UI may be served from any origin.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

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

    @app.get("/app", include_in_schema=False)
    def serve_app_page() -> FileResponse:
        """Demo-day hard-reload fix: ``/app`` must serve the workspace page.

        ``StaticFiles(html=True)`` only maps ``/app`` → ``app/index.html``,
        but the static export is a flat ``app.html`` — a refresh or a
        direct URL previously hit the API 404 instead.  This explicit
        route serves the file.
        """
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
    def assess(request: AssessRequest) -> dict[str, Any]:
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
    def inspect(request: InspectRequest) -> dict[str, Any]:
        settings = get_settings()
        try:
            return _run_inspection_with_audit(request, settings)
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
                detail={"error": "invalid_batch", "message": str(exc)},
            ) from exc
        except audit.AuditError as exc:
            raise HTTPException(
                status_code=500,
                detail={"error": "audit_error", "message": str(exc)},
            ) from exc
        except pipeline.LiveAIUnavailableError as exc:
            # Fail-closed (LYNCEUS_ALLOW_STUB_FALLBACK=0): never return a
            # stub verdict as if the live model answered.
            raise HTTPException(
                status_code=503,
                detail={"error": "live_ai_unavailable", "message": str(exc)},
            ) from exc

    @app.get("/inspections", response_model=None)
    def list_inspections(request: Request) -> dict[str, Any] | FileResponse:
        """Ledger view: one summary row per inspection, newest first.

        ``list_inspections`` (audit) scans the filesystem and skips corrupt
        records with ``ok: False`` — the listing never crashes.  For healthy
        rows the verdict fields are read from the full record so the summary
        stays consistent with what a strict decode would return.

        Direct browser navigation (``Accept: text/html`` without an explicit
        JSON preference) gets the static-export ledger page; the JSON API —
        used by the frontend ``fetch`` (explicit ``application/json`` or the
        ``*/*`` default) — is unchanged.
        """
        if _wants_html(request):
            page = _web_file("inspections.html")
            if page.is_file():
                return FileResponse(page, media_type="text/html")
            # No export to serve — fall through to the JSON API so a
            # browser never gets a 404 where the API still works.
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
            rows.append(
                {
                    "record_id": record.record_id,
                    "truck_id": record.inputs.truck_id,
                    "decision": record.verdict.decision,
                    "decided_at_utc": record.verdict.decided_at_utc,
                    "prevented_loss_idr": impact.estimate_prevented_loss(
                        record.verdict.decision,
                        {"detected": record.ai_outputs.vlm.detected},
                        record.inputs.weight.value_kg,
                    )["prevented_loss_idr"],
                    "gate_states": states,
                }
            )
        # Newest inspection first: record_id is zero-padded, so a plain
        # string sort matches numeric order.
        rows.sort(key=lambda row: row["record_id"], reverse=True)
        return {"inspections": rows}

    @app.get("/inspections/{record_id}")
    def get_inspection(record_id: str) -> dict[str, Any]:
        """Full audit record for one inspection (strict decode).

        The record_id is validated against the audit's own closed pattern
        before it ever reaches the filesystem — ``../etc/passwd`` and
        friends are rejected with 422, not probed on disk.
        """
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
        record_path = (
            Path(settings.storage_dir) / record_id / audit.RECORD_FILENAME
        )
        try:
            record = audit.load_record(record_path)
        except audit.AuditError as exc:
            # Missing file (IO_ERROR) and strict-decode failures both mean
            # "no servable record here" — 404, not a 500 crash.
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "record_not_found",
                    "message": str(exc),
                },
            ) from exc
        return record.model_dump()


    if _WEB_DIR.is_dir():
        app.mount("/", StaticFiles(directory=str(_WEB_DIR), html=True), name="web")

    return app


app = create_app()
