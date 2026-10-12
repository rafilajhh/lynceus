"""Ledger API tests — GET /inspections and GET /inspections/{record_id}.

The ledger reads only what ``lynceus.audit`` persisted:
``list_inspections`` for the filesystem scan (corrupt records come back with
``ok: False`` and must never crash the listing) plus ``load_record`` for each
entry.  Expected verdicts come from the demo stories (PLAN.md §5.1) and
expected impact figures from the research constants in ``lynceus.impact`` —
never from the implementation under test.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from lynceus import audit, impact, pipeline
from lynceus.api import create_app
from lynceus.config import LYNCEUS_STORAGE_DIR_ENV

# Closed enums & constants — single source of truth is lynceus.audit.
Decision = audit.Decision
GateState = audit.GateState
GATE_NAMES = audit.GATE_NAMES
RECORD_FILENAME = audit.RECORD_FILENAME


# ---------------------------------------------------------------------------
# Demo payloads mirroring the demo-UI waybill stories (web/app.js,
# PLAN.md §5.1: green → ACCEPT, amber → ESCALATE_HUMAN, red → REJECT).
# ---------------------------------------------------------------------------
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

_DEMO_PAYLOADS = [
    (
        "green",
        "B-9174-KT",
        Decision.ACCEPT,
        {
            "truck_id": "B-9174-KT",
            "demo_case": "green",
            "manifest_text": _GREEN_MANIFEST,
            "weight_kg": 18500,
            "waste_stream": "rdf-feedstock",
            "moisture": 0.095,
            "age_h": 5,
        },
    ),
    (
        "amber",
        "DK-4418-WR",
        Decision.ESCALATE_HUMAN,
        {
            "truck_id": "DK-4418-WR",
            "demo_case": "amber",
            "manifest_text": _AMBER_MANIFEST,
            "weight_kg": 11450,
            "waste_stream": "organic-rich",
            "moisture": 0.57,
            "age_h": 76,
        },
    ),
    (
        "red",
        "F-7702-TS",
        Decision.REJECT,
        {
            "truck_id": "F-7702-TS",
            "demo_case": "red",
            "manifest_text": _RED_MANIFEST,
            "weight_kg": 19300,  # weighbridge far above the declared 15,500 kg
            "waste_stream": "mixed-msw",
            "moisture": 0.14,
            "age_h": 8,
        },
    ),
]

# Expected prevented-loss figures from the documented formulas
# (lynceus.impact docstrings + docs/research-realcase-indonesia.md):
# accept → tonnes × RDF price; reject w/ hard contaminant → shredder +
# 1 h kiln downtime priced at the research USD rate.
_EXPECTED_ACCEPT_IDR = round(18_500 / 1000 * impact.RDF_PRICE_IDR_PER_TONNE)
_EXPECTED_REJECT_IDR = round(
    impact.SHREDDER_COST_IDR
    + impact.KILN_DOWNTIME_USD_PER_HOUR
    * impact.KILN_DOWNTIME_HOURS
    * impact.USD_IDR_RATE
)

# ---------------------------------------------------------------------------
# Fixtures — same isolation contract as test_inspect_e2e.
# ---------------------------------------------------------------------------


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """TestClient with LYNCEUS_STORAGE_DIR pointed at a pytest temp dir and
    the AI layer pinned to the offline stub (no network, deterministic)."""
    monkeypatch.setenv(LYNCEUS_STORAGE_DIR_ENV, str(tmp_path))
    monkeypatch.setattr(pipeline, "_vlm_reachable", lambda *a, **k: False)
    return TestClient(create_app())


def _seed(client, payload: dict) -> str:
    """POST /inspect a demo case and return its record_id."""
    resp = client.post("/inspect", json=payload)
    assert resp.status_code == 200, resp.text
    record_id = resp.json()["record_id"]
    assert isinstance(record_id, str) and record_id, resp.text
    return record_id


# ---------------------------------------------------------------------------
# 1. GET /inspections — seeded ledger, sorted desc, verdicts & impact.
# ---------------------------------------------------------------------------


def test_list_inspections_empty_storage_returns_empty_list(client):
    resp = client.get("/inspections")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"inspections": []}


def test_list_inspections_returns_seeded_records_sorted_desc(client):
    record_ids = [_seed(client, payload) for _, _, _, payload in _DEMO_PAYLOADS]
    assert record_ids == [
        "inspection-000001",
        "inspection-000002",
        "inspection-000003",
    ], record_ids

    resp = client.get("/inspections")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    inspections = body["inspections"]
    assert len(inspections) == 3, inspections

    # Sorted descending by record_id (newest inspection first).
    listed_ids = [row["record_id"] for row in inspections]
    assert listed_ids == sorted(listed_ids, reverse=True) == [
        "inspection-000003",
        "inspection-000002",
        "inspection-000001",
    ], listed_ids

    # Each row carries the fields the ledger view needs.
    by_id = {row["record_id"]: row for row in inspections}
    for demo_case, truck_id, expected_decision, _ in _DEMO_PAYLOADS:
        record_id = record_ids[_DEMO_INDEX[demo_case]]
        row = by_id[record_id]
        assert row["truck_id"] == truck_id, (demo_case, row)
        assert row["decision"] == expected_decision, (demo_case, row)
        assert audit.TIMESTAMP_RE.match(row["decided_at_utc"]), row
        assert isinstance(row["prevented_loss_idr"], int), row
        assert row["prevented_loss_idr"] >= 0, row
        # All five audit gates stated, each from the closed enum.
        states = row["gate_states"]
        assert set(states) == set(GATE_NAMES), (demo_case, states)
        assert all(state in GateState.ALL for state in states.values()), states

    # Red: weight-mismatch gate failed on the REJECT row.
    red_states = by_id["inspection-000003"]["gate_states"]
    assert red_states["weight_plausibility"] == GateState.FAILED, red_states

    # Impact figures match the documented formulas.
    assert by_id["inspection-000001"]["prevented_loss_idr"] == _EXPECTED_ACCEPT_IDR
    assert by_id["inspection-000003"]["prevented_loss_idr"] == _EXPECTED_REJECT_IDR
    assert by_id["inspection-000002"]["prevented_loss_idr"] > 0


#: demo_case → position in _DEMO_PAYLOADS (seeding order).
_DEMO_INDEX = {case: i for i, (case, _, _, _) in enumerate(_DEMO_PAYLOADS)}


# ---------------------------------------------------------------------------
# 2. GET /inspections/{record_id} — full audit record.
# ---------------------------------------------------------------------------


def test_get_single_record_returns_full_audit_record(client, tmp_path):
    record_id = _seed(client, _DEMO_PAYLOADS[2][3])  # red

    resp = client.get(f"/inspections/{record_id}")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # The endpoint serves exactly the strict-decoded on-disk record.
    on_disk = audit.load_record(
        tmp_path / record_id / RECORD_FILENAME
    ).model_dump()
    assert body == on_disk

    # Spot-checks against the demo story (PLAN.md §5.1).
    assert body["record_id"] == record_id
    assert body["execution_status"] == audit.ExecutionStatus.COMPLETED
    assert body["verdict"]["decision"] == Decision.REJECT
    assert body["inputs"]["truck_id"] == "F-7702-TS"
    assert audit.SHA256_FIELD_RE.match(body["digest"]["record_sha256"])
    assert set(body["gates"]) == set(GATE_NAMES)
    assert body["gates"]["weight_plausibility"]["state"] == GateState.FAILED


def test_get_unknown_record_returns_404(client):
    resp = client.get("/inspections/inspection-999999")
    assert resp.status_code == 404, resp.text
    assert resp.json()["detail"]["error"] == "record_not_found"


# ---------------------------------------------------------------------------
# 3. record_id validation — anti path traversal, never a 500.
# ---------------------------------------------------------------------------


def test_path_traversal_record_id_is_rejected_not_500(client):
    """Traversal payloads never crash the endpoint (never a 500).

    The HTTP layer normalizes dot-segments before routing, so traversal
    strings are a route miss (404); ids that do reach the handler are
    rejected by the audit's own record_id pattern.  Either layer keeps
    the guarantee: no path is ever probed on disk.
    """
    for path in (
        "/inspections/../../etc/passwd",
        "/inspections/..%2Fetc%2Fpasswd",
        "/inspections/%2e%2e%2fetc%2fpasswd",
        "/inspections/%2e%2e/etc/passwd",
    ):
        resp = client.get(path)
        assert resp.status_code in (404, 422), (path, resp.status_code, resp.text)


def test_malformed_record_id_returns_422(client):
    """Malformed ids that reach the handler get a 422 from the closed
    record_id pattern — the anti-traversal backstop behind the router."""
    for bad_id in (
        "inspection-abcdef",
        "inspection-",
        "foo%20bar",
        "inspection-99999999999999..",
        "inspection-000001%00",
    ):
        resp = client.get(f"/inspections/{bad_id}")
        assert resp.status_code == 422, (bad_id, resp.text)
        assert resp.json()["detail"]["error"] == "invalid_record_id"


# ---------------------------------------------------------------------------
# 4. Corrupt records: the listing skips them, never crashes.
# ---------------------------------------------------------------------------


def test_corrupt_record_is_skipped_not_fatal(client, tmp_path):
    first = _seed(client, _DEMO_PAYLOADS[0][3])
    second = _seed(client, _DEMO_PAYLOADS[1][3])
    assert (first, second) == ("inspection-000001", "inspection-000002")

    # Corrupt the first record's audit.json on disk.
    (tmp_path / first / RECORD_FILENAME).write_text("{not json", encoding="utf-8")

    resp = client.get("/inspections")
    assert resp.status_code == 200, resp.text
    inspections = resp.json()["inspections"]
    assert [row["record_id"] for row in inspections] == [second], inspections

    # The corrupt record itself is not servable — 404, not a 500 crash.
    detail = client.get(f"/inspections/{first}")
    assert detail.status_code == 404, detail.text


# ---------------------------------------------------------------------------
# 5. CORS stays allow-all on the new endpoints (demo UI from any origin).
# ---------------------------------------------------------------------------


def test_inspections_cors_allow_all(client):
    resp = client.get("/inspections", headers={"Origin": "http://example.com"})
    assert resp.status_code == 200, resp.text
    assert resp.headers["access-control-allow-origin"] == "*"
