"""Shift report + supplier risk (``lynceus.shift``, ``GET /shift-report``).

Expected values are computed by hand from the brief's formulas
(``risk_score = (reject + 0.5 * escalate) / trucks`` rounded to 2 dp,
``flagged = trucks >= 3 and risk_score >= 0.34``) and from the research
constants in ``lynceus.impact`` — never from the code under test.
"""

from __future__ import annotations

import copy
import importlib
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lynceus import audit, impact, pipeline, shift
from lynceus.api import create_app
from lynceus.config import LYNCEUS_STORAGE_DIR_ENV

_SHA = "sha256:" + "0" * 64

_BASE_RECORD = {
    "format_version": 2,
    "record_id": "inspection-000001",
    "execution_status": "completed",
    "started_at_utc": "2026-10-14T01:00:00Z",
    "finished_at_utc": "2026-10-14T01:00:14Z",
    "application": {"name": "lynceus", "version": "test"},
    "inputs": {
        "truck_id": "B-1-XX",
        "photo": {
            "filename": "photo.jpg",
            "sha256": _SHA,
            "captured_at_utc": "2026-10-14T01:00:00Z",
            "provenance": "user_upload",
        },
        "manifest_text": {
            "source": "manual_text",
            "raw_text_sha256": _SHA,
            "extracted_fields": {},
            "ocr_confidence": 0.95,
        },
        "weight": {
            "value_kg": 10000.0,
            "source": "weighbridge",
            "measured_at_utc": "2026-10-14T01:00:00Z",
        },
        "gas": {"readings_ppm": {}, "source": "not_measured",
                "measured_at_utc": "2026-10-14T01:00:00Z"},
        "supplier": "CV Uji",
    },
    "ai_outputs": {
        "vlm": {"model": "m", "model_version": "1", "raw_output_sha256": _SHA,
                "detected": {}, "confidence": 0.8},
        "llm": {"model": "m", "model_version": "1", "prompt_sha256": _SHA,
                "raw_output_sha256": _SHA, "reasoning": "", "confidence": 0.8},
    },
    "engine_outputs": {
        "suitability": {"classification": "screening_estimate", "score": 0.8, "rule": "r"},
        "recommendation": {"actionable": True, "route": "hold_for_review", "headline": "",
                           "insufficient": False, "missing": [], "caveats": [],
                           "alternative": ""},
    },
    "verdict": {"decision": "accept", "decided_at_utc": "2026-10-14T01:00:14Z",
                "classification": "screening_estimate", "uncertainty": ""},
    "gates": {g: {"state": "passed"} for g in audit.GATE_NAMES},
    "digest": {"record_sha256": _SHA, "input_digests": {}, "algorithm": "sha256"},
}

_n = 0


def _rec(
    decision: str = "accept",
    supplier: str | None = "CV Uji",
    started: str = "2026-10-14T01:00:00Z",
    finished: str | None = "2026-10-14T01:00:14Z",
    hard: list[str] | None = None,
    light: list[str] | None = None,
    provenance: str = "user_upload",
    weight_kg: float = 10000.0,
    moisture: float | None = None,
    status: str = "completed",
    v1: bool = False,
) -> audit.AuditRecord:
    """One strictly validated audit record built from the template."""
    global _n
    _n += 1
    data = copy.deepcopy(_BASE_RECORD)
    data["record_id"] = f"inspection-{_n:06d}"
    data["execution_status"] = status
    data["started_at_utc"] = started
    data["finished_at_utc"] = finished
    data["inputs"]["photo"]["provenance"] = provenance
    data["inputs"]["weight"]["value_kg"] = weight_kg
    data["verdict"]["decision"] = decision
    if decision == "refuse_insufficient_input":
        data["engine_outputs"]["recommendation"]["missing"] = ["photo"]
    detected: dict = {"hard_contaminants": hard or [], "light_contaminants": light or []}
    if moisture is not None:
        detected["moisture"] = moisture
    data["ai_outputs"]["vlm"]["detected"] = detected
    if v1:
        data["format_version"] = 1
        del data["inputs"]["supplier"]
    else:
        data["inputs"]["supplier"] = supplier
    return audit.AuditRecord.model_validate(data)


def _row(report: dict, supplier: str) -> dict:
    rows = [r for r in report["suppliers"] if r["supplier"] == supplier]
    assert len(rows) == 1, report["suppliers"]
    return rows[0]


@pytest.fixture(autouse=True)
def _fresh_cache():
    shift.clear_explanation_cache()
    yield
    shift.clear_explanation_cache()


# ---------------------------------------------------------------------------
# build_report — aggregation
# ---------------------------------------------------------------------------


def test_aggregation_counts_verdicts_contaminants_loss_and_median():
    records = [
        _rec("accept", finished="2026-10-14T01:00:10Z"),
        _rec("accept", finished="2026-10-14T01:00:20Z", light=["plastic_film"]),
        _rec("reject", hard=["metal"], weight_kg=19300, finished="2026-10-14T01:00:30Z"),
        _rec("escalate_human", light=["wet_mix", "plastic_film"], moisture=0.55,
             weight_kg=11450, finished="2026-10-14T01:00:40Z"),
        _rec("refuse_insufficient_input", finished="2026-10-14T01:00:50Z"),
    ]
    report = shift.build_report(records, None, None)

    assert report["trucks"] == 5
    assert report["by_verdict"] == {
        "accept": 2, "reject": 1, "escalate_human": 1, "refuse_insufficient_input": 1,
    }
    assert report["contaminants"] == {"metal": 1, "plastic_film": 2, "wet_mix": 1}

    # Prevented loss counts reject + escalate only; an accepted load's figure
    # is its market value, not a prevented loss (impact.py's own note).
    reject_idr = round(
        impact.SHREDDER_COST_IDR
        + impact.KILN_DOWNTIME_USD_PER_HOUR * impact.KILN_DOWNTIME_HOURS * impact.USD_IDR_RATE
    )
    water_kg = 11450 * 0.55
    escalate_idr = round(
        water_kg * impact.WATER_LATENT_HEAT_MJ_PER_KG
        / (impact.RDF_CALORIFIC_MJ_PER_KG * 1000.0)
        * impact.RDF_PRICE_IDR_PER_TONNE
    )
    assert report["prevented_loss_idr"] == pytest.approx(reject_idr + escalate_idr)
    assert isinstance(report["prevented_loss_idr"], float)

    # Durations 10, 20, 30, 40, 50 s → median 30.
    assert report["median_seconds_per_truck"] == 30.0
    assert report["sample"] is False


def test_contaminant_label_counted_once_per_truck():
    report = shift.build_report([_rec("reject", hard=["metal", "metal"])], None, None)
    assert report["contaminants"] == {"metal": 1}


def test_median_none_without_finished_durations_and_empty_report():
    report = shift.build_report([], None, None)
    assert report["trucks"] == 0
    assert report["median_seconds_per_truck"] is None
    assert report["suppliers"] == []
    assert report["prevented_loss_idr"] == 0.0
    assert report["sample"] is False  # nothing to label as sample


def test_only_completed_records_are_counted():
    report = shift.build_report(
        [_rec("accept"), _rec("escalate_human", status="in_progress", finished=None)],
        None, None,
    )
    assert report["trucks"] == 1
    assert report["by_verdict"]["escalate_human"] == 0


def test_supplier_rows_and_risk_score():
    records = (
        [_rec("reject", supplier="UD Sinar Abadi") for _ in range(2)]
        + [_rec("escalate_human", supplier="UD Sinar Abadi")]
        + [_rec("accept", supplier="UD Sinar Abadi") for _ in range(2)]
        + [_rec("accept", supplier="CV Sumber Bersih") for _ in range(4)]
    )
    report = shift.build_report(records, None, None)
    # (2 + 0.5 * 1) / 5 = 0.5
    assert _row(report, "UD Sinar Abadi") == {
        "supplier": "UD Sinar Abadi", "trucks": 5, "reject": 2, "escalate": 1,
        "risk_score": 0.5, "flagged": True,
    }
    assert _row(report, "CV Sumber Bersih") == {
        "supplier": "CV Sumber Bersih", "trucks": 4, "reject": 0, "escalate": 0,
        "risk_score": 0.0, "flagged": False,
    }
    # Riskiest supplier first.
    assert report["suppliers"][0]["supplier"] == "UD Sinar Abadi"


# ---------------------------------------------------------------------------
# Risk / flag thresholds at the boundary
# ---------------------------------------------------------------------------


def test_two_trucks_never_flagged_even_all_rejected():
    report = shift.build_report([_rec("reject"), _rec("reject")], None, None)
    row = _row(report, "CV Uji")
    assert row["risk_score"] == 1.0
    assert row["flagged"] is False


def test_three_trucks_one_reject_is_0_33_not_flagged():
    report = shift.build_report([_rec("reject"), _rec("accept"), _rec("accept")], None, None)
    row = _row(report, "CV Uji")
    assert row["risk_score"] == 0.33
    assert row["flagged"] is False


def test_risk_exactly_0_34_is_flagged():
    records = [_rec("reject") for _ in range(17)] + [_rec("accept") for _ in range(33)]
    row = _row(shift.build_report(records, None, None), "CV Uji")
    assert row["trucks"] == 50
    assert row["risk_score"] == 0.34
    assert row["flagged"] is True


def test_three_trucks_one_reject_one_escalate_flagged():
    records = [_rec("reject"), _rec("escalate_human"), _rec("accept")]
    row = _row(shift.build_report(records, None, None), "CV Uji")
    assert row["risk_score"] == 0.5
    assert row["flagged"] is True


# ---------------------------------------------------------------------------
# Supplier normalisation — v1 records and blanks are "unknown"
# ---------------------------------------------------------------------------


def test_v1_record_without_supplier_counts_as_unknown():
    v1 = _rec("reject", v1=True)
    assert v1.format_version == 1 and v1.inputs.supplier is None
    report = shift.build_report([v1, _rec("accept", supplier=None),
                                 _rec("accept", supplier="  ")], None, None)
    row = _row(report, "unknown")
    assert row["trucks"] == 3 and row["reject"] == 1


def test_supplier_name_whitespace_is_trimmed():
    report = shift.build_report([_rec(supplier=" CV Uji "), _rec(supplier="CV Uji")], None, None)
    assert _row(report, "CV Uji")["trucks"] == 2


# ---------------------------------------------------------------------------
# Window filtering
# ---------------------------------------------------------------------------


def test_window_since_inclusive_until_exclusive():
    records = [
        _rec(started="2026-10-14T00:59:59Z", finished="2026-10-14T01:00:10Z"),
        _rec(started="2026-10-14T01:00:00Z", finished="2026-10-14T01:00:10Z"),
        _rec(started="2026-10-14T05:00:00Z", finished="2026-10-14T05:00:10Z"),
        _rec(started="2026-10-14T09:00:00Z", finished="2026-10-14T09:00:10Z"),
    ]
    report = shift.build_report(records, "2026-10-14T01:00:00Z", "2026-10-14T09:00:00Z")
    assert report["trucks"] == 2
    assert report["window"]["since"] == "2026-10-14T01:00:00Z"
    assert report["window"]["until"] == "2026-10-14T09:00:00Z"
    assert report["window"]["first_truck_utc"] == "2026-10-14T01:00:00Z"
    assert report["window"]["last_truck_utc"] == "2026-10-14T05:00:00Z"

    only_since = shift.build_report(records, "2026-10-14T05:00:00Z", None)
    assert only_since["trucks"] == 2
    only_until = shift.build_report(records, None, "2026-10-14T01:00:00Z")
    assert only_until["trucks"] == 1


def test_window_fractional_seconds_compare_as_time():
    records = [_rec(started="2026-10-14T01:00:00.500Z", finished="2026-10-14T01:00:10Z")]
    assert shift.build_report(records, "2026-10-14T01:00:00Z", None)["trucks"] == 1
    assert shift.build_report(records, "2026-10-14T01:00:01Z", None)["trucks"] == 0


@pytest.mark.parametrize("bad", ["2026-10-14", "yesterday", "2026-10-14T01:00:00+07:00"])
def test_window_rejects_non_utc_timestamps(bad):
    with pytest.raises(ValueError):
        shift.build_report([], bad, None)


def test_window_since_after_until_rejected():
    with pytest.raises(ValueError):
        shift.build_report([], "2026-10-14T09:00:00Z", "2026-10-14T01:00:00Z")


# ---------------------------------------------------------------------------
# Sample flag
# ---------------------------------------------------------------------------


def test_sample_true_only_when_every_record_is_scripted():
    scripted = [_rec(provenance=p) for p in ("green", "amber", "red", "sample")]
    report = shift.build_report(scripted, None, None)
    assert report["sample"] is True
    assert report["sample_records"] == 4
    mixed = shift.build_report(scripted + [_rec(provenance="user_upload")], None, None)
    assert mixed["sample"] is False
    assert mixed["sample_records"] == 4


# ---------------------------------------------------------------------------
# explain_supplier — grounded numbers or the deterministic fallback
# ---------------------------------------------------------------------------

ROW = {"supplier": "UD Sinar Abadi", "trucks": 7, "reject": 3, "escalate": 1,
       "risk_score": 0.5, "flagged": True}
FALLBACK = (
    "UD Sinar Abadi: 3 of 7 loads rejected and 1 escalated. "
    "Recommend a supplier quality review before the next delivery."
)


def _structured_reply(row=ROW, recommendation="visual_check"):
    return {"stats": {k: row[k] for k in ("trucks", "reject", "escalate", "risk_score")},
            "recommendation": recommendation}


def _visual_explanation(row=ROW):
    return (f"{row['supplier']}: {row['reject']} of {row['trucks']} loads rejected "
            f"and {row['escalate']} escalated. Hold the next delivery for a full visual check.")


class FakeClient:
    def __init__(self, reply=None, error: Exception | None = None):
        self.reply = reply
        self.error = error
        self.calls: list[list] = []

    def assist(self, messages, max_tokens: int = 700):
        self.calls.append(messages)
        if self.error:
            raise self.error
        return self.reply, 9.0


def test_model_cannot_name_a_supplier_absent_from_records():
    records = [_rec("reject", supplier="CV Uji") for _ in range(3)]
    row = _row(shift.build_report(records, None, None), "CV Uji")
    client = FakeClient({"explanation": "PT Invented had 3 of 3 loads rejected. Review it."})
    text = shift.explain_supplier(row, client)
    assert text.startswith("CV Uji:")
    assert "PT Invented" not in text


def test_supplier_identity_in_structured_fields_is_not_rendered():
    client = FakeClient({
        "supplier": "PT Invented",
        "stats": {"trucks": 7, "reject": 3, "escalate": 1, "risk_score": 0.5},
        "recommendation": "Review PT Invented before delivery.",
    })
    assert shift.explain_supplier(ROW, client) == FALLBACK


def test_structured_statistics_must_match_aggregated_row():
    reply = _structured_reply()
    reply["stats"]["reject"] = 7
    assert shift.explain_supplier(ROW, FakeClient(reply)) == FALLBACK


def test_no_client_gives_fallback_text():
    assert shift.explain_supplier(ROW, None) == FALLBACK


def test_grounded_explanation_is_returned_and_sees_only_the_row():
    client = FakeClient(_structured_reply())
    assert shift.explain_supplier(ROW, client) == _visual_explanation()
    prompt = "\n".join(m["content"] for m in client.calls[0])
    assert "UD Sinar Abadi" not in prompt and '"trucks": 7' in prompt


def test_invented_number_falls_back():
    client = FakeClient({"explanation": "UD Sinar Abadi had 3 of 7 loads rejected, "
                                        "costing Rp 12 million. Review it."})
    assert shift.explain_supplier(ROW, client) == FALLBACK


def test_invented_percentage_falls_back_but_risk_percent_is_accepted():
    bad = FakeClient({"explanation": "43% of UD Sinar Abadi loads were rejected."})
    assert shift.explain_supplier(ROW, bad) == FALLBACK
    shift.clear_explanation_cache()
    good = FakeClient(_structured_reply())
    assert shift.explain_supplier(ROW, good) == _visual_explanation()


def test_risk_score_decimal_and_thousands_forms():
    row = dict(ROW, trucks=1200, reject=600, escalate=0, risk_score=0.5)
    client = FakeClient(_structured_reply(row))
    assert "600 of 1200" in shift.explain_supplier(row, client)


def test_more_than_three_sentences_falls_back():
    client = FakeClient({"explanation": "One. Two. Three. Four."})
    assert shift.explain_supplier(ROW, client) == FALLBACK


@pytest.mark.parametrize("reply", [None, {}, {"explanation": ""}, {"explanation": 7},
                                   {"answer": "UD Sinar Abadi is risky."}])
def test_malformed_reply_falls_back(reply):
    assert shift.explain_supplier(ROW, FakeClient(reply)) == FALLBACK


def test_client_error_falls_back():
    assert shift.explain_supplier(ROW, FakeClient(error=RuntimeError("429"))) == FALLBACK


def test_explanations_cached_per_supplier_and_stats():
    text = _visual_explanation()
    client = FakeClient(_structured_reply())
    assert shift.explain_supplier(ROW, client) == text
    assert shift.explain_supplier(dict(ROW), client) == text
    assert len(client.calls) == 1
    # Cached live text is served even when no client is resolved later.
    assert shift.explain_supplier(ROW, None) == text
    # Different stats → a new call.
    shift.explain_supplier(dict(ROW, trucks=8, risk_score=0.44), client)
    assert len(client.calls) == 2


def test_failed_explanations_are_not_cached_forever(monkeypatch):
    failing = FakeClient(error=RuntimeError("down"))
    assert shift.explain_supplier(ROW, failing) == FALLBACK
    # Within the retry back-off the failure is not retried …
    assert shift.explain_supplier(ROW, failing) == FALLBACK
    assert len(failing.calls) == 1
    # … after it, the model is asked again.
    real = shift._now
    monkeypatch.setattr(shift, "_now", lambda: real() + shift.FAILURE_RETRY_S + 1)
    assert shift.explain_supplier(ROW, FakeClient(_structured_reply())) == _visual_explanation()


# ---------------------------------------------------------------------------
# API — supplier persisted, GET /shift-report
# ---------------------------------------------------------------------------


@pytest.fixture()
def api(tmp_path, monkeypatch):
    monkeypatch.setenv(LYNCEUS_STORAGE_DIR_ENV, str(tmp_path))
    monkeypatch.setattr(pipeline, "_vlm_reachable", lambda *a, **k: False)
    monkeypatch.setattr(pipeline, "resolve_assist_client", lambda *a, **k: None)
    return TestClient(create_app())


def _inspect(api, case: str, supplier: str | None) -> dict:
    body = {"truck_id": "B-1-XX", "demo_case": case, "weight_kg": 10000}
    if supplier is not None:
        body["supplier"] = supplier
    resp = api.post("/inspect", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_inspect_persists_supplier_into_audit_inputs(api):
    out = _inspect(api, "green", "  CV Sumber Bersih ")
    assert out["audit_record"]["inputs"]["supplier"] == "CV Sumber Bersih"
    rid = out["record_id"]
    assert api.get(f"/inspections/{rid}").json()["inputs"]["supplier"] == "CV Sumber Bersih"
    assert _inspect(api, "green", None)["audit_record"]["inputs"]["supplier"] is None


def test_shift_report_endpoint_explains_flagged_rows(api, monkeypatch):
    for _ in range(3):
        _inspect(api, "red", "UD Sinar Abadi")
    _inspect(api, "green", "CV Sumber Bersih")
    row = dict(ROW, trucks=3, reject=3, escalate=0, risk_score=1.0)
    text = _visual_explanation(row)
    fake = FakeClient(_structured_reply(row))
    monkeypatch.setattr(pipeline, "resolve_assist_client", lambda *a, **k: fake)

    resp = api.get("/shift-report")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["trucks"] == 4
    assert body["by_verdict"]["reject"] == 3
    assert body["sample"] is True  # demo_case provenance is scripted
    flagged = _row(body, "UD Sinar Abadi")
    assert flagged["flagged"] is True
    assert flagged["explanation"] == text
    assert flagged["explanation_source"] == "model"
    assert body["explanation_model"] and body["explanation_provider"]
    clean = _row(body, "CV Sumber Bersih")
    assert "explanation" not in clean

    # Second load: served from the cache, the model is not called again.
    api.get("/shift-report")
    assert len(fake.calls) == 1


def test_shift_report_fallback_is_labelled_rule(api):
    for _ in range(3):
        _inspect(api, "red", "UD Sinar Abadi")
    body = api.get("/shift-report").json()
    row = _row(body, "UD Sinar Abadi")
    assert row["explanation"] == (
        "UD Sinar Abadi: 3 of 3 loads rejected and 0 escalated. "
        "Recommend a supplier quality review before the next delivery."
    )
    assert row["explanation_source"] == "rule"
    assert body["explanation_model"] is None and body["explanation_provider"] is None


def test_shift_report_window_and_validation(api):
    _inspect(api, "green", "CV Sumber Bersih")
    assert api.get("/shift-report", params={"since": "2099-01-01T00:00:00Z"}).json()["trucks"] == 0
    assert api.get("/shift-report", params={"since": "not-a-time"}).status_code == 422
    assert api.get("/shift-report", params={
        "since": "2026-10-14T09:00:00Z", "until": "2026-10-14T01:00:00Z"}).status_code == 422


# ---------------------------------------------------------------------------
# seed_demo.py --shift
# ---------------------------------------------------------------------------


def test_seed_demo_shift_writes_24_sample_records(tmp_path, monkeypatch):
    scripts = Path(__file__).resolve().parents[1] / "scripts"
    monkeypatch.syspath_prepend(str(scripts))
    monkeypatch.setenv(LYNCEUS_STORAGE_DIR_ENV, str(tmp_path))
    monkeypatch.setattr(pipeline, "_vlm_reachable", lambda *a, **k: False)
    sys.modules.pop("seed_demo", None)
    seed_demo = importlib.import_module("seed_demo")

    (tmp_path / "inspection-000099").mkdir()  # an old record --reset removes
    assert seed_demo.main(["--reset", "--shift", "--storage-dir", str(tmp_path)]) == 0
    records = [
        audit.load_record(tmp_path / e["record_id"] / audit.RECORD_FILENAME)
        for e in audit.list_inspections(tmp_path)
    ]
    assert len(records) == 24
    assert not (tmp_path / "inspection-000099").exists()
    assert {r.inputs.photo.provenance for r in records} == {"sample"}

    report = shift.build_report(records, None, None)
    assert report["sample"] is True
    assert {r["supplier"] for r in report["suppliers"]} == {
        "CV Sumber Bersih", "PT Daur Ulang Jaya", "UD Sinar Abadi"}
    assert [r["supplier"] for r in report["suppliers"] if r["flagged"]] == ["UD Sinar Abadi"]
    assert report["median_seconds_per_truck"] is not None
    assert report["median_seconds_per_truck"] > 0


# ---------------------------------------------------------------------------
# Final review: money the row never carried, grouped numbers as one number
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text", [
    "UD Sinar Abadi had 3 of 7 loads rejected, costing Rp 3.000.000. Review it.",
    "UD Sinar Abadi had 3 of 7 loads rejected, about twelve million rupiah. Review it.",
    "UD Sinar Abadi had 3 of 7 loads rejected, costing IDR 3,000,000. Review it.",
    "UD Sinar Abadi had 3 of 7 loads rejected, a US$ loss. Review it.",
    "UD Sinar Abadi had 3 of 7 loads rejected, losing tiga juta. Review it.",
])
def test_money_in_explanation_falls_back(text):
    shift.clear_explanation_cache()
    assert shift.explain_supplier(ROW, FakeClient({"explanation": text})) == FALLBACK


def test_dot_grouped_number_is_one_number():
    # "3.000" must be 3000, not the allowed 3 and a stray 0.
    shift.clear_explanation_cache()
    text = "UD Sinar Abadi had 3.000 loads rejected. Review it."
    assert shift.explain_supplier(ROW, FakeClient({"explanation": text})) == FALLBACK
    assert shift._numbers_in("3.000.000 and 1,200 and 0.67") == [3000000.0, 1200.0, 0.67]


def test_counts_and_risk_percent_still_accepted():
    shift.clear_explanation_cache()
    reply = dict(_structured_reply(), supplier="PT Invented", explanation="PT Invented is risky.")
    text = shift.explain_supplier(ROW, FakeClient(reply))
    assert text == _visual_explanation()
    assert "PT Invented" not in text


def test_rp_amount_rejected_even_when_zero_is_an_allowed_number():
    # With escalate == 0 the old tokeniser read "Rp 3.000.000" as 3.0 and 0.0
    # (both "allowed") and let the invented amount through.
    row = dict(ROW, escalate=0)
    shift.clear_explanation_cache()
    text = "UD Sinar Abadi had 3 of 7 loads rejected, costing Rp 3.000.000. Review it."
    reply = FakeClient({"explanation": text})
    assert shift.explain_supplier(row, reply) == shift.fallback_explanation(row)
