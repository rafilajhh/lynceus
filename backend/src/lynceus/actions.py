"""Deterministic next-step card: what the gate operator does after the verdict.

Pure, rule-table logic (no AI): the steps follow from the verdict plus the
stated gate states and the VLM ``detected`` lists, and every step cites a
clause of the reference gate SOP (``knowledge/sop-rdf-gate.md``).

Semantics (controller ruling 16): for a verdict, the steps are ALL matching
rows for that verdict in table order, deduplicated by ``sop_ref`` (the first
occurrence wins, so a clause is cited once) and renumbered from 1.  An
unmatched reject / escalate yields the single manual-check fallback.  The gas
row is appended last whenever ``gas_plausibility`` failed, for any verdict.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from lynceus.audit import Decision, GateState
from lynceus.decision import LIGHT_CONTAMINANTS

__all__ = ["next_steps"]

_FALLBACK = ("Hold the ticket; supervisor performs a manual visual check.", "SOP-RDF-5.2")

_GAS_STEP = (
    "Gas alert: ventilate the tipping area before unloading; keep the cab closed.",
    "SOP-RDF-7.1",
)

#: Marker in the ``manifest_crosscheck`` gate reason that
#: ``decision.decide`` writes for a waybill/visual moisture conflict.  A
#: test feeds real ``decide`` output through here so any drift is caught.
_MOISTURE_CONFLICT_MARKER = "moisture conflict"


def _gate_state(gates: Dict[str, Any], name: str) -> Optional[str]:
    gate = (gates or {}).get(name)
    return gate.get("state") if isinstance(gate, dict) else None


def _failed(gates: Dict[str, Any], name: str) -> bool:
    return _gate_state(gates, name) == GateState.FAILED


def _moisture_conflict(gates: Dict[str, Any]) -> bool:
    gate = (gates or {}).get("manifest_crosscheck")
    if not isinstance(gate, dict) or gate.get("state") != GateState.FAILED:
        return False
    return _MOISTURE_CONFLICT_MARKER in str(gate.get("reason") or "").lower()


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
) -> List[Dict[str, Any]]:
    """Ordered ``{"order", "text", "sop_ref"}`` steps for the operator."""
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
        if _failed(gates, "weight_plausibility"):
            steps += [
                ("Hold the ticket and re-weigh the truck.", "SOP-RDF-3.2"),
                ("Ask the driver for the original waybill and notify the supplier.", "SOP-RDF-4.3"),
            ]
        if _failed(gates, "vlm_confidence"):
            steps += [
                ("Retake the load photo from the top platform.", "SOP-RDF-2.1"),
                ("Supervisor performs a manual visual check.", "SOP-RDF-5.2"),
            ]
        if not steps:
            steps.append(_FALLBACK)
    elif verdict == Decision.ESCALATE_HUMAN:
        if _moisture_conflict(gates):
            steps += [
                ("Hold the ticket; supervisor takes a grab sample for moisture.", "SOP-RDF-5.1"),
                ("If confirmed wet, apply the contract moisture penalty.", "SOP-RDF-5.3"),
            ]
        if light:
            steps.append(("Tip to the pre-sort line, not direct feed.", "SOP-RDF-4.4"))
        if _failed(gates, "manifest_crosscheck"):
            steps.append(
                ("Verify the waybill with the driver; correct or void the ticket.", "SOP-RDF-3.3")
            )
        if not steps:
            steps.append(_FALLBACK)
    elif verdict == Decision.ACCEPT:
        steps.append(("Tip to the RDF storage bay and release the ticket.", "SOP-RDF-6.1"))
    elif verdict == Decision.REFUSE_INSUFFICIENT_INPUT:
        what = ", ".join(missing_names) if missing_names else "not itemised"
        steps.append(
            (f"Collect the missing inputs ({what}) and re-run the inspection.", "SOP-RDF-2.2")
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
