"""Deterministic next-step card: what the gate operator does after the verdict.

Pure, rule-table logic (no AI): the steps follow from the verdict plus the
stated gate states and the VLM ``detected`` lists, and every step cites a
clause of the reference gate SOP (``knowledge/sop-rdf-gate.md``).

Semantics (controller ruling 16): for a verdict, the steps are ALL matching
rows for that verdict in table order, deduplicated by ``sop_ref`` (the first
occurrence wins, so a clause is cited once) and renumbered from 1.  An
unmatched reject yields the single manual-check fallback; every escalate
ends with the supervisor review (the only step when nothing else matched).
A plate mismatch (``weight_plausibility`` failed with the plate marker) is
verified first; a poor photo or a vision-vote split each add their own step.
The risk-based lab-sample row is appended for an accept or escalate when
``sampling["sample_this_truck"]`` is true (a rejected load is not tipped).
The gas row is appended last whenever ``gas_plausibility`` failed, for any
verdict.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from lynceus.audit import Decision, GateState
from lynceus.decision import (
    DECLARED_SORTED_MARKER,
    EARLY_MAJORITY_MARKER,
    LIGHT_CONTAMINANTS,
    LOW_CONFIDENCE_HARD_MARKER,
    MOISTURE_CONFLICT_MARKER,
    PHOTO_QUALITY_MARKER,
    PLATE_MISMATCH_MARKER,
    VOTE_SPLIT_MARKER,
)

__all__ = ["next_steps"]

_FALLBACK = ("Hold the ticket; supervisor performs a manual visual check.", "SOP-RDF-5.2")

_SUPERVISOR_REVIEW = (
    (
        "Supervisor reviews the load and records the call on this record: accept, sort "
        "then accept, or reject."
    ),
    "SOP-RDF-5.2",
)

_LAB_SAMPLE_STEP = (
    (
        "Take a risk-based lab sample as the load is tipped (moisture, NCV, chlorine); "
        "the supplier's risk tier sets the rate."
    ),
    "SOP-RDF-5.4",
)

_PLATE_STEP = (
    "Plate does not match the waybill: verify the truck and its papers first.",
    "SOP-RDF-3.3",
)

_GAS_STEP = (
    "Gas alert: ventilate the tipping area before unloading; keep the cab closed.",
    "SOP-RDF-7.1",
)

#: Markers in the ``manifest_crosscheck`` gate reason that ``decision.decide``
#: writes (imported from there).  A test feeds real ``decide`` output through
#: here so any drift is caught.
_MOISTURE_CONFLICT_MARKER = MOISTURE_CONFLICT_MARKER.lower()
_DECLARED_SORTED_MARKER = DECLARED_SORTED_MARKER.lower()


def _gate_state(gates: Dict[str, Any], name: str) -> Optional[str]:
    gate = (gates or {}).get(name)
    return gate.get("state") if isinstance(gate, dict) else None


def _failed(gates: Dict[str, Any], name: str) -> bool:
    return _gate_state(gates, name) == GateState.FAILED


def _crosscheck_says(gates: Dict[str, Any], marker: str) -> bool:
    """True when ``manifest_crosscheck`` failed with ``marker`` in its reason."""
    gate = (gates or {}).get("manifest_crosscheck")
    if not isinstance(gate, dict) or gate.get("state") != GateState.FAILED:
        return False
    return marker in str(gate.get("reason") or "").lower()


def _moisture_conflict(gates: Dict[str, Any]) -> bool:
    return _crosscheck_says(gates, _MOISTURE_CONFLICT_MARKER)


def _reason(gates: Dict[str, Any], name: str) -> str:
    gate = (gates or {}).get(name)
    return str(gate.get("reason") or "") if isinstance(gate, dict) else ""


def _plate_mismatch(gates: Dict[str, Any]) -> bool:
    """The weighbridge gate failed because the truck's plate is not the waybill's."""
    return _failed(gates, "weight_plausibility") and (
        PLATE_MISMATCH_MARKER in _reason(gates, "weight_plausibility")
    )


def _weight_off(gates: Dict[str, Any]) -> bool:
    """The weighbridge gate failed on the weight itself (not only the plate)."""
    if not _failed(gates, "weight_plausibility"):
        return False
    reason = _reason(gates, "weight_plausibility")
    return PLATE_MISMATCH_MARKER not in reason or "ticket correction" in reason.lower()


def _names(value: Any) -> List[str]:
    """Contaminant / missing-input list → clean list of non-empty strings."""
    if not isinstance(value, (list, tuple)):
        return []
    return [str(v).strip() for v in value if str(v).strip()]


def next_steps(
    verdict: str,
    gates: Dict[str, Any],
    detected: Dict[str, Any],
    missing: Sequence[str],
    record_id: str = "",
    *,
    sampling: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Ordered ``{"order", "text", "sop_ref"}`` steps for the operator.

    ``sampling`` is the supplier's risk-based sampling call
    (``suppliers.sampling_for``: ``{"sample_this_truck": bool, ...}``), or
    None when there is none.
    """
    detected = detected if isinstance(detected, dict) else {}
    hard = _names(detected.get("hard_contaminants"))
    # Only the light contaminants decide() itself escalates on: the VLM may
    # also list plastic film / textile, which are RDF feedstock, not a reason
    # to send the load to the pre-sort line.
    light = [n for n in _names(detected.get("light_contaminants")) if n in LIGHT_CONTAMINANTS]
    missing_names = _names(list(missing or []))

    steps: List[Tuple[str, str]] = []

    if verdict == Decision.REJECT:
        if hard:
            steps += [
                ("Do not tip. Keep the truck on the weighbridge.", "SOP-RDF-4.1"),
                (f"Send the load to the sorting bay to remove: {', '.join(hard)}.", "SOP-RDF-4.2"),
                (
                    "Photograph the load and notify the supplier"
                    + (f" with record {record_id}." if record_id else "."),
                    "SOP-RDF-4.3",
                ),
            ]
            if _crosscheck_says(gates, _DECLARED_SORTED_MARKER):
                steps.append((
                    "Contract breach: send the supplier notice quoting "
                    + (f"record {record_id}" if record_id else "the record")
                    + " and the sealed photo; apply the breach fee per contract.",
                    "SOP-RDF-4.5",
                ))
        if _plate_mismatch(gates):
            steps.append(_PLATE_STEP)
        if _weight_off(gates):
            steps += [
                ("Hold the ticket and re-weigh the truck.", "SOP-RDF-3.2"),
                ("Ask the driver for the original waybill and notify the supplier.", "SOP-RDF-4.3"),
            ]
        if not steps:
            steps.append(_FALLBACK)
    elif verdict == Decision.ESCALATE_HUMAN:
        if _plate_mismatch(gates):
            steps.append(_PLATE_STEP)
        if _failed(gates, "vlm_confidence"):
            steps.append((
                "Photo quality poor: retake the load photo from the top platform."
                if PHOTO_QUALITY_MARKER in _reason(gates, "vlm_confidence")
                else "Photo unreadable: retake the load photo from the top platform.",
                "SOP-RDF-2.1",
            ))
        if VOTE_SPLIT_MARKER in _reason(gates, "vlm_confidence"):
            steps.append((
                (
                    "Vision reads disagree on a hard item: the supervisor checks the load "
                    "by hand and records the call."
                ),
                "SOP-RDF-5.2",
            ))
        if LOW_CONFIDENCE_HARD_MARKER in _reason(gates, "vlm_confidence"):
            steps.append((
                (
                    "Hard item listed below the confidence bar: the supervisor checks the "
                    "load by hand and records the call."
                ),
                "SOP-RDF-5.2",
            ))
        if EARLY_MAJORITY_MARKER in _reason(gates, "vlm_confidence"):
            steps.append((
                (
                    "Vision decided on two of three reads with no second look: the "
                    "supervisor checks the load by hand and records the call."
                ),
                "SOP-RDF-5.2",
            ))
        if _moisture_conflict(gates):
            steps += [
                ("Hold the ticket; supervisor takes a grab sample for moisture.", "SOP-RDF-5.1"),
                ("If confirmed wet, apply the contract moisture penalty.", "SOP-RDF-5.3"),
            ]
        if light:
            steps.append(("Tip to the pre-sort line, not direct feed.", "SOP-RDF-4.4"))
        if _weight_off(gates):
            steps += [
                (
                    (
                        "Ticket correction: re-weigh the truck; if the scale holds, "
                        "correct the waybill weight."
                    ),
                    "SOP-RDF-3.2",
                ),
                (
                    (
                        "Confirm the corrected net weight with the driver; correct or "
                        "void the ticket."
                    ),
                    "SOP-RDF-3.3",
                ),
            ]
        if _failed(gates, "ocr_confidence"):
            steps.append((
                (
                    "Waybill read uncertain: check the highlighted fields against the "
                    "paper waybill."
                ),
                "SOP-RDF-3.3",
            ))
        if _failed(gates, "manifest_crosscheck"):
            steps.append(
                ("Verify the waybill with the driver; correct or void the ticket.", "SOP-RDF-3.3")
            )
        steps.append(_SUPERVISOR_REVIEW)
    elif verdict == Decision.ACCEPT:
        steps.append(("Tip to the RDF storage bay and release the ticket.", "SOP-RDF-6.1"))
    elif verdict == Decision.REFUSE_INSUFFICIENT_INPUT:
        what = ", ".join(missing_names) if missing_names else "not itemised"
        steps.append(
            (f"Collect the missing inputs ({what}) and re-run the inspection.", "SOP-RDF-2.2")
        )

    if (
        verdict in (Decision.ACCEPT, Decision.ESCALATE_HUMAN)
        and isinstance(sampling, dict)
        and sampling.get("sample_this_truck") is True
    ):
        reason = str(sampling.get("reason") or "").strip()
        steps.append(
            (
                "Take a lab sample as the load is tipped (moisture, NCV, chlorine): " + reason,
                _LAB_SAMPLE_STEP[1],
            )
            if reason
            else _LAB_SAMPLE_STEP
        )

    if _failed(gates, "gas_plausibility"):
        steps.append(_GAS_STEP)

    out: List[Dict[str, Any]] = []
    seen: set = set()
    for text, ref in steps:
        if ref in seen:
            continue
        seen.add(ref)
        out.append({"order": len(out) + 1, "text": text, "sop_ref": ref})
    return out
