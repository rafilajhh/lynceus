"""Pythia API: the streamed ``/assist`` answer and the shift handover briefing.

Routes (behind ``auth.require_auth``)::

    POST /assist/stream         — same body as POST /assist; NDJSON, one event per line
    POST /shift/briefing        — {window?: shift|day|all} → the handover briefing
    POST /shift/briefing/seal   — {briefing} → stored under briefings/ with a digest

Events, in order:

* ``{"event": "thinking", "turn": n}`` before each model turn (live only);
* ``{"event": "step", "tool", "args", "summary", "ms"}`` as each lookup ends;
* ``{"event": "result", "data": <the exact POST /assist response>}``, or
  ``{"event": "error", "status", "error", "message"}`` when the answer failed.

A malformed body or ``record_id`` is a plain 422 and an unknown record a
404, before any line is streamed (same rules as ``POST /assist``).
"""

from __future__ import annotations

import logging
import queue
import threading
from typing import Any, Dict, Iterator, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict

from lynceus import assist, auth, briefing, pipeline
from lynceus.api import NDJSON_MEDIA_TYPE, AssistRequest, _load_record_or_http, _ndjson
from lynceus.config import get_settings

router = APIRouter()
_log = logging.getLogger(__name__)


@router.post("/assist/stream", response_model=None)
def assist_stream(
    request: AssistRequest, _user: str | None = Depends(auth.require_auth)
) -> StreamingResponse:
    """Pythia's answer as NDJSON: lookups and model turns live, then the result."""
    record = None
    if request.record_id is not None:
        record = _load_record_or_http(request.record_id).model_dump()
    events: queue.Queue = queue.Queue()

    def work() -> None:
        try:
            client = pipeline.resolve_assist_client(get_settings())
            result = assist.answer(request.question, record, client, progress=events.put)
            events.put({"event": "result", "data": result})
        except Exception:  # noqa: BLE001 — reported as a line, logged in full
            _log.exception("streamed assist failed")
            events.put({"event": "error", "status": 500, "error": "internal_error",
                        "message": "Pythia failed unexpectedly."})
        finally:
            events.put(None)

    threading.Thread(target=work, name="lynceus-assist-stream", daemon=True).start()

    def lines() -> Iterator[bytes]:
        while (event := events.get()) is not None:
            yield _ndjson(event)

    headers: dict[str, Any] = {"Cache-Control": "no-store", "X-Accel-Buffering": "no"}
    return StreamingResponse(lines(), media_type=NDJSON_MEDIA_TYPE, headers=headers)


class BriefingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    window: Literal["shift", "day", "all"] = "shift"


class SealRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    briefing: Dict[str, Any]


@router.post("/shift/briefing")
def shift_briefing(
    request: BriefingRequest = BriefingRequest(),
    _user: str | None = Depends(auth.require_auth),
) -> Dict[str, Any]:
    """The shift handover briefing: a grounded Pythia draft, else the template."""
    settings = get_settings()
    client = pipeline.resolve_assist_client(settings)
    return briefing.draft_briefing(settings.storage_dir, request.window, client)


@router.post("/shift/briefing/seal")
def seal_briefing(
    request: SealRequest, http: Request, _user: str | None = Depends(auth.require_auth)
) -> Dict[str, Any]:
    """Store the supervisor's handover under ``briefings/`` with a digest (422 if
    its ``facts_digest`` does not match its facts)."""
    actor = (auth.current_user(http) or "").strip() or "demo"
    try:
        return briefing.seal(get_settings().storage_dir, request.briefing, actor)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"error": "invalid_briefing",
                                                     "message": str(exc)}) from exc
