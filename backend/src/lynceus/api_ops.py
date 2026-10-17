"""Ops-loop API: sealed follow-ups, the supplier scorecard, the example contract.

Routes (all behind ``auth.require_auth``):

    GET  /inspections/{record_id}/followups  — the chain and its verification
    POST /inspections/{record_id}/resolution — supervisor decision
    POST /inspections/{record_id}/lab        — lab result + contract effect
    POST /inspections/{record_id}/notice     — supplier notice (LLM or template)
    GET  /inspections/{record_id}/evidence-pack — dispute evidence (JSON, ?format=zip)
    GET  /followups/summary                  — follow-up kinds per record (ledger badges)
    GET  /suppliers                          — supplier profiles + contract
    GET  /contract                           — example contract + tier rules
    GET  /kiln/intake?window=shift           — accepted fuel energy and chlorine input
    GET  /carbon?window=shift                — CO2 view of the accepted fuel
    GET  /alerts                             — deterministic alarm feed
    GET  /control/summary                    — the control room in one call

Errors: 422 for a malformed record id or body, 404 for an unknown record,
409 for a record that is not completed or a chain that fails verification.
The actor is the session's username, or ``"demo"`` when auth is off.
"""

from __future__ import annotations

import io
import json
import zipfile
from typing import Any, Dict, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from lynceus import audit, auth, contracts, control, followups, fuel, pipeline, suppliers
from lynceus.config import get_settings

router = APIRouter()

DEMO_ACTOR = "demo"


class ResolutionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["accept", "sort_then_accept", "reject", "retake"]
    note: str = Field(default="", max_length=500)
    hand_check_minutes: Optional[float] = Field(default=None, ge=0.0, le=600.0)


class LabRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    moisture_pct: float = Field(ge=0.0, le=100.0)
    ncv_mj_kg: float = Field(ge=0.0, le=40.0)
    chlorine_pct: float = Field(ge=0.0, le=10.0)
    ash_pct: Optional[float] = Field(default=None, ge=0.0, le=100.0)
    hg_mg_mj: Optional[float] = Field(default=None, ge=0.0, le=10.0)
    sample_id: Optional[str] = Field(default=None, max_length=64)
    lab: Optional[str] = Field(default=None, max_length=120)


class NoticeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _actor(request: Request) -> str:
    return (auth.current_user(request) or "").strip() or DEMO_ACTOR


def _storage() -> str:
    return str(get_settings().storage_dir)


def _http(exc: Exception) -> HTTPException:
    if isinstance(exc, followups.InvalidRecordId):
        return HTTPException(422, detail={"error": "invalid_record_id", "message": str(exc)})
    if isinstance(exc, followups.RecordNotFound):
        return HTTPException(404, detail={"error": "record_not_found", "message": str(exc)})
    if isinstance(exc, followups.RecordNotCompleted):
        return HTTPException(409, detail={"error": "record_not_completed", "message": str(exc)})
    if isinstance(exc, ValueError):
        return HTTPException(422, detail={"error": "invalid_body", "message": str(exc)})
    return HTTPException(409, detail={"error": "chain_broken", "message": str(exc)})


def _contract() -> Dict[str, Any]:
    return {
        **contracts.DEFAULT_CONTRACT,
        "tier_rules": suppliers.TIER_RULES,
        "risk_formula": suppliers.RISK_FORMULA,
    }


@router.get("/inspections/{record_id}/followups")
def get_followups(
    record_id: str, _user: str | None = Depends(auth.require_auth)
) -> Dict[str, Any]:
    try:
        followups.load_completed(_storage(), record_id)
    except followups.RecordNotCompleted:
        pass  # an in-progress record simply has no follow-ups yet
    except (followups.InvalidRecordId, followups.RecordNotFound) as exc:
        raise _http(exc) from exc
    chain, _problems = followups.read_chain(_storage(), record_id)
    return {
        "record_id": record_id,
        "followups": chain,
        "chain": followups.verify_chain(_storage(), record_id),
    }


@router.post("/inspections/{record_id}/resolution")
def post_resolution(
    record_id: str,
    body: ResolutionRequest,
    request: Request,
    _user: str | None = Depends(auth.require_auth),
) -> Dict[str, Any]:
    try:
        return followups.append_resolution(
            _storage(),
            record_id,
            body.decision,
            actor=_actor(request),
            note=body.note,
            hand_check_minutes=body.hand_check_minutes,
        )
    except (followups.FollowupError, ValueError) as exc:
        raise _http(exc) from exc


@router.post("/inspections/{record_id}/lab")
def post_lab(
    record_id: str,
    body: LabRequest,
    request: Request,
    _user: str | None = Depends(auth.require_auth),
) -> Dict[str, Any]:
    try:
        return followups.append_lab(
            _storage(),
            record_id,
            moisture_pct=body.moisture_pct,
            ncv_mj_kg=body.ncv_mj_kg,
            chlorine_pct=body.chlorine_pct,
            ash_pct=body.ash_pct,
            hg_mg_mj=body.hg_mg_mj,
            sample_id=body.sample_id,
            lab=body.lab,
            actor=_actor(request),
        )
    except (followups.FollowupError, ValueError) as exc:
        raise _http(exc) from exc


@router.post("/inspections/{record_id}/notice")
def post_notice(
    record_id: str,
    request: Request,
    body: Optional[NoticeRequest] = None,
    _user: str | None = Depends(auth.require_auth),
) -> Dict[str, Any]:
    storage = _storage()
    try:
        # Validate before probing the model: a bad id never costs a request.
        followups.load_completed(storage, record_id)
        client = pipeline.resolve_assist_client(get_settings())
        return followups.append_notice(storage, record_id, actor=_actor(request), client=client)
    except (followups.FollowupError, ValueError) as exc:
        raise _http(exc) from exc


@router.get("/suppliers")
def get_suppliers(_user: str | None = Depends(auth.require_auth)) -> Dict[str, Any]:
    return {
        "generated_at_utc": audit.now_utc(),
        "contract": _contract(),
        "suppliers": suppliers.profiles(_storage()),
    }


@router.get("/contract")
def get_contract(_user: str | None = Depends(auth.require_auth)) -> Dict[str, Any]:
    return _contract()


@router.get("/inspections/{record_id}/evidence-pack", response_model=None)
def get_evidence_pack(
    record_id: str,
    format: Literal["json", "zip"] = "json",
    _user: str | None = Depends(auth.require_auth),
) -> Dict[str, Any] | Response:
    """One record's dispute evidence: JSON, or a zip with the files themselves."""
    try:
        pack, files = followups.evidence_pack(_storage(), record_id)
    except followups.FollowupError as exc:
        raise _http(exc) from exc
    if format == "json":
        return pack
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("evidence-pack.json", json.dumps(pack, indent=2, ensure_ascii=False))
        for arcname, path in files:
            archive.write(path, arcname)
    return Response(
        content=buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{record_id}-evidence.zip"'},
    )


@router.get("/followups/summary")
def get_followups_summary(_user: str | None = Depends(auth.require_auth)) -> Dict[str, Any]:
    return {"records": followups.summary(_storage())}


def _window(call: Any, window: str) -> Dict[str, Any]:
    try:
        return call(_storage(), window)
    except ValueError as exc:
        raise HTTPException(422, detail={"error": "invalid_window", "message": str(exc)}) from exc


@router.get("/kiln/intake")
def get_kiln_intake(
    window: str = "shift", _user: str | None = Depends(auth.require_auth)
) -> Dict[str, Any]:
    return _window(fuel.kiln_intake, window)


@router.get("/carbon")
def get_carbon(
    window: str = "shift", _user: str | None = Depends(auth.require_auth)
) -> Dict[str, Any]:
    return _window(fuel.carbon, window)


@router.get("/alerts")
def get_alerts(_user: str | None = Depends(auth.require_auth)) -> Dict[str, Any]:
    now = audit.now_utc()
    return {"generated_at_utc": now, "rules": control.ALERT_RULES,
            "alerts": control.alerts(_storage(), now=now)}


@router.get("/control/summary")
def get_control_summary(_user: str | None = Depends(auth.require_auth)) -> Dict[str, Any]:
    return control.control_summary(_storage())
