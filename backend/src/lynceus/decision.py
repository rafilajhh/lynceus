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

   * VLM confidence < 0.3: the photo is unreadable, retake it;
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
    "confident_hard_contaminants",
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
    *,
    detector_hard_conf: float = DETECTOR_HARD_CONFIDENCE,
    detector_light_conf: float = DETECTOR_LIGHT_CONFIDENCE,
    detector_escalate_light: bool = True,
    benchmarked_vlm_models: Sequence[str] = BENCHMARKED_VLM_MODELS,
) -> Tuple[str, Dict[str, Any], List[str]]:
    """Fuse all pipeline outputs into ``(verdict, gates, reasons)``.

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
        return Decision.REFUSE_INSUFFICIENT_INPUT, gates, reasons

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

    # ----- VLM confidence gate (an unreadable photo is retaken) -----------
    assert vlm_confidence is not None  # refused above, kept for type checkers
    unreadable = vlm_confidence < UNSAFE_VLM_CONFIDENCE
    vlm_gate = _gate(
        GateState.FAILED if unreadable else GateState.PASSED,
        value=vlm_confidence,
        threshold=UNSAFE_VLM_CONFIDENCE,
        reason=(
            f"VLM confidence {vlm_confidence:.2f} is below the safe minimum of "
            f"{UNSAFE_VLM_CONFIDENCE:.2f}: photo unreadable, retake it."
            if unreadable
            else f"VLM confidence {vlm_confidence:.2f} is within the safe range."
        ),
    )

    # ----- Contamination scan (hard: shared helper; light: VLM detections) --
    light_hits = light_contaminant_hits(vlm_result)
    confident_hard = confident_hard_contaminants(inputs, vlm_result, llm_result)

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

    if reasons:  # a confident hard contaminant → reject
        if unbenchmarked:
            if detector_reasons:
                detector_gate["reason"] += _DETECTOR_HELD
            return (
                Decision.ESCALATE_HUMAN,
                gates,
                [unbenchmarked, *reasons, *detector_reasons],
            )
        if detector_reasons:  # the gate failed, but the reject outranks it
            detector_gate["reason"] += _DETECTOR_OUTRANKED
        return Decision.REJECT, gates, reasons

    # Amber flags → escalate (a person looks; never a reject)
    escalate_reasons: List[str] = []
    if unreadable:
        escalate_reasons.append(
            f"Photo unreadable: VLM confidence {vlm_confidence:.2f} is below the safe "
            f"minimum of {UNSAFE_VLM_CONFIDENCE:.2f}; retake the photo."
        )
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
    if detector_reasons:
        detector_gate["reason"] += _DETECTOR_HELD

    if escalate_reasons:
        return Decision.ESCALATE_HUMAN, gates, escalate_reasons

    # Engine actionability (engine refuse-to-answer, pattern 14)
    recommendation = (engine_result or {}).get("recommendation") or {}
    if recommendation.get("insufficient") or not recommendation.get("actionable", True):
        reasons.append(
            "The engine recommendation is not actionable: "
            + str(recommendation.get("headline") or "insufficient data for routing.")
        )
        if recommendation.get("missing"):
            for item in recommendation["missing"]:
                reasons.append(f"Engine missing input: {item}.")
        return Decision.REFUSE_INSUFFICIENT_INPUT, gates, reasons

    # A tied engine ranking cannot pick a route, so a clean load is not
    # waved through: the audit route is hold_for_review and the verdict
    # must say the same (reject/refuse above keep their precedence).
    if recommendation.get("tied"):
        return (
            Decision.ESCALATE_HUMAN,
            gates,
            ["Engine routes tied within 0.02; hold for supervisor review."],
        )

    if unbenchmarked:
        return Decision.ESCALATE_HUMAN, gates, [unbenchmarked]

    reasons.append(
        "No red flags: no hard contamination, weight within tolerance, VLM confidence "
        "in the safe range, and the engine recommendation is actionable "
        f"(route: {recommendation.get('route', Route.HOLD_FOR_REVIEW)})."
    )
    return Decision.ACCEPT, gates, reasons
