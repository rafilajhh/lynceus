"""AMD inference numbers for the console: measured run, live ledger, eval card.

Three read-only views, all from files already on disk (no model call):

* :func:`latest` — the newest committed ``*.amd-throughput.json`` written by
  ``benchmark/amd_throughput.py`` (a live run against AMD Token Factory).
* :func:`live_telemetry` — p50/p95 of the vision and detector latency over the
  last N completed inspections whose AI provenance is ``live``.
* :func:`eval_card` — metal let through, clean loads passed and loads held
  for a human, shipped gate vs VLM-only vs detector-only, read from the
  committed benchmark summaries (no new labels, no new numbers).

Every reader is cached by file mtime, so a console poll costs a few stats.
"""

from __future__ import annotations

import json
import math
import os
import re
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from lynceus import audit, impact

#: The measured-run summary files (``benchmark/results/<date>.amd-throughput.json``).
RESULT_GLOB = "*.amd-throughput.json"
RESULT_KIND = "amd_throughput"
#: Live records scanned at most per call, so a ledger full of stub runs
#: cannot turn one poll into a full-ledger read.
MAX_SCAN = 500
#: How a completed record states its AI provenance (``api._build_record``).
_LIVE_PROVENANCE_RE = re.compile(r"^AI provenance: live\.")

_lock = threading.Lock()
#: path -> (mtime_ns, parsed JSON) for the result and summary files.
_json_cache: Dict[str, Tuple[int, Any]] = {}
#: audit.json path -> (mtime_ns, extracted telemetry row or None).
_record_cache: Dict[str, Tuple[int, Optional[Dict[str, Any]]]] = {}


def _results_dir() -> Path:
    value = os.environ.get("LYNCEUS_BENCHMARK_DIR", "").strip()
    root = Path(value) if value else Path(__file__).resolve().parents[2] / "benchmark"
    return root / "results"


def percentile(values: List[float], q: float) -> Optional[float]:
    """Nearest-rank percentile (deterministic, no interpolation), as
    ``benchmark/metrics.py`` computes it; ``None`` for no values."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(1, math.ceil(q * len(ordered))) - 1]


def _spread(values: List[float]) -> Dict[str, Any]:
    p50, p95 = percentile(values, 0.50), percentile(values, 0.95)
    return {
        "p50": None if p50 is None else round(p50, 1),
        "p95": None if p95 is None else round(p95, 1),
        "n": len(values),
    }


def _read_json(path: Path) -> Any:
    """``path`` parsed, cached by mtime; ``None`` when missing or unreadable."""
    try:
        mtime = path.stat().st_mtime_ns
    except OSError:
        return None
    key = str(path)
    with _lock:
        hit = _json_cache.get(key)
    if hit is not None and hit[0] == mtime:
        return hit[1]
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        parsed = None
    with _lock:
        _json_cache[key] = (mtime, parsed)
    return parsed


# ---------------------------------------------------------------------------
# Measured run
# ---------------------------------------------------------------------------


def latest(results_dir: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    """The newest (by file name) readable AMD throughput summary, else ``None``."""
    results = Path(results_dir) if results_dir is not None else _results_dir()
    for path in sorted(results.glob(RESULT_GLOB), reverse=True):
        summary = _read_json(path)
        if isinstance(summary, dict) and summary.get("kind") == RESULT_KIND:
            return {**summary, "file": path.name}
    return None


# ---------------------------------------------------------------------------
# Live ledger telemetry
# ---------------------------------------------------------------------------


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) and value >= 0 else None


def _telemetry_row(path: Path) -> Optional[Dict[str, Any]]:
    """The latency fields of one completed live record, else ``None``.

    Raw JSON, not the strict audit model: a poll must stay cheap, and only
    four fields are read.
    """
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(record, dict):
        return None
    if record.get("execution_status") != audit.ExecutionStatus.COMPLETED:
        return None
    verdict = record.get("verdict") if isinstance(record.get("verdict"), dict) else {}
    if not _LIVE_PROVENANCE_RE.match(str(verdict.get("uncertainty", ""))):
        return None
    ai = record.get("ai_outputs") if isinstance(record.get("ai_outputs"), dict) else {}
    vlm = ai.get("vlm") if isinstance(ai.get("vlm"), dict) else {}
    det = ai.get("detector") if isinstance(ai.get("detector"), dict) else {}
    return {
        "record_id": record.get("record_id"),
        "finished_at_utc": record.get("finished_at_utc"),
        "vlm_latency_ms": _number(vlm.get("latency_ms")),
        "vlm_model": vlm.get("model") if isinstance(vlm.get("model"), str) else None,
        "vlm_provider": vlm.get("provider") if isinstance(vlm.get("provider"), str) else None,
        "detector_latency_ms": _number(det.get("latency_ms")),
    }


def _cached_row(path: Path) -> Optional[Dict[str, Any]]:
    try:
        mtime = path.stat().st_mtime_ns
    except OSError:
        return None
    key = str(path)
    with _lock:
        hit = _record_cache.get(key)
    if hit is not None and hit[0] == mtime:
        return hit[1]
    row = _telemetry_row(path)
    with _lock:
        _record_cache[key] = (mtime, row)
    return row


def live_telemetry(storage_dir: "str | os.PathLike[str]", n: int = 50) -> Dict[str, Any]:
    """p50/p95 of ``ai_outputs.vlm.latency_ms`` and the detector latency over
    the last ``n`` completed live inspections (newest first by record number).

    A record counts when it is completed and its verdict states
    ``AI provenance: live.``; stub, fallback and degraded runs never do.
    """
    n = max(1, int(n))
    storage = Path(storage_dir)
    numbered: List[Tuple[int, Path]] = []
    if storage.is_dir():
        for entry in storage.iterdir():
            m = audit.INSPECTION_DIR_RE.match(entry.name)
            if m:
                numbered.append((int(m.group(1)), entry / audit.RECORD_FILENAME))
    numbered.sort(reverse=True)

    rows: List[Dict[str, Any]] = []
    for _num, path in numbered[:MAX_SCAN]:
        row = _cached_row(path)
        if row is not None:
            rows.append(row)
            if len(rows) >= n:
                break

    models: Dict[str, int] = {}
    providers: Dict[str, int] = {}
    for row in rows:
        for key, counts in (("vlm_model", models), ("vlm_provider", providers)):
            if row[key]:
                counts[row[key]] = counts.get(row[key], 0) + 1
    return {
        "source": "ledger",
        "window": n,
        "count": len(rows),
        "vlm_latency_ms": _spread(
            [r["vlm_latency_ms"] for r in rows if r["vlm_latency_ms"] is not None]
        ),
        "detector_latency_ms": _spread(
            [r["detector_latency_ms"] for r in rows if r["detector_latency_ms"] is not None]
        ),
        "vlm_models": models,
        "vlm_providers": providers,
        "newest_record": rows[0]["record_id"] if rows else None,
        "oldest_record": rows[-1]["record_id"] if rows else None,
        "note": "Completed inspections with AI provenance live; vision latency is "
        "the whole vote (all reads, retries included).",
    }


# ---------------------------------------------------------------------------
# Eval card
# ---------------------------------------------------------------------------


def _count(value: Any) -> int:
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0


#: What each eval-card number counts; every row of the lift table carries all
#: of them, so no row can look good on one number by holding loads.
DEFINITIONS = {
    "metal_let_through": "Metal photos the gate accepted (passed with no human check).",
    "metal_rejected": "Metal photos the gate rejected on its own.",
    "clean_passed": "Clean-load photos the gate accepted.",
    "held_for_human": "Photos of any class the gate held for a human. They are also "
    "counted per class: metal, glass or organic (where a hold is the intended "
    "outcome) and clean (where a hold is a false alarm).",
    "classes": "RealWaste photos. Metal: 20 Metal photos. Glass or organic: Glass, "
    "Food Organics and Vegetation. Clean: Cardboard, Paper, Plastic and Textile Trash.",
}


def _gate_row(confusion: Any) -> Optional[Dict[str, Any]]:
    """The eval-card numbers from a confusion matrix ``{truth: {verdict:
    count}}`` (truth ``reject`` = metal photos, ``escalate`` = glass/organic,
    ``accept`` = clean loads)."""
    if not isinstance(confusion, dict):
        return None
    rows = {t: confusion.get(t) for t in ("reject", "escalate", "accept")}
    if not all(isinstance(r, dict) for r in rows.values()):
        return None
    sizes = {t: sum(_count(v) for v in r.values()) for t, r in rows.items()}
    total = sum(sizes.values())
    return {
        "metal_let_through": {"count": _count(rows["reject"].get("accept")), "n": sizes["reject"]},
        "metal_rejected": {"count": _count(rows["reject"].get("reject")), "n": sizes["reject"]},
        "clean_passed": {"count": _count(rows["accept"].get("accept")), "n": sizes["accept"]},
        "held_for_human": {
            "count": sum(_count(r.get("escalate")) for r in rows.values()),
            "n": total,
        },
        "held_by_class": {
            name: {"count": _count(rows[truth].get("escalate")), "n": sizes[truth]}
            for name, truth in (("metal", "reject"), ("glass_organic", "escalate"),
                                ("clean", "accept"))
        },
        "errors": sum(_count(r.get("error")) for r in rows.values()),
    }


def _advisory_row(findings: Any) -> Optional[Dict[str, Any]]:
    """The detector's findings read as a verdict (metal -> reject, glass or
    organic -> escalate, nothing -> accept), as the hybrid re-score stored
    them in ``detector_findings.by_expected``.  Lynceus never does this."""
    by = findings.get("by_expected") if isinstance(findings, dict) else None
    if not isinstance(by, dict):
        return None
    confusion = {}
    for truth in ("reject", "escalate", "accept"):
        row = by.get(truth)
        if not isinstance(row, dict):
            return None
        confusion[truth] = {
            "reject": _count(row.get("metal")),
            "escalate": _count(row.get("light")),
            "accept": _count(row.get("nothing")),
        }
    return _gate_row(confusion)


def eval_card(results_dir: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    """The three-number eval card and the fusion-lift table, else ``None``.

    Shipped gate: the ``hybrid_light_escalation_on`` variant of the hybrid
    re-score of the newest live run (``impact.shipped_gate_summary``).
    VLM-only: that live run's own confusion matrix.  Detector-only: the same
    re-score's ``detector_only_degraded`` variant (what ships when the vision
    model is down: every truck held), plus the advisory reading of its
    findings, labelled as never used as a verdict.
    """
    results = Path(results_dir) if results_dir is not None else _results_dir()
    live_found = next(impact.benchmark_summaries(results, "live"), None)
    hybrid_found = impact.shipped_gate_summary(results)
    if live_found is None or hybrid_found is None:
        return None
    (live, live_name), (hybrid, hybrid_name) = live_found, hybrid_found
    variants = hybrid.get("variants") if isinstance(hybrid.get("variants"), dict) else {}
    shipped_variant = variants.get(impact.SHIPPED_HYBRID_VARIANT) or {}
    degraded_variant = variants.get("detector_only_degraded") or {}

    shipped = _gate_row(shipped_variant.get("confusion"))
    vlm_only = _gate_row(live.get("confusion"))
    if shipped is None or vlm_only is None:
        return None
    lift = [
        {
            "variant": "detector_only_degraded",
            "label": "Detector only (as shipped when the vision model is down)",
            "note": "Holds every truck for a human by design.",
            **(_gate_row(degraded_variant.get("confusion")) or {}),
        },
        {
            "variant": "detector_only_advisory",
            "label": "Detector only, findings read as a verdict",
            "note": "Offline reading of the stored detector findings; Lynceus never "
            "lets the detector alone accept or reject. In-domain and optimistic: the "
            "detector was fine-tuned on RealWaste photos from the same sessions as "
            "these test images, not on truck beds of mixed RDF.",
            **(_advisory_row(degraded_variant.get("detector_findings")) or {}),
        },
        {"variant": "vlm_only", "label": f"VLM only ({live.get('vlm_model')})", **vlm_only},
        {"variant": impact.SHIPPED_HYBRID_VARIANT,
         "label": "Shipped gate (VLM + CPU detector)", **shipped},
    ]
    return {
        "source": {"live": live_name, "hybrid": hybrid_name},
        "vlm_model": live.get("vlm_model"),
        "detector": (hybrid.get("detector") or {}).get("model"),
        "framing": live.get("framing"),
        "disclosure": hybrid.get("disclosure"),
        "card": {
            key: {"shipped": shipped[key], "vlm_only": vlm_only[key]}
            for key in ("metal_let_through", "clean_passed", "held_for_human")
        },
        "definitions": DEFINITIONS,
        "fusion_lift": [row for row in lift if "held_for_human" in row],
    }
