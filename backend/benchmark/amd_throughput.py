"""Live throughput of the Lynceus vision call on AMD Token Factory.

Sends the production vision request (``pipeline._VLM_PROMPT``, the same
body: temperature 0.1, seed 0, max_tokens 1024, the photo as a JPEG data URI
downscaled to a 1280 px long edge as the web client does) to the endpoint in
``backend/.env`` through its own small httpx client, so every call's latency
and ``usage`` tokens are recorded.  Three modes over the same photos:

* ``sequential`` — per inspection, the 3 reads one after another;
* ``parallel``   — per inspection, the 3 reads at once (production);
* ``concurrent`` — 3 inspections at once, each with 3 parallel reads, at most
  :data:`MAX_IN_FLIGHT` calls in flight (Token Factory's shared key allows 8).

The CPU detector (``lynceus.detector``) is timed on the same photos.  Writes
``results/<date>.amd-throughput.json`` (summary) and ``.jsonl`` (one row per
call and per inspection).  The key is never printed, logged or written; only
the endpoint host is.

Usage (from ``backend/``)::

    PYTHONPATH=src python -m benchmark.amd_throughput --model DeepSeek-V4-Flash-Vision-Exp

Budget: at most :data:`CALLS_PER_MODE` HTTP calls per mode (JSON retries and
429/503 back-off retries included), a 1 s pause between batches.  A mode
whose first inspections all fail stops the run: an endpoint that is down is
recorded as down, never filled in.
"""

from __future__ import annotations

import argparse
import base64
import csv
import io
import json
import os
import platform
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlparse

BENCH_DIR = Path(__file__).resolve().parent
BACKEND_DIR = BENCH_DIR.parent
DEMO_DIR = BACKEND_DIR.parent / "web" / "public" / "demo"
IMAGES_DIR = BENCH_DIR / "images"
MANIFEST = BENCH_DIR / "manifest.csv"
RESULTS_DIR = BENCH_DIR / "results"

#: The web client's downscale (web/components/workspace/photo-encode.ts).
MAX_PHOTO_EDGE_PX = 1280
PHOTO_JPEG_QUALITY = 85
#: The production request body (pipeline.VLLMClient._chat_attempt / _chat_json).
TEMPERATURE = 0.1
SEED = 0
MAX_TOKENS = 1024
TIMEOUT_S = 90.0
VOTES = 3
#: Inspections run at once in the concurrent mode, and the cap on calls in
#: flight: Token Factory allows 8 concurrent calls per shared key, 2 are left
#: for teammates on the same key.
CONCURRENT_INSPECTIONS = 3
MAX_IN_FLIGHT = 6
CALLS_PER_MODE = 40
PAUSE_S = 1.0
#: Back-off waits on 429 / "no available workers" (then the call fails).
BACKOFF_S = (2.0, 5.0)
MAX_BACKOFF_S = 10.0
#: Inspections that fail outright at the start of a mode before the run stops.
ABORT_AFTER_FAILED = 3
#: Benchmark photos picked per ground-truth class (first in manifest order).
BENCH_PER_CLASS = 2
DETECTOR_REPEATS = 3
#: AMD Developer Cloud MI300X on-demand list price used for the projection.
MI300X_USD_PER_HOUR = 1.99

MODES = ("sequential", "parallel", "concurrent")
HARD = ("metal", "rock", "concrete", "tire", "e-waste")
_NO_WORKERS_RE = re.compile(r"no available workers", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Summary math (pure; unit-tested)
# ---------------------------------------------------------------------------


def _percentile(values: List[float], q: float) -> Optional[float]:
    from lynceus.amd_bench import percentile

    return percentile(values, q)


def spread(values: List[float]) -> Dict[str, Any]:
    """p50 / p95 (nearest rank), mean and n of ``values``, rounded to 0.1."""
    vals = [float(v) for v in values if isinstance(v, (int, float))]
    p50, p95 = _percentile(vals, 0.50), _percentile(vals, 0.95)
    return {
        "p50": None if p50 is None else round(p50, 1),
        "p95": None if p95 is None else round(p95, 1),
        "mean": round(sum(vals) / len(vals), 1) if vals else None,
        "n": len(vals),
    }


def hard_set(parsed: Any) -> List[str]:
    """The allow-listed hard contaminants of one parsed read, sorted."""
    raw = parsed.get("hard_contaminants") if isinstance(parsed, dict) else None
    if not isinstance(raw, list):
        return []
    return sorted({h.strip().lower() for h in raw if isinstance(h, str)} & set(HARD))


def agreement(read_sets: List[List[str]]) -> str:
    """``"3/3"`` when all reads name the same hard contaminants, ``"2/3"`` when
    exactly a majority do, ``"split"`` otherwise (any read count >= 2)."""
    keys = [tuple(s) for s in read_sets]
    top = max(keys.count(k) for k in keys)
    if top == len(keys):
        return f"{len(keys)}/{len(keys)}"
    if top > len(keys) // 2:
        return f"{top}/{len(keys)}"
    return "split"


def agreement_buckets(inspections: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Share of inspections (all 3 reads parsed) per agreement bucket."""
    labels = [i["agreement"] for i in inspections if i.get("agreement")]
    n = len(labels)
    out: Dict[str, Any] = {"n": n}
    for bucket in ("3/3", "2/3", "split"):
        count = labels.count(bucket)
        out[bucket] = {"count": count, "share": round(count / n, 3) if n else None}
    return out


def majority(read_sets: List[List[str]]) -> List[str]:
    """Hard contaminants named by more than half the reads (the production vote)."""
    votes: Dict[str, int] = {}
    for s in read_sets:
        for h in set(s):
            votes[h] = votes.get(h, 0) + 1
    return sorted(h for h, c in votes.items() if c > len(read_sets) // 2)


def speedup(sequential_p50: Optional[float], parallel_p50: Optional[float]) -> Optional[float]:
    """Parallel speed-up: sequential inspection p50 / parallel inspection p50."""
    if not sequential_p50 or not parallel_p50:
        return None
    return round(sequential_p50 / parallel_p50, 2)


def per_minute(completed: int, wall_s: float) -> Optional[float]:
    """Inspections per minute: completed over the summed batch wall time."""
    if completed <= 0 or wall_s <= 0:
        return None
    return round(completed * 60.0 / wall_s, 2)


def projection(inspections_per_min: Optional[float], usd_per_hour: float = MI300X_USD_PER_HOUR) -> Optional[Dict[str, Any]]:
    """$ per 1,000 inspections if one MI300X at ``usd_per_hour`` sustained the
    measured rate.  A projection: nothing ran on a self-hosted MI300X."""
    if not inspections_per_min:
        return None
    per_hour = inspections_per_min * 60.0
    return {
        "label": "projection, not measured on MI300X",
        "usd_per_hour": usd_per_hour,
        "inspections_per_hour": round(per_hour, 1),
        "usd_per_1k_inspections": round(usd_per_hour / per_hour * 1000.0, 2),
        "basis": "AMD Developer Cloud MI300X list price / inspections per hour "
        "measured on Token Factory in the concurrent mode",
    }


def mode_metrics(calls: List[Dict[str, Any]], inspections: List[Dict[str, Any]], wall_s: float) -> Dict[str, Any]:
    """The summary block of one mode."""
    ok_calls = [c for c in calls if c.get("status") == 200 and c.get("parsed_ok")]
    wall_s = round(wall_s, 2)  # as written, so a rebuild from the rows gives the same rate
    done = [i for i in inspections if i.get("ok")]
    tokens = [i["tokens"]["total"] for i in done if i["tokens"]["total"] is not None]
    prompt = [i["tokens"]["prompt"] for i in done if i["tokens"]["prompt"] is not None]
    completion = [i["tokens"]["completion"] for i in done if i["tokens"]["completion"] is not None]
    statuses: Dict[str, int] = {}
    for c in calls:
        key = str(c.get("status") if c.get("status") is not None else "transport_error")
        statuses[key] = statuses.get(key, 0) + 1
    return {
        "inspections": {"attempted": len(inspections), "completed": len(done)},
        "calls": len(calls),
        "read_latency_ms": spread([c["latency_ms"] for c in ok_calls]),
        "ttfb_ms": spread([c["ttfb_ms"] for c in ok_calls if c.get("ttfb_ms") is not None]),
        "inspection_latency_ms": spread([i["wall_ms"] for i in done]),
        "over_production_budget": sum(1 for i in done if i["wall_ms"] > TIMEOUT_S * 1000.0),
        "tokens_per_inspection": {
            "total": spread(tokens),
            "prompt": spread(prompt),
            "completion": spread(completion),
        },
        "wall_s": wall_s,
        "inspections_per_min": per_minute(len(done), wall_s),
        "agreement": agreement_buckets(done),
        "statuses": statuses,
        "errors": sum(1 for c in calls if c.get("error")),
        "json_retries": sum(1 for c in calls if c.get("json_retry")),
        "backoff_retries": sum(len(c.get("backoffs") or []) for c in calls),
        "rate_limited": sum(1 for c in calls for b in (c.get("backoffs") or []) if b["status"] == 429),
        "no_workers": sum(1 for c in calls for b in (c.get("backoffs") or []) if b["reason"] == "no_workers"),
        "budget_skipped": sum(1 for c in calls if c.get("error") == "budget_exhausted"),
    }


# ---------------------------------------------------------------------------
# Photos
# ---------------------------------------------------------------------------


def downscale_jpeg(data: bytes) -> tuple[bytes, tuple[int, int], bool]:
    """``(bytes sent, (w, h), re-encoded)``, as the web client encodes a photo:
    EXIF orientation applied, longest edge over 1280 px scaled down onto white
    and re-encoded as JPEG q0.85; otherwise the original bytes."""
    from PIL import Image, ImageOps

    img = ImageOps.exif_transpose(Image.open(io.BytesIO(data)))
    w, h = img.size
    if max(w, h) <= MAX_PHOTO_EDGE_PX:
        return data, (w, h), False
    scale = MAX_PHOTO_EDGE_PX / max(w, h)
    size = (max(1, round(w * scale)), max(1, round(h * scale)))
    canvas = Image.new("RGB", size, "white")
    resized = img.convert("RGBA").resize(size, Image.Resampling.LANCZOS)
    canvas.paste(resized, mask=resized.split()[3])
    out = io.BytesIO()
    canvas.save(out, "JPEG", quality=PHOTO_JPEG_QUALITY)
    return out.getvalue(), size, True


def pick_photos() -> List[Dict[str, Any]]:
    """The 6 demo photos, then the first ``BENCH_PER_CLASS`` benchmark images of
    each ground-truth class in manifest order."""
    picked: List[Dict[str, Any]] = []
    for path in sorted(DEMO_DIR.glob("t-*.jpg")):
        picked.append({"name": path.name, "source": "demo", "expected": None, "path": path})
    with MANIFEST.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    for expected in ("reject", "escalate", "accept"):
        chosen = [r for r in rows if r["expected"] == expected and (IMAGES_DIR / r["image"]).is_file()]
        for r in chosen[:BENCH_PER_CLASS]:
            picked.append({"name": r["image"], "source": "benchmark", "expected": expected,
                           "category": r["category"], "path": IMAGES_DIR / r["image"]})
    for p in picked:
        raw = p["path"].read_bytes()
        sent, size, reencoded = downscale_jpeg(raw)
        p.update(raw_bytes=raw, bytes=sent, b64=base64.b64encode(sent).decode("ascii"),
                 sent_px=list(size), sent_bytes=len(sent), reencoded=reencoded)
    return picked


# ---------------------------------------------------------------------------
# Endpoint client
# ---------------------------------------------------------------------------


class BudgetExhausted(RuntimeError):
    pass


class Budget:
    """A thread-safe count of HTTP calls left in one mode."""

    def __init__(self, calls: int) -> None:
        self._left = calls
        self._lock = threading.Lock()

    def take(self) -> None:
        with self._lock:
            if self._left <= 0:
                raise BudgetExhausted("budget_exhausted")
            self._left -= 1


def _check_deadline(started: float) -> None:
    """Production's wall-clock read budget: a trickling stream fails at 90 s."""
    if time.perf_counter() - started > TIMEOUT_S:
        raise TimeoutError(f"no complete reply within {TIMEOUT_S:g} s")


def _parse_body(response: Any, started: float) -> tuple[str, Optional[Dict[str, Any]], Optional[float]]:
    """``(content, usage, ttfb_ms)`` from an SSE or plain JSON reply."""
    ttfb_ms: Optional[float] = None
    content_type = response.headers.get("content-type", "")
    if "text/event-stream" in content_type:
        parts: List[str] = []
        usage: Optional[Dict[str, Any]] = None
        for line in response.iter_lines():
            _check_deadline(started)
            if ttfb_ms is None:
                ttfb_ms = (time.perf_counter() - started) * 1000.0
            line = line.strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                chunk = json.loads(data)
            except ValueError:
                continue
            if isinstance(chunk.get("usage"), dict):
                usage = chunk["usage"]
            try:
                delta = chunk["choices"][0]["delta"].get("content")
            except (KeyError, IndexError, TypeError, AttributeError):
                delta = None
            if delta:
                parts.append(delta)
        return "".join(parts), usage, ttfb_ms
    body = bytearray()
    for chunk in response.iter_bytes():
        _check_deadline(started)
        if ttfb_ms is None:
            ttfb_ms = (time.perf_counter() - started) * 1000.0
        body.extend(chunk)
    payload = json.loads(body.decode("utf-8"))
    usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else None
    return str(payload["choices"][0]["message"]["content"]), usage, ttfb_ms


class Endpoint:
    """The production vision request, with timing and usage captured."""

    def __init__(self, url: str, key: str, model: str, prompt: str,
                 extract_json: Callable[[str], Optional[Dict[str, Any]]],
                 in_flight: Optional[threading.Semaphore] = None,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        import httpx

        self.url = f"{url.rstrip('/')}/chat/completions"
        self.model = model
        self.prompt = prompt
        self._extract = extract_json
        self._headers = {"Authorization": f"Bearer {key}"} if key else {}
        self._client = httpx.Client(timeout=TIMEOUT_S)
        self.in_flight = in_flight
        self._sleep = sleep

    def close(self) -> None:
        self._client.close()

    def _post(self, messages: list, budget: Budget) -> Dict[str, Any]:
        """One chat call with up to 2 back-offs on 429 / no available workers."""
        backoffs: List[Dict[str, Any]] = []
        for attempt in range(len(BACKOFF_S) + 1):
            budget.take()
            body = {"model": self.model, "messages": messages, "max_tokens": MAX_TOKENS,
                    "temperature": TEMPERATURE, "seed": SEED}
            gate = self.in_flight
            if gate is not None:
                gate.acquire()
            started = time.perf_counter()
            try:
                with self._client.stream("POST", self.url, json=body, headers=self._headers) as r:
                    status = r.status_code
                    if status == 200:
                        content, usage, ttfb = _parse_body(r, started)
                        return {"status": 200, "content": content, "usage": usage, "ttfb_ms": ttfb,
                                "latency_ms": (time.perf_counter() - started) * 1000.0,
                                "backoffs": backoffs}
                    text = r.read().decode("utf-8", "replace")[:300]
                    latency_ms = (time.perf_counter() - started) * 1000.0
                    retry_after = r.headers.get("retry-after")
            finally:
                if gate is not None:
                    gate.release()
            reason = "rate_limited" if status == 429 else (
                "no_workers" if _NO_WORKERS_RE.search(text) else None)
            if reason is None or attempt == len(BACKOFF_S):
                return {"status": status, "error": f"HTTP {status}: {text}", "latency_ms": latency_ms,
                        "backoffs": backoffs}
            try:
                wait = float(retry_after) if retry_after else BACKOFF_S[attempt]
            except ValueError:
                wait = BACKOFF_S[attempt]
            wait = min(MAX_BACKOFF_S, max(wait, BACKOFF_S[attempt]))
            backoffs.append({"status": status, "reason": reason, "wait_s": wait})
            self._sleep(wait)
        raise AssertionError("unreachable")

    def read(self, photo_b64: str, budget: Budget) -> Dict[str, Any]:
        """One vision read: the call, and one JSON retry as production does."""
        messages = [{"role": "user", "content": [
            {"type": "text", "text": self.prompt},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{photo_b64}"}},
        ]}]
        row: Dict[str, Any] = {"started_utc": datetime.now(timezone.utc).isoformat(timespec="milliseconds")}
        wall = time.perf_counter()
        usage_total = {"prompt": 0, "completion": 0, "total": 0, "reported": 0}

        def call(msgs: list) -> Dict[str, Any]:
            try:
                out = self._post(msgs, budget)
            except BudgetExhausted:
                return {"status": None, "error": "budget_exhausted", "latency_ms": None, "backoffs": []}
            except Exception as exc:  # noqa: BLE001 — transport or malformed body: an error row
                return {"status": None, "error": f"{type(exc).__name__}: {str(exc)[:200]}",
                        "latency_ms": None, "backoffs": []}
            usage = out.get("usage")
            if isinstance(usage, dict):
                usage_total["reported"] += 1
                for k, src in (("prompt", "prompt_tokens"), ("completion", "completion_tokens"),
                               ("total", "total_tokens")):
                    if isinstance(usage.get(src), (int, float)):
                        usage_total[k] += int(usage[src])
            return out

        first = call(messages)
        row.update(status=first["status"], ttfb_ms=_r(first.get("ttfb_ms")),
                   backoffs=list(first.get("backoffs") or []), json_retry=False)
        parsed = None
        if first["status"] == 200:
            parsed = self._extract(first["content"])
            if parsed is None:
                row["json_retry"] = True
                retry = call(messages + [
                    {"role": "assistant", "content": first["content"]},
                    {"role": "user", "content": "Your previous reply was not valid JSON. "
                     "Reply again with ONLY the JSON object — no prose, no code fences."},
                ])
                row["status"] = retry["status"]
                row["backoffs"] += list(retry.get("backoffs") or [])
                if retry["status"] == 200:
                    parsed = self._extract(retry["content"])
                    if parsed is None:
                        row["error"] = "unparseable JSON after one retry"
                else:
                    row["error"] = retry.get("error")
        else:
            row["error"] = first.get("error")
        row["latency_ms"] = _r((time.perf_counter() - wall) * 1000.0)
        reported = usage_total["reported"] > 0
        row["usage"] = {k: (usage_total[k] if reported else None) for k in ("prompt", "completion", "total")}
        row["parsed_ok"] = parsed is not None
        row["hard"] = hard_set(parsed) if parsed is not None else None
        conf = parsed.get("confidence") if isinstance(parsed, dict) else None
        row["confidence"] = float(conf) if isinstance(conf, (int, float)) and not isinstance(conf, bool) else None
        return row


def _r(value: Optional[float]) -> Optional[float]:
    return None if value is None else round(float(value), 1)


# ---------------------------------------------------------------------------
# Modes
# ---------------------------------------------------------------------------


def run_inspection(endpoint: Endpoint, photo: Dict[str, Any], mode: str, index: int,
                   budget: Budget, parallel: bool) -> tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """One inspection: ``VOTES`` reads, sequential or at once."""
    started = time.perf_counter()
    if parallel:
        with ThreadPoolExecutor(max_workers=VOTES) as pool:
            reads = list(pool.map(lambda _i: endpoint.read(photo["b64"], budget), range(VOTES)))
    else:
        reads = [endpoint.read(photo["b64"], budget) for _ in range(VOTES)]
    wall_ms = (time.perf_counter() - started) * 1000.0
    inspection_id = f"{mode}-{index:02d}"
    calls = []
    for n, read in enumerate(reads, 1):
        calls.append({"type": "call", "mode": mode, "inspection": inspection_id, "photo": photo["name"],
                      "read": n, **read})
    ok = all(c["parsed_ok"] for c in calls)
    sets = [c["hard"] for c in calls] if ok else []
    totals = {k: (sum(c["usage"][k] for c in calls) if ok and all(c["usage"][k] is not None for c in calls)
                  else None) for k in ("prompt", "completion", "total")}
    inspection = {
        "type": "inspection", "mode": mode, "inspection": inspection_id, "photo": photo["name"],
        "source": photo["source"], "expected": photo.get("expected"), "ok": ok,
        "wall_ms": _r(wall_ms), "tokens": totals,
        "read_hard": sets or None, "voted_hard": majority(sets) if ok else None,
        "agreement": agreement(sets) if ok else None,
        "confidences": [c["confidence"] for c in calls],
    }
    return inspection, calls


def run_mode(endpoint: Endpoint, photos: List[Dict[str, Any]], mode: str,
             log: Callable[[str], None], pause: Callable[[float], None] = time.sleep) -> Dict[str, Any]:
    """Every photo once in ``mode``; stops early if the endpoint looks down."""
    budget = Budget(CALLS_PER_MODE)
    inspections: List[Dict[str, Any]] = []
    calls: List[Dict[str, Any]] = []
    wall_s = 0.0
    aborted: Optional[str] = None
    size = CONCURRENT_INSPECTIONS if mode == "concurrent" else 1
    batches = [photos[i:i + size] for i in range(0, len(photos), size)]
    for b, batch in enumerate(batches):
        if b:
            pause(PAUSE_S)
        started = time.perf_counter()
        base = len(inspections)
        if size == 1:
            results = [run_inspection(endpoint, batch[0], mode, base + 1, budget, mode != "sequential")]
        else:
            with ThreadPoolExecutor(max_workers=len(batch)) as pool:
                futures = [pool.submit(run_inspection, endpoint, p, mode, base + k + 1, budget, True)
                           for k, p in enumerate(batch)]
                results = [f.result() for f in futures]
        wall_s += time.perf_counter() - started
        for inspection, rows in results:
            inspections.append(inspection)
            calls.extend(rows)
            log(f"  {mode} {inspection['inspection']} {inspection['photo']}: "
                f"{'ok' if inspection['ok'] else 'FAILED'} {inspection['wall_ms']} ms "
                f"hard={inspection['read_hard']}")
        if all(c.get("error") == "budget_exhausted" for c in calls[-VOTES * len(batch):]):
            aborted = "call budget for this mode spent"
            break
        if len(inspections) >= ABORT_AFTER_FAILED and not any(i["ok"] for i in inspections):
            aborted = f"the first {len(inspections)} inspections all failed; endpoint treated as down"
            break
    return {"inspections": inspections, "calls": calls, "wall_s": wall_s, "aborted": aborted}


def time_detector(photos: List[Dict[str, Any]], log: Callable[[str], None]) -> Dict[str, Any]:
    """CPU detector latency on the same (sent) photos, warm model."""
    try:
        from lynceus import detector
        from lynceus.config import get_settings
    except ImportError as exc:
        return {"available": False, "reason": f"import failed: {exc}"}
    settings = get_settings()
    if not detector.warm(settings):
        return {"available": False, "reason": "detector disabled (no model or runtime)"}
    detector.detect(photos[0]["bytes"], settings)  # first run pays session setup
    inference: List[float] = []
    wall: List[float] = []
    for _ in range(DETECTOR_REPEATS):
        for p in photos:
            started = time.perf_counter()
            out = detector.detect(p["bytes"], settings)
            wall.append((time.perf_counter() - started) * 1000.0)
            if out and isinstance(out.get("latency_ms"), (int, float)):
                inference.append(float(out["latency_ms"]))
    log(f"  detector: {len(wall)} runs")
    return {
        "available": True,
        "model": os.path.basename(settings.detector_model_path),
        "runtime": "onnxruntime-cpu",
        "threads": settings.detector_threads,
        "cpu": platform.processor() or platform.machine(),
        "cpu_count": os.cpu_count(),
        "runs": len(wall),
        "inference_ms": spread(inference),
        "call_wall_ms": spread(wall),
        "note": "inference_ms is the detector's own timing (decode + model); call_wall_ms "
        "adds the run slot. Measured on the benchmark machine's CPU, not the deployment host.",
    }


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


def build_summary(run: Dict[str, Any]) -> Dict[str, Any]:
    """The summary JSON from the raw mode results (pure)."""
    modes = {m: mode_metrics(r["calls"], r["inspections"], r["wall_s"]) for m, r in run["modes"].items()}
    for m, r in run["modes"].items():
        modes[m]["aborted"] = r.get("aborted")
    seq = modes.get("sequential", {}).get("inspection_latency_ms", {}).get("p50")
    par = modes.get("parallel", {}).get("inspection_latency_ms", {}).get("p50")
    conc = modes.get("concurrent", {})
    per_min = conc.get("inspections_per_min")
    all_done = [i for r in run["modes"].values() for i in r["inspections"] if i.get("ok")]
    all_calls = [c for r in run["modes"].values() for c in r["calls"]]
    tokens = spread([i["tokens"]["total"] for i in all_done if i["tokens"]["total"] is not None])
    usage_reported = any(c.get("usage", {}).get("total") is not None for c in all_calls)
    production = modes.get("parallel", {})
    return {
        "kind": "amd_throughput",
        "run_date": run["run_date"],
        "started_at_utc": run["started_at_utc"],
        "finished_at_utc": run["finished_at_utc"],
        "provider": "amd-token-factory",
        "endpoint_host": run["endpoint_host"],
        "model": run["model"],
        "settings": {
            "votes": VOTES, "temperature": TEMPERATURE, "seed": SEED, "max_tokens": MAX_TOKENS,
            "timeout_s": TIMEOUT_S, "image_max_edge_px": MAX_PHOTO_EDGE_PX,
            "jpeg_quality": PHOTO_JPEG_QUALITY, "concurrent_inspections": CONCURRENT_INSPECTIONS,
            "max_in_flight": MAX_IN_FLIGHT, "calls_per_mode_budget": CALLS_PER_MODE,
            "pause_between_batches_s": PAUSE_S, "prompt": "lynceus.pipeline._VLM_PROMPT",
            "json_retry": "one, as production", "stream": "not requested (as production)",
        },
        "photos": run["photos"],
        "headline": {
            "read_latency_ms": production.get("read_latency_ms"),
            "inspection_latency_ms": production.get("inspection_latency_ms"),
            "inspections_per_min_concurrent": per_min,
            "tokens_per_inspection": tokens,
            "parallel_speedup": speedup(seq, par),
            "read_agreement": agreement_buckets(all_done),
            "errors": sum(m["errors"] for m in modes.values()),
            "retries": sum(m["json_retries"] + m["backoff_retries"] for m in modes.values()),
            "calls": len(all_calls),
        },
        "modes": modes,
        "detector_cpu": run.get("detector"),
        "cost": {
            "token_factory": {
                "basis": "quota-based",
                "tokens_per_inspection": tokens,
                "note": "AMD Token Factory is a free tier with a usage quota "
                "(about $10/day per third-party sources; the terms are not published), "
                "so no per-call price is claimed.",
            },
            "mi300x_projection": projection(per_min),
        },
        "usage_reported": usage_reported,
        "aborted": next((r["aborted"] for r in run["modes"].values() if r.get("aborted")), None),
        "caveats": caveats(run, usage_reported),
        "raw_rows": run["raw_rows"],
    }


def caveats(run: Dict[str, Any], usage_reported: bool) -> List[str]:
    out = [
        "One run on a shared, hosted endpoint (AMD Token Factory): latency includes "
        "network and queueing and moves with the endpoint's load at the time.",
        f"{len(run['photos'])} photos per mode (6 demo photos + 6 RealWaste benchmark "
        "images), 3 reads per inspection; small n, so p95 is close to the slowest call.",
        f"Concurrent mode runs {CONCURRENT_INSPECTIONS} inspections at once with at most "
        f"{MAX_IN_FLIGHT} calls in flight (the shared key allows 8). The production "
        "server caps vision reads at 3 in flight process-wide, so one server's "
        "throughput is the parallel mode's, not this one's.",
        "The modes ran one after another, not interleaved: endpoint load may differ "
        "between them, which moves the speed-up.",
        "Read agreement compares the allow-listed hard contaminants of each read; "
        "temperature 0.1 and seed 0 as production.",
        "The MI300X cost is a projection from Token Factory throughput, not a "
        "measurement on a self-hosted MI300X.",
        "The CPU detector was timed on the benchmark machine, not the deployment host.",
        f"Each call here fails at {TIMEOUT_S:g} s wall clock. Production gives the whole "
        f"vote (every read and retry) one {TIMEOUT_S:g} s budget, so an inspection "
        "counted in over_production_budget would have gone to the fallback model or "
        "the detector-only hold in production.",
    ]
    if not usage_reported:
        out.append("The endpoint returned no usage block, so token counts are not available.")
    if run.get("model_note"):
        out.append(run["model_note"])
    return out


def rebuild_run(summary: Dict[str, Any], rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """The ``run`` behind a written summary, from its raw rows (pure): the
    summary math can be re-derived without a single new call.  Batch wall
    times, the detector block and the photo list come from the summary."""
    run: Dict[str, Any] = {k: summary.get(k) for k in (
        "run_date", "started_at_utc", "finished_at_utc", "endpoint_host", "model",
        "photos", "raw_rows")}
    run["detector"] = summary.get("detector_cpu")
    run["model_note"] = next((c for c in summary.get("caveats") or []
                              if c.startswith("Model set on the command line")), None)
    run["modes"] = {}
    for mode, block in (summary.get("modes") or {}).items():
        run["modes"][mode] = {
            "calls": [r for r in rows if r.get("mode") == mode and r.get("type") == "call"],
            "inspections": [r for r in rows if r.get("mode") == mode and r.get("type") == "inspection"],
            "wall_s": float(block.get("wall_s") or 0.0),
            "aborted": block.get("aborted"),
        }
    return run


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", default=None, help="vision model (default: VLM_MODEL)")
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--out-dir", type=Path, default=RESULTS_DIR)
    parser.add_argument("--skip-detector", action="store_true")
    parser.add_argument("--from-raw", action="store_true",
                        help="rebuild the summary of --date from its .jsonl rows; no calls")
    args = parser.parse_args(argv)

    if args.from_raw:
        out = args.out_dir / f"{args.date}.amd-throughput.json"
        old = json.loads(out.read_text(encoding="utf-8"))
        raw = args.out_dir / old["raw_rows"]
        rows = [json.loads(line) for line in raw.read_text(encoding="utf-8").splitlines() if line.strip()]
        summary = build_summary(rebuild_run(old, rows))
        out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        print(f"summary rebuilt from {raw.name} -> {out}")
        return 0

    sys.path.insert(0, str(BACKEND_DIR / "src"))
    os.chdir(BACKEND_DIR)  # lynceus.config loads backend/.env relative to the cwd
    from lynceus import config, pipeline

    settings = config.get_settings()
    model = args.model or settings.vlm_model
    host = urlparse(settings.vllm_vlm_url).hostname or ""
    log = lambda msg: print(msg, flush=True)  # noqa: E731
    if not settings.vllm_api_key:
        log("VLLM_API_KEY is not set (backend/.env); nothing measured.")
        return 2
    log(f"AMD throughput: model={model} host={host}")

    photos = pick_photos()
    log(f"photos: {len(photos)}")
    endpoint = Endpoint(settings.vllm_vlm_url, settings.vllm_api_key, model,
                        pipeline._VLM_PROMPT, pipeline._extract_json)
    run: Dict[str, Any] = {
        "run_date": args.date, "endpoint_host": host, "model": model,
        "started_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "photos": [{k: p.get(k) for k in ("name", "source", "expected", "category", "sent_px",
                                          "sent_bytes", "reencoded")} for p in photos],
        "modes": {},
    }
    if model != settings.vlm_model:
        run["model_note"] = (f"Model set on the command line ({model}); the local "
                             f"backend/.env names {settings.vlm_model}.")
    try:
        for i, mode in enumerate(MODES):
            if i:
                time.sleep(PAUSE_S)
            endpoint.in_flight = threading.BoundedSemaphore(MAX_IN_FLIGHT) if mode == "concurrent" else None
            log(f"mode {mode}")
            run["modes"][mode] = run_mode(endpoint, photos, mode, log)
            if run["modes"][mode]["aborted"] and not any(x["ok"] for x in run["modes"][mode]["inspections"]):
                log(f"stopping: {run['modes'][mode]['aborted']}")
                break
    finally:
        endpoint.close()
    run["detector"] = None if args.skip_detector else time_detector(photos, log)
    run["finished_at_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    raw = args.out_dir / f"{args.date}.amd-throughput.jsonl"
    run["raw_rows"] = raw.name
    with raw.open("w", encoding="utf-8") as fh:
        for r in run["modes"].values():
            for row in r["calls"] + r["inspections"]:
                fh.write(json.dumps(row, sort_keys=True) + "\n")
    summary = build_summary(run)
    out = args.out_dir / f"{args.date}.amd-throughput.json"
    out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    log(f"summary -> {out}")
    log(json.dumps(summary["headline"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
