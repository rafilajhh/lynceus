"""End-to-end tests for POST /inspect — no AI server required (StubAIClients).

The full inspection pipeline (VLM + LLM + decision engine + audit record) is
exercised through ``pipeline.StubAIClients`` so these tests never touch the
network and never depend on a live vLLM deployment on the MI300X.

Verified contract (backend/src/lynceus/api.py ``InspectRequest``, pipeline.py,
decision.py, audit.py; demo stories per docs/PLAN.md §5.1 and web/app.js):

  POST /inspect
    payload: {"truck_id", "demo_case": green|amber|red?, "photo_base64"?,
              "manifest_text"?, "weight_kg", "declared_weight_kg"?,
              "waste_stream", "moisture" (fraction 0..1), "age_h"}
    response: {"record_id": "inspection-NNNNNN",
               "verdict": {"decision": ..., ...},
               "gates": {gate -> {"state": ...}, ...}   (five audit gates),
               "reasons": [str, ...],
               "provenance", "ai_outputs", "engine_outputs",
               "audit_record": {...}}

  decision — closed enum (audit.Decision):
             accept | reject | refuse_insufficient_input | escalate_human
  gate     — closed enum (audit.GateState):
             not_evaluated | not_run | passed | failed
  record_id — "inspection-NNN", allocated from the filesystem, never reused.

Demo-case verdicts (PLAN.md §5.1): green → accept, amber → escalate_human,
red → reject.
"""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from lynceus import audit, pipeline
from lynceus.api import create_app
from lynceus.config import LYNCEUS_STORAGE_DIR_ENV

# Closed enums & constants — single source of truth is lynceus.audit.
Decision = audit.Decision
GateState = audit.GateState
GATE_NAMES = audit.GATE_NAMES
RECORD_FILENAME = audit.RECORD_FILENAME

#: record_id as produced by audit.allocate_inspection_id: "inspection-NNN"
#: zero-padded to 6 digits, monotonic, never reused.
RECORD_ID_RE = re.compile(r"^inspection-(\d{6})$")

#: Manifest texts mirroring the demo-UI waybill stories (web/app.js).
_GREEN_MANIFEST = (
    "DUTY OF CARE — WASTE TRANSFER NOTE\n"
    "Producer: Eco RDF Processing Plant 2\n"
    "Waste type: SRF / RDF fluff, pre-sorted, baled\n"
    "Origin: MRF Bintara sorting line\n"
    "Declared weight: 18,400 kg\n"
    "Moisture declared: 10% (dry, stored under cover)\n"
    "Collected: 2026-10-13 01:20 UTC"
)
_AMBER_MANIFEST = (
    "DUTY OF CARE — WASTE TRANSFER NOTE\n"
    "Producer: TPA Suwung transfer station\n"
    "Waste type: organic-rich source-separated biowaste\n"
    "Origin: kerbside organics collection, district 4\n"
    "Declared weight: 11,200 kg\n"
    "Moisture declared: 30%\n"
    "Collected: 2026-10-10 08:00 UTC"
)
_RED_MANIFEST = (
    "DUTY OF CARE — WASTE TRANSFER NOTE\n"
    "Producer: Metro Scrap Trading CV\n"
    "Waste type: clean RDF fluff, dry, no contamination\n"
    "Origin: industrial park skip hire\n"
    "Declared weight: 15,500 kg\n"
    "Moisture declared: 12%\n"
    "Collected: 2026-10-13 00:45 UTC"
)

#: Demo case → expected verdict (PLAN.md §5.1: green/amber/red) and the
#: payload the demo UI would submit (moisture is a 0..1 fraction here).
DEMO_CASES = {
    "green": {
        "expected": Decision.ACCEPT,
        "payload": {
            "truck_id": "B-9174-KT",
            "demo_case": "green",
            "manifest_text": _GREEN_MANIFEST,
            "weight_kg": 18500,
            "waste_stream": "rdf-feedstock",
            "moisture": 0.095,
            "age_h": 5,
        },
    },
    "amber": {
        "expected": Decision.ESCALATE_HUMAN,
        "payload": {
            "truck_id": "DK-4418-WR",
            "demo_case": "amber",
            "manifest_text": _AMBER_MANIFEST,
            "weight_kg": 11450,
            "waste_stream": "organic-rich",
            "moisture": 0.57,
            "age_h": 76,
        },
    },
    "red": {
        "expected": Decision.REJECT,
        "payload": {
            "truck_id": "F-7702-TS",
            "demo_case": "red",
            "manifest_text": _RED_MANIFEST,
            "weight_kg": 19300,  # weighbridge far above the declared 15,500 kg
            "waste_stream": "mixed-msw",
            "moisture": 0.14,
            "age_h": 8,
        },
    },
}


# ---------------------------------------------------------------------------
# Fixtures — temp storage dir, offline stub AI, fresh app per test.
# ---------------------------------------------------------------------------


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """TestClient with LYNCEUS_STORAGE_DIR pointed at a pytest temp dir
    (auto-cleaned) and the AI layer pinned to the offline stub.

    ``_vlm_reachable`` is forced False so ``resolve_clients`` can never pick
    the live vLLM client: no test attempts a network call, and a stray
    vLLM server on localhost:8000 cannot make results non-deterministic.
    Demo cases resolve to StubAIClients regardless; manual-mode tests rely
    on this patch for their stub fallback.
    """
    monkeypatch.setenv(LYNCEUS_STORAGE_DIR_ENV, str(tmp_path))
    monkeypatch.setattr(pipeline, "_vlm_reachable", lambda *a, **k: False)
    return TestClient(create_app())


# ---------------------------------------------------------------------------
# Response-shape helpers.
# ---------------------------------------------------------------------------


def _decision(body: dict) -> str:
    verdict = body.get("verdict") or {}
    return str(verdict.get("decision") or body.get("decision") or "")


def _gate_states(body: dict) -> dict:
    """Normalize gates to {gate_name: state} (object or bare-string states)."""
    gates = body.get("gates") or {}
    return {
        name: (gate.get("state") if isinstance(gate, dict) else gate)
        for name, gate in gates.items()
    }


def _load_audit_record(storage_dir, record_id):
    """Strict-decode the on-disk audit record for ``record_id``."""
    return audit.load_record(storage_dir / record_id / RECORD_FILENAME)


# ---------------------------------------------------------------------------
# 1. Demo cases: green / amber / red → ACCEPT / ESCALATE / REJECT.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("demo_case", ["green", "amber", "red"])
def test_inspect_demo_case_verdicts(client, tmp_path, demo_case):
    case = DEMO_CASES[demo_case]
    resp = client.post("/inspect", json=case["payload"])
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # Verdict from the closed decision enum.
    decision = _decision(body)
    assert decision == case["expected"], (
        f"demo_case {demo_case!r}: expected {case['expected']!r}, "
        f"got {decision!r}"
    )
    assert decision in Decision.ALL

    # Reasons must be non-empty — never an unexplained verdict.
    reasons = body.get("reasons")
    assert isinstance(reasons, list) and reasons, (
        f"demo_case {demo_case!r}: reasons must be non-empty"
    )
    assert all(isinstance(r, str) and r.strip() for r in reasons)

    # Gates: all five audit gates stated, each from the closed gate enum,
    # and consistent with the verdict (PLAN.md §5.1).
    states = _gate_states(body)
    for name in GATE_NAMES:
        assert name in states, f"gate {name!r} missing from response gates"
    for name, state in states.items():
        assert state in GateState.ALL, f"gate {name!r}: illegal state {state!r}"
    if demo_case == "green":
        # PLAN.md: "semua gates passed" — accepting with a failed gate would
        # be an inconsistent verdict.
        assert GateState.FAILED not in states.values(), states
    elif demo_case == "amber":
        # Amber = flagged for human review, not silently waved through.
        # The gas digital twin now runs for every complete batch
        # description; the declared wet organic mix legitimately explains
        # its high CH4, so the gas gate passes and the escalation rides on
        # the VLM's light-contamination detections.  (Before the twin, the
        # not_run gas gate satisfied the old "some gate not passed" check.)
        # The real guarantee stays: an explained escalation, never a silent
        # accept.
        assert _decision(body) == Decision.ESCALATE_HUMAN
        assert any("contamination" in r.lower() for r in body["reasons"]), body["reasons"]
    else:  # red — declared 15,500 kg vs weighbridge 19,300 kg
        assert states.get("weight_plausibility") == GateState.FAILED, states

    # Audit record persisted in LYNCEUS_STORAGE_DIR (the tmp dir) and
    # strict-decodes with a matching verdict.
    record_id = body.get("record_id")
    assert isinstance(record_id, str) and RECORD_ID_RE.match(record_id), (
        f"bad record_id {record_id!r}"
    )
    record = _load_audit_record(tmp_path, record_id)
    assert record.record_id == record_id
    assert record.execution_status == audit.ExecutionStatus.COMPLETED
    assert record.verdict.decision == case["expected"]


# ---------------------------------------------------------------------------
# 2. Refuse-to-answer: no photo and no demo_case → refuse_insufficient_input.
# ---------------------------------------------------------------------------


def test_inspect_refuses_without_photo_or_demo_case(client, tmp_path):
    payload = {
        "truck_id": "B-9174-KT",
        # Deliberately NO photo_base64 and NO demo_case — the pipeline must
        # refuse, never guess (audit invariant 14: refuse-to-answer).
        "manifest_text": _GREEN_MANIFEST,
        "weight_kg": 18500,
        "waste_stream": "rdf-feedstock",
        "moisture": 0.095,
        "age_h": 5,
    }
    resp = client.post("/inspect", json=payload)
    # Refusing is a verdict, not an error: the caller gets an explanation.
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert _decision(body) == Decision.REFUSE_INSUFFICIENT_INPUT, body
    recommendation = (body.get("engine_outputs") or {}).get("recommendation") or {}
    missing = recommendation.get("missing")
    assert isinstance(missing, list) and missing, (
        "refuse_insufficient_input must list the missing fields "
        f"(got {missing!r})"
    )
    assert all(isinstance(item, str) and item.strip() for item in missing)

    # The frozen audit record enforces the same coherence (invariant 4).
    record_id = body.get("record_id")
    assert record_id and RECORD_ID_RE.match(record_id)
    record = _load_audit_record(tmp_path, record_id)
    assert record.verdict.decision == Decision.REFUSE_INSUFFICIENT_INPUT
    assert record.execution_status == audit.ExecutionStatus.COMPLETED


# ---------------------------------------------------------------------------
# 3. Weight mismatch: declared 15,500 kg vs weighbridge 19,300 kg → REJECT.
# ---------------------------------------------------------------------------


def test_inspect_weight_mismatch_is_rejected(client):
    payload = {
        "truck_id": "F-7702-TS",
        # No demo_case: the stub falls back to the clean (green) VLM script,
        # so the rejection must come from the declared-vs-actual weight
        # comparison in the decision engine, not a canned demo route.
        "photo_base64": "/9j/4HN0dWItcGhvdG8=",  # any bytes: the stub ignores content
        "manifest_text": _RED_MANIFEST,
        "weight_kg": 19300,  # weighbridge far above the declared 15,500 kg
        "declared_weight_kg": 15500,
        "waste_stream": "mixed-msw",
        "moisture": 0.14,
        "age_h": 8,
    }
    resp = client.post("/inspect", json=payload)
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert _decision(body) == Decision.REJECT, body
    reasons = body.get("reasons")
    assert isinstance(reasons, list) and reasons, "a REJECT must carry reasons"
    states = _gate_states(body)
    assert states.get("weight_plausibility") == GateState.FAILED, states


# ---------------------------------------------------------------------------
# 4. Audit trail: two inspections → two records, strict decode, monotonic IDs.
# ---------------------------------------------------------------------------


def test_audit_trail_two_inspections(client, tmp_path):
    record_ids = []
    for demo_case in ("green", "amber"):
        resp = client.post("/inspect", json=DEMO_CASES[demo_case]["payload"])
        assert resp.status_code == 200, resp.text
        record_id = resp.json().get("record_id")
        assert isinstance(record_id, str) and RECORD_ID_RE.match(record_id)
        record_ids.append(record_id)

    # record_id format "inspection-NNN", strictly monotonic allocation
    # (filesystem-allocated, never reused — audit invariant 10).
    numbers = [int(RECORD_ID_RE.match(rid).group(1)) for rid in record_ids]
    assert numbers[0] == 1, f"fresh storage must start at 1, got {numbers}"
    assert numbers == sorted(numbers) and len(set(numbers)) == len(numbers), (
        f"record ids must be strictly monotonic, got {record_ids}"
    )

    # list_inspections sees exactly the two completed records, sorted.
    listing = audit.list_inspections(tmp_path)
    assert len(listing) == 2, listing
    assert [entry["record_id"] for entry in listing] == record_ids
    for entry in listing:
        assert entry["ok"] is True, entry
        assert entry["execution_status"] == audit.ExecutionStatus.COMPLETED, entry

    # Every record strict-decodes (load_record validates enums, digests and
    # timestamps — invariants 6/20) and matches its HTTP response.
    for demo_case, record_id in zip(("green", "amber"), record_ids):
        record = _load_audit_record(tmp_path, record_id)
        assert record.record_id == record_id
        assert record.verdict.decision == DEMO_CASES[demo_case]["expected"]


# ---------------------------------------------------------------------------
# 5. Regression: POST /assess stays green (mixed-msw → 200).
# ---------------------------------------------------------------------------


def test_assess_mixed_msw_still_green(client):
    resp = client.post(
        "/assess",
        json={
            "waste_stream": "mixed-msw",
            "tonnage_t": 100.0,
            "moisture": 0.40,
            "age_h": 48.0,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["tonnage_t"] == 100.0
    assert body["moisture"] == 0.40
    assert body["age_h"] == 48.0


# ---------------------------------------------------------------------------
# 6. Health: the rule-based engine must be available.
# ---------------------------------------------------------------------------


def test_health_engine_available(client):
    resp = client.get("/health")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "ok"
    assert body["engine_available"] is True


# ---------------------------------------------------------------------------
# 7. Fail-closed: live AI failure with stub fallback disabled → 503.
# ---------------------------------------------------------------------------

_LIVE_PAYLOAD = {
    "truck_id": "B-9174-KT",
    "photo_base64": "/9j/4HN0dWItcGhvdG8=",
    "manifest_text": _GREEN_MANIFEST,
    "weight_kg": 18500,
    "waste_stream": "rdf-feedstock",
    "moisture": 0.095,
    "age_h": 5,
}


class _BrokenLiveClient:
    """Provenance-live client whose calls always raise — no httpx involved."""

    provenance = "live"

    def vlm(self, photo):
        raise ConnectionError("vLLM endpoint unreachable")

    def llm(self, manifest_text, context):
        raise ConnectionError("vLLM endpoint unreachable")


def _force_broken_live_client(monkeypatch):
    monkeypatch.setattr(
        pipeline, "resolve_clients", lambda payload, settings=None: _BrokenLiveClient()
    )


def test_live_failure_falls_back_to_stub_by_default(client, monkeypatch, tmp_path):
    _force_broken_live_client(monkeypatch)
    resp = client.post("/inspect", json=_LIVE_PAYLOAD)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("provenance") == "stub_fallback_live_error", body
    assert "live" in (body.get("verdict") or {}).get("uncertainty", "").lower()


def test_live_failure_is_503_when_stub_fallback_disabled(client, monkeypatch):
    monkeypatch.setenv("LYNCEUS_ALLOW_STUB_FALLBACK", "0")
    _force_broken_live_client(monkeypatch)
    resp = client.post("/inspect", json=_LIVE_PAYLOAD)
    assert resp.status_code == 503, resp.text
    detail = resp.json().get("detail") or {}
    assert detail.get("error") == "live_ai_unavailable", detail
    assert "verdict" not in (resp.json() if isinstance(resp.json(), dict) else {})


# ---------------------------------------------------------------------------
# Gas channel: an inspection with no gas data must still complete.
# ---------------------------------------------------------------------------


def test_inspect_without_gas_data_completes(client, tmp_path):
    # No waste_stream / moisture / age_h: the gas twin cannot run, so there is
    # no gas data for this inspection — the record must say so, not 500.
    resp = client.post(
        "/inspect",
        json={
            "truck_id": "T1",
            "photo_base64": "/9j/4HN0dWItcGhvdG8=",
            "manifest_text": "SURAT JALAN",
            "weight_kg": 5200,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    rec = body["audit_record"]
    assert rec["execution_status"] == "completed"
    gas = rec["ai_outputs"]["gas"]
    assert gas is None or gas["source"] == "not_measured"
    # The on-disk record strict-decodes (no orphaned in_progress record).
    record = _load_audit_record(tmp_path, body["record_id"])
    assert record.execution_status == audit.ExecutionStatus.COMPLETED


def test_pipeline_resolve_clients_without_settings_arg():
    assert pipeline.resolve_clients({"demo_case": "green"}).provenance == "stub"


def test_legacy_record_without_ai_gas_still_decodes(client, tmp_path):
    """Records written before the gas channel existed have no ai_outputs.gas."""
    import json

    resp = client.post("/inspect", json=DEMO_CASES["green"]["payload"])
    assert resp.status_code == 200, resp.text
    path = tmp_path / resp.json()["record_id"] / RECORD_FILENAME
    data = json.loads(path.read_text(encoding="utf-8"))
    data["ai_outputs"].pop("gas")
    path.write_text(json.dumps(data), encoding="utf-8")
    record = audit.load_record(path)
    assert record.ai_outputs.gas is None


def test_inspect_with_live_gate_sensor_stamps_measured_source(
    client, tmp_path, monkeypatch
):
    from lynceus import gas_ingest

    class _Gateway:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "readings_ppm": {"ch4": 54.1, "co2": 56.4, "h2s": 0.0039, "tvoc": 0.067},
                "measured_at_utc": "2026-10-13T09:00:00Z",
            }

    monkeypatch.setenv(gas_ingest.GAS_SENSOR_URL_ENV, "http://gate-sensor.invalid/r")
    monkeypatch.setattr(gas_ingest.httpx, "get", lambda *a, **k: _Gateway())
    resp = client.post("/inspect", json=DEMO_CASES["green"]["payload"])
    assert resp.status_code == 200, resp.text
    rec = _load_audit_record(tmp_path, resp.json()["record_id"])
    assert rec.inputs.gas.source == "sentinel_gate_sensor"
    assert rec.inputs.gas.measured_at_utc == "2026-10-13T09:00:00Z"
    assert rec.ai_outputs.gas.source == "sentinel_gate_sensor"


def test_inspect_with_nan_in_gateway_instrument_completes(
    client, tmp_path, monkeypatch
):
    from lynceus import gas_ingest

    class _Gateway:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "readings_ppm": {"ch4": 54.1, "co2": 56.4},
                "instrument": {"model": "X", "x": float("nan")},
            }

    monkeypatch.setenv(gas_ingest.GAS_SENSOR_URL_ENV, "http://gate-sensor.invalid/r")
    monkeypatch.setattr(gas_ingest.httpx, "get", lambda *a, **k: _Gateway())
    resp = client.post("/inspect", json=DEMO_CASES["green"]["payload"])
    assert resp.status_code == 200, resp.text
    rec = _load_audit_record(tmp_path, resp.json()["record_id"])
    assert rec.execution_status == audit.ExecutionStatus.COMPLETED
    assert rec.ai_outputs.gas.instrument == {"model": "X"}


def test_inspect_with_invalid_sensor_url_falls_back_to_twin(
    client, tmp_path, monkeypatch
):
    from lynceus import gas_ingest

    monkeypatch.setenv(gas_ingest.GAS_SENSOR_URL_ENV, "http://[::1")
    resp = client.post("/inspect", json=DEMO_CASES["green"]["payload"])
    assert resp.status_code == 200, resp.text
    rec = _load_audit_record(tmp_path, resp.json()["record_id"])
    assert rec.inputs.gas.source == "digital_twin"


# ---------------------------------------------------------------------------
# Audit v2: provider / latency provenance on ai_outputs.vlm / .llm.
# ---------------------------------------------------------------------------


def test_stub_inspection_has_no_provider_provenance(client, tmp_path):
    resp = client.post("/inspect", json=DEMO_CASES["green"]["payload"])
    assert resp.status_code == 200, resp.text
    rec = _load_audit_record(tmp_path, resp.json()["record_id"])
    assert rec.format_version == 2
    assert rec.ai_outputs.vlm.provider is None
    assert rec.ai_outputs.vlm.latency_ms is None
    assert rec.ai_outputs.llm.provider is None
    assert rec.ai_outputs.llm.latency_ms is None


def test_live_inspection_persists_provider_and_latency(client, tmp_path, monkeypatch):
    from lynceus.config import get_settings

    monkeypatch.setenv("VLLM_VLM_URL", "https://developer.amd.com.cn/radeon/api/v1")
    monkeypatch.setenv("VLLM_LLM_URL", "https://developer.amd.com.cn/radeon/api/v1")
    live = pipeline.VLLMClient(settings=get_settings())
    monkeypatch.setattr(
        pipeline.VLLMClient,
        "_chat_once",
        lambda self, *a, **k: (
            '{"contamination": "none detected", "moisture": 0.1, '
            '"hard_contaminants": [], "light_contaminants": [], '
            '"reasoning": "ok", "crosscheck_notes": "consistent", "confidence": 0.8}'
        ),
    )
    monkeypatch.setattr(
        pipeline, "resolve_clients", lambda payload, settings=None: live
    )
    resp = client.post("/inspect", json=_LIVE_PAYLOAD)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["provenance"] == "live", body
    rec = _load_audit_record(tmp_path, body["record_id"])
    for out in (rec.ai_outputs.vlm, rec.ai_outputs.llm):
        assert out.provider == "amd-token-factory"
        assert out.latency_ms is not None and out.latency_ms >= 0
