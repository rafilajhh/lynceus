"""Follow-up actions on a sealed inspection: notify the supplier, escalate.

The audit record (``audit.json``) is sealed and never modified.  What the
operator does after the verdict lives beside it in an append-only,
hash-chained log, ``<storage_dir>/<record_id>/actions.jsonl``: one JSON
object per line, each carrying the previous entry's digest
(``prev_sha256``; the first entry uses :data:`audit.EMPTY_SHA256_FIELD`) and
its own (``entry_sha256``, over the canonical JSON of the entry without that
field).  Editing or removing a line in the middle breaks the chain, which
:func:`read_actions` reports instead of hiding.

The supplier notice is built deterministically from the sealed record (no
AI).  It is POSTed to ``SUPPLIER_NOTIFY_WEBHOOK`` when one is configured;
otherwise, or when delivery fails, it is logged only and the entry says so.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx

from lynceus import actions
from lynceus import audit

__all__ = [
    "ACTIONS_FILENAME",
    "KINDS",
    "NOTE_MAX_CHARS",
    "append_action",
    "build_notice",
    "count_actions",
    "read_actions",
]

ACTIONS_FILENAME = "actions.jsonl"
#: Closed set of follow-up kinds.
KINDS = ("notify_supplier", "escalate")
NOTE_MAX_CHARS = 500
#: Seconds the supplier webhook gets before the notice is logged instead.
WEBHOOK_TIMEOUT_S = 5.0

#: Serialises appends process-wide: the chain needs the previous digest.
_WRITE_LOCK = threading.Lock()

#: Verdict → (subject phrase, body phrase).
_VERDICT_WORDS = {
    audit.Decision.REJECT: ("Load rejected at gate", "rejected at the gate"),
    audit.Decision.ESCALATE_HUMAN: (
        "Load held for review at gate",
        "held at the gate for a human check",
    ),
    audit.Decision.ACCEPT: ("Load accepted at gate", "accepted at the gate"),
    audit.Decision.REFUSE_INSUFFICIENT_INPUT: (
        "Inspection refused at gate",
        "not inspected: mandatory inputs were missing",
    ),
}


def _canonical(entry: Dict[str, Any]) -> bytes:
    """Sorted keys, no whitespace: the bytes ``entry_sha256`` is taken over."""
    return json.dumps(
        entry, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def _entry_digest(entry: Dict[str, Any]) -> str:
    body = {k: v for k, v in entry.items() if k != "entry_sha256"}
    return audit.sha256_field(_canonical(body))


def _log_path(storage_dir: "str | os.PathLike[str]", record_id: str) -> Path:
    return Path(storage_dir) / record_id / ACTIONS_FILENAME


def _read_lines(path: Path) -> List[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    return [line for line in text.splitlines() if line.strip()]


def read_actions(
    storage_dir: "str | os.PathLike[str]", record_id: str
) -> Tuple[List[Dict[str, Any]], bool]:
    """Every parseable entry, oldest first, and whether the chain verifies.

    No log yet is an empty, intact chain.  A line that does not parse, a
    digest that does not match its entry, or a ``prev_sha256`` that does not
    match the entry before it all make ``chain_ok`` False; the parseable
    entries are still returned so nothing is hidden.
    """
    entries: List[Dict[str, Any]] = []
    chain_ok = True
    prev = audit.EMPTY_SHA256_FIELD
    for line in _read_lines(_log_path(storage_dir, record_id)):
        try:
            entry = json.loads(line)
        except ValueError:
            chain_ok = False
            continue
        if not isinstance(entry, dict):
            chain_ok = False
            continue
        try:
            digest_ok = _entry_digest(entry) == entry.get("entry_sha256")
        except (ValueError, audit.AuditError):
            digest_ok = False
        if not digest_ok or entry.get("prev_sha256") != prev:
            chain_ok = False
        prev = entry.get("entry_sha256")
        entries.append(entry)
    return entries, chain_ok


def count_actions(storage_dir: "str | os.PathLike[str]", record_id: str) -> Dict[str, int]:
    """``{kind: n}`` for the ledger row (zeros when there is no log)."""
    counts = {kind: 0 for kind in KINDS}
    for entry in read_actions(storage_dir, record_id)[0]:
        if entry.get("kind") in counts:
            counts[entry["kind"]] += 1
    return counts


def _names(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    return [str(v).replace("_", " ").strip() for v in value if str(v).strip()]


def _next_steps(record: audit.AuditRecord) -> List[Dict[str, Any]]:
    """The SOP-cited steps sealed in the record; recomputed by
    :func:`actions.next_steps` for records written before steps were stored."""
    stored = record.engine_outputs.recommendation.actions
    if stored:
        return [step.model_dump() for step in stored]
    dumped = record.model_dump()
    return actions.next_steps(
        record.verdict.decision,
        dumped.get("gates") or {},
        record.ai_outputs.vlm.detected,
        record.engine_outputs.recommendation.missing,
        record.record_id,
    )


def build_notice(record: audit.AuditRecord, note: Optional[str]) -> Dict[str, str]:
    """The supplier notice, from sealed record fields only (no AI)."""
    supplier = (record.inputs.supplier or "").strip() or "Supplier on file"
    plate = record.inputs.truck_id
    decision = record.verdict.decision
    subject_words, body_words = _VERDICT_WORDS.get(
        decision, ("Gate inspection result", f"decided: {decision}")
    )
    detected = record.ai_outputs.vlm.detected
    detected = detected if isinstance(detected, dict) else {}
    hard = _names(detected.get("hard_contaminants"))
    light = _names(detected.get("light_contaminants"))
    digest = record.digest.record_sha256
    short_digest = digest[: len("sha256:") + 12]

    lines = [
        f"Truck {plate} was {body_words} on {record.verdict.decided_at_utc} (UTC).",
        f"Supplier: {supplier}",
        "",
        "Contaminants seen by the gate camera:",
        f"- Hard: {', '.join(hard) if hard else 'none'}",
        f"- Light: {', '.join(light) if light else 'none'}",
    ]
    steps = _next_steps(record)
    if steps:
        lines += ["", "Steps taken at the gate (reference gate SOP):"]
        lines += [f"{s['order']}. {s['text']} [{s['sop_ref']}]" for s in steps]
    lines += ["", f"Record: {record.record_id} (digest {short_digest})"]
    if note:
        lines += ["", f"Operator note: {note}"]
    if decision in (audit.Decision.REJECT, audit.Decision.ESCALATE_HUMAN):
        lines += [
            "",
            "Please confirm the corrective action you will take before your next delivery.",
        ]
    return {
        "to": supplier,
        "subject": f"{subject_words} — {plate} ({record.record_id})",
        "body": "\n".join(lines),
    }


def _deliver(
    webhook_url: str, record_id: str, notice: Dict[str, str]
) -> Tuple[str, Optional[str]]:
    """``("webhook", None)`` on a 2xx from the webhook, else ``("logged", why)``;
    no webhook configured is ``("logged", None)``."""
    if not webhook_url:
        return "logged", None
    if not webhook_url.lower().startswith("https://"):
        return "logged", "SUPPLIER_NOTIFY_WEBHOOK is not an https URL"
    try:
        response = httpx.post(
            webhook_url,
            json={"record_id": record_id, **notice},
            timeout=WEBHOOK_TIMEOUT_S,
        )
    except Exception as exc:  # noqa: BLE001 — any failure is logged, not raised
        return "logged", f"{type(exc).__name__}: {str(exc)[:160]}"
    if 200 <= response.status_code < 300:
        return "webhook", None
    return "logged", f"webhook answered HTTP {response.status_code}"


def append_action(
    storage_dir: "str | os.PathLike[str]",
    record: audit.AuditRecord,
    kind: str,
    note: Optional[str],
    actor: Optional[str],
    webhook_url: str = "",
) -> Dict[str, Any]:
    """Deliver (notify_supplier only) and append one chained entry; returns it.

    Delivery runs before the lock is taken: a slow webhook must not hold
    every other record's appends.  The caller validated ``kind`` and ``note``
    and strict-loaded ``record``.
    """
    if kind not in KINDS:
        raise ValueError(f"unknown follow-up kind {kind!r}")
    notice = delivery = delivery_error = None
    if kind == "notify_supplier":
        notice = build_notice(record, note)
        delivery, delivery_error = _deliver(webhook_url, record.record_id, notice)

    path = _log_path(storage_dir, record.record_id)
    with _WRITE_LOCK:
        lines = _read_lines(path)
        prev = audit.EMPTY_SHA256_FIELD
        for line in reversed(lines):
            try:
                last = json.loads(line)
            except ValueError:
                continue
            if isinstance(last, dict) and isinstance(last.get("entry_sha256"), str):
                prev = last["entry_sha256"]
                break
        entry: Dict[str, Any] = {
            "action_id": f"act-{len(lines) + 1:04d}",
            "record_id": record.record_id,
            "kind": kind,
            "created_at_utc": audit.now_utc(),
            "actor": actor,
            "note": note,
            "notice": notice,
            "delivery": delivery,
            "delivery_error": delivery_error,
            "prev_sha256": prev,
        }
        entry["entry_sha256"] = _entry_digest(entry)
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    return entry
