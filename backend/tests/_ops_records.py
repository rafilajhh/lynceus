"""Write strictly valid, digest-stamped audit records for the ops-loop tests.

Records are built from a fixed template and stamped with the writer's own
digest (``audit._stamp_record_digest``), so ``audit.load_record`` accepts
them exactly as it accepts records written by ``/inspect``.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

from lynceus import audit

_SHA = "sha256:" + "0" * 64

_TEMPLATE = {
    "format_version": 2,
    "record_id": "inspection-000001",
    "execution_status": "completed",
    "started_at_utc": "2026-10-14T01:00:00Z",
    "finished_at_utc": "2026-10-14T01:00:14Z",
    "application": {"name": "lynceus", "version": "test"},
    "inputs": {
        "truck_id": "B 9723 KXW",
        "photo": {"filename": "photo.jpg", "sha256": _SHA,
                  "captured_at_utc": "2026-10-14T01:00:00Z", "provenance": "user_upload"},
        "manifest_text": {"source": "manual_text", "raw_text_sha256": _SHA,
                          "extracted_fields": {}, "ocr_confidence": 0.95},
        "weight": {"value_kg": 10000.0, "source": "weighbridge",
                   "measured_at_utc": "2026-10-14T01:00:00Z"},
        "gas": {"readings_ppm": {}, "source": "not_measured",
                "measured_at_utc": "2026-10-14T01:00:00Z"},
        "supplier": "CV Uji",
    },
    "ai_outputs": {
        "vlm": {"model": "m", "model_version": "1", "raw_output_sha256": _SHA,
                "detected": {}, "confidence": 0.83},
        "llm": {"model": "m", "model_version": "1", "prompt_sha256": _SHA,
                "raw_output_sha256": _SHA, "reasoning": "", "confidence": 0.8},
    },
    "engine_outputs": {
        "suitability": {"classification": "screening_estimate", "score": 0.8, "rule": "r"},
        "recommendation": {"actionable": True, "route": "hold_for_review", "headline": "",
                           "insufficient": False, "missing": [], "caveats": [],
                           "alternative": "", "actions": []},
    },
    "verdict": {"decision": "accept", "decided_at_utc": "2026-10-14T01:00:14Z",
                "classification": "screening_estimate", "uncertainty": ""},
    "gates": {g: {"state": "passed"} for g in audit.GATE_NAMES},
    "digest": {"record_sha256": _SHA, "input_digests": {}, "algorithm": "sha256"},
}


def write_record(
    storage: Path,
    n: int,
    *,
    decision: str = "accept",
    supplier: str | None = "CV Uji",
    truck: str = "B 9723 KXW",
    hard: list[str] | None = None,
    light: list[str] | None = None,
    moisture: float | None = None,
    confidence: float = 0.83,
    conflict: bool = False,
    conflict_reason: str = "Waybill declares sorted RDF fluff; the camera sees metal",
    weight_kg: float = 10000.0,
    started: str | None = None,
    duration_s: int = 14,
    status: str = "completed",
    fields: dict | None = None,
    sop_refs: tuple[str, ...] = (),
) -> str:
    """Write ``inspection-<n>`` into ``storage``; return its record id."""
    data = copy.deepcopy(_TEMPLATE)
    record_id = f"inspection-{n:06d}"
    minute = n % 60
    hour = 1 + n // 60
    started = started or f"2026-10-14T{hour:02d}:{minute:02d}:00Z"
    finished = started[:-3] + f"{duration_s:02d}Z" if duration_s < 60 else None
    data["record_id"] = record_id
    data["execution_status"] = status
    data["started_at_utc"] = started
    data["finished_at_utc"] = None if status == "in_progress" else finished
    data["inputs"]["truck_id"] = truck
    data["inputs"]["supplier"] = supplier
    data["inputs"]["weight"]["value_kg"] = weight_kg
    data["inputs"]["manifest_text"]["extracted_fields"] = dict(fields or {})
    data["verdict"]["decision"] = decision
    if decision == "refuse_insufficient_input":
        data["engine_outputs"]["recommendation"]["missing"] = ["photo"]
    detected: dict = {"hard_contaminants": hard or [], "light_contaminants": light or []}
    if moisture is not None:
        detected["moisture"] = moisture
    data["ai_outputs"]["vlm"]["detected"] = detected
    data["ai_outputs"]["vlm"]["confidence"] = confidence
    if conflict:
        data["gates"]["manifest_crosscheck"] = {"state": "failed", "reason": conflict_reason}
    data["engine_outputs"]["recommendation"]["actions"] = [
        {"order": i + 1, "text": f"Step {i + 1}.", "sop_ref": ref}
        for i, ref in enumerate(sop_refs)
    ]
    audit._stamp_record_digest(data)
    audit.AuditRecord.model_validate(data)
    folder = storage / record_id
    folder.mkdir(parents=True, exist_ok=True)
    (folder / audit.RECORD_FILENAME).write_text(json.dumps(data, indent=2), encoding="utf-8")
    return record_id


def load(storage: Path, record_id: str) -> audit.AuditRecord:
    return audit.load_record(storage / record_id / audit.RECORD_FILENAME)
