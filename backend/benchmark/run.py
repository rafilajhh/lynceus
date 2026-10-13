"""Live benchmark of the Lynceus vision gate on public RealWaste images.

Posts every image in ``manifest.csv`` to ``POST /inspect`` through FastAPI's
``TestClient`` against the live AMD Token Factory endpoint configured in
``backend/.env`` (never printed, never written to a result row).

Every item uses the same fixed, neutral waybill and a consistent weight so the
weight / cross-check gates pass and the verdict is decided by the vision gate
alone.  There is no ``demo_case``: each row must come back with provenance
``live`` or the run aborts without writing that row.

Usage (from ``backend/``)::

    PYTHONPATH=src python -m benchmark.run --min-interval 4

The output is resumable: images that already have a clean row in the output
file are skipped.  A request error is recorded as a row with ``error`` set (and
retried on the next run); three errors in a row stop the run so a throttled
shared key is not hammered.

Rate limiting is different: when the live client has exhausted its own 429
retries the API answers 503 with a message saying the endpoint is
rate-limited.  That is not a measurement, so the run stops at once (exit code
2), writes NO row for that image, and a re-run resumes from it.
"""

from __future__ import annotations

import argparse
import base64
import csv
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

BENCH_DIR = Path(__file__).resolve().parent
BACKEND_DIR = BENCH_DIR.parent
MANIFEST = BENCH_DIR / "manifest.csv"
IMAGES_DIR = BENCH_DIR / "images"
RESULTS_DIR = BENCH_DIR / "results"
RUNS_DIR = BENCH_DIR / "runs"

#: Fixed neutral waybill: a mixed RDF load, no moisture claim, no contaminant
#: words, so only the photo can move the verdict.
MANIFEST_TEXT = (
    "WASTE TRANSFER NOTE\n"
    "Waste type: mixed RDF feedstock load, municipal origin\n"
    "Declared weight: 5,200 kg\n"
    "Supplier: Benchmark"
)
WEIGHT_KG = 5200
SUPPLIER = "Benchmark"
MAX_CONSECUTIVE_ERRORS = 3
#: Stated with every summary; the API serves the same sentence (tested equal).
FRAMING = "component validation on public RealWaste images — not field data from a plant"


class ProvenanceError(RuntimeError):
    """A response was not produced by the live models; the run must stop."""


class RateLimitedError(RuntimeError):
    """The shared endpoint is rate-limited; the run must stop without a row."""


_RATE_LIMIT_RE = re.compile(r"rate[- ]limited", re.IGNORECASE)


def _error_message(body: Any) -> str:
    detail = body.get("detail") if isinstance(body, dict) else None
    return (detail.get("message") if isinstance(detail, dict) else str(detail)) or ""


def is_rate_limited(status: int, body: Any) -> bool:
    """True for the API's rate-limit failure: HTTP 503 whose message says so.

    The live client retries 429s itself and then raises "endpoint rate-limited
    after 3 attempts"; with stub fallback disabled the API reports that as 503
    ``live_ai_unavailable`` carrying that text.  Any other status, or a 503
    that does not mention rate limiting (timeouts, bad output, ...), is an
    ordinary error row.
    """
    return status == 503 and bool(_RATE_LIMIT_RE.search(_error_message(body)))


def read_manifest(path: Path = MANIFEST) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def build_payload(item: dict[str, str], n: int, photo_b64: str) -> dict[str, Any]:
    """The /inspect payload for one benchmark image (no demo_case)."""
    return {
        "truck_id": f"BENCH-{n}",
        "supplier": SUPPLIER,
        "photo_filename": f"bench-{n}.jpg",  # neutral: the class must not leak via the name
        "photo_base64": photo_b64,
        "manifest_text": MANIFEST_TEXT,
        "weight_kg": WEIGHT_KG,
        "declared_weight_kg": WEIGHT_KG,
    }


def row_from_response(
    item: dict[str, str], body: dict[str, Any], total_ms: float
) -> dict[str, Any]:
    """One result row from a successful /inspect response.

    Raises :class:`ProvenanceError` unless ``provenance == "live"``.
    """
    provenance = body.get("provenance")
    if provenance != "live":
        raise ProvenanceError(
            f"{item['image']}: response provenance is {provenance!r}, not 'live'. "
            "A benchmark row from a stub is not a measurement; check backend/.env "
            "and the endpoint, then re-run."
        )
    ai = body.get("ai_outputs") or {}
    vlm = ai.get("vlm") or {}
    llm = ai.get("llm") or {}
    detected = vlm.get("detected") or {}
    return {
        "image": item["image"],
        "category": item["category"],
        "expected": item["expected"],
        "predicted": (body.get("verdict") or {}).get("decision"),
        "gates": {name: g.get("state") for name, g in (body.get("gates") or {}).items()},
        "detected": {
            "contamination": detected.get("contamination"),
            "moisture": detected.get("moisture"),
            "hard_contaminants": detected.get("hard_contaminants") or [],
            "light_contaminants": detected.get("light_contaminants") or [],
        },
        "vlm_confidence": vlm.get("confidence"),
        "boxes": len(vlm.get("boxes") or []),
        "latency_ms": vlm.get("latency_ms"),
        "llm_latency_ms": llm.get("latency_ms"),
        "total_ms": round(total_ms, 1),
        "vlm_model": vlm.get("model"),
        "llm_model": llm.get("model"),
        "provider": vlm.get("provider"),
        "provenance": provenance,
        "record_id": body.get("record_id"),
        "reasons": body.get("reasons") or [],
        "error": None,
    }


def error_row(item: dict[str, str], message: str, total_ms: float) -> dict[str, Any]:
    return {
        "image": item["image"],
        "category": item["category"],
        "expected": item["expected"],
        "predicted": None,
        "total_ms": round(total_ms, 1),
        "error": message,
    }


def load_rows(path: Path) -> list[dict[str, Any]]:
    """Rows in the jsonl file, the last row per image winning (retries)."""
    if not path.is_file():
        return []
    latest: dict[str, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            latest[row["image"]] = row
    return list(latest.values())


def load_attempts(path: Path) -> list[dict[str, Any]]:
    """Every raw line of the jsonl, in order (failed attempts included)."""
    if not path.is_file():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def done_images(path: Path) -> set[str]:
    return {r["image"] for r in load_rows(path) if not r.get("error")}


def build_summary(
    rows: list[dict[str, Any]],
    date: str,
    manifest_n: int,
    attempts: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    """Summary of the final row per image plus the raw-attempt disclosure.

    ``attempts`` is every jsonl line (default: just ``rows``).  ``n``/latency
    cover completed requests; ``attempt_stats`` covers every attempt.
    """
    from benchmark import metrics

    summary = metrics.compute(rows)
    good = [r for r in rows if not r.get("error")]
    summary.update(
        {
            "framing": FRAMING,
            "date": date,
            "manifest_n": manifest_n,
            "complete": len(good) == manifest_n,
            "attempt_stats": metrics.attempt_stats(attempts if attempts is not None else rows),
            "vlm_model": next((r["vlm_model"] for r in good if r.get("vlm_model")), None),
            "llm_model": next((r["llm_model"] for r in good if r.get("llm_model")), None),
            "provider": next((r["provider"] for r in good if r.get("provider")), None),
            "provenance": sorted({r["provenance"] for r in good if r.get("provenance")}),
            "per_category": _per_category(rows),
        }
    )
    return summary


def _per_category(rows: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    """Predicted-label counts per RealWaste category (for the write-up)."""
    from benchmark import metrics

    table: dict[str, dict[str, int]] = {}
    for row in rows:
        cell = table.setdefault(row["category"], {c: 0 for c in metrics.COLUMNS})
        cell[metrics.label_for(row)] += 1
    return table


def _default_post(app_factory: Callable[[], Any]) -> Callable[[dict[str, Any]], tuple[int, dict[str, Any]]]:
    from fastapi.testclient import TestClient

    client = TestClient(app_factory())

    def post(payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        response = client.post("/inspect", json=payload)
        try:
            return response.status_code, response.json()
        except ValueError:
            return response.status_code, {"detail": response.text[:200]}

    return post


def _bootstrap_env() -> None:
    """Point storage at the gitignored runs dir and load backend/.env.

    Must run before ``lynceus.api`` is imported or settings are built.
    """
    os.environ["LYNCEUS_STORAGE_DIR"] = str(RUNS_DIR)
    # Fail closed: a live failure is an error row, never a silent stub verdict.
    os.environ["LYNCEUS_ALLOW_STUB_FALLBACK"] = "0"
    sys.path.insert(0, str(BACKEND_DIR))
    sys.path.insert(0, str(BACKEND_DIR / "src"))
    from lynceus import config

    config._load_dotenv(str(BACKEND_DIR / ".env"))
    os.environ["LYNCEUS_STORAGE_DIR"] = str(RUNS_DIR)


def run(
    *,
    out: Path,
    min_interval: float,
    manifest: Path = MANIFEST,
    images_dir: Path = IMAGES_DIR,
    post: Optional[Callable[[dict[str, Any]], tuple[int, dict[str, Any]]]] = None,
    sleep: Callable[[float], None] = time.sleep,
    limit: Optional[int] = None,
    log: Callable[[str], None] = print,
) -> dict[str, Any]:
    items = read_manifest(manifest)
    if post is None:
        _bootstrap_env()
        from lynceus.api import create_app

        post = _default_post(create_app)
    out.parent.mkdir(parents=True, exist_ok=True)
    done = done_images(out)
    todo = [(i, it) for i, it in enumerate(items, start=1) if it["image"] not in done]
    if limit is not None:
        todo = todo[:limit]
    log(f"{len(items)} in manifest, {len(done)} already done, {len(todo)} to run")

    consecutive_errors = 0
    last_end = 0.0
    rate_limited: Optional[str] = None
    for n, item in todo:
        wait = min_interval - (time.monotonic() - last_end) if last_end else 0.0
        if wait > 0:
            sleep(wait)
        photo = base64.b64encode((images_dir / item["image"]).read_bytes()).decode("ascii")
        started = time.perf_counter()
        status, body = post(build_payload(item, n, photo))
        total_ms = (time.perf_counter() - started) * 1000.0
        last_end = time.monotonic()
        if is_rate_limited(status, body):
            # Not a measurement: write no row, stop now, resume from here later.
            rate_limited = f"{item['image']}: {_error_message(body)}"[:300]
            log(f"[{n}/{len(items)}] {item['image']} RATE LIMITED: stopping, no row written")
            break
        if status == 200:
            row = row_from_response(item, body, total_ms)  # may abort: no row written
            consecutive_errors = 0
        else:
            message = _error_message(body)
            row = error_row(item, f"HTTP {status}: {message}"[:300], total_ms)
            consecutive_errors += 1
        with out.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        log(
            f"[{n}/{len(items)}] {item['image']} expected={item['expected']} "
            f"predicted={row.get('predicted')} total={row['total_ms']:.0f}ms"
            + (f" ERROR {row['error']}" if row.get("error") else "")
        )
        if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
            log(
                f"{MAX_CONSECUTIVE_ERRORS} consecutive errors: stopping so the shared "
                "key is not hammered. Partial results are kept; re-run to resume."
            )
            break

    rows = load_rows(out)
    summary = build_summary(rows, out.stem, len(items), load_attempts(out))
    summary_path = out.with_name(out.stem + ".summary.json")
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    log(f"summary -> {summary_path}")
    if rate_limited:
        raise RateLimitedError(
            f"endpoint rate-limited at {rate_limited}. Items already measured are kept; "
            "re-run later to resume."
        )
    return summary


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    parser.add_argument("--min-interval", type=float, default=4.0, help="seconds between requests")
    parser.add_argument("--out", type=Path, default=RESULTS_DIR / f"{today}.jsonl")
    parser.add_argument("--limit", type=int, default=None, help="run at most N pending images")
    args = parser.parse_args(argv)
    try:
        run(out=args.out, min_interval=args.min_interval, limit=args.limit)
    except (ProvenanceError, RateLimitedError) as exc:
        print(f"ABORT: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    # Importing as ``benchmark.run`` keeps ``from benchmark import metrics`` valid.
    sys.path.insert(0, str(BACKEND_DIR))
    raise SystemExit(main())
