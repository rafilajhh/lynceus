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
to replay).
"""

from __future__ import annotations

import argparse
import base64
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
    "The rule change this replay scores (plastic film and textile are RDF feedstock and "
    "no longer escalate a load) was motivated by this same run's data, so these rates are "
    "not a held-out result. Only a new live run on unseen images can confirm them."
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
def _replay_app(clients: Dict[str, ReplayAIClients]) -> Iterator[Callable[[Dict[str, Any]], tuple]]:
    """A ``post(payload)`` against the real app, offline, in a temp storage dir.

    ``pipeline.resolve_clients`` is swapped for a lookup by ``truck_id`` and
    the gas sensor URL is unset, so nothing can reach the network.  The
    environment and the pipeline are restored on exit.
    """
    from fastapi.testclient import TestClient

    from lynceus import gas_ingest, pipeline
    from lynceus.api import create_app
    from lynceus.config import LYNCEUS_ALLOW_STUB_FALLBACK_ENV, LYNCEUS_STORAGE_DIR_ENV

    keys = (LYNCEUS_STORAGE_DIR_ENV, LYNCEUS_ALLOW_STUB_FALLBACK_ENV, gas_ingest.GAS_SENSOR_URL_ENV)
    saved = {key: os.environ.get(key) for key in keys}
    original = pipeline.resolve_clients
    with tempfile.TemporaryDirectory(prefix="lynceus-rescore-") as storage:
        os.environ[LYNCEUS_STORAGE_DIR_ENV] = storage
        os.environ[LYNCEUS_ALLOW_STUB_FALLBACK_ENV] = "0"
        os.environ.pop(gas_ingest.GAS_SENSOR_URL_ENV, None)
        pipeline.resolve_clients = lambda payload, settings=None: clients[payload["truck_id"]]
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
    with _replay_app(clients) as post:
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
    gates_changed = [
        r["image"] for r in good if r.get("gates") != recorded[r["image"]].get("gates")
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
    args = parser.parse_args(argv)
    source = args.source or _default_source()
    if source is None or not source.is_file():
        print(f"ABORT: no live run jsonl found ({source})", file=sys.stderr)
        return 2
    sys.path.insert(0, str(BACKEND_DIR / "src"))
    rescore(source)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
