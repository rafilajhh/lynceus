"""Replay re-score of a recorded live benchmark run through the current rules.

Every row of a live run (``run.py``) carries the structured VLM output it got
(``detected``, ``vlm_confidence``) and the gate states.  This script posts each
recorded image again to ``POST /inspect`` through the real app (FastAPI
``TestClient``, a throwaway storage dir) with the same payload ``run.py`` built
(``MANIFEST_TEXT`` / ``WEIGHT_KG``), but the AI clients are replaced by a
replay client that returns the recorded VLM output and an LLM result
consistent with the recorded gates.  No network, no model call: only the
current decision rules run, so the result answers "what would HEAD decide on
the same model outputs".

Usage (from ``backend/``)::

    PYTHONPATH=src python -m benchmark.rescore --source benchmark/results/2026-10-13.jsonl

Writes ``<stem>.rescore.jsonl`` and ``<stem>.rescore.summary.json`` next to the
source; the live files are never modified.  The latest row per image is
replayed; a recorded error row stays an error row (there is no model output
to replay).  The plain replay runs with the CPU detector off: the recorded
run had none.

Hybrid what-if (the same recorded VLM outputs fused with the CPU detector)::

    PYTHONPATH=src python -m benchmark.rescore --source benchmark/results/2026-10-13.jsonl --hybrid
    # or run lynceus.detector over benchmark/images instead of the ml/ results:
    PYTHONPATH=src python -m benchmark.rescore --source benchmark/results/2026-10-13.jsonl --hybrid --run-detector

writes ``<today>.hybrid-rescore.summary.json``: VLM-only vs hybrid (light
escalation on / off), a ``detector_hard_conf`` sweep, and detector-only
degraded mode.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, Optional

BENCH_DIR = Path(__file__).resolve().parent
BACKEND_DIR = BENCH_DIR.parent

if __package__ in (None, ""):
    sys.path.insert(0, str(BACKEND_DIR))

from benchmark import metrics  # noqa: E402
from benchmark import run as bench  # noqa: E402

#: Stated with every replay summary (``{source_run}`` is the live run's date).
FRAMING = (
    "Re-scored: the recorded live model outputs of the {source_run} AMD Token Factory "
    "run, replayed through the current decision rules. No new model calls."
)
#: The replay is not a held-out evaluation; the summary says so.
DISCLOSURE = (
    "The replay scores every decision-rule change made after the live run, not one: "
    "hard contaminants are now read from the structured fields only, not from the "
    "model's prose (one recorded reject, plastic_277.jpg, came from the word "
    "'concrete' in prose; that change alone moves metal precision from 0.86 to 0.90), "
    "and plastic film and textile are RDF feedstock and no longer escalate a load. "
    "Both changes were motivated by this same run's data, so these rates are not a "
    "held-out result. Only a new live run on unseen images can confirm them."
)
#: How the LLM side of the replay is built (the live rows kept only gate states).
LLM_NOTE = (
    "The live rows recorded the LLM's gate outcome, not its text, so the replayed LLM "
    "result is rebuilt from the recorded manifest_crosscheck state with a fixed confidence "
    "of {confidence}. That confidence only fills the ocr_confidence gate value, which has "
    "no threshold and never moves the verdict. The VLM prompt was not changed for this "
    "re-score; latency is not re-measured (no model was called)."
)
#: Fills the ocr_confidence gate value only (see LLM_NOTE).
REPLAY_LLM_CONFIDENCE = 0.95
REPLAY_PROVENANCE = "replay"
#: Detector settings (``lynceus.config``), named here so this module imports
#: nothing from ``lynceus`` before ``main`` has set up the path.
DETECTOR_MODEL_PATH_ENV = "DETECTOR_MODEL_PATH"
DETECTOR_HARD_CONF_ENV = "DETECTOR_HARD_CONF"
DETECTOR_LIGHT_CONF_ENV = "DETECTOR_LIGHT_CONF"
DETECTOR_ESCALATE_LIGHT_ENV = "DETECTOR_ESCALATE_LIGHT"


class ReplayAIClients:
    """AI clients that answer with one recorded live row, never the network."""

    provenance = REPLAY_PROVENANCE

    def __init__(self, row: Dict[str, Any]) -> None:
        self._row = row

    def vlm(self, photo: Optional[str]) -> Dict[str, Any]:
        detected = dict(self._row.get("detected") or {})
        confidence = self._row.get("vlm_confidence")
        return {
            "detected": detected,
            "confidence": confidence,
            "boxes": [],
            "model": self._row.get("vlm_model") or "",
            "model_version": self._row.get("vlm_model") or "",
            "raw_output": json.dumps(
                {"detected": detected, "confidence": confidence}, sort_keys=True
            ),
            "provenance": REPLAY_PROVENANCE,
            "provider": self._row.get("provider"),
            "latency_ms": None,
        }

    def llm(self, manifest_text: str, context: Dict[str, Any]) -> Dict[str, Any]:
        failed = (self._row.get("gates") or {}).get("manifest_crosscheck") == "failed"
        notes = "recorded cross-check failed" if failed else "consistent"
        return {
            "reasoning": "Replayed from the recorded gate states of the live run.",
            "confidence": REPLAY_LLM_CONFIDENCE,
            "declared_weight_kg": None,
            "declared_moisture_fraction": None,
            "crosscheck_notes": notes,
            "crosscheck_failed": failed,
            "model": self._row.get("llm_model") or "",
            "model_version": self._row.get("llm_model") or "",
            "raw_output": json.dumps({"crosscheck_failed": failed}, sort_keys=True),
            "provenance": REPLAY_PROVENANCE,
            "provider": self._row.get("provider"),
            "latency_ms": None,
        }


@contextmanager
def _replay_app(
    clients: Dict[str, Any],
    env: Optional[Dict[str, str]] = None,
    detections: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Iterator[Callable[[Dict[str, Any]], tuple]]:
    """A ``post(payload)`` against the real app, offline, in a temp storage dir.

    ``pipeline.resolve_clients`` is swapped for a lookup by ``truck_id`` and
    the gas sensor URL is unset, so nothing can reach the network.  ``env``
    adds variables for this replay (the plain replay turns the CPU detector
    off with ``DETECTOR_MODEL_PATH=""``: it scores the recorded VLM-only
    run).  ``detections`` (photo sha256 -> recorded detector boxes) replaces
    the detector with those recordings.  The environment and the pipeline are
    restored on exit.
    """
    from fastapi.testclient import TestClient

    from lynceus import detector, gas_ingest, pipeline
    from lynceus.api import create_app
    from lynceus.config import LYNCEUS_ALLOW_STUB_FALLBACK_ENV, LYNCEUS_STORAGE_DIR_ENV

    env = dict(env or {})
    keys = (
        LYNCEUS_STORAGE_DIR_ENV,
        LYNCEUS_ALLOW_STUB_FALLBACK_ENV,
        gas_ingest.GAS_SENSOR_URL_ENV,
        *env,
    )
    saved = {key: os.environ.get(key) for key in keys}
    original = pipeline.resolve_clients
    original_detect = pipeline.safe_detect

    def recorded_detect(photo_bytes: bytes, settings: Any) -> Optional[Dict[str, Any]]:
        found = detections.get(hashlib.sha256(photo_bytes).hexdigest()) if detections else None
        if found is None:
            return None
        floor = min(settings.detector_hard_conf, settings.detector_light_conf)
        return detector.summarize(
            [b for b in found["boxes"] if b["confidence"] >= floor],
            found.get("latency_ms"),
            settings.detector_hard_conf,
            settings.detector_light_conf,
            escalate_light=settings.detector_escalate_light,
        )

    with tempfile.TemporaryDirectory(prefix="lynceus-rescore-") as storage:
        os.environ[LYNCEUS_STORAGE_DIR_ENV] = storage
        os.environ[LYNCEUS_ALLOW_STUB_FALLBACK_ENV] = "0"
        os.environ.pop(gas_ingest.GAS_SENSOR_URL_ENV, None)
        os.environ.update(env)
        pipeline.resolve_clients = lambda payload, settings=None: clients[payload["truck_id"]]
        if detections is not None:
            pipeline.safe_detect = recorded_detect
        try:
            client = TestClient(create_app())

            def post(payload: Dict[str, Any]) -> tuple:
                response = client.post("/inspect", json=payload)
                try:
                    return response.status_code, response.json()
                except ValueError:
                    return response.status_code, {"detail": response.text[:200]}

            yield post
        finally:
            pipeline.resolve_clients = original
            pipeline.safe_detect = original_detect
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


def _replay_row(recorded: Dict[str, Any], status: int, body: Dict[str, Any]) -> Dict[str, Any]:
    base = {
        "image": recorded["image"],
        "category": recorded["category"],
        "expected": recorded["expected"],
        "recorded_predicted": recorded.get("predicted"),
    }
    if status != 200 or body.get("provenance") != REPLAY_PROVENANCE:
        return {
            **base,
            "predicted": None,
            "error": f"replay HTTP {status}: {bench._error_message(body)}"[:300],
        }
    return {
        **base,
        "predicted": (body.get("verdict") or {}).get("decision"),
        "gates": {name: g.get("state") for name, g in (body.get("gates") or {}).items()},
        "detected": recorded.get("detected"),
        "vlm_confidence": recorded.get("vlm_confidence"),
        "reasons": body.get("reasons") or [],
        "actions": [a.get("sop_ref") for a in body.get("actions") or []],
        "vlm_model": recorded.get("vlm_model"),
        "llm_model": recorded.get("llm_model"),
        "provider": recorded.get("provider"),
        "provenance": REPLAY_PROVENANCE,
        "source_provenance": recorded.get("provenance"),
        "error": None,
    }


def rescore(
    source: Path,
    *,
    images_dir: Path = bench.IMAGES_DIR,
    manifest: Path = bench.MANIFEST,
    log: Callable[[str], None] = print,
    today: Optional[str] = None,
) -> Dict[str, Any]:
    """Replay ``source`` (a live run's jsonl) and write the two rescore files."""
    recorded_rows = bench.load_rows(source)
    if not recorded_rows:
        raise ValueError(f"{source}: no recorded rows to replay")
    source_run = source.stem
    clients: Dict[str, ReplayAIClients] = {}
    payloads = []
    for n, row in enumerate(recorded_rows, start=1):
        if row.get("error"):
            continue
        photo = base64.b64encode((images_dir / row["image"]).read_bytes()).decode("ascii")
        payload = bench.build_payload(row, n, photo)
        clients[payload["truck_id"]] = ReplayAIClients(row)
        payloads.append((row, payload))

    replayed: Dict[str, Dict[str, Any]] = {}
    # The recorded run had no detector: replay it VLM-only.
    with _replay_app(clients, env={DETECTOR_MODEL_PATH_ENV: ""}) as post:
        for row, payload in payloads:
            status, body = post(payload)
            replayed[row["image"]] = _replay_row(row, status, body)

    rows = []
    for row in recorded_rows:
        if row.get("error"):
            rows.append({**row, "recorded_predicted": None})  # nothing to replay
        else:
            rows.append(replayed[row["image"]])

    out = source.with_name(f"{source_run}.rescore.jsonl")
    out.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8"
    )
    summary = build_summary(
        rows,
        recorded_rows,
        source_run,
        len(bench.read_manifest(manifest)),
        today or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    )
    summary_path = source.with_name(f"{source_run}.rescore.summary.json")
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    log(f"replayed {len(payloads)} rows ({len(rows) - len(payloads)} recorded errors kept)")
    log(f"rescore -> {out}")
    log(f"summary -> {summary_path}")
    return summary


def build_summary(
    rows: list[Dict[str, Any]],
    recorded_rows: list[Dict[str, Any]],
    source_run: str,
    manifest_n: int,
    rescored_on: str,
) -> Dict[str, Any]:
    """Replay metrics plus the recorded confusion and every changed verdict."""
    summary = metrics.compute(rows)
    recorded = {r["image"]: r for r in recorded_rows}
    good = [r for r in rows if not r.get("error")]
    changed = [
        {
            "image": r["image"],
            "expected": r["expected"],
            "recorded": metrics.label_for(recorded[r["image"]]),
            "replay": metrics.label_for(r),
        }
        for r in rows
        if metrics.label_for(r) != metrics.label_for(recorded[r["image"]])
    ]
    # Gates the live run recorded only: a gate added since (the detector's)
    # is new information, not a change.
    gates_changed = [
        r["image"]
        for r in good
        if {k: v for k, v in (r.get("gates") or {}).items()
            if k in (recorded[r["image"]].get("gates") or {})}
        != recorded[r["image"]].get("gates")
    ]
    summary.update(
        {
            "kind": "replay",
            "source_run": source_run,
            "framing": FRAMING.format(source_run=source_run),
            "scope": bench.FRAMING,
            "disclosure": DISCLOSURE,
            "llm_note": LLM_NOTE.format(confidence=REPLAY_LLM_CONFIDENCE),
            "date": source_run,
            "rescored_on": rescored_on,
            "manifest_n": manifest_n,
            "complete": len(good) == manifest_n,
            "vlm_model": next((r["vlm_model"] for r in good if r.get("vlm_model")), None),
            "llm_model": next((r["llm_model"] for r in good if r.get("llm_model")), None),
            "provider": next((r["provider"] for r in good if r.get("provider")), None),
            "provenance": [REPLAY_PROVENANCE] if good else [],
            "source_provenance": sorted(
                {r["source_provenance"] for r in good if r.get("source_provenance")}
            ),
            "per_category": bench._per_category(rows),
            "recorded_confusion": metrics.compute(recorded_rows)["confusion"],
            "changed": changed,
            "gates_changed": gates_changed,
        }
    )
    return summary


# ---------------------------------------------------------------------------
# Hybrid what-if: the recorded VLM outputs fused with the CPU detector
# ---------------------------------------------------------------------------

#: Per-image detections of the fine-tuned detector (written by ml/eval_finetuned.py).
DEFAULT_DETECTIONS = BACKEND_DIR.parent / "ml" / "results" / "finetuned_yolo26s_e26l_nmsfree.json"
HYBRID_FRAMING = (
    "What-if re-score: the recorded live VLM outputs of the {source_run} AMD Token Factory "
    "run, fused with the CPU detector (YOLO26s fine-tuned on RealWaste + TACO) through the "
    "current decision rules. No new model calls."
)
HYBRID_DISCLOSURE = (
    "In-domain and optimistic. The detector was fine-tuned on RealWaste photos from the "
    "same sessions as these 80 held-out images (one item per frame on the same floor; the "
    "held-out images were excluded from training) plus TACO litter photos. The default "
    "thresholds were picked on a separate val split (RealWaste val + TACO val) by a rule "
    "fixed before any test read, but the sweep below is read on this test set. It shows "
    "the fusion rules work as designed on these images, not that the detector works on a "
    "truck bed of mixed RDF. The VLM side carries the replay's own caveat: the decision "
    "rules were changed after the live run, using that run's data."
)
DEGRADED_NOTE = (
    "Detector-only degraded mode (vision model unavailable, stub fallback off) holds "
    "every truck for a human by design, so its verdict is escalate on all images. "
    "'detector_findings' counts what the hold reasons would list; 'advisory_gate' reads "
    "those findings as if they were a verdict (metal -> reject, glass/organic -> escalate, "
    "else accept), which Lynceus never does."
)
#: Swept ``detector_hard_conf`` values (light threshold fixed at the default);
#: includes the default (``decision.DETECTOR_HARD_CONFIDENCE``).
_SWEEP_HARD_CONF = (0.05, 0.1, 0.25, 0.35, 0.5)


def _default_thresholds() -> tuple[float, float]:
    """The shipped ``(hard, light)`` detector defaults (lazy: ``src`` joins
    ``sys.path`` only in :func:`main`)."""
    from lynceus.decision import DETECTOR_HARD_CONFIDENCE, DETECTOR_LIGHT_CONFIDENCE

    return DETECTOR_HARD_CONFIDENCE, DETECTOR_LIGHT_CONFIDENCE


def load_detections(path: Path) -> Dict[str, Dict[str, Any]]:
    """``image -> {"boxes": [{label, confidence, box}], "latency_ms": None}``
    from an ``ml/results/finetuned_*.json`` file (``conf`` renamed)."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        item["image"]: {
            "boxes": [
                {"label": b["label"], "confidence": float(b["conf"]), "box": list(b["box"])}
                for b in item.get("boxes") or []
                if b["box"][0] < b["box"][2] and b["box"][1] < b["box"][3]
            ],
            "latency_ms": None,
        }
        for item in data
    }


def run_detections(images_dir: Path, images: list[str], min_conf: float = 0.05) -> Dict[str, Dict[str, Any]]:
    """Same shape as :func:`load_detections`, from ``lynceus.detector`` itself."""
    from lynceus import detector
    from lynceus.config import get_settings

    settings = get_settings()
    if not detector.enabled(settings):
        raise RuntimeError("the detector is disabled (no model, or onnxruntime/numpy/Pillow missing)")
    found = {}
    for name in images:
        result = detector.detect((images_dir / name).read_bytes(), settings, min_conf=min_conf)
        found[name] = {"boxes": result["boxes"], "latency_ms": result["latency_ms"],
                       "model_sha256": result.get("model_sha256"),
                       "runtime": result["runtime"]}
    return found


def _variant_row(recorded: Dict[str, Any], status: int, body: Dict[str, Any]) -> Dict[str, Any]:
    row = {"image": recorded["image"], "category": recorded["category"],
           "expected": recorded["expected"]}
    if status != 200 or body.get("provenance") not in (REPLAY_PROVENANCE, "detector_only_degraded"):
        return {**row, "predicted": None,
                "error": f"replay HTTP {status}: {bench._error_message(body)}"[:300]}
    gate = (body.get("gates") or {}).get("detector_second_opinion") or {}
    return {**row, "predicted": (body.get("verdict") or {}).get("decision"),
            "detector_gate": gate.get("state"), "error": None}


def _variant_metrics(rows: list[Dict[str, Any]], baseline: Optional[list[Dict[str, Any]]] = None) -> Dict[str, Any]:
    m = metrics.compute(rows)
    graded = [r for r in rows if metrics.label_for(r) != "error"]
    correct = sum(1 for r in rows if metrics.label_for(r) == r["expected"])
    out = {
        "n": m["n"],
        "errors": m["errors"],
        "clean_accept_rate": m["clean_accept_rate"],
        "review_rate": m["review_rate"],
        "escalate_recall": m["escalate_recall"],
        "metal_reject": {k: m["reject"][k] for k in ("precision", "recall", "tp", "fp", "fn")},
        # The costly miss: a metal load waved through.
        "metal_accepted": m["confusion"]["reject"]["accept"],
        "gate_accuracy": correct / len(rows) if rows else None,
        "gate_correct": f"{correct}/{len(rows)}",
        "graded": len(graded),
        "confusion": m["confusion"],
        "detector_gate_failed": sum(1 for r in rows if r.get("detector_gate") == "failed"),
    }
    if baseline is not None:
        before = {r["image"]: metrics.label_for(r) for r in baseline}
        out["changed_vs_vlm_only"] = [
            {"image": r["image"], "expected": r["expected"],
             "vlm_only": before.get(r["image"]), "hybrid": metrics.label_for(r)}
            for r in rows
            if metrics.label_for(r) != before.get(r["image"])
        ]
    return out


def _detector_findings(
    detections: Dict[str, Dict[str, Any]],
    recorded_rows: list[Dict[str, Any]],
    hard_conf: float,
    light_conf: float,
) -> Dict[str, Any]:
    """What detector-only mode would list per expected label, plus the
    advisory reading of those findings as a verdict."""
    from lynceus import detector

    by_expected: Dict[str, Dict[str, int]] = {}
    advisory_correct = 0
    for row in recorded_rows:
        hard, light = detector.flagged(detections.get(row["image"]), hard_conf, light_conf)
        cell = by_expected.setdefault(row["expected"], {"n": 0, "metal": 0, "light": 0, "nothing": 0})
        cell["n"] += 1
        cell["metal"] += bool(hard)
        cell["light"] += bool(light) and not hard
        cell["nothing"] += not hard and not light
        advisory = "reject" if hard else "escalate" if light else "accept"
        advisory_correct += advisory == row["expected"]
    return {
        "thresholds": {"hard": hard_conf, "light": light_conf},
        "by_expected": by_expected,
        "advisory_gate": f"{advisory_correct}/{len(recorded_rows)}",
        "advisory_gate_accuracy": advisory_correct / len(recorded_rows) if recorded_rows else None,
    }


def hybrid_rescore(
    source: Path,
    detections: Dict[str, Dict[str, Any]],
    *,
    detections_source: str,
    detector_runtime: str = "onnxruntime-cpu",
    detector_model: Optional[str] = None,
    out: Optional[Path] = None,
    images_dir: Path = bench.IMAGES_DIR,
    manifest: Path = bench.MANIFEST,
    log: Callable[[str], None] = print,
    today: Optional[str] = None,
) -> Dict[str, Any]:
    """Re-decide every recorded VLM output with the detector fused in.

    Variants: VLM-only (detector off), hybrid with light escalation on and
    off, a ``detector_hard_conf`` sweep, and detector-only degraded mode (the
    vision model made unavailable).  Writes ``out`` (default
    ``<today>.hybrid-rescore.summary.json`` next to the source).
    """
    from lynceus import detector, pipeline

    hard_default, light_default = _default_thresholds()
    today = today or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    recorded_rows = bench.load_rows(source)
    if not recorded_rows:
        raise ValueError(f"{source}: no recorded rows to replay")
    missing = [r["image"] for r in recorded_rows if r["image"] not in detections]
    if missing:
        raise ValueError(f"no detections for {len(missing)} images, e.g. {missing[:3]}")
    by_sha: Dict[str, Dict[str, Any]] = {}
    jobs = []
    for n, row in enumerate(recorded_rows, start=1):
        raw = (images_dir / row["image"]).read_bytes()
        by_sha[hashlib.sha256(raw).hexdigest()] = detections[row["image"]]
        jobs.append((row, bench.build_payload(row, n, base64.b64encode(raw).decode("ascii"))))

    def run_variant(env: Dict[str, str], degraded: bool = False) -> list[Dict[str, Any]]:
        if degraded:
            clients = {p["truck_id"]: pipeline.UnavailableAIClients(
                "what-if: vision model unavailable") for _, p in jobs}
        else:
            clients = {p["truck_id"]: ReplayAIClients(r) for r, p in jobs if not r.get("error")}
        rows = []
        detector_off = env.get(DETECTOR_MODEL_PATH_ENV) == ""
        with _replay_app(clients, env=env, detections=None if detector_off else by_sha) as post:
            for row, payload in jobs:
                if row.get("error") and not degraded:
                    rows.append({**row, "predicted": None})  # nothing to replay
                    continue
                rows.append(_variant_row(row, *post(payload)))
        return rows

    def detector_env(hard: float, light_on: bool) -> Dict[str, str]:
        return {
            DETECTOR_HARD_CONF_ENV: str(hard),
            DETECTOR_LIGHT_CONF_ENV: str(light_default),
            DETECTOR_ESCALATE_LIGHT_ENV: "1" if light_on else "0",
        }

    log("variant vlm_only")
    vlm_only = run_variant({DETECTOR_MODEL_PATH_ENV: ""})
    sweep: Dict[str, Dict[str, Any]] = {}
    hybrid: Dict[str, list] = {}
    for hard in _SWEEP_HARD_CONF:
        for light_on in (True, False):
            key = "light_escalation_on" if light_on else "light_escalation_off"
            log(f"variant hard_conf={hard} {key}")
            rows = run_variant(detector_env(hard, light_on))
            sweep.setdefault(str(hard), {})[key] = _variant_metrics(rows, vlm_only)
            if hard == hard_default:
                hybrid[key] = rows
    log("variant detector_only_degraded")
    degraded_rows = run_variant(detector_env(hard_default, True), degraded=True)

    def headline(rows: list[Dict[str, Any]]) -> Dict[str, Any]:
        m = _variant_metrics(rows)
        return {
            "clean_accept_rate": m["clean_accept_rate"],
            "review_rate": m["review_rate"],
            "metal_reject_recall": m["metal_reject"]["recall"],
            "metal_reject_precision": m["metal_reject"]["precision"],
            "metal_accepted": m["metal_accepted"],
            "escalate_recall": m["escalate_recall"],
            "gate_accuracy": m["gate_accuracy"],
        }

    degraded_metrics = _variant_metrics(degraded_rows)
    degraded_metrics["note"] = DEGRADED_NOTE
    degraded_metrics["detector_findings"] = _detector_findings(
        detections, recorded_rows, hard_default, light_default
    )
    source_run = source.stem
    summary = {
        "kind": "hybrid_replay",
        "source_run": source_run,
        "framing": HYBRID_FRAMING.format(source_run=source_run),
        "scope": bench.FRAMING,
        "disclosure": HYBRID_DISCLOSURE,
        "llm_note": LLM_NOTE.format(confidence=REPLAY_LLM_CONFIDENCE),
        "rescored_on": today,
        "manifest_n": len(bench.read_manifest(manifest)),
        "vlm_model": next((r["vlm_model"] for r in recorded_rows if r.get("vlm_model")), None),
        "detector": {
            "model": detector_model or detector.MODEL_NAME,
            # What produced the boxes: lynceus.detector, or the ml/ results.
            "runtime": detector_runtime,
            "model_sha256": next(
                (d["model_sha256"] for d in detections.values() if d.get("model_sha256")), None
            ),
            "detections_source": detections_source,
            "hard_conf_default": hard_default,
            "light_conf": light_default,
            "thresholds_note": (
                "Defaults picked on the val split (RealWaste val + TACO val) by a rule fixed "
                "before any test read (ml/eval_val.py); the sweep is read on this test set."
            ),
        },
        "table": {
            "vlm_only": headline(vlm_only),
            "hybrid_light_escalation_on": headline(hybrid["light_escalation_on"]),
            "hybrid_light_escalation_off": headline(hybrid["light_escalation_off"]),
            "detector_only_degraded": headline(degraded_rows),
        },
        "variants": {
            "vlm_only": _variant_metrics(vlm_only),
            "hybrid_light_escalation_on": _variant_metrics(hybrid["light_escalation_on"], vlm_only),
            "hybrid_light_escalation_off": _variant_metrics(hybrid["light_escalation_off"], vlm_only),
            "detector_only_degraded": degraded_metrics,
        },
        "sweep_detector_hard_conf": sweep,
    }
    out = out or source.with_name(f"{today}.hybrid-rescore.summary.json")
    out.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    log(f"hybrid summary -> {out}")
    return summary


def _default_source() -> Optional[Path]:
    live = [
        p for p in sorted(bench.RESULTS_DIR.glob("*.jsonl")) if not p.name.endswith(".rescore.jsonl")
    ]
    return live[-1] if live else None


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--source", type=Path, default=None, help="live run jsonl (default: newest in results/)"
    )
    parser.add_argument(
        "--hybrid", action="store_true",
        help="what-if: fuse the CPU detector into every recorded VLM output "
        "(writes <today>.hybrid-rescore.summary.json)",
    )
    parser.add_argument(
        "--detections", type=Path, default=DEFAULT_DETECTIONS,
        help="per-image detector results for --hybrid (default: the ml/ NMS-free results)",
    )
    parser.add_argument(
        "--run-detector", action="store_true",
        help="--hybrid with lynceus.detector run over the images instead of --detections",
    )
    parser.add_argument("--out", type=Path, default=None, help="--hybrid summary path")
    args = parser.parse_args(argv)
    source = args.source or _default_source()
    if source is None or not source.is_file():
        print(f"ABORT: no live run jsonl found ({source})", file=sys.stderr)
        return 2
    sys.path.insert(0, str(BACKEND_DIR / "src"))
    if not args.hybrid:
        rescore(source)
        return 0
    if args.run_detector:
        images = [r["image"] for r in bench.load_rows(source)]
        detections = run_detections(bench.IMAGES_DIR, images)
        # The provider the detector actually ran on (DETECTOR_PROVIDERS, CPU fallback).
        detector_runtime = next(
            (d["runtime"] for d in detections.values() if d.get("runtime")), "onnxruntime-cpu"
        )
        detections_source = (
            f"lynceus.detector ({detector_runtime}) run over benchmark/images, conf >= 0.05"
        )
        from lynceus import detector
        from lynceus.config import get_settings

        detector_model = detector.model_name(get_settings().detector_model_path)
    else:
        if not args.detections.is_file():
            print(f"ABORT: detections file not found ({args.detections})", file=sys.stderr)
            return 2
        detections = load_detections(args.detections)
        try:  # a repo-relative path: no machine paths in a committed summary
            shown = args.detections.resolve().relative_to(BACKEND_DIR.parent).as_posix()
        except ValueError:
            shown = args.detections.name
        detections_source = f"{shown} (Ultralytics predict, conf >= 0.05)"
        detector_runtime = "ultralytics-predict"
        # The default file is the bundled model's; any other is named by its file.
        detector_model = None if args.detections == DEFAULT_DETECTIONS else args.detections.stem
    hybrid_rescore(source, detections, detections_source=detections_source,
                   detector_runtime=detector_runtime, detector_model=detector_model,
                   out=args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
