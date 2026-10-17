"""Operator checks: what the gate operator reads instead of the raw gates.

:func:`build_checks` turns one inspection (an ``/inspect`` response dict or
an audit record ``model_dump()``) into six plain checks, one ``why``
sentence and the decision ``receipt`` (:func:`decision.rule_trace`).  Pure
and deterministic: no I/O, no AI, no clock.

Check shape::

    {"key": "vision|second_look|waybill_read|declaration|weight|supplier",
     "label": "Load photo|Second look|Waybill read|Waybill vs load|Weighbridge|Supplier record",
     "status": "pass|warn|fail|info|skipped",
     "finding": "Metal · 0.85",          # at most 28 characters
     "detail": "One plain sentence.",
     "gate": "vlm_confidence|...|None"}

The vision check also carries ``agreement`` ("Reads 3/3 agree", "Reads
split 1/3", or None with one read).  Sensor observations fold into the
existing tiles: image quality into the load photo, the ANPR plate into the
weighbridge.

Rules the operator can rely on:

* A check never shows a green ``pass`` for the thing that caused a REJECT:
  the confident hard contaminant fails the load-photo check, and a reject
  recorded under an older rule (weight, unreadable photo) fails the check
  it came from.
* The detector not seeing a contaminant the vision model confidently found
  is ``info`` ("Did not see it"), never a green pass and never a veto.
* ``why`` is one sentence (at most 140 characters) that starts with the
  cause.

Old records (format v1/v2: LLM cross-check, gas twin readings, no waybill
fields) are read as they are: missing pieces become ``skipped``.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from lynceus import decision
from lynceus.audit import Decision, GateState
from lynceus.decision import (
    ARITHMETIC_MARKER,
    DECLARED_SORTED_MARKER,
    DETECTOR_MISSED_MARKER,
    HARD_CONTAMINANTS,
    MOISTURE_CONFLICT_MARKER,
    PHOTO_QUALITY_MARKER,
    PLATE_MISMATCH_MARKER,
    WAYBILL_READ_MIN_CONFIDENCE,
    WEIGHT_TOLERANCE,
    confident_hard_contaminants,
    contract_moisture_spec_pct,
    declared_moisture_fraction,
    light_contaminant_hits,
    plate_mismatch,
    poor_image_notes,
    vote_agreement,
    vote_split,
)

__all__ = ["CHECK_KEYS", "FINDING_MAX", "WAYBILL_FIELDS", "WHY_MAX", "build_checks"]

#: ``(key, label, gate)`` in the order the operator reads them.
CHECK_KEYS: Tuple[Tuple[str, str, Optional[str]], ...] = (
    ("vision", "Load photo", "vlm_confidence"),
    ("second_look", "Second look", "detector_second_opinion"),
    ("waybill_read", "Waybill read", "ocr_confidence"),
    ("declaration", "Waybill vs load", "manifest_crosscheck"),
    ("weight", "Weighbridge", "weight_plausibility"),
    ("supplier", "Supplier record", None),
)
FINDING_MAX = 28
WHY_MAX = 140
#: The waybill fields the reader extracts (``POST /waybill/read``).
WAYBILL_FIELDS = (
    "document_no", "plate", "date", "origin", "destination", "carrier", "shipper",
    "driver", "reference_no", "gross_kg", "tare_kg", "net_kg", "load_type",
    "moisture_pct", "remarks",
)
#: Operator words for contaminant names.
_NICE = {"organic_residue": "organic", "wet_mix": "wet mix"}
#: "flagged <name> (<conf>)" in a detector gate reason (decision wording).
_FLAGGED_RE = re.compile(r"flagged ([a-z][a-z_\-]*) \((\d(?:\.\d+)?)\)")
_MISSING_WORDS = {"photo": "photo", "manifest_text": "waybill", "vlm_result": "vision read"}


# ---------------------------------------------------------------------------
# Reading either shape
# ---------------------------------------------------------------------------


def _dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _num(value: Any) -> Optional[float]:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip().rstrip("%").strip())
        except ValueError:
            return None
    return None


def _state(gate: Any) -> Optional[str]:
    return gate.get("state") if isinstance(gate, dict) else None


def _reason(gate: Any) -> str:
    return str(gate.get("reason") or "") if isinstance(gate, dict) else ""


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _nice(name: str) -> str:
    return _NICE.get(name, name)


def _names(names: Sequence[str], capital: bool = True, compact: bool = False) -> str:
    """"Metal and tire"; ``compact`` (for a finding): "Metal, tire"."""
    words = [_nice(n) for n in names]
    if compact or len(words) == 1:
        text = ", ".join(words)
    else:
        text = ", ".join(words[:-1]) + " and " + words[-1]
    return text[:1].upper() + text[1:] if capital else text


def _fields_and_confidences(inputs: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, float]]:
    """Waybill field values (``waybill_fields`` of a payload, or a record's
    ``manifest_text.extracted_fields``), unwrapping ``{value, confidence}``."""
    raw = inputs.get("waybill_fields")
    if not isinstance(raw, dict):
        raw = _dict(_dict(inputs.get("manifest_text")).get("extracted_fields"))
    values: Dict[str, Any] = {}
    confidences: Dict[str, float] = {}
    for name, item in raw.items():
        if isinstance(item, dict) and "value" in item:
            values[name] = item.get("value")
            conf = _num(item.get("confidence"))
            if conf is not None:
                confidences[name] = conf
        else:
            values[name] = item
    return values, confidences


def _waybill_read(inputs: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """``{"confidence", "edited_fields"}`` when the waybill was read from a
    photo (payload ``waybill_read``, or a record whose manifest source says
    ``waybill_photo_ai_read``), else None (typed by the operator)."""
    read = inputs.get("waybill_read")
    if isinstance(read, dict):
        return {
            "confidence": _num(read.get("confidence")),
            "edited_fields": [str(f) for f in read.get("edited_fields") or []],
        }
    manifest = _dict(inputs.get("manifest_text"))
    source = str(manifest.get("source") or "")
    if source.startswith("waybill_photo"):
        return {
            "confidence": _num(manifest.get("ocr_confidence")),
            "edited_fields": ["(operator edited)"] if source.endswith("operator_edited") else [],
        }
    return None


class _Record:
    """The parts of one inspection the checks read, from either shape."""

    def __init__(self, rec: Dict[str, Any], sampling: Optional[Dict[str, Any]] = None) -> None:
        audit_record = _dict(rec.get("audit_record"))
        self.recommendation: Dict[str, Any] = {}
        verdict = rec.get("verdict", audit_record.get("verdict"))
        self.decision: Optional[str] = (
            verdict.get("decision") if isinstance(verdict, dict)
            else verdict if isinstance(verdict, str) else None
        )
        self.gates = _dict(rec.get("gates")) or _dict(audit_record.get("gates"))
        ai = _dict(rec.get("ai_outputs")) or _dict(audit_record.get("ai_outputs"))
        self.vlm = _dict(ai.get("vlm"))
        self.detector = ai.get("detector") if isinstance(ai.get("detector"), dict) else None
        self.inputs = _dict(rec.get("inputs")) or _dict(audit_record.get("inputs"))
        self.fields, self.field_confidence = _fields_and_confidences(self.inputs)
        self.read = _waybill_read(self.inputs)
        engine = _dict(rec.get("engine_outputs")) or _dict(audit_record.get("engine_outputs"))
        recommendation = _dict(engine.get("recommendation"))
        self.recommendation = recommendation
        self.missing = [
            str(m) for m in (self.gates.get("missing") or recommendation.get("missing") or [])
        ]
        self.reasons = [str(r) for r in rec.get("reasons") or []]
        self.sampling = _dict(sampling) if isinstance(sampling, dict) else _dict(rec.get("sampling"))
        self.receipt = rec.get("receipt") if isinstance(rec.get("receipt"), list) else None
        # Wave-2 evidence: vision votes and the gate's observations.
        self.observations = [
            o for o in self.inputs.get("observations") or [] if isinstance(o, dict)
        ] if isinstance(self.inputs.get("observations"), list) else []
        self.agreement = vote_agreement(self.vlm)
        self.split = vote_split(self.vlm)
        self.poor_photo = poor_image_notes(self.inputs)
        self.plate = plate_mismatch(
            {"waybill_fields": self.fields, "observations": self.observations}
        )
        fraction, _ = declared_moisture_fraction({"waybill_fields": self.fields})
        self.declared_moisture_pct = None if fraction is None else round(fraction * 100.0, 6)
        self.moisture_spec_pct = contract_moisture_spec_pct()
        # Payload: weight_kg / declared_weight_kg; record: weight.value_kg.
        weight = _dict(self.inputs.get("weight"))
        self.weight_kg = _num(self.inputs.get("weight_kg"))
        if self.weight_kg is None:
            self.weight_kg = _num(weight.get("value_kg"))
        self.weight_source = str(self.inputs.get("weight_source") or weight.get("source") or "")
        self.declared_kg = _num(self.inputs.get("declared_weight_kg"))
        if self.declared_kg is None:
            self.declared_kg = _num(self.fields.get("net_kg"))
        self.supplier = str(self.inputs.get("supplier") or self.fields.get("carrier") or "").strip()
        # The hard contaminants decide() rejects on (allowlist, VLM >= 0.6).
        self.hard = confident_hard_contaminants(None, self.vlm, None)
        self.light = light_contaminant_hits(self.vlm)
        self.vlm_confidence = _num(self.vlm.get("confidence"))

    def gate(self, name: Optional[str]) -> Dict[str, Any]:
        return _dict(self.gates.get(name)) if name else {}

    def failed(self, name: str) -> bool:
        return _state(self.gates.get(name)) == GateState.FAILED

    @property
    def legacy_reject(self) -> bool:
        """A REJECT without a confident hard contaminant: recorded under an
        older rule (weight > 10 %, VLM confidence < 0.3, prose)."""
        return self.decision == Decision.REJECT and not self.hard

    @property
    def plate_flagged(self) -> bool:
        """The weighbridge gate (or the ANPR observation) says wrong truck."""
        return self.plate is not None or (
            PLATE_MISMATCH_MARKER in _reason(self.gates.get("weight_plausibility"))
        )

    @property
    def weight_off(self) -> bool:
        """The weighbridge gate failed on the weight itself, not only the plate."""
        reason = _reason(self.gates.get("weight_plausibility"))
        return self.failed("weight_plausibility") and (
            PLATE_MISMATCH_MARKER not in reason or "ticket correction" in reason.lower()
        )

    @property
    def above_spec(self) -> bool:
        return (
            self.declared_moisture_pct is not None
            and self.declared_moisture_pct > self.moisture_spec_pct
        )

    def weight_delta(self) -> Optional[float]:
        """Signed (scale - declared) / declared, else the gate's unsigned value."""
        if self.weight_kg is not None and self.declared_kg:
            return (self.weight_kg - self.declared_kg) / self.declared_kg
        return _num(self.gate("weight_plausibility").get("value"))

    def weight_text(self) -> str:
        delta = self.weight_delta()
        if delta is None:
            return "?"
        signed = self.weight_kg is not None and bool(self.declared_kg)
        return f"{delta * 100:+.1f} %" if signed else f"{delta * 100:.1f} %"

    def detector_flag(self) -> Optional[Tuple[str, float]]:
        """The first ``(name, confidence)`` the detector gate reason flags."""
        match = _FLAGGED_RE.search(_reason(self.gates.get("detector_second_opinion")))
        return (match.group(1), float(match.group(2))) if match else None


def _check(key: str, status: str, finding: str, detail: str) -> Dict[str, Any]:
    _, label, gate = next(row for row in CHECK_KEYS if row[0] == key)
    return {
        "key": key,
        "label": label,
        "status": status,
        "finding": _clip(finding, FINDING_MAX),
        "detail": detail,
        "gate": gate,
    }


# ---------------------------------------------------------------------------
# The six checks
# ---------------------------------------------------------------------------


def _vision(r: _Record) -> Dict[str, Any]:
    """The load-photo check; ``agreement`` says how the vision reads voted."""
    check = _vision_check(r)
    check["agreement"] = r.agreement
    if r.agreement and r.agreement not in check["detail"]:
        check["detail"] += f" {r.agreement}."
    return check


def _vision_check(r: _Record) -> Dict[str, Any]:
    gate = r.gate("vlm_confidence")
    state = _state(gate)
    conf = r.vlm_confidence
    if state in (None, GateState.NOT_RUN, GateState.NOT_EVALUATED):
        return _check("vision", "skipped", "Not run",
                      _reason(gate) or "The vision model did not read the photo.")
    if r.hard:
        return _check(
            "vision", "fail", f"{_names(r.hard, compact=True)} · {conf or 0:.2f}",
            f"The vision model sees {_names(r.hard, capital=False)} in the load "
            f"(confidence {conf or 0:.2f}).",
        )
    if state == GateState.FAILED:
        poor = r.poor_photo or PHOTO_QUALITY_MARKER in _reason(gate)
        return _check(
            "vision", "fail" if r.legacy_reject else "warn",
            "Poor photo · retake" if poor else "Unreadable · retake",
            (" ".join(r.poor_photo) or "The image-quality check marked the photo poor.")
            + " Retake it from the top platform."
            if poor
            else f"The vision model read the photo at {conf or 0:.2f} confidence: retake it "
            "from the top platform.",
        )
    if r.split:
        _, (seen, of) = min(r.split.items())
        return _check(
            "vision", "warn", r.agreement or f"Reads split {seen}/{of}",
            "; ".join(f"{s} of {o} vision reads saw {_nice(n)}" for n, (s, o) in sorted(r.split.items()))
            + ": check the load by hand.",
        )
    if r.legacy_reject and not r.failed("weight_plausibility"):
        return _check(
            "vision", "fail", "Hard item (older rule)",
            "Rejected under an older rule that also read the vision model's prose; "
            "check the recorded reasons.",
        )
    if r.light:
        return _check(
            "vision", "warn", _names(r.light, compact=True),
            f"The vision model sees {_names(r.light, capital=False)}: light contamination "
            "for the pre-sort line.",
        )
    listed = [
        n for n in _dict(r.vlm.get("detected")).get("hard_contaminants") or []
        if isinstance(n, str) and n in HARD_CONTAMINANTS
    ]
    if listed:
        return _check(
            "vision", "warn", f"Possible {_nice(listed[0])} · {conf or 0:.2f}",
            f"The vision model lists {_names(listed, capital=False)} below its 0.60 trust "
            "bar: not acted on.",
        )
    return _check("vision", "pass", r.agreement or "Nothing hard seen",
                  f"Nothing hard seen: no hard or light contaminant in the photo (confidence "
                  f"{conf or 0:.2f}).")


def _second_look(r: _Record) -> Dict[str, Any]:
    gate = r.gate("detector_second_opinion")
    state = _state(gate)
    reason = _reason(gate)
    if state in (None, GateState.NOT_RUN):
        return _check("second_look", "skipped", "Not run",
                      reason or "The CPU detector did not run on this photo.")
    if state == GateState.NOT_EVALUATED:
        return _check("second_look", "skipped", "Not evaluated", reason)
    flag = r.detector_flag()
    if state == GateState.FAILED:
        finding = f"Flags {_nice(flag[0])} {flag[1]:.2f}" if flag else "Flags a finding"
        return _check("second_look", "warn", finding, reason)
    detector_hard = set(_dict(r.detector).get("hard_contaminants") or [])
    if DETECTOR_MISSED_MARKER in reason or (r.hard and not detector_hard & set(r.hard)):
        return _check(
            "second_look", "info", "Did not see it",
            "Second look did not find it; the vision finding stands (the detector is "
            "trained on close-ups, not truck beds).",
        )
    if "set not to escalate" in reason:
        finding = f"Flags {_nice(flag[0])} · not acted on" if flag else "Light flag · not acted on"
        return _check("second_look", "info", finding, reason)
    return _check("second_look", "pass", "Agrees", reason or "The detector agrees.")


def _waybill_read_check(r: _Record) -> Dict[str, Any]:
    if r.read is None:
        return _check("waybill_read", "skipped", "Typed by operator",
                      "No waybill photo; the operator typed the fields.")
    gate = r.gate("ocr_confidence")
    conf = r.read["confidence"]
    if conf is None:
        conf = _num(gate.get("value"))
    filled = sum(1 for f in WAYBILL_FIELDS if r.fields.get(f) not in (None, ""))
    unsure = sorted(f for f, c in r.field_confidence.items() if c < WAYBILL_READ_MIN_CONFIDENCE)
    edited = r.read["edited_fields"]
    notes = []
    if unsure:
        notes.append(f"unsure: {', '.join(unsure)}")
    if edited:
        notes.append(f"operator edited: {', '.join(edited)}")
    note = f" ({'; '.join(notes)})" if notes else ""
    if _state(gate) == GateState.FAILED or (conf is not None and conf < WAYBILL_READ_MIN_CONFIDENCE):
        finding = f"{len(unsure)} fields unsure" if unsure else f"Unsure · {conf or 0:.2f}"
        return _check(
            "waybill_read", "warn", finding,
            f"The waybill read is uncertain (confidence {conf or 0:.2f}): check the fields "
            f"against the paper{note}.",
        )
    if conf is None:
        return _check("waybill_read", "warn", "No read confidence",
                      "The waybill read carries no confidence: check the fields.")
    return _check(
        "waybill_read", "pass", f"{filled}/{len(WAYBILL_FIELDS)} fields · {conf:.2f}",
        f"Waybill read from the photo at {conf:.2f} confidence{note}.",
    )


def _declaration(r: _Record) -> Dict[str, Any]:
    gate = r.gate("manifest_crosscheck")
    state = _state(gate)
    reason = _reason(gate)
    if state in (None, GateState.NOT_RUN):
        return _check("declaration", "skipped", "Not run", reason or "Not compared.")
    if state == GateState.NOT_EVALUATED and not r.above_spec:
        return _check("declaration", "skipped", "Nothing declared",
                      "The waybill declares nothing the load can be compared on.")
    if state == GateState.FAILED:
        if DECLARED_SORTED_MARKER in reason:
            seen = _nice(r.hard[0]) if r.hard else "hard item"
            return _check("declaration", "fail", f"Declared sorted · {seen}", reason)
        if MOISTURE_CONFLICT_MARKER.lower() in reason.lower():
            return _check("declaration", "fail", "Wetter than declared", reason)
        if ARITHMETIC_MARKER in reason:
            return _check("declaration", "fail", "Net does not add up", reason)
        # An older record: the LLM's own cross-check.
        return _check("declaration", "warn", "Fields disagree", reason)
    if r.above_spec:
        return _check(
            "declaration", "warn",
            f"Declared {r.declared_moisture_pct:g} % > {r.moisture_spec_pct:g} % spec",
            f"Declared moisture {r.declared_moisture_pct:g} % is above the "
            f"{r.moisture_spec_pct:g} % contract spec: the load is priced on the lab sample "
            "(SOP-RDF-5.4).",
        )
    return _check("declaration", "pass", "Matches", reason or "The waybill matches the load.")


def _weight(r: _Record) -> Dict[str, Any]:
    gate = r.gate("weight_plausibility")
    state = _state(gate)
    simulated = " (simulated scale feed)" if "simulated" in r.weight_source else ""
    if r.plate_flagged:
        read, expected = r.plate or ("another plate", "the waybill plate")
        weight_note = (
            f" The scale is also {r.weight_text()} from the waybill net." if r.weight_off else ""
        )
        return _check(
            "weight", "fail", f"Plate {read} ≠ waybill",
            f"The plate camera reads {read}; the waybill says {expected}: verify the truck."
            + weight_note,
        )
    if state in (None, GateState.NOT_RUN):
        return _check("weight", "skipped", "No scale reading", "No weighbridge weight supplied.")
    if state == GateState.NOT_EVALUATED:
        return _check("weight", "skipped", "No declared weight",
                      "The waybill states no net weight to compare the scale with.")
    pct = r.weight_text()
    if state == GateState.FAILED:
        if r.legacy_reject:
            return _check("weight", "fail", f"{pct} vs waybill",
                          f"Rejected under the older 10 % weight rule{simulated}.")
        return _check(
            "weight", "warn", f"{pct} · correct ticket",
            f"The scale is {pct} from the waybill net, beyond {WEIGHT_TOLERANCE:.0%}: "
            f"re-weigh or correct the ticket{simulated}.",
        )
    return _check("weight", "pass", f"{pct} vs waybill",
                  f"The scale is within {WEIGHT_TOLERANCE:.0%} of the waybill net{simulated}.")


def _supplier(r: _Record, profile: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if r.sampling.get("sample_this_truck") is True:
        return _check(
            "supplier", "warn", "Sample this truck",
            str(r.sampling.get("reason") or "Risk-based lab sample due (SOP-RDF-5.4)."),
        )
    if not isinstance(profile, dict) or not profile:
        if r.supplier:
            return _check("supplier", "skipped", "New supplier",
                          f"No record for {r.supplier} yet.")
        return _check("supplier", "skipped", "No supplier named",
                      "The waybill names no supplier.")
    tier = str(profile.get("tier") or "new")
    sampling = _dict(profile.get("sampling"))
    every_n = _num(sampling.get("every_n"))
    trucks = _num(profile.get("trucks"))
    name = str(profile.get("supplier") or r.supplier or "this supplier")
    rate = str(sampling.get("label") or (f"1 in {every_n:.0f}" if every_n else "")).strip()
    count = int(trucks or 0)
    detail = (f"{count} truck{'' if count == 1 else 's'} on record for {name}"
              + (f"; sampling {rate}." if rate else "."))
    if tier == "new":
        return _check("supplier", "skipped", "New supplier", detail)
    label = f"{tier.capitalize()} risk"
    if tier == "high":
        finding = f"{label} · lab sample"
    elif every_n:
        finding = f"{label} · 1 in {every_n:.0f} sampled"
    else:
        finding = label
    return _check("supplier", "pass" if tier == "low" else "warn", finding, detail)


# ---------------------------------------------------------------------------
# The "why" sentence
# ---------------------------------------------------------------------------


def _moisture_words(r: _Record) -> str:
    """The declared moisture from the waybill field, else the typed dry claim."""
    fraction, _ = declared_moisture_fraction({"waybill_fields": r.fields})
    return f"the declared {fraction * 100:.0f} %" if fraction is not None else "the waybill's dry claim"


def _why(r: _Record) -> str:
    d = r.decision
    if d == Decision.REFUSE_INSUFFICIENT_INPUT:
        if r.missing:
            words = ", ".join(_MISSING_WORDS.get(m, m) for m in r.missing)
            return f"Missing {words}: collect it and re-run; no verdict without it."
        return "Not enough data to route the load: collect the missing inputs and re-run."
    if d == Decision.REJECT:
        if r.hard:
            seen = _names(r.hard)
            if DECLARED_SORTED_MARKER in _reason(r.gates.get("manifest_crosscheck")):
                return (f"{seen} seen in a load declared as sorted RDF: risk to the shredder "
                        "and kiln. Do not tip.")
            return f"{seen} seen in the load: risk to the shredder and kiln. Do not tip."
        if r.failed("weight_plausibility"):
            return (f"Weight {r.weight_text()} off the waybill (older 10 % rule): re-weigh and "
                    "check the ticket.")
        if r.failed("vlm_confidence"):
            return "Photo unreadable (older rule): retake it before deciding."
        return "Rejected under an older rule: check the recorded reasons before tipping."
    if d == Decision.ESCALATE_HUMAN:
        vlm_state = _state(r.gates.get("vlm_confidence"))
        flag = r.detector_flag()
        if vlm_state in (None, GateState.NOT_RUN):
            if flag:
                return (f"Vision model unavailable; the second look flags {_nice(flag[0])}: "
                        "inspect the load before tipping.")
            return "Vision model unavailable: a person inspects the load before tipping."
        if r.plate_flagged:
            if r.plate:
                return (f"Plate {r.plate[0]} does not match the waybill ({r.plate[1]}): verify "
                        "the truck before tipping.")
            return "Plate does not match the waybill: verify the truck before tipping."
        if r.hard:
            return (f"{_names(r.hard)} seen by a fallback vision model: the supervisor checks "
                    "the load before tipping.")
        if vlm_state == GateState.FAILED:
            if r.poor_photo or PHOTO_QUALITY_MARKER in _reason(r.gates.get("vlm_confidence")):
                return "Photo quality is poor: retake it from the top platform before deciding."
            return "Photo unreadable: retake it from the top platform before deciding."
        if r.split:
            name, (seen, of) = min(r.split.items())
            return (f"{seen} of {of} vision reads saw {_nice(name)}: check the load by hand "
                    "before tipping.")
        detector_failed = r.failed("detector_second_opinion")
        if detector_failed and flag and flag[0] in HARD_CONTAMINANTS:
            return (f"Second look flags {flag[0]} the vision model did not confirm: the "
                    "supervisor checks the load.")
        cross = _reason(r.gates.get("manifest_crosscheck"))
        cross_failed = r.failed("manifest_crosscheck")
        if cross_failed and MOISTURE_CONFLICT_MARKER.lower() in cross.lower():
            return (f"Load looks wetter than {_moisture_words(r)}: take a grab sample before "
                    "tipping.")
        if r.weight_off:
            return (f"Scale reads {r.weight_text()} vs the waybill: re-weigh or correct the "
                    "ticket before tipping.")
        if cross_failed and ARITHMETIC_MARKER in cross:
            return "Waybill gross minus tare does not give the net: correct the ticket before tipping."
        if r.failed("ocr_confidence"):
            return "Waybill read is uncertain: check the fields against the paper before tipping."
        if r.light:
            return f"{_names(r.light)} seen in the load: tip to the pre-sort line, not direct feed."
        if detector_failed and flag:
            return (f"Second look flags {_nice(flag[0])} the vision model did not report: the "
                    "supervisor checks the load.")
        if cross_failed:
            return "Waybill fields disagree with the load: verify with the driver before tipping."
        if any("tied" in reason for reason in r.reasons):
            return "Engine routes tied: the supervisor picks the route before tipping."
        return "Held for the supervisor: review the record before tipping."
    if d == Decision.ACCEPT:
        if r.above_spec:
            return (f"Accept for tipping: nothing hard seen; declared moisture "
                    f"{r.declared_moisture_pct:g} % is above the {r.moisture_spec_pct:g} % "
                    "spec, so sample it to settle the price.")
        parts = ["nothing hard seen"]
        if _state(r.gates.get("weight_plausibility")) == GateState.PASSED:
            parts.append(f"weight within {WEIGHT_TOLERANCE * 100:.0f} %")
        if _state(r.gates.get("manifest_crosscheck")) == GateState.PASSED:
            parts.append("waybill matches the load")
        return "Clean RDF: " + ", ".join(parts) + "."
    return "No verdict recorded yet."


# ---------------------------------------------------------------------------
# The decision receipt
# ---------------------------------------------------------------------------

#: Verdict → the receipt's effect word.
_EFFECT = {
    Decision.REJECT: "reject",
    Decision.ESCALATE_HUMAN: "hold",
    Decision.ACCEPT: "accept",
    Decision.REFUSE_INSUFFICIENT_INPUT: "refuse",
}


def _replay_args(r: _Record) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Best-effort ``decide`` payload and keyword arguments from a record.

    A sealed record keeps the waybill text only as a digest, so a typed
    waybill's "declared weight" / "moisture" text cannot be re-read.
    """
    inputs = r.inputs
    manifest = inputs.get("manifest_text")
    photo = bool(
        inputs.get("photo") or inputs.get("photo_base64") or inputs.get("photo_filename")
        or inputs.get("demo_case") or r.vlm
    )
    weight_ran = _state(r.gates.get("weight_plausibility")) not in (None, GateState.NOT_RUN)
    payload: Dict[str, Any] = {
        "photo_filename": "sealed-photo" if photo else None,
        "manifest_text": manifest if isinstance(manifest, str)
        else "(sealed waybill text)" if isinstance(manifest, dict) else "",
        "waybill_fields": r.fields or None,
        "waybill_read": dict(r.read) if r.read else None,
        "weight_kg": r.weight_kg if weight_ran or "weight_kg" in inputs else None,
        "declared_weight_kg": r.declared_kg,
        "moisture": inputs.get("moisture"),
        "gas": inputs.get("gas"),
        "observations": r.observations,
    }
    thresholds = _dict(_dict(r.detector).get("thresholds"))
    kwargs: Dict[str, Any] = {}
    if _num(thresholds.get("hard")) is not None:
        kwargs["detector_hard_conf"] = float(thresholds["hard"])
    if _num(thresholds.get("light")) is not None:
        kwargs["detector_light_conf"] = float(thresholds["light"])
    if isinstance(thresholds.get("escalate_light"), bool):
        kwargs["detector_escalate_light"] = thresholds["escalate_light"]
    return payload, kwargs


def _receipt(r: _Record) -> List[Dict[str, Any]]:
    """The receipt the response carries, else :func:`decision.rule_trace`
    replayed on the record.  When the replay disagrees with the sealed
    verdict (older rules, or inputs kept only as digests) a last row says so:
    the sealed verdict stands."""
    if r.receipt is not None:
        return [row for row in r.receipt if isinstance(row, dict)]
    payload, kwargs = _replay_args(r)
    engine = {"recommendation": r.recommendation} if r.recommendation else None
    vlm = r.vlm or None
    replayed, _, _ = decision.decide(payload, vlm, None, engine, r.detector, **kwargs)
    rows = decision.rule_trace(payload, vlm, None, engine, r.detector, **kwargs)
    if r.decision and r.decision != replayed:
        degraded = not r.vlm and _state(r.gates.get("vlm_confidence")) in (None, GateState.NOT_RUN)
        rows.append({
            "id": "recorded_verdict",
            "rule": "The sealed verdict stands as recorded",
            "fired": True,
            "evidence": (
                f"Recorded {r.decision} in degraded mode: the vision model was unavailable, "
                "so a person inspects the load."
                if degraded and r.decision == Decision.ESCALATE_HUMAN
                else f"Recorded {r.decision}; today's rules on the stored outputs give "
                f"{replayed} (decided under older rules, or on inputs the record keeps "
                "only as digests)."
            ),
            "effect": _EFFECT.get(r.decision, "none"),
        })
    return rows


def build_checks(
    response_like: Dict[str, Any],
    supplier_profile: Optional[Dict[str, Any]] = None,
    sampling: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """``{"why": str, "checks": [check, ...], "receipt": [rule, ...]}``.

    ``response_like`` is an ``/inspect`` response dict or an audit record
    ``model_dump()``; any part may be missing.  ``supplier_profile`` is the
    supplier's ``suppliers.profile`` dict (``tier``, ``sampling``, ``trucks``),
    or None when there is none.  ``sampling`` is this truck's
    ``suppliers.sampling_for`` call (default: ``response_like["sampling"]``).
    ``receipt`` is ``response_like["receipt"]`` when the caller computed it
    with :func:`decision.rule_trace`, else replayed from the record.
    """
    r = _Record(response_like if isinstance(response_like, dict) else {}, sampling)
    return {
        "why": _clip(_why(r), WHY_MAX),
        "checks": [
            _vision(r),
            _second_look(r),
            _waybill_read_check(r),
            _declaration(r),
            _weight(r),
            _supplier(r, supplier_profile),
        ],
        "receipt": _receipt(r),
    }
