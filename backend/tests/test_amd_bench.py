"""AMD throughput benchmark: summary math, endpoint client, readers, route.

All network is mocked (httpx.MockTransport or a fake endpoint); nothing here
calls AMD Token Factory.
"""

from __future__ import annotations

import io
import json
import os
import sys
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from benchmark import amd_throughput as at  # noqa: E402
from lynceus import amd_bench, api, auth, pipeline  # noqa: E402
from lynceus.config import LYNCEUS_STORAGE_DIR_ENV  # noqa: E402

RESULTS = Path(__file__).resolve().parents[1] / "benchmark" / "results"
READ = {"contamination": "x", "moisture": 0.1, "hard_contaminants": ["metal"],
        "light_contaminants": [], "confidence": 0.8, "locations": []}


# ---------------------------------------------------------------------------
# Summary math
# ---------------------------------------------------------------------------


def test_percentile_is_nearest_rank():
    vals = [float(v) for v in range(1, 21)]  # 1..20
    assert amd_bench.percentile(vals, 0.50) == 10.0
    assert amd_bench.percentile(vals, 0.95) == 19.0
    assert amd_bench.percentile([7.0], 0.95) == 7.0
    assert amd_bench.percentile([], 0.5) is None
    assert at.spread([3, 1, 2]) == {"p50": 2.0, "p95": 3.0, "mean": 2.0, "n": 3}
    assert at.spread([]) == {"p50": None, "p95": None, "mean": None, "n": 0}


def test_agreement_buckets_and_majority():
    assert at.agreement([["metal"], ["metal"], ["metal"]]) == "3/3"
    assert at.agreement([[], [], []]) == "3/3"
    assert at.agreement([["metal"], ["metal"], []]) == "2/3"
    assert at.agreement([["metal"], ["rock"], []]) == "split"
    assert at.majority([["metal"], ["metal", "rock"], []]) == ["metal"]
    assert at.majority([["metal"], ["rock"], []]) == []
    inspections = [{"agreement": a} for a in ("3/3", "3/3", "2/3", "split")] + [{"agreement": None}]
    b = at.agreement_buckets(inspections)
    assert b["n"] == 4
    assert b["3/3"] == {"count": 2, "share": 0.5}
    assert b["2/3"] == {"count": 1, "share": 0.25}
    assert b["split"] == {"count": 1, "share": 0.25}
    assert at.agreement_buckets([])["3/3"] == {"count": 0, "share": None}


def test_hard_set_keeps_allowlisted_strings_only():
    assert at.hard_set({"hard_contaminants": ["Metal", "metal", "plastic", 3, "tire"]}) == ["metal", "tire"]
    assert at.hard_set({"hard_contaminants": "metal"}) == []
    assert at.hard_set(None) == []


def test_speedup_rate_and_projection():
    assert at.speedup(30000.0, 10000.0) == 3.0
    assert at.speedup(None, 10000.0) is None
    assert at.speedup(30000.0, 0) is None
    assert at.per_minute(12, 120.0) == 6.0
    assert at.per_minute(0, 120.0) is None
    p = at.projection(6.0)  # 360 inspections/h
    assert p["label"] == "projection, not measured on MI300X"
    assert p["inspections_per_hour"] == 360.0
    assert p["usd_per_1k_inspections"] == round(1.99 / 360 * 1000, 2) == 5.53
    assert at.projection(None) is None


# ---------------------------------------------------------------------------
# Photos
# ---------------------------------------------------------------------------


def _jpeg(w: int, h: int) -> bytes:
    from PIL import Image

    out = io.BytesIO()
    Image.new("RGB", (w, h), (90, 90, 90)).save(out, "JPEG")
    return out.getvalue()


def test_downscale_matches_the_web_client():
    from PIL import Image

    sent, size, reencoded = at.downscale_jpeg(_jpeg(1536, 1024))
    assert reencoded and size == (1280, 853)
    assert Image.open(io.BytesIO(sent)).size == (1280, 853)
    small = _jpeg(524, 524)
    assert at.downscale_jpeg(small) == (small, (524, 524), False)


# ---------------------------------------------------------------------------
# Endpoint client (mocked transport)
# ---------------------------------------------------------------------------


def _endpoint(handler, **kw) -> at.Endpoint:
    ep = at.Endpoint("https://tf.example/v1", "k-secret", "m", "PROMPT", pipeline._extract_json,
                     sleep=kw.pop("sleep", lambda s: None), **kw)
    ep._client = httpx.Client(transport=httpx.MockTransport(handler))
    return ep


def _json_reply(content: str, usage=None) -> httpx.Response:
    body = {"choices": [{"message": {"content": content}}]}
    if usage is not None:
        body["usage"] = usage
    return httpx.Response(200, json=body)


def test_read_sends_the_production_body_and_records_usage():
    seen = []

    def handler(request):
        seen.append(request)
        return _json_reply(json.dumps(READ), {"prompt_tokens": 900, "completion_tokens": 60,
                                              "total_tokens": 960})

    row = _endpoint(handler).read("QUJD", at.Budget(5))
    body = json.loads(seen[0].content)
    assert body["temperature"] == 0.1 and body["seed"] == 0 and body["max_tokens"] == 1024
    assert "stream" not in body
    assert body["messages"][0]["content"][0]["text"] == "PROMPT"
    assert body["messages"][0]["content"][1]["image_url"]["url"] == "data:image/jpeg;base64,QUJD"
    assert seen[0].headers["authorization"] == "Bearer k-secret"
    assert row["status"] == 200 and row["parsed_ok"] and row["hard"] == ["metal"]
    assert row["confidence"] == 0.8 and row["json_retry"] is False
    assert row["usage"] == {"prompt": 900, "completion": 60, "total": 960}
    assert "k-secret" not in json.dumps(row)


def test_read_parses_sse_and_its_usage_chunk():
    content = json.dumps(READ)
    lines = [f"data: {json.dumps({'choices': [{'delta': {'content': content[:20]}}]})}",
             f"data: {json.dumps({'choices': [{'delta': {'content': content[20:]}}]})}",
             f"data: {json.dumps({'choices': [], 'usage': {'prompt_tokens': 5, 'completion_tokens': 2, 'total_tokens': 7}})}",
             "data: [DONE]", ""]

    def handler(request):
        return httpx.Response(200, headers={"content-type": "text/event-stream"},
                              content="\n".join(lines).encode())

    row = _endpoint(handler).read("QUJD", at.Budget(5))
    assert row["parsed_ok"] and row["hard"] == ["metal"]
    assert row["usage"]["total"] == 7 and row["ttfb_ms"] is not None


def test_read_retries_unparseable_json_once_and_sums_usage():
    replies = iter([_json_reply("not json", {"total_tokens": 10, "prompt_tokens": 8, "completion_tokens": 2}),
                    _json_reply(json.dumps(READ), {"total_tokens": 20, "prompt_tokens": 15, "completion_tokens": 5})])
    row = _endpoint(lambda r: next(replies)).read("QUJD", at.Budget(5))
    assert row["json_retry"] and row["parsed_ok"]
    assert row["usage"] == {"prompt": 23, "completion": 7, "total": 30}


def test_read_backs_off_on_429_and_no_workers():
    waits = []
    replies = iter([httpx.Response(429, headers={"retry-after": "3"}, text="slow down"),
                    httpx.Response(503, text='{"error": "no available workers"}'),
                    _json_reply(json.dumps(READ))])
    row = _endpoint(lambda r: next(replies), sleep=waits.append).read("QUJD", at.Budget(5))
    assert row["parsed_ok"] and row["status"] == 200
    assert [b["reason"] for b in row["backoffs"]] == ["rate_limited", "no_workers"]
    assert waits == [3.0, 5.0]
    assert row["usage"] == {"prompt": None, "completion": None, "total": None}


def test_read_gives_up_after_two_backoffs_and_on_other_errors():
    row = _endpoint(lambda r: httpx.Response(429, text="no")).read("QUJD", at.Budget(9))
    assert row["status"] == 429 and not row["parsed_ok"] and len(row["backoffs"]) == 2
    row = _endpoint(lambda r: httpx.Response(400, text="model not supported")).read("QUJD", at.Budget(9))
    assert row["status"] == 400 and row["backoffs"] == [] and "400" in row["error"]

    def boom(request):
        raise httpx.ConnectError("down")

    row = _endpoint(boom).read("QUJD", at.Budget(9))
    assert row["status"] is None and "ConnectError" in row["error"]


def test_budget_caps_calls():
    calls = []
    ep = _endpoint(lambda r: calls.append(1) or _json_reply(json.dumps(READ)))
    budget = at.Budget(2)
    assert ep.read("QUJD", budget)["parsed_ok"]
    assert ep.read("QUJD", budget)["parsed_ok"]
    row = ep.read("QUJD", budget)
    assert row["error"] == "budget_exhausted" and len(calls) == 2


# ---------------------------------------------------------------------------
# Modes + summary
# ---------------------------------------------------------------------------


class _FakeEndpoint:
    """Reads that name metal on 2 of 3 calls for demo photos, nothing else."""

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.n = 0
        self.in_flight = None

    def read(self, photo_b64, budget):
        try:
            budget.take()
        except at.BudgetExhausted:
            return {"status": None, "error": "budget_exhausted", "latency_ms": None, "ttfb_ms": None,
                    "backoffs": [], "json_retry": False, "usage": {"prompt": None, "completion": None,
                    "total": None}, "parsed_ok": False, "hard": None, "confidence": None}
        self.n += 1
        if self.fail:
            return {"status": 503, "error": "HTTP 503", "latency_ms": 5.0, "ttfb_ms": None,
                    "backoffs": [], "json_retry": False, "usage": {"prompt": None, "completion": None,
                    "total": None}, "parsed_ok": False, "hard": None, "confidence": None}
        hard = ["metal"] if photo_b64 == "metal" and self.n % 3 else []
        return {"status": 200, "latency_ms": 100.0, "ttfb_ms": 50.0, "backoffs": [],
                "json_retry": False, "usage": {"prompt": 900, "completion": 100, "total": 1000},
                "parsed_ok": True, "hard": hard, "confidence": 0.7}


def _photos(n=4):
    return [{"name": f"p{i}.jpg", "source": "demo", "b64": "metal" if i % 2 else "clean"} for i in range(n)]


def test_run_mode_and_summary_shape():
    log = []
    run = {"run_date": "2026-10-17", "started_at_utc": "s", "finished_at_utc": "f",
           "endpoint_host": "tf.example", "model": "m", "photos": [{"name": "p"}] * 4,
           "raw_rows": "x.jsonl", "detector": {"available": False}, "modes": {}}
    for mode in at.MODES:
        run["modes"][mode] = at.run_mode(_FakeEndpoint(), _photos(), mode, log.append, pause=lambda s: None)
    conc = run["modes"]["concurrent"]
    assert len(conc["inspections"]) == 4 and len(conc["calls"]) == 12 and conc["aborted"] is None
    s = at.build_summary(run)
    assert s["kind"] == "amd_throughput" and s["endpoint_host"] == "tf.example"
    h = s["headline"]
    assert h["tokens_per_inspection"]["p50"] == 3000.0
    assert h["calls"] == 36 and h["errors"] == 0
    assert h["read_agreement"]["n"] == 12
    assert h["read_agreement"]["3/3"]["count"] + h["read_agreement"]["2/3"]["count"] == 12
    assert s["cost"]["token_factory"]["basis"] == "quota-based"
    assert s["cost"]["mi300x_projection"]["label"] == "projection, not measured on MI300X"
    assert s["modes"]["parallel"]["read_latency_ms"]["p50"] == 100.0
    assert s["usage_reported"] is True
    assert any("projection" in c for c in s["caveats"])


def test_summary_rebuilds_from_raw_rows_without_calls(tmp_path):
    run = {"run_date": "2026-10-17", "started_at_utc": "s", "finished_at_utc": "f",
           "endpoint_host": "tf.example", "model": "m", "photos": [{"name": "p"}] * 4,
           "raw_rows": "x.jsonl", "detector": {"available": False},
           "model_note": "Model set on the command line (m); the local backend/.env names n.",
           "modes": {m: at.run_mode(_FakeEndpoint(), _photos(), m, lambda s: None, pause=lambda s: None)
                     for m in at.MODES}}
    summary = at.build_summary(run)
    rows = [row for r in run["modes"].values() for row in r["calls"] + r["inspections"]]
    rows = [json.loads(json.dumps(row)) for row in rows]  # through JSON, as the .jsonl is
    rebuilt = at.build_summary(at.rebuild_run(json.loads(json.dumps(summary)), rows))
    assert rebuilt == json.loads(json.dumps(summary))


def test_run_mode_stops_when_the_endpoint_is_down():
    fake = _FakeEndpoint(fail=True)
    out = at.run_mode(fake, _photos(6), "parallel", lambda m: None, pause=lambda s: None)
    assert out["aborted"] and len(out["inspections"]) == at.ABORT_AFTER_FAILED
    assert fake.n == at.ABORT_AFTER_FAILED * at.VOTES


def test_run_mode_stops_when_the_budget_is_spent(monkeypatch):
    monkeypatch.setattr(at, "CALLS_PER_MODE", 4)
    out = at.run_mode(_FakeEndpoint(), _photos(6), "sequential", lambda m: None, pause=lambda s: None)
    assert out["aborted"] == "call budget for this mode spent"


# ---------------------------------------------------------------------------
# latest()
# ---------------------------------------------------------------------------


def test_latest_reads_the_newest_throughput_file(tmp_path):
    assert amd_bench.latest(tmp_path) is None
    (tmp_path / "2026-10-16.amd-throughput.json").write_text(json.dumps({"kind": "amd_throughput", "d": 16}))
    (tmp_path / "2026-10-17.amd-throughput.json").write_text(json.dumps({"kind": "amd_throughput", "d": 17}))
    (tmp_path / "2026-10-18.amd-throughput.json").write_text("{broken")
    (tmp_path / "2026-10-19.amd-throughput.json").write_text(json.dumps({"kind": "other"}))
    got = amd_bench.latest(tmp_path)
    assert got["d"] == 17 and got["file"] == "2026-10-17.amd-throughput.json"


# ---------------------------------------------------------------------------
# live_telemetry()
# ---------------------------------------------------------------------------


def _record(storage: Path, n: int, provenance: str = "live", status: str = "completed",
            vlm_ms=1000.0, det_ms=40.0) -> Path:
    d = storage / f"inspection-{n:06d}"
    d.mkdir(parents=True, exist_ok=True)
    rec = {"record_id": d.name, "execution_status": status, "finished_at_utc": "2026-10-17T00:00:00Z",
           "verdict": {"uncertainty": f"AI provenance: {provenance}. Verdict is a screening estimate."},
           "ai_outputs": {"vlm": {"latency_ms": vlm_ms, "model": "DeepSeek-V4-Flash-Vision-Exp",
                                  "provider": "amd-token-factory"},
                          "detector": {"latency_ms": det_ms} if det_ms is not None else None}}
    path = d / "audit.json"
    path.write_text(json.dumps(rec), encoding="utf-8")
    return path


def test_live_telemetry_counts_only_completed_live_records(tmp_path):
    for i in range(1, 11):
        _record(tmp_path, i, vlm_ms=float(i * 1000), det_ms=float(i * 10))
    _record(tmp_path, 11, provenance="stub")
    _record(tmp_path, 12, provenance="stub_fallback_live_error")
    _record(tmp_path, 13, provenance="detector_only_degraded")
    _record(tmp_path, 14, status="in_progress")
    _record(tmp_path, 15, det_ms=None, vlm_ms=11000.0)
    (tmp_path / "not-an-inspection").mkdir()
    t = amd_bench.live_telemetry(tmp_path, n=5)
    assert t["count"] == 5 and t["newest_record"] == "inspection-000015"
    assert t["oldest_record"] == "inspection-000007"
    assert t["vlm_latency_ms"] == {"p50": 9000.0, "p95": 11000.0, "n": 5}
    assert t["detector_latency_ms"] == {"p50": 80.0, "p95": 100.0, "n": 4}
    assert t["vlm_providers"] == {"amd-token-factory": 5}
    assert amd_bench.live_telemetry(tmp_path)["count"] == 11
    assert amd_bench.live_telemetry(tmp_path / "missing")["count"] == 0


def test_live_telemetry_is_cached_by_mtime(tmp_path, monkeypatch):
    path = _record(tmp_path, 1, vlm_ms=1000.0)
    reads = []
    real = amd_bench._telemetry_row
    monkeypatch.setattr(amd_bench, "_telemetry_row", lambda p: reads.append(p) or real(p))
    assert amd_bench.live_telemetry(tmp_path)["vlm_latency_ms"]["p50"] == 1000.0
    assert amd_bench.live_telemetry(tmp_path)["vlm_latency_ms"]["p50"] == 1000.0
    assert len(reads) == 1
    _record(tmp_path, 1, vlm_ms=2000.0)
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))
    assert amd_bench.live_telemetry(tmp_path)["vlm_latency_ms"]["p50"] == 2000.0
    assert len(reads) == 2


# ---------------------------------------------------------------------------
# eval_card()
# ---------------------------------------------------------------------------


def test_eval_card_from_the_committed_results():
    card = amd_bench.eval_card(RESULTS)
    assert card["source"] == {"live": "2026-10-17.deepseek-vision-exp.summary.json",
                              "hybrid": "2026-10-17.deepseek-vision-exp.hybrid-rescore.summary.json"}
    c = card["card"]
    assert c["metal_let_through"] == {"shipped": {"count": 0, "n": 20}, "vlm_only": {"count": 12, "n": 20}}
    assert c["clean_passed"] == {"shipped": {"count": 37, "n": 40}, "vlm_only": {"count": 40, "n": 40}}
    assert c["held_for_human"] == {"shipped": {"count": 35, "n": 80}, "vlm_only": {"count": 7, "n": 80}}
    lift = {row["variant"]: row for row in card["fusion_lift"]}
    assert list(lift) == ["detector_only_degraded", "detector_only_advisory", "vlm_only",
                          "hybrid_light_escalation_on"]
    # Every row carries the same three numbers, and no single "correct" figure.
    three = ("metal_let_through", "clean_passed", "held_for_human")
    assert all(set(three) <= set(row) and "gate_correct" not in row for row in lift.values())
    assert set(three) <= set(card["definitions"])
    assert lift["detector_only_degraded"]["held_for_human"] == {"count": 80, "n": 80}
    adv = lift["detector_only_advisory"]
    assert (adv["metal_let_through"]["count"], adv["clean_passed"]["count"],
            adv["held_for_human"]["count"]) == (0, 37, 22)
    # The stored advisory 77/80 = metal rejected + glass/organic held + clean passed.
    assert adv["metal_rejected"]["count"] + adv["held_by_class"]["glass_organic"]["count"]         + adv["clean_passed"]["count"] == 77
    shipped = lift["hybrid_light_escalation_on"]
    assert shipped["held_by_class"] == {"metal": {"count": 12, "n": 20},
                                        "glass_organic": {"count": 20, "n": 20},
                                        "clean": {"count": 3, "n": 40}}


def test_eval_card_is_none_without_summaries(tmp_path):
    assert amd_bench.eval_card(tmp_path) is None


def _confusion(rr, re_, ra, er, ee, ea, ar, ae, aa):
    return {"reject": {"reject": rr, "escalate": re_, "accept": ra, "error": 0},
            "escalate": {"reject": er, "escalate": ee, "accept": ea, "error": 0},
            "accept": {"reject": ar, "escalate": ae, "accept": aa, "error": 0}}


def test_eval_card_reads_the_hybrid_of_the_newest_live_run(tmp_path):
    (tmp_path / "2026-10-20.summary.json").write_text(json.dumps(
        {"kind": "live", "date": "2026-10-20", "vlm_model": "V", "confusion": _confusion(1, 0, 1, 0, 1, 1, 0, 0, 2)}))
    (tmp_path / "2026-10-21.hybrid-rescore.summary.json").write_text(json.dumps(
        {"kind": "hybrid_replay", "source_run": "2026-10-20", "variants": {
            "hybrid_light_escalation_on": {"confusion": _confusion(1, 1, 0, 0, 2, 0, 0, 1, 1)}}}))
    # An older run's hybrid: never the shipped gate.
    (tmp_path / "2026-10-22.hybrid-rescore.summary.json").write_text(json.dumps(
        {"kind": "hybrid_replay", "source_run": "2026-10-01", "variants": {
            "hybrid_light_escalation_on": {"confusion": _confusion(0, 0, 2, 0, 0, 2, 0, 0, 2)}}}))
    card = amd_bench.eval_card(tmp_path)
    assert card["card"]["metal_let_through"]["shipped"] == {"count": 0, "n": 2}
    assert card["card"]["metal_let_through"]["vlm_only"] == {"count": 1, "n": 2}
    assert card["card"]["held_for_human"]["shipped"] == {"count": 4, "n": 6}
    # No detector-only variant stored: the lift table carries only what exists.
    assert [r["variant"] for r in card["fusion_lift"]] == ["vlm_only", "hybrid_light_escalation_on"]


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


@pytest.fixture
def client(tmp_path, monkeypatch):
    for env in (auth.LYNCEUS_ADMIN_USERNAME_ENV, auth.LYNCEUS_ADMIN_PASSWORD_ENV,
                auth.LYNCEUS_ADMIN_PASSWORD_SHA256_ENV):
        monkeypatch.delenv(env, raising=False)
    bench = tmp_path / "bench"
    (bench / "results").mkdir(parents=True)
    for name in ("2026-10-17.deepseek-vision-exp.summary.json",
                 "2026-10-17.deepseek-vision-exp.hybrid-rescore.summary.json"):
        (bench / "results" / name).write_bytes((RESULTS / name).read_bytes())
    (bench / "results" / "2026-10-17.amd-throughput.json").write_text(
        json.dumps({"kind": "amd_throughput", "headline": {"calls": 108}}))
    storage = tmp_path / "runs"
    _record(storage, 1)
    monkeypatch.setattr(api, "_BENCHMARK_DIR", bench)
    monkeypatch.setenv(LYNCEUS_STORAGE_DIR_ENV, str(storage))
    return TestClient(api.create_app())


def test_route_shape(client):
    r = client.get("/benchmark/amd")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"measured", "live", "eval"}
    assert body["measured"]["headline"]["calls"] == 108
    assert body["live"]["count"] == 1 and body["live"]["window"] == 50
    assert body["eval"]["card"]["metal_let_through"]["shipped"]["count"] == 0


def test_route_requires_auth_when_enabled(client, monkeypatch):
    monkeypatch.setenv(auth.LYNCEUS_ADMIN_USERNAME_ENV, "admin")
    monkeypatch.setenv(auth.LYNCEUS_ADMIN_PASSWORD_ENV, "pw")
    assert client.get("/benchmark/amd").status_code == 401
