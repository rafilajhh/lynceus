"""Lynceus decision (fusion) layer.

Fuses the VLM photo analysis, the waybill declarations, the weighbridge
reading and the Lynceus engine assessment into one final verdict plus a set
of **stated** quality gates and human-readable English reasons for the UI.

Priority order (a red flag always outranks an amber one, and refusing to
answer always outranks everything — a speculative verdict built on missing
inputs is "the most destructive output", research-audit-provenance
pattern 14):

1. ``refuse_insufficient_input`` — a mandatory input is missing (no photo,
   VLM failed, empty manifest).  The verdict carries the ``missing`` list.
2. ``reject`` — only a confident hard contaminant (metal / rock / concrete /
   tire / e-waste with VLM confidence >= 0.6).  When the waybill declares
   processed (sorted) RDF, the declaration check fails too and the reasons
   add a contract-breach notice.
3. ``escalate_human`` — anything a person must look at, never a reject:

   * an ANPR plate observation that differs from the waybill plate: verify
     the truck (R3);
   * an ``image_quality`` observation marked poor: retake the photo (R2);
   * VLM confidence < 0.3: the photo is unreadable, retake it;
   * some vision reads (``votes``) saw a hard contaminant the majority
     dropped: check by hand (R1);
   * weighbridge vs declared weight beyond 5 %: ticket correction;
   * the waybill photo read below 0.6 confidence: check the fields;
   * the load looks wetter than declared (waybill field: visual moisture
     >= declared + 15 points; typed text: a dry claim < 15 % against a
     visual >= 15 %): grab sample;
   * waybill arithmetic: |gross - tare - net| > 1 % of net;
   * light/ambiguous contamination (glass, organic residue, wet mix;
     plastic film and textile are RDF feedstock);
   * an engine ranking whose top two routes are tied within 0.02.
4. ``accept`` — no red flags and the engine recommendation is actionable
   and not tied.

:func:`rule_trace` returns the decision receipt: every rule above, in
priority order, with whether it fired and its evidence.  A declared moisture
above the contract spec is listed there but never moves the verdict.

The LLM's own cross-check verdict (``crosscheck_failed``) no longer moves
the verdict: its notes stay in the audit as a narrative.  The
``manifest_crosscheck`` gate is the deterministic declaration check
("Waybill vs load"), ``not_evaluated`` when the waybill declares nothing
it can be compared on.  ``ocr_confidence`` is the waybill photo read's own
confidence (``not_run`` for a typed waybill).  ``gas_plausibility`` runs only
on a live gate sensor's readings (:mod:`lynceus.gas_ingest`); otherwise it
is ``not_run`` "No gas sensor at this gate".

The CPU object detector (:mod:`lynceus.detector`) is a second opinion, never
a verdict of its own: a hard contaminant it flags (at/above
``detector_hard_conf``) that the VLM did not confidently confirm holds the
truck for a human (escalate, never accept, never reject); a light one the VLM
did not report does the same unless ``detector_escalate_light`` is off.  A
confident VLM hard contaminant the detector did not flag stays a reject: the
gate passes with a reason saying the vision finding stands.  When
the live vision model is unavailable, :func:`decide_degraded` holds every
truck for a human and lists what the detector saw (or refuses, when a
mandatory input is missing).

A VLM answer from a fallback model outside the benchmarked set never
decides a load on its own: an accept or a reject becomes ``escalate_human``.
A VLM answer with no numeric confidence counts as a missing VLM result.

Only the audit enums are used so the fused output slots straight into
``audit.finish_record`` without any mapping layer.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from lynceus import detector as cv_detector
from lynceus.audit import Decision, GateState, Route
from lynceus.config import DEFAULT_DETECTOR_HARD_CONF, DEFAULT_DETECTOR_LIGHT_CONF
from lynceus.gas_ingest import LIVE_GAS_SOURCE

__all__ = [
    "HARD_CONTAMINANTS",
    "LIGHT_CONTAMINANTS",
    "HARD_CONTAMINANT_CONFIDENCE",
    "UNSAFE_VLM_CONFIDENCE",
    "WEIGHT_TOLERANCE",
    "WEIGHT_MISMATCH_THRESHOLD",
    "WAYBILL_READ_MIN_CONFIDENCE",
    "MOISTURE_DECLARED_MARGIN",
    "ARITHMETIC_TOLERANCE",
    "DETECTOR_HARD_CONFIDENCE",
    "DETECTOR_LIGHT_CONFIDENCE",
    "DECLARED_SORTED_MARKER",
    "MOISTURE_CONFLICT_MARKER",
    "ARITHMETIC_MARKER",
    "DETECTOR_MISSED_MARKER",
    "PHOTO_QUALITY_MARKER",
    "VOTE_SPLIT_MARKER",
    "PLATE_MISMATCH_MARKER",
    "RULES",
    "confident_hard_contaminants",
    "contract_moisture_spec_pct",
    "plate_mismatch",
    "poor_image_notes",
    "vote_agreement",
    "vote_split",
    "rule_trace",
    "light_contaminant_hits",
    "declares_processed_rdf",
    "declared_moisture_fraction",
    "GAS_CH4_ANAEROBIC_THRESHOLD_PPM",
    "decide",
    "decide_degraded",
]


# ---------------------------------------------------------------------------
# Tunables (stated thresholds, never inferred — engine pattern 11)
# ---------------------------------------------------------------------------

#: Contaminants that make a load unfit for RDF processing no matter what.
HARD_CONTAMINANTS = ("metal", "rock", "concrete", "tire", "e-waste")
#: Contaminants that require human review but are not automatically fatal.
#: Plastic film and textile are deliberately absent: they are the calorific
#: fraction of RDF, not a contaminant of it (the engine routes textile to
#: RDF, ``lynceus_engine/massbalance.py``; the benchmark labels clean
#: plastic, paper, cardboard and textile loads ``accept``).  The VLM may
#: still list them under ``light_contaminants``; that alone never escalates.
LIGHT_CONTAMINANTS = ("glass", "organic_residue", "wet_mix")
#: VLM confidence at/above which a hard-contaminant detection is trusted.
HARD_CONTAMINANT_CONFIDENCE = 0.6
#: VLM confidence below which the visual analysis is considered unsafe to act on.
UNSAFE_VLM_CONFIDENCE = 0.3
#: Allowed relative deviation between declared and weighed net weight
#: (fraction).  Beyond it the ticket is corrected, never the load rejected.
WEIGHT_TOLERANCE = 0.05
#: Older name of :data:`WEIGHT_TOLERANCE`, kept for callers that import it.
WEIGHT_MISMATCH_THRESHOLD = WEIGHT_TOLERANCE
#: Waybill photo read confidence below which the operator checks the fields.
WAYBILL_READ_MIN_CONFIDENCE = 0.6
#: Typed waybill text: a "dry" claim (below this) conflicts with a visibly
#: wet load at/above this visual moisture estimate (fraction, wet basis).
MOISTURE_CONFLICT_MARGIN = 0.15
#: Waybill moisture field: the load looks wetter than declared when the
#: visual estimate is at/above declared + this margin (fraction points).
MOISTURE_DECLARED_MARGIN = 0.15
#: Waybill arithmetic: |gross - tare - net| above this fraction of net fails.
ARITHMETIC_TOLERANCE = 0.01
#: Markers in the ``manifest_crosscheck`` reason, read by
#: :mod:`lynceus.actions` and :mod:`lynceus.checks` (one source of wording).
DECLARED_SORTED_MARKER = "declares sorted RDF"
MOISTURE_CONFLICT_MARKER = "Moisture conflict"
ARITHMETIC_MARKER = "Waybill arithmetic"
#: Marker in the ``detector_second_opinion`` reason when the detector did not
#: flag a hard contaminant the vision model confidently found.
DETECTOR_MISSED_MARKER = "Second look did not find it"
#: Wave-2 markers: a poor photo and a vision-vote split (``vlm_confidence``
#: reason), a plate mismatch (``weight_plausibility`` reason: the truck at
#: the weighbridge is not the one on the waybill).
PHOTO_QUALITY_MARKER = "Photo quality poor"
VOTE_SPLIT_MARKER = "Reads split"
PLATE_MISMATCH_MARKER = "Plate mismatch"
#: Load-type / remarks wording that declares processed (sorted) RDF.
_PROCESSED_RDF_RE = re.compile(
    r"\b(?:rdf|srf|fluff)\b|pemilahan|hasil proses", re.IGNORECASE
)
#: CH4 concentration above which a load is strongly anaerobic / spoiling
#: (ppmv above the bin).  Very high CH4 with a "dry" waybill claim means
#: the load is far wetter and older than declared.
GAS_CH4_ANAEROBIC_THRESHOLD_PPM = 100.0
#: Default detector thresholds (``config.Settings`` overrides them per call).
#: Picked on the val split, never on the test images (one source: config).
DETECTOR_HARD_CONFIDENCE = DEFAULT_DETECTOR_HARD_CONF
DETECTOR_LIGHT_CONFIDENCE = DEFAULT_DETECTOR_LIGHT_CONF
#: How reasons name the detector.
DETECTOR_NAME = "Detector (YOLO26m)"
#: Vision models with a benchmark run behind them (``config.Settings``
#: overrides this per call): a fallback model outside it cannot decide alone.
BENCHMARKED_VLM_MODELS: Tuple[str, ...] = ("MiniCPM-V-4.7-35B-A3B",)


def _gate(
    state: str,
    value: Optional[float] = None,
    threshold: Optional[float] = None,
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    """Build one stated gate result in the ``audit.GateResult`` shape."""
    return {"state": state, "value": value, "threshold": threshold, "reason": reason}


def _not_run(reason: str) -> Dict[str, Any]:
    return _gate(GateState.NOT_RUN, reason=reason)


def _find_terms(text: str, terms: Tuple[str, ...]) -> List[str]:
    """Whole-word scan of a lowercased blob for the given contaminant terms."""
    return [term for term in terms if re.search(rf"\b{re.escape(term)}\b", text)]


def _as_float(value: Any) -> Optional[float]:
    """Best-effort numeric coercion; anything non-finite/non-numeric is None."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _weight_mismatch_fraction(
    declared_kg: Optional[float], actual_kg: Optional[float]
) -> Optional[float]:
    """Relative deviation |actual - declared| / declared, None when unknowable."""
    if declared_kg is None or actual_kg is None:
        return None
    if declared_kg <= 0:
        return None
    return abs(actual_kg - declared_kg) / declared_kg


def _waybill_moisture_claim(text: str) -> Optional[float]:
    """Extract the declared moisture percentage from waybill free text.

    Looks for ``<number>%`` near the word "moisture" (case-insensitive);
    returns a wet-basis fraction, or None when the waybill states nothing.
    """
    if not text:
        return None
    for match in re.finditer(r"moisture[^0-9%]{0,24}?([0-9]+(?:\.[0-9]+)?)\s*%", text, re.IGNORECASE):
        pct = float(match.group(1))
        if 0.0 <= pct <= 100.0:
            return pct / 100.0
    return None


def _number(value: Any) -> Optional[float]:
    """A waybill field as a number: ints/floats, or a plain numeric string."""
    number = _as_float(value)
    if number is not None or not isinstance(value, str):
        return number
    try:
        return float(value.strip().rstrip("%").strip())
    except ValueError:
        return None


def _waybill_fields(inputs: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """The operator-confirmed waybill field values (``inputs["waybill_fields"]``)."""
    fields = (inputs or {}).get("waybill_fields")
    return dict(fields) if isinstance(fields, dict) else {}


def declares_processed_rdf(fields: Optional[Dict[str, Any]]) -> bool:
    """True when the waybill's load type or remarks declare processed RDF
    (RDF, SRF, fluff, "pemilahan" = sorting, "hasil proses" = processed)."""
    fields = fields if isinstance(fields, dict) else {}
    text = " ".join(str(fields.get(k) or "") for k in ("load_type", "remarks"))
    return bool(_PROCESSED_RDF_RE.search(text))


def declared_moisture_fraction(inputs: Optional[Dict[str, Any]]) -> Tuple[Optional[float], str]:
    """``(fraction, origin)`` of the declared moisture: the waybill field
    ``moisture_pct`` (origin ``"waybill"``), else the typed text's
    "moisture ... N %" (origin ``"text"``), else ``(None, "")``."""
    pct = _number(_waybill_fields(inputs).get("moisture_pct"))
    if pct is not None and 0.0 <= pct <= 100.0:
        return pct / 100.0, "waybill"
    claim = _waybill_moisture_claim(str((inputs or {}).get("manifest_text") or ""))
    return (claim, "text") if claim is not None else (None, "")


def light_contaminant_hits(vlm_result: Optional[Dict[str, Any]]) -> List[str]:
    """The light contaminants :func:`decide` escalates on, read from every
    value of the VLM's ``detected`` block (whole words, deduplicated, sorted)."""
    detected = (vlm_result or {}).get("detected") if isinstance(vlm_result, dict) else None
    if not isinstance(detected, dict):
        return []
    text = " ".join(str(part) for part in detected.values()).lower()
    return sorted(set(_find_terms(text, LIGHT_CONTAMINANTS)))


def confident_hard_contaminants(
    inputs: Optional[Dict[str, Any]],
    vlm_result: Optional[Dict[str, Any]],
    llm_result: Optional[Dict[str, Any]],
) -> List[str]:
    """Hard contaminants that make :func:`decide` reject, else ``[]``.

    Only allowlisted strings in ``detected.hard_contaminants`` count, trusted
    when VLM confidence is at/above ``HARD_CONTAMINANT_CONFIDENCE``. Prose in
    detections, manifests and cross-check notes is not evidence of presence.
    Returned sorted and de-duplicated.
    """
    vlm_result = vlm_result if isinstance(vlm_result, dict) else {}
    detected = vlm_result.get("detected")
    if not isinstance(detected, dict):
        return []
    contaminants = detected.get("hard_contaminants")
    if not isinstance(contaminants, list):
        return []
    hits = [
        item for item in contaminants
        if isinstance(item, str) and item in HARD_CONTAMINANTS
    ]
    confidence = _as_float(vlm_result.get("confidence"))
    if hits and confidence is not None and confidence >= HARD_CONTAMINANT_CONFIDENCE:
        return sorted(set(hits))
    return []


def _listed_hard(vlm_result: Optional[Dict[str, Any]]) -> List[str]:
    """Allowlisted hard contaminants the merged vision read lists (any confidence)."""
    detected = (vlm_result or {}).get("detected") if isinstance(vlm_result, dict) else None
    listed = detected.get("hard_contaminants") if isinstance(detected, dict) else None
    if not isinstance(listed, list):
        return []
    return sorted({n for n in listed if isinstance(n, str) and n in HARD_CONTAMINANTS})


def _votes(vlm_result: Optional[Dict[str, Any]]) -> List[set]:
    """Each vision read's allowlisted hard contaminants (``vlm_result["votes"]``)."""
    votes = (vlm_result or {}).get("votes") if isinstance(vlm_result, dict) else None
    if not isinstance(votes, list):
        return []
    out = []
    for vote in votes:
        if not isinstance(vote, dict):
            continue
        hard = vote.get("hard") if isinstance(vote.get("hard"), list) else []
        out.append({n for n in hard if isinstance(n, str) and n in HARD_CONTAMINANTS})
    return out


def vote_split(vlm_result: Optional[Dict[str, Any]]) -> Dict[str, Tuple[int, int]]:
    """Hard contaminants some vision reads saw but the merged read dropped:
    ``{name: (reads that saw it, reads)}``.  Needs two or more reads (R1)."""
    votes = _votes(vlm_result)
    if len(votes) < 2:
        return {}
    merged = set(_listed_hard(vlm_result))
    names = set().union(*votes) - merged
    return {name: (sum(name in v for v in votes), len(votes)) for name in sorted(names)}


def vote_agreement(vlm_result: Optional[Dict[str, Any]]) -> Optional[str]:
    """"Reads 3/3 agree" or "Reads split 1/3" (hard contaminants), else None
    with fewer than two reads.  An early majority whose third read came late
    or failed (``vlm_result["third_read"]``): "2 of 3 reads (third late)"."""
    votes = _votes(vlm_result)
    if len(votes) < 2:
        return None
    n = len(votes)
    counts = [sum(name in v for v in votes) for name in sorted(set().union(*votes))]
    disagree = [c for c in counts if 0 < c < n]
    if disagree:
        return f"Reads split {min(disagree)}/{n}"
    third = (vlm_result or {}).get("third_read")
    if n == 2 and third in ("late", "failed"):
        return f"2 of 3 reads (third {third})"
    return f"Reads {n}/{n} agree"


def _observations(inputs: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    obs = (inputs or {}).get("observations")
    return [o for o in obs if isinstance(o, dict)] if isinstance(obs, list) else []


def poor_image_notes(inputs: Optional[Dict[str, Any]]) -> List[str]:
    """Notes of the ``image_quality`` observations whose status is poor (R2)."""
    return [
        str(o.get("note") or "The image-quality check marked the photo poor.")
        for o in _observations(inputs)
        if o.get("kind") == "image_quality" and o.get("status") == "poor"
    ]


def _norm_plate(plate: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(plate or "").upper())


def plate_mismatch(inputs: Optional[Dict[str, Any]]) -> Optional[Tuple[str, str]]:
    """``(camera plate, waybill plate)`` when an ANPR ``plate`` observation
    disagrees with the waybill plate (spaces and case ignored), else None (R3)."""
    waybill_plate = str(_waybill_fields(inputs).get("plate") or "").strip()
    for obs in _observations(inputs):
        if obs.get("kind") != "plate":
            continue
        read = str(obs.get("value") or "").strip()
        differs = bool(read and waybill_plate) and _norm_plate(read) != _norm_plate(waybill_plate)
        if differs or (obs.get("status") == "mismatch" and read):
            return read, waybill_plate or "another plate"
    return None


def contract_moisture_spec_pct() -> float:
    """The contract's moisture spec (``contracts.SPECS``), 20 % without it."""
    try:
        from lynceus import contracts  # lazy: an optional module

        return float(contracts.DEFAULT_CONTRACT["specs"]["moisture_pct_max"])
    except Exception:  # absent or reshaped: the stated default
        return 20.0


#: The decision receipt's rules, in priority order: ``(id, rule, effect)``.
RULES: Tuple[Tuple[str, str, str], ...] = (
    ("inputs", "Photo, waybill and a vision read are present, or refuse", "refuse"),
    ("hard_contaminant",
     f"A hard contaminant seen at VLM confidence >= {HARD_CONTAMINANT_CONFIDENCE:.2f} rejects",
     "reject"),
    ("declared_sorted",
     "Waybill declares sorted RDF but a hard contaminant is seen: contract breach", "reject"),
    ("unbenchmarked_model",
     "A fallback vision model without a benchmark run cannot accept or reject", "hold"),
    ("plate_mismatch", "The ANPR plate must match the waybill plate", "hold"),
    ("image_quality", "A poor photo (blur, exposure, size) is retaken", "hold"),
    ("vlm_confidence",
     f"VLM confidence below {UNSAFE_VLM_CONFIDENCE:.2f}: retake the photo", "hold"),
    ("vote_split", "A hard item seen by only some vision reads is checked by hand", "hold"),
    ("weight_tolerance",
     f"Scale within {WEIGHT_TOLERANCE:.0%} of the waybill net, else ticket correction", "hold"),
    ("waybill_read",
     f"Waybill read confidence >= {WAYBILL_READ_MIN_CONFIDENCE:.2f}, else check the fields",
     "hold"),
    ("moisture_declared",
     "The load looks no wetter than declared (+15 points), else grab sample", "hold"),
    ("arithmetic",
     f"Gross - tare = net within {ARITHMETIC_TOLERANCE:.0%}, else correct the ticket", "hold"),
    ("light_contaminant", "Glass, organic residue or a wet mix go to the pre-sort line", "hold"),
    ("detector", "An unconfirmed second-look finding holds the truck", "hold"),
    ("moisture_spec",
     "Declared moisture above the contract spec: sample to settle the price", "none"),
    ("engine_actionable", "The engine must give an actionable route, or refuse", "refuse"),
    ("engine_tie", "Tied engine routes are held for the supervisor", "hold"),
    ("accept", "Nothing above fired: accept", "accept"),
)


def _receipt(evidence: Dict[str, Tuple[bool, str]]) -> List[Dict[str, Any]]:
    """The receipt rows from ``{rule id: (fired, evidence)}``."""
    rows = []
    for rule_id, rule, effect in RULES:
        fired, text = evidence[rule_id]
        rows.append({
            "id": rule_id,
            "rule": rule,
            "fired": bool(fired),
            "evidence": text,
            "effect": effect if fired else "none",
        })
    return rows


def _findings_text(findings: Dict[str, float]) -> str:
    return ", ".join(f"{name} ({conf:.2f})" for name, conf in sorted(findings.items()))


def _top_finding(
    hard: Dict[str, float], light: Dict[str, float], hard_conf: float, light_conf: float
) -> Tuple[Optional[float], float]:
    """``(value, threshold)`` for a detector gate: the highest finding and the
    threshold of its own class (hard or light), so the two share a unit.
    Nothing found: ``(None, hard_conf)``."""
    best = max(
        [(conf, hard_conf) for conf in hard.values()]
        + [(conf, light_conf) for conf in light.values()],
        default=None,
    )
    return (None, hard_conf) if best is None else best


_NO_WAYBILL_PHOTO = "No waybill photo; fields typed by the operator."
_NO_GAS_SENSOR = "No gas sensor at this gate."

#: Appended to a failed detector gate's reason once the verdict is known.
_DETECTOR_HELD = " The truck is held for a manual check."
_DETECTOR_OUTRANKED = (
    " Not acted on: the load is rejected on other grounds, which outrank a "
    "detector finding."
)


def _missing_mandatory(inputs: Dict[str, Any]) -> List[str]:
    """The mandatory inputs (photo, manifest) the payload lacks."""
    photo_present = bool(
        inputs.get("photo_base64")
        or inputs.get("photo")
        or inputs.get("photo_filename")
        or inputs.get("demo_case")
    )
    missing = [] if photo_present else ["photo"]
    if not str(inputs.get("manifest_text") or "").strip():
        missing.append("manifest_text")
    return missing


def _detector_second_opinion(
    detector_result: Optional[Dict[str, Any]],
    confirmed_hard: List[str],
    confirmed_light: List[str],
    hard_conf: float,
    light_conf: float,
    escalate_light: bool,
) -> Tuple[Dict[str, Any], List[str]]:
    """The ``detector_second_opinion`` gate and its escalate reasons.

    The gate fails when the detector flags a contaminant the VLM did not
    confirm (a hard one not in the VLM's confident list; a light one the VLM
    did not report, only while ``escalate_light`` is on).  Agreement, or
    nothing flagged, passes.  The detector never produces a reject.  A failed
    gate's reason states the finding only; :func:`decide` appends what came
    of it once the verdict is known (held, or outranked by a reject).
    """
    if not isinstance(detector_result, dict):
        return (
            _not_run("Detector second opinion did not run (disabled, no photo, or "
                     "an image it could not read)."),
            [],
        )
    hard, light = cv_detector.flagged(detector_result, hard_conf, light_conf)
    unconfirmed_hard = {k: v for k, v in hard.items() if k not in confirmed_hard}
    unconfirmed_light = {k: v for k, v in light.items() if k not in confirmed_light}
    findings = [
        f"{DETECTOR_NAME} flagged {name} ({conf:.2f}) that the vision model did not confirm"
        for name, conf in sorted(unconfirmed_hard.items())
    ]
    if escalate_light:
        findings += [
            f"{DETECTOR_NAME} flagged {name} ({conf:.2f}) that the vision model did not report"
            for name, conf in sorted(unconfirmed_light.items())
        ]
    if findings:
        value, threshold = _top_finding(
            unconfirmed_hard, unconfirmed_light if escalate_light else {}, hard_conf, light_conf
        )
        return (
            _gate(
                GateState.FAILED,
                value=value,
                threshold=threshold,
                reason=" ".join(f"{f}." for f in findings),
            ),
            [f"{f}; hold for a manual check." for f in findings],
        )
    found = {**hard, **light}
    missed = [name for name in confirmed_hard if name not in hard]
    if missed:
        # The detector is a second opinion, never a veto: a confident vision
        # finding it did not see stands (it is trained on close-ups).
        reason = (
            f"{DETECTOR_MISSED_MARKER}; the vision finding stands (the detector is "
            f"trained on close-ups, not truck beds). {DETECTOR_NAME} did not flag "
            f"{', '.join(missed)}."
        )
    elif unconfirmed_light:  # escalate_light is off
        reason = (
            f"{DETECTOR_NAME} flagged {_findings_text(unconfirmed_light)} that the vision "
            "model did not report; light detector findings are set not to escalate."
        )
    elif found:
        reason = f"{DETECTOR_NAME} findings agree with the vision model: {_findings_text(found)}."
    else:
        reason = (
            f"{DETECTOR_NAME} found no hard contaminant at/above {hard_conf:.2f} and no "
            f"light one at/above {light_conf:.2f}."
        )
    value, threshold = _top_finding(hard, light, hard_conf, light_conf)
    return (
        _gate(GateState.PASSED, value=value, threshold=threshold, reason=reason),
        [],
    )


def decide_degraded(
    detector_result: Dict[str, Any],
    failure: str,
    *,
    detector_hard_conf: float = DETECTOR_HARD_CONFIDENCE,
    detector_light_conf: float = DETECTOR_LIGHT_CONFIDENCE,
    vision_label: str = "AMD vision model",
    inputs: Optional[Dict[str, Any]] = None,
    failed_stage: str = "vlm",
) -> Tuple[str, Dict[str, Any], List[str]]:
    """Verdict when a live model call failed but the detector answered.

    ``escalate_human``: one CPU detector trained on RealWaste and TACO photos may hold
    a truck for a human, never clear or reject it on its own.  The reasons
    say which live call failed (``failed_stage``: ``"vlm"``, the vision
    model; ``"llm"``, the waybill model, whose vision answer is then
    discarded unfused) and list what the detector saw; every AI-dependent
    gate is stated ``not_run``, and a detector that flagged nothing is
    ``not_evaluated`` (with no vision answer to compare against, silence is
    no clearance).  When ``inputs`` lacks a mandatory input (photo,
    manifest) the verdict is ``refuse_insufficient_input`` instead, exactly
    as :func:`decide` refuses (``gates["missing"]`` lists them): never an
    accept or a reject.
    """
    hard, light = cv_detector.flagged(detector_result, detector_hard_conf, detector_light_conf)
    unavailable = (
        f"The waybill model was unavailable ({failure}); the vision answer was not "
        "fused and is discarded."
        if failed_stage == "llm"
        else f"The {vision_label} was unavailable ({failure})."
    )
    missing = _missing_mandatory(dict(inputs)) if inputs is not None else []
    gates: Dict[str, Any]
    if missing:
        gates = {
            "vlm_confidence": _not_run(unavailable),
            "ocr_confidence": _not_run("Manifest analysis not run: input incomplete."),
            "manifest_crosscheck": _not_run("Cross-check not run: input incomplete."),
            "gas_plausibility": _not_run("Gas readings not part of this inspection."),
            "weight_plausibility": _not_run("Weight not evaluated: input incomplete."),
            "detector_second_opinion": _gate(
                GateState.NOT_EVALUATED,
                reason="Detector second opinion not evaluated: input incomplete.",
            ),
            "missing": missing,
        }
        return (
            Decision.REFUSE_INSUFFICIENT_INPUT,
            gates,
            [
                f"Mandatory input missing: {name}. The inspection cannot proceed without it."
                for name in missing
            ],
        )
    found = {**hard, **light}
    value, threshold = _top_finding(hard, light, detector_hard_conf, detector_light_conf)
    gates = {
        "vlm_confidence": _not_run(unavailable),
        "ocr_confidence": _not_run("Manifest analysis not run: live AI unavailable."),
        "manifest_crosscheck": _not_run("Cross-check not run: live AI unavailable."),
        "gas_plausibility": _not_run("Not evaluated in detector-only degraded mode."),
        "weight_plausibility": _not_run("Not evaluated in detector-only degraded mode."),
        "detector_second_opinion": _gate(
            GateState.FAILED if found else GateState.NOT_EVALUATED,
            value=value,
            threshold=threshold,
            reason=(
                f"Detector-only mode: {DETECTOR_NAME} flagged {_findings_text(found)}."
                if found
                else f"Detector-only mode: {DETECTOR_NAME} flagged nothing at/above "
                "its thresholds; with no vision answer to compare against, that is "
                "not a clearance."
            ),
        ),
    }
    reasons = [unavailable + " The truck is held for a human inspector."]
    if hard:
        reasons.append(f"{DETECTOR_NAME} flagged hard contamination: {_findings_text(hard)}.")
    if light:
        reasons.append(f"{DETECTOR_NAME} flagged light contamination: {_findings_text(light)}.")
    if not found:
        reasons.append(
            f"{DETECTOR_NAME} flagged no contaminant at/above its thresholds; the "
            "detector alone cannot clear a load."
        )
    reasons.append("Detector-only degraded mode never accepts or rejects a load.")
    return Decision.ESCALATE_HUMAN, gates, reasons


# ---------------------------------------------------------------------------
# The fusion layer
# ---------------------------------------------------------------------------


def decide(
    inputs: Dict[str, Any],
    vlm_result: Optional[Dict[str, Any]],
    llm_result: Optional[Dict[str, Any]],
    engine_result: Optional[Dict[str, Any]],
    detector_result: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> Tuple[str, Dict[str, Any], List[str]]:
    """Fuse all pipeline outputs into ``(verdict, gates, reasons)``.

    The keyword arguments are those of :func:`_fuse` (detector thresholds,
    light escalation, the benchmarked vision models).
    """
    verdict, gates, reasons, _ = _fuse(
        inputs, vlm_result, llm_result, engine_result, detector_result, **kwargs
    )
    return verdict, gates, reasons


def rule_trace(
    inputs: Dict[str, Any],
    vlm_result: Optional[Dict[str, Any]],
    llm_result: Optional[Dict[str, Any]],
    engine_result: Optional[Dict[str, Any]],
    detector_result: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> List[Dict[str, Any]]:
    """The decision receipt: every rule of :func:`decide`, in priority order.

    Each entry is ``{"id", "rule", "fired", "evidence", "effect"}``; ``effect``
    is what the rule does when it fires (``refuse``, ``reject``, ``hold``,
    ``accept``) and ``none`` when it did not fire (or, like ``moisture_spec``,
    never moves the verdict).  Pure: the same inputs and keyword arguments as
    :func:`decide` give the same receipt.
    """
    return _fuse(inputs, vlm_result, llm_result, engine_result, detector_result, **kwargs)[3]


def _fuse(
    inputs: Dict[str, Any],
    vlm_result: Optional[Dict[str, Any]],
    llm_result: Optional[Dict[str, Any]],
    engine_result: Optional[Dict[str, Any]],
    detector_result: Optional[Dict[str, Any]] = None,
    *,
    detector_hard_conf: float = DETECTOR_HARD_CONFIDENCE,
    detector_light_conf: float = DETECTOR_LIGHT_CONFIDENCE,
    detector_escalate_light: bool = True,
    benchmarked_vlm_models: Sequence[str] = BENCHMARKED_VLM_MODELS,
) -> Tuple[str, Dict[str, Any], List[str], List[Dict[str, Any]]]:
    """``(verdict, gates, reasons, receipt)``: :func:`decide` plus its receipt.

    A VLM result that came from a fallback model (non-empty
    ``fallback_from``) whose ``model`` is not in ``benchmarked_vlm_models``
    may hold a load but never accept or reject it: either becomes
    ``escalate_human`` with a reason naming the model.

    Args:
        inputs: The inspection payload dict (``truck_id``, ``photo_base64``,
            ``manifest_text``, ``weight_kg``, ``declared_weight_kg``, ...).
            All keys optional at this layer; absence feeds the refuse logic.
        vlm_result: ``ai_clients.vlm(photo)`` output — must contain
            ``detected`` (dict) and ``confidence`` (float 0..1); ``None``
            means the VLM call failed outright, and a result without a
            numeric ``confidence`` is refused the same way.
        llm_result: ``ai_clients.llm(manifest_text, context)`` output with
            ``reasoning`` / ``confidence`` / optional ``crosscheck``.
        engine_result: ``engine_adapter.run_assessment`` output dict, or None
            when the engine was unavailable.
        detector_result: :func:`lynceus.detector.detect` output, or None when
            the detector did not run (gate ``detector_second_opinion`` then
            says ``not_run``).  Its thresholds and the light-escalation
            switch come from the keyword arguments.

        ``gas_plausibility``, ``weight_plausibility``) and ``reasons`` is a
        list of human-readable English sentences for the demo UI.

    The ``missing`` list for a ``refuse_insufficient_input`` verdict is
    exposed through the ``missing`` key appended to the returned gates dict
    (``gates["missing"]``) so callers can route it into
    ``engine_outputs.recommendation.missing``.
    """
    inputs = dict(inputs or {})
    vlm_result = dict(vlm_result) if isinstance(vlm_result, dict) else None
    llm_result = dict(llm_result) if isinstance(llm_result, dict) else None
    engine_result = dict(engine_result) if isinstance(engine_result, dict) else None

    reasons: List[str] = []
    missing: List[str] = []

    # ----- Mandatory input presence (refuse-to-answer, pattern 14) --------
    photo_present = bool(
        inputs.get("photo_base64")
        or inputs.get("photo")
        or inputs.get("photo_filename")
        or inputs.get("demo_case")
    )
    manifest_text = inputs.get("manifest_text") or ""
    manifest_present = bool(manifest_text.strip())

    vlm_detected: Dict[str, Any] = (vlm_result or {}).get("detected") or {}
    vlm_confidence = _as_float((vlm_result or {}).get("confidence"))

    if not photo_present:
        missing.append("photo")
    # A VLM answer without a numeric confidence is no answer: it could
    # otherwise slip past every confidence rule into an accept.
    if vlm_result is None or vlm_confidence is None:
        missing.append("vlm_result")
    if not manifest_present:
        missing.append("manifest_text")

    if missing:
        # Even the gates stay honest: a gate that could not run says so.
        gates = {
            "vlm_confidence": _not_run("VLM analysis could not be completed."),
            "ocr_confidence": _gate(
                GateState.NOT_EVALUATED,
                value=_as_float(inputs["waybill_read"].get("confidence")),
                threshold=WAYBILL_READ_MIN_CONFIDENCE,
                reason="Waybill read not evaluated: input incomplete.",
            )
            if isinstance(inputs.get("waybill_read"), dict)
            else _not_run(_NO_WAYBILL_PHOTO),
            "manifest_crosscheck": _not_run("Cross-check not run: input incomplete."),
            "gas_plausibility": _not_run("Gas readings not part of this inspection."),
            "weight_plausibility": _not_run("Weight not evaluated: input incomplete."),
            "detector_second_opinion": _gate(
                GateState.NOT_EVALUATED,
                reason="Detector second opinion not evaluated: input incomplete.",
            )
            if isinstance(detector_result, dict)
            else _not_run("Detector second opinion did not run."),
            "missing": missing,
        }
        reasons = [
            f"Mandatory input missing: {name}. The inspection cannot proceed without it."
            for name in missing
        ]
        skipped = (False, "Not evaluated: input incomplete.")
        evidence = {rule_id: skipped for rule_id, _, _ in RULES}
        evidence["inputs"] = (True, f"Missing: {', '.join(missing)}.")
        return Decision.REFUSE_INSUFFICIENT_INPUT, gates, reasons, _receipt(evidence)

    # ----- Weight plausibility (a ticket problem, never a reject) ----------
    fields = _waybill_fields(inputs)
    declared_weight_kg = _as_float(inputs.get("declared_weight_kg"))
    if declared_weight_kg is None:
        declared_weight_kg = _number(fields.get("net_kg"))
    actual_weight_kg = _as_float(inputs.get("weight_kg"))

    # A typed waybill may state a declared weight when the caller did not
    # supply one (e.g. "Declared weight: 18,400 kg").
    if declared_weight_kg is None and manifest_text:
        for match in re.finditer(
            r"declared(?:\s+weight)?[^0-9]{0,24}?([0-9][0-9,\.]*)\s*kg",
            manifest_text,
            re.IGNORECASE,
        ):
            try:
                candidate = float(match.group(1).replace(",", ""))
            except ValueError:
                continue
            if candidate > 0:
                declared_weight_kg = candidate
                break
    weight_mismatch = _weight_mismatch_fraction(declared_weight_kg, actual_weight_kg)
    weight_off = weight_mismatch is not None and weight_mismatch > WEIGHT_TOLERANCE

    if actual_weight_kg is None:
        weight_gate = _not_run("No weighbridge weight supplied.")
    elif weight_mismatch is None or declared_weight_kg is None:
        weight_gate = _gate(
            GateState.NOT_EVALUATED,
            threshold=WEIGHT_TOLERANCE,
            reason="No declared weight available for comparison.",
        )
    else:
        signed = (actual_weight_kg - declared_weight_kg) / declared_weight_kg
        weight_gate = _gate(
            GateState.FAILED if weight_off else GateState.PASSED,
            value=weight_mismatch,
            threshold=WEIGHT_TOLERANCE,
            reason=(
                f"Weighbridge {actual_weight_kg:,.0f} kg is {signed:+.1%} from the declared "
                f"{declared_weight_kg:,.0f} kg (tolerance {WEIGHT_TOLERANCE:.0%}): "
                + (
                    "ticket correction: re-weigh or correct the waybill."
                    if weight_off
                    else "within tolerance."
                )
            ),
        )

    weight_evidence = str(weight_gate.get("reason") or "No weighbridge weight.")

    # ----- Plate (ANPR) vs waybill: a wrong truck is held (R3) -------------
    plate = plate_mismatch(inputs)
    plate_reason = (
        f"{PLATE_MISMATCH_MARKER}: the camera reads {plate[0]}, the waybill says "
        f"{plate[1]}; verify the truck."
        if plate
        else None
    )
    if plate_reason:
        prior = weight_gate.get("reason")
        weight_gate = dict(weight_gate, state=GateState.FAILED)
        weight_gate["reason"] = plate_reason + (f" {prior}" if prior else "")

    # ----- VLM confidence gate (unreadable or poor photo: retake, R2) -----
    assert vlm_confidence is not None  # refused above, kept for type checkers
    unreadable = vlm_confidence < UNSAFE_VLM_CONFIDENCE
    poor_photo = poor_image_notes(inputs)
    vlm_reason = (
        f"VLM confidence {vlm_confidence:.2f} is below the safe minimum of "
        f"{UNSAFE_VLM_CONFIDENCE:.2f}: photo unreadable, retake it."
        if unreadable
        else f"VLM confidence {vlm_confidence:.2f} is within the safe range."
    )
    if poor_photo:
        vlm_reason = f"{PHOTO_QUALITY_MARKER}: {' '.join(poor_photo)} " + vlm_reason
    # ----- Contamination scan (hard: shared helper; light: VLM detections) --
    light_hits = light_contaminant_hits(vlm_result)
    confident_hard = confident_hard_contaminants(inputs, vlm_result, llm_result)
    # A hard item some vision reads saw but the majority dropped (R1).
    split = vote_split(vlm_result)
    if split:
        vlm_reason += f" {VOTE_SPLIT_MARKER}: " + "; ".join(
            f"{seen} of {of} saw {name}" for name, (seen, of) in sorted(split.items())
        ) + "."
    vlm_gate = _gate(
        GateState.FAILED if unreadable or poor_photo else GateState.PASSED,
        value=vlm_confidence,
        threshold=UNSAFE_VLM_CONFIDENCE,
        reason=vlm_reason,
    )

    # ----- Waybill read gate (the waybill photo read's own confidence) ------
    waybill_read = inputs.get("waybill_read")
    read_confidence: Optional[float] = None
    read_uncertain = False
    if not isinstance(waybill_read, dict):
        ocr_gate = _not_run(_NO_WAYBILL_PHOTO)
    else:
        read_confidence = _as_float(waybill_read.get("confidence"))
        edited = [str(f) for f in waybill_read.get("edited_fields") or [] if str(f).strip()]
        edited_note = f" Operator edited: {', '.join(edited)}." if edited else ""
        if read_confidence is None:
            ocr_gate = _gate(
                GateState.NOT_EVALUATED,
                threshold=WAYBILL_READ_MIN_CONFIDENCE,
                reason="The waybill read carries no confidence." + edited_note,
            )
        else:
            read_uncertain = read_confidence < WAYBILL_READ_MIN_CONFIDENCE
            ocr_gate = _gate(
                GateState.FAILED if read_uncertain else GateState.PASSED,
                value=read_confidence,
                threshold=WAYBILL_READ_MIN_CONFIDENCE,
                reason=(
                    f"Waybill read confidence {read_confidence:.2f} is below "
                    f"{WAYBILL_READ_MIN_CONFIDENCE:.2f}: check the fields."
                    if read_uncertain
                    else f"Waybill read confidence {read_confidence:.2f}."
                )
                + edited_note,
            )

    # ----- Declaration check ("Waybill vs load"), deterministic -----------
    # The LLM's own crosscheck_failed no longer moves anything: its notes
    # stay in the audit as a narrative.
    declared_sorted = declares_processed_rdf(fields)
    moisture_claim, moisture_origin = declared_moisture_fraction(inputs)
    visual_moisture = _as_float(vlm_detected.get("moisture"))
    moisture_conflict: Optional[bool] = None  # None: nothing to compare
    if moisture_claim is not None and visual_moisture is not None:
        if moisture_origin == "waybill":
            moisture_conflict = (
                round(visual_moisture - moisture_claim, 6) >= MOISTURE_DECLARED_MARGIN
            )
        else:  # typed text: the original dry-claim rule
            moisture_conflict = (
                moisture_claim < MOISTURE_CONFLICT_MARGIN
                and visual_moisture >= MOISTURE_CONFLICT_MARGIN
            )
    gross, tare, net = (_number(fields.get(k)) for k in ("gross_kg", "tare_kg", "net_kg"))
    arithmetic_gap: Optional[float] = None
    if gross is not None and tare is not None and net is not None and net > 0:
        arithmetic_gap = abs(gross - tare - net)
    arithmetic_off = arithmetic_gap is not None and net is not None and (
        arithmetic_gap > ARITHMETIC_TOLERANCE * net
    )

    cross_failed: List[str] = []
    cross_matched: List[str] = []
    if declared_sorted:
        declared_as = str(fields.get("load_type") or "").strip() or "per the remarks"
        if confident_hard:
            cross_failed.append(
                f"Waybill {DECLARED_SORTED_MARKER} ({declared_as}); the camera sees "
                f"{', '.join(confident_hard)}."
            )
        else:
            cross_matched.append(f"declared sorted RDF ({declared_as}), no hard contaminant seen")
    if moisture_conflict:
        assert moisture_claim is not None and visual_moisture is not None
        cross_failed.append(
            f"{MOISTURE_CONFLICT_MARKER}: the waybill declares {moisture_claim:.0%} moisture "
            f"but the load looks like {visual_moisture:.0%}."
            if moisture_origin == "waybill"
            else f"{MOISTURE_CONFLICT_MARKER}: the waybill declares a dry load "
            f"(<{MOISTURE_CONFLICT_MARGIN:.0%}) but the visual analysis estimates "
            f"{visual_moisture:.0%} moisture."
        )
    elif moisture_conflict is False:
        assert moisture_claim is not None and visual_moisture is not None
        cross_matched.append(
            f"declared moisture {moisture_claim:.0%}, the load looks like {visual_moisture:.0%}"
        )
    if arithmetic_off:
        assert gross is not None and tare is not None and net is not None
        cross_failed.append(
            f"{ARITHMETIC_MARKER}: gross {gross:,.0f} - tare {tare:,.0f} = "
            f"{gross - tare:,.0f} kg, but the waybill net says {net:,.0f} kg."
        )
    elif arithmetic_gap is not None:
        cross_matched.append("gross - tare = net")

    if cross_failed:
        manifest_gate = _gate(GateState.FAILED, reason=" ".join(cross_failed))
    elif cross_matched:
        manifest_gate = _gate(
            GateState.PASSED,
            reason="Waybill declarations match the load: " + "; ".join(cross_matched) + ".",
        )
    else:
        manifest_gate = _gate(
            GateState.NOT_EVALUATED,
            reason="Nothing declared on the waybill to compare with the load "
            "(no load type, moisture or weight breakdown).",
        )

    # ----- Gas plausibility (a live gate sensor only, supporting) ----------
    # The gas channel corroborates or contradicts the waybill's moisture /
    # age claims but never overrides the verdict.  Only a live sensor's
    # measurement counts: a simulated reading is no evidence about this load.
    gas_input = inputs.get("gas")
    gas_input = dict(gas_input) if isinstance(gas_input, dict) else {}
    readings = gas_input.get("readings_ppm")
    if gas_input.get("source") != LIVE_GAS_SOURCE or not isinstance(readings, dict) or not readings:
        gas_gate = _not_run(_NO_GAS_SENSOR)
    else:
        ch4_ppm = _as_float(readings.get("ch4"))
        if ch4_ppm is None:
            gas_gate = _not_run("No CH4 reading from the gate gas sensor.")
        elif ch4_ppm > GAS_CH4_ANAEROBIC_THRESHOLD_PPM:
            # High CH4 means a strongly anaerobic, spoiling load.  It only
            # contradicts the waybill when the load is claimed dry (the
            # same <15 % boundary the typed-text moisture conflict uses); a
            # declared or supplied wet mix explains the reading.
            claimed_moisture = _waybill_moisture_claim(manifest_text)
            supplied_moisture = _as_float(inputs.get("moisture"))
            dry_claimed = claimed_moisture is not None and claimed_moisture < MOISTURE_CONFLICT_MARGIN
            dry_supplied = supplied_moisture is not None and supplied_moisture < MOISTURE_CONFLICT_MARGIN
            if dry_claimed or (dry_supplied and claimed_moisture is None):
                gas_gate = _gate(
                    GateState.FAILED,
                    value=ch4_ppm,
                    threshold=GAS_CH4_ANAEROBIC_THRESHOLD_PPM,
                    reason=(
                        f"CH4 reading {ch4_ppm:.0f} ppm exceeds "
                        f"{GAS_CH4_ANAEROBIC_THRESHOLD_PPM:.0f} ppm: the load is strongly "
                        "anaerobic / spoiling, conflicting with the dry-load claim."
                    ),
                )
            else:
                gas_gate = _gate(
                    GateState.PASSED,
                    value=ch4_ppm,
                    threshold=GAS_CH4_ANAEROBIC_THRESHOLD_PPM,
                    reason=(
                        f"CH4 reading {ch4_ppm:.0f} ppm indicates an anaerobic load, "
                        "consistent with the claimed moisture and age of the load."
                    ),
                )
        else:
            gas_gate = _gate(
                GateState.PASSED,
                value=ch4_ppm,
                threshold=GAS_CH4_ANAEROBIC_THRESHOLD_PPM,
                reason=(
                    f"CH4 reading {ch4_ppm:.0f} ppm is consistent with the claimed "
                    "moisture and age of the load."
                ),
            )

    detector_gate, detector_reasons = _detector_second_opinion(
        detector_result,
        confident_hard,
        light_hits,
        detector_hard_conf,
        detector_light_conf,
        detector_escalate_light,
    )

    gates: Dict[str, Any] = {
        "vlm_confidence": vlm_gate,
        "ocr_confidence": ocr_gate,
        "manifest_crosscheck": manifest_gate,
        "gas_plausibility": gas_gate,
        "weight_plausibility": weight_gate,
        "detector_second_opinion": detector_gate,
    }

    # ----- Verdict fusion (priority: refuse > reject > escalate > accept) --
    # Only a confident hard contaminant rejects.
    if confident_hard:
        reasons.append(
            f"Hard contamination detected in the load: {', '.join(confident_hard)} "
            f"(VLM confidence {vlm_confidence:.2f})."
        )
        if declared_sorted:
            reasons.append(
                "Contract breach: the waybill declares sorted RDF but the load carries "
                f"{', '.join(confident_hard)}; issue a supplier notice."
            )

    # A fallback vision model with no benchmark run behind it may hold a
    # load, never decide one: its would-be accept or reject is escalated.
    fallback_from = (vlm_result or {}).get("fallback_from")
    answered_by = str((vlm_result or {}).get("model") or "unknown")
    unbenchmarked = (
        f"The photo was read by {answered_by}, a fallback vision model with no "
        "benchmark run behind it (failed first: "
        f"{'; '.join(str(f) for f in fallback_from)}). An unbenchmarked model cannot "
        "accept or reject a load on its own; hold for a manual check."
        if fallback_from and answered_by not in benchmarked_vlm_models
        else None
    )

    # Amber flags → escalate (a person looks; never a reject)
    escalate_reasons: List[str] = []
    if plate_reason:
        escalate_reasons.append(plate_reason)
    if poor_photo:
        escalate_reasons.append(
            f"{PHOTO_QUALITY_MARKER}: {' '.join(poor_photo)} Retake the photo."
        )
    if unreadable:
        escalate_reasons.append(
            f"Photo unreadable: VLM confidence {vlm_confidence:.2f} is below the safe "
            f"minimum of {UNSAFE_VLM_CONFIDENCE:.2f}; retake the photo."
        )
    for name, (seen, of) in sorted(split.items()):
        escalate_reasons.append(f"{seen} of {of} vision reads saw {name}: check by hand.")
    if weight_off:
        assert declared_weight_kg is not None and actual_weight_kg is not None
        escalate_reasons.append(
            f"Ticket correction: the weighbridge reads {actual_weight_kg:,.0f} kg against a "
            f"declared {declared_weight_kg:,.0f} kg "
            f"({(actual_weight_kg - declared_weight_kg) / declared_weight_kg:+.1%}, tolerance "
            f"{WEIGHT_TOLERANCE:.0%}); re-weigh or correct the waybill."
        )
    if read_uncertain:
        assert read_confidence is not None
        escalate_reasons.append(
            f"Waybill read uncertain (confidence {read_confidence:.2f}): check the fields."
        )
    if moisture_conflict:
        assert moisture_claim is not None
        escalate_reasons.append(
            f"Load looks wetter than the declared {moisture_claim:.0%}: take a grab sample."
            if moisture_origin == "waybill"
            else "The visual moisture estimate conflicts with the waybill's dry claim."
        )
    if arithmetic_off:
        escalate_reasons.append(
            "Waybill arithmetic does not add up (gross - tare differs from net by more "
            f"than {ARITHMETIC_TOLERANCE:.0%}): correct the ticket."
        )
    if light_hits:
        escalate_reasons.append(
            f"Light or ambiguous contamination detected: {', '.join(light_hits)}."
        )
    # The detector's unconfirmed findings: never a reject, never an accept.
    escalate_reasons.extend(detector_reasons)

    recommendation = (engine_result or {}).get("recommendation") or {}
    engine_unusable = bool(
        recommendation.get("insufficient") or not recommendation.get("actionable", True)
    )
    engine_tied = bool(recommendation.get("tied"))

    if reasons:  # a confident hard contaminant → reject
        if unbenchmarked:
            if detector_reasons:
                detector_gate["reason"] += _DETECTOR_HELD
            verdict, out = Decision.ESCALATE_HUMAN, [unbenchmarked, *reasons, *detector_reasons]
        else:
            if detector_reasons:  # the gate failed, but the reject outranks it
                detector_gate["reason"] += _DETECTOR_OUTRANKED
            verdict, out = Decision.REJECT, reasons
    elif escalate_reasons:
        if detector_reasons:
            detector_gate["reason"] += _DETECTOR_HELD
        verdict, out = Decision.ESCALATE_HUMAN, escalate_reasons
    elif engine_unusable:
        # Engine actionability (engine refuse-to-answer, pattern 14)
        out = [
            "The engine recommendation is not actionable: "
            + str(recommendation.get("headline") or "insufficient data for routing.")
        ]
        out += [f"Engine missing input: {item}." for item in recommendation.get("missing") or []]
        verdict = Decision.REFUSE_INSUFFICIENT_INPUT
    elif engine_tied:
        # A tied engine ranking cannot pick a route, so a clean load is not
        # waved through: the audit route is hold_for_review and the verdict
        # must say the same (reject/refuse above keep their precedence).
        verdict, out = Decision.ESCALATE_HUMAN, [
            "Engine routes tied within 0.02; hold for supervisor review."
        ]
    elif unbenchmarked:
        verdict, out = Decision.ESCALATE_HUMAN, [unbenchmarked]
    else:
        verdict, out = Decision.ACCEPT, [
            (
                "No red flags: no hard contamination, weight within tolerance, VLM confidence "
                "in the safe range, and the engine recommendation is actionable "
                f"(route: {recommendation.get('route', Route.HOLD_FOR_REVIEW)})."
            )
        ]

    # ----- Decision receipt: every rule, in priority order ----------------
    listed_hard = _listed_hard(vlm_result)
    spec_pct = contract_moisture_spec_pct()
    declared_pct = None if moisture_claim is None else round(moisture_claim * 100.0, 6)
    above_spec = declared_pct is not None and declared_pct > spec_pct
    observations = _observations(inputs)
    agreement = vote_agreement(vlm_result)
    evidence: Dict[str, Tuple[bool, str]] = {
        "inputs": (False, "Photo, waybill text and a vision read with a confidence are present."),
        "hard_contaminant": (
            bool(confident_hard),
            f"{', '.join(confident_hard)} at VLM confidence {vlm_confidence:.2f} "
            f"(bar {HARD_CONTAMINANT_CONFIDENCE:.2f})."
            if confident_hard
            else f"{', '.join(listed_hard)} listed at VLM confidence {vlm_confidence:.2f}, "
            f"below the {HARD_CONTAMINANT_CONFIDENCE:.2f} bar."
            if listed_hard
            else "No hard contaminant in the vision read.",
        ),
        "declared_sorted": (
            bool(declared_sorted and confident_hard),
            (
                f"Waybill declares sorted RDF ({fields.get('load_type') or 'per the remarks'}); "
                + ("a hard contaminant is seen." if confident_hard else "nothing hard seen.")
            )
            if declared_sorted
            else "The waybill does not declare sorted RDF.",
        ),
        "unbenchmarked_model": (
            bool(unbenchmarked),
            unbenchmarked or f"Read by {answered_by}.",
        ),
        "plate_mismatch": (
            bool(plate_reason),
            plate_reason
            or (
                "The ANPR plate matches the waybill."
                if any(o.get("kind") == "plate" for o in observations)
                else "No ANPR plate reading."
            ),
        ),
        "image_quality": (
            bool(poor_photo),
            " ".join(poor_photo)
            if poor_photo
            else "Image quality ok."
            if any(o.get("kind") == "image_quality" for o in observations)
            else "No image-quality observation.",
        ),
        "vlm_confidence": (
            unreadable,
            f"VLM confidence {vlm_confidence:.2f} (minimum {UNSAFE_VLM_CONFIDENCE:.2f}).",
        ),
        "vote_split": (
            bool(split),
            "; ".join(f"{seen} of {of} reads saw {name}" for name, (seen, of) in sorted(split.items()))
            + "."
            if split
            else f"{agreement}."
            if agreement
            else "One vision read: no votes to compare.",
        ),
        "weight_tolerance": (weight_off, weight_evidence),
        "waybill_read": (read_uncertain, str(ocr_gate.get("reason") or "")),
        "moisture_declared": (
            bool(moisture_conflict),
            "No declared moisture."
            if moisture_claim is None
            else "No visual moisture estimate."
            if visual_moisture is None
            else f"Declared {moisture_claim:.0%}, the load looks like {visual_moisture:.0%}.",
        ),
        "arithmetic": (
            arithmetic_off,
            f"Gross {gross:,.0f} - tare {tare:,.0f} = {gross - tare:,.0f} kg vs net {net:,.0f} kg."
            if arithmetic_gap is not None and gross is not None and tare is not None
            and net is not None
            else "No gross, tare and net on the waybill.",
        ),
        "light_contaminant": (
            bool(light_hits),
            f"Seen: {', '.join(light_hits)}."
            if light_hits
            else "No glass, organic residue or wet mix seen.",
        ),
        "detector": (bool(detector_reasons), str(detector_gate.get("reason") or "")),
        "moisture_spec": (
            above_spec,
            "No declared moisture."
            if declared_pct is None
            else f"Declared moisture {declared_pct:g} % vs the {spec_pct:g} % contract spec"
            + (": sample to settle the price." if above_spec else ": within spec."),
        ),
        "engine_actionable": (
            engine_unusable,
            str(recommendation.get("headline") or "insufficient data for routing.")
            if engine_unusable
            else "No engine assessment; it does not block the verdict."
            if not recommendation
            else f"Engine route {recommendation.get('route', Route.HOLD_FOR_REVIEW)} is actionable.",
        ),
        "engine_tie": (
            engine_tied,
            "Engine routes tied within 0.02." if engine_tied else "Engine routes not tied.",
        ),
        "accept": (
            verdict == Decision.ACCEPT,
            "No rule above holds or rejects the load."
            if verdict == Decision.ACCEPT
            else f"Verdict {verdict}: a rule above decided.",
        ),
    }
    return verdict, gates, out, _receipt(evidence)
