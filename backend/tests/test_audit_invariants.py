"""Pytest wrapper for audit invariant verification.

The body runs the same 57 invariant checks as a single test; a failed
check raises AssertionError with the check name so pytest reports it.
"""
import pytest
"""Live verification of every invariant in backend/src/lynceus/audit.py."""
import json, shutil, sys, tempfile
from pathlib import Path

from lynceus import audit as A


PASS = FAIL = 0


def test_audit_invariants():
    global PASS, FAIL
    PASS = FAIL = 0
    def check(name, cond, detail=""):
        global PASS, FAIL
        if cond: PASS += 1; print(f"  PASS  {name}")
        else: FAIL += 1; print(f"  FAIL  {name} {detail}")

    def raises(name, fn, *args, contains=None, **kw):
        try:
            fn(*args, **kw)
        except A.AuditError as e:
            ok = True
            if contains is not None:
                ok = contains in str(e)
            check(name, ok, f"(got: {e})")
            return str(e)
        except Exception as e:  # noqa
            check(name, False, f"(wrong exception type: {type(e).__name__}: {e})")
            return ""
        check(name, False, "(no exception raised)")
        return ""

    tmp = Path(tempfile.mkdtemp(prefix="lynceus-audit-test-"))
    storage = tmp / "storage"

    photo_bytes = b"\xff\xd8fake-jpeg-bytes"
    manifest_bytes = b"WASTE MANIFEST\norganik\nTPA Suwung\n4200kg"
    prompt_bytes = b"You are a waste inspection assistant..."

    inputs = {
        "truck_id": "B-9174-KT",
        "photo": {"filename": "photo_0001.jpg", "sha256": A.sha256_field(photo_bytes),
                  "captured_at_utc": "2099-01-01T02:14:52Z", "provenance": "gate_camera"},
        "manifest_text": {"source": "paper_manifest_ocr", "raw_text_sha256": A.sha256_field(manifest_bytes),
                          "extracted_fields": {"waste_type": "organik", "origin": "TPA Suwung",
                                               "declared_weight_kg": 4200.0},
                          "ocr_confidence": 0.91},
        "weight": {"value_kg": 4185.0, "source": "weighbridge", "measured_at_utc": "2099-01-01T02:14:55Z"},
        "gas": {"readings_ppm": {"ch4": 15.2, "co2": 850.0}, "source": "portable_sensor",
                "measured_at_utc": "2099-01-01T02:14:58Z"},
    }
    ai_outputs = {
        "vlm": {"model": "qwen2.5-vl-7b", "model_version": "2026-09-01",
                "raw_output_sha256": A.sha256_field(b"vlm-raw"), "detected": {"visual_waste_type": "organik", "contamination_visible": True},
                "confidence": 0.87},
        "llm": {"model": "llama-3.1-8b-instruct", "model_version": "2026-08-15",
                "prompt_sha256": A.sha256_field(prompt_bytes), "raw_output_sha256": A.sha256_field(b"llm-raw"),
                "reasoning": "Foto menunjukkan dominasi sisa organik rumah tangga.", "confidence": 0.82},
        "gas": {"source": "digital_twin",
                "instrument": {"model": "virtual TDLAS gate monitor (physics twin)",
                               "technology": "Tunable Diode Laser Absorption Spectroscopy (TDLAS)"},
                "model_basis": "Eq. HH-1 40 CFR 98"},
    }
    engine_outputs = {
        "suitability": {"classification": "acceptable", "score": 0.74,
                        "rule": "organik < 60% kontaminasi, gas dalam rentang"},
        "recommendation": {"actionable": True, "route": "accept_processing",
                           "headline": "Diterima untuk proses komposting.", "insufficient": False,
                           "missing": [], "caveats": ["moisture 58%: drying prerequisite"],
                           "alternative": "rejection scores 0.31 (margin 0.43)"},
    }
    verdict = {"decision": "accept", "decided_at_utc": "2099-01-01T02:15:40Z",
               "classification": "screening_estimate",
               "uncertainty": "Keputusan AI tanpa validasi eksperimental silang; gunakan untuk triase."}
    gates = {
        "vlm_confidence": {"state": "passed", "value": 0.87, "threshold": 0.80},
        "ocr_confidence": {"state": "passed", "value": 0.91, "threshold": 0.75},
        "manifest_crosscheck": {"state": "failed", "reason": "waste_type konflik: manifest 'organik' vs VLM 'campuran'"},
        "gas_plausibility": {"state": "passed", "value": 15.2, "threshold": 50.0},
        "weight_plausibility": {"state": "not_evaluated", "reason": "tidak ada rentang referensi untuk truck class ini"},
    }
    input_digests = {"photo": A.sha256_field(photo_bytes), "manifest_text": A.sha256_field(manifest_bytes),
                     "prompt": A.sha256_field(prompt_bytes)}

    print("== helpers ==")
    check("sha256_hex 64 hex", len(A.sha256_hex(b"x")) == 64)
    check("sha256_field format", A.sha256_field(b"x") == "sha256:" + A.sha256_hex(b"x"))
    raises("sha256_hex rejects str", A.sha256_hex, "not-bytes", contains="FORMAT_ERROR")
    check("now_utc ends with Z and matches regex", A.TIMESTAMP_RE.match(A.now_utc()) is not None)
    raises("bad timestamp no-Z", A.validate_timestamp, "2099-01-01T02:15:00+00:00", contains="Z")
    raises("bad timestamp naive", A.validate_timestamp, "2099-01-01 02:15:00", contains="ISO 8601 UTC")
    raises("bad timestamp offset", A.validate_timestamp, "2099-01-01T02:15:00+07:00", contains="ISO 8601")

    print("== begin_record (invariant 1, 3) ==")
    rec = A.begin_record(storage, {"name": "lynceus", "version": "0.1.0"}, inputs, input_digests)
    check("record_id format", rec.record_id == "inspection-000001", rec.record_id)
    check("status in_progress", rec.execution_status == "in_progress")
    check("finished_at null", rec.finished_at_utc is None)
    disk = json.loads((storage / "inspection-000001" / "audit.json").read_text(encoding="utf-8"))
    check("on-disk status in_progress", disk["execution_status"] == "in_progress")
    check("writer stamps format_version 2", disk["format_version"] == 2 == A.AUDIT_FORMAT_VERSION)
    check("input digests frozen on disk", disk["digest"]["input_digests"] == input_digests)
    check("no .tmp leftover", not any(p.name.endswith(".tmp") for p in (storage / "inspection-000001").iterdir()))
    check("begin record reloads strictly", A.load_record(storage / "inspection-000001" / "audit.json").record_id == rec.record_id)

    print("== finish_record happy path (invariants 1,2,3,7) ==")
    final = A.finish_record(storage, rec.record_id, "completed", "2099-01-01T02:15:41Z",
                            {"name": "lynceus", "version": "0.1.0"}, inputs, ai_outputs,
                            engine_outputs, verdict, gates,
                            frozen_inputs={"photo": photo_bytes, "manifest_text": manifest_bytes})
    check("final status completed", final.execution_status == "completed")
    check("finished_at set", final.finished_at_utc == "2099-01-01T02:15:41Z")
    check("gates preserved", final.gates.manifest_crosscheck.state == "failed")
    final_disk = json.loads((storage / "inspection-000001" / "audit.json").read_text(encoding="utf-8"))
    check("digest stamped", final_disk["digest"]["record_sha256"] != A.EMPTY_SHA256_FIELD)

    print("== invariant 2: single-shot finalization ==")
    raises("terminal cannot be re-finalized", A.finish_record, storage, rec.record_id, "failed", "2099-01-01T02:16:00Z",
           {"name": "lynceus", "version": "0.1.0"}, inputs, ai_outputs, engine_outputs, verdict, gates,
           contains="already terminal")
    check("re-finalize attempt left record intact",
          json.loads((storage / "inspection-000001" / "audit.json").read_text(encoding="utf-8"))["execution_status"] == "completed")

    print("== invariant 3: frozen input mismatch ==")
    rec2 = A.begin_record(storage, {"name": "lynceus", "version": "0.1.0"}, inputs, input_digests)
    check("second id incremented", rec2.record_id == "inspection-000002", rec2.record_id)
    raises("tampered photo rejected", A.finish_record, storage, rec2.record_id, "completed", "2099-01-01T02:15:41Z",
           {"name": "lynceus", "version": "0.1.0"}, inputs, ai_outputs, engine_outputs, verdict, gates,
           frozen_inputs={"photo": b"tampered!" + photo_bytes, "manifest_text": manifest_bytes},
           contains=A._ERR_INPUT_MISMATCH)
    raises("unknown frozen input rejected", A.finish_record, storage, rec2.record_id, "completed", "2099-01-01T02:15:41Z",
           {"name": "lynceus", "version": "0.1.0"}, inputs, ai_outputs, engine_outputs, verdict, gates,
           frozen_inputs={"surprise": b"x"}, contains=A._ERR_INPUT_MISMATCH)
    # leave inspection-000002 in_progress on purpose (crash simulation)

    print("== invariant 10: non-terminal finish + bad values ==")
    rec3 = A.begin_record(storage, {"name": "lynceus", "version": "0.1.0"}, inputs, input_digests)
    raises("in_progress status rejected by finish", A.finish_record, storage, rec3.record_id, "in_progress", "2099-01-01T02:15:41Z",
           {"name": "lynceus", "version": "0.1.0"}, inputs, ai_outputs, engine_outputs, verdict, gates,
           contains="terminal status")
    raises("missing finished_at rejected at entry", A.finish_record, storage, rec3.record_id, "failed", "not-a-time",
           {"name": "lynceus", "version": "0.1.0"}, inputs, ai_outputs, engine_outputs, verdict, gates,
           contains="finished_at_utc")
    bad_verdict = dict(verdict); bad_verdict["decision"] = "maybe"
    raises("closed enum verdict", A.finish_record, storage, rec3.record_id, "completed", "2099-01-01T02:15:41Z",
           {"name": "lynceus", "version": "0.1.0"}, inputs, ai_outputs, engine_outputs, bad_verdict, gates,
           contains="verdict.decision")
    bad_ai = json.loads(json.dumps(ai_outputs)); bad_ai["vlm"]["confidence"] = 1.5
    raises("confidence >1 rejected", A.finish_record, storage, rec3.record_id, "completed", "2099-01-01T02:15:41Z",
           {"name": "lynceus", "version": "0.1.0"}, inputs, bad_ai, engine_outputs, verdict, gates,
           contains="ai_outputs.vlm.confidence")
    bad_ai2 = json.loads(json.dumps(ai_outputs)); bad_ai2["llm"]["confidence"] = float("nan")
    raises("NaN confidence rejected (allow_nan=False guard + validator)",
           A.finish_record, storage, rec3.record_id, "completed", "2099-01-01T02:15:41Z",
           {"name": "lynceus", "version": "0.1.0"}, inputs, bad_ai2, engine_outputs, verdict, gates,
           contains="non-finite")
    bad_gates = json.loads(json.dumps(gates)); bad_gates["ocr_confidence"]["state"] = "skipped"
    raises("closed enum gate state", A.finish_record, storage, rec3.record_id, "completed", "2099-01-01T02:15:41Z",
           {"name": "lynceus", "version": "0.1.0"}, inputs, ai_outputs, engine_outputs, verdict, bad_gates,
           contains="gates")
    # record 3 still in_progress on disk after all failed finishes
    check("record 3 untouched by failed finishes",
          A.load_record(storage / "inspection-000003" / "audit.json").execution_status == "in_progress")

    print("== invariant 4: refuse_insufficient_input requires missing list ==")
    refuse_verdict = dict(verdict); refuse_verdict["decision"] = "refuse_insufficient_input"
    raises("refuse without missing list rejected", A.finish_record, storage, rec3.record_id, "failed", "2099-01-01T02:15:41Z",
           {"name": "lynceus", "version": "0.1.0"}, inputs, ai_outputs, engine_outputs, refuse_verdict, gates,
           contains="refuse_insufficient_input")
    refuse_rec = {**engine_outputs, "recommendation": {**engine_outputs["recommendation"],
                   "actionable": False, "route": "hold_for_review", "insufficient": True,
                   "missing": ["manifest_text"], "headline": "Manifest tidak terbaca."}}
    A.finish_record(storage, rec3.record_id, "failed", "2099-01-01T02:15:41Z",
                    {"name": "lynceus", "version": "0.1.0"}, inputs, ai_outputs, refuse_rec, refuse_verdict, gates)
    check("refuse with missing list accepted",
          A.load_record(storage / "inspection-000003" / "audit.json").verdict.decision == "refuse_insufficient_input")

    print("== invariant 8: relative paths only ==")
    abs_inputs = json.loads(json.dumps(inputs)); abs_inputs["photo"]["filename"] = "C:/Users/evidence/photo.jpg"
    raises("absolute photo filename rejected at begin", A.begin_record, storage,
           {"name": "lynceus", "version": "0.1.0"}, abs_inputs, input_digests,
           contains="inputs.photo.filename")
    rec4 = A.begin_record(storage, {"name": "lynceus", "version": "0.1.0"}, inputs, input_digests)
    trav_inputs = json.loads(json.dumps(inputs)); trav_inputs["photo"]["filename"] = "../../etc/passwd"
    raises("parent traversal rejected", A.begin_record, storage, {"name": "lynceus", "version": "0.1.0"}, trav_inputs, input_digests,
           contains="parent traversal")

    print("== invariant 6: load_record rejects hand-edits ==")
    p1 = storage / "inspection-000001" / "audit.json"
    orig = p1.read_text(encoding="utf-8")

    def edit_and_load(mutate, restamp=False):
        data = json.loads(orig)
        mutate(data)
        if restamp:
            # A schema-valid body change (e.g. a v1 downgrade) must re-stamp
            # the digest exactly as that writer would have, or the load-time
            # tamper check correctly rejects the record.
            data["digest"]["record_sha256"] = A.EMPTY_SHA256_FIELD
            A._stamp_record_digest(data)
        p1.write_text(json.dumps(data), encoding="utf-8")
        try:
            A.load_record(p1)
            return None
        except A.AuditError as e:
            return str(e)

    def set_status(d): d["execution_status"] = "succeeded"
    def bump_version(d): d["format_version"] = 99
    def bad_digest(d): d["inputs"]["photo"]["sha256"] = "deadbeef"
    def extra_key(d): d["sneaky"] = True
    def bad_ts(d): d["verdict"]["decided_at_utc"] = "2099-01-01T02:15:40+00:00"
    def strip_finished(d): del d["finished_at_utc"]
    def inf_gas(d): d["inputs"]["gas"]["readings_ppm"]["ch4"] = 1e400
    def bad_decision(d): d["verdict"]["decision"] = "approve"

    check("hand-edit status enum rejected", "execution_status" in (edit_and_load(set_status) or ""))
    check("future format_version rejected", "format_version" in (edit_and_load(bump_version) or ""))
    check("v1 format_version still readable", edit_and_load(lambda d: d.update(format_version=1), restamp=True) is None)
    check("bad digest regex rejected", "inputs.photo.sha256" in (edit_and_load(bad_digest) or ""))
    check("extra key rejected (extra=forbid)", "sneaky" in (edit_and_load(extra_key) or ""))
    check("non-Z timestamp rejected", "verdict.decided_at_utc" in (edit_and_load(bad_ts) or ""))
    check("terminal without finished_at rejected", "finished_at_utc" in (edit_and_load(strip_finished) or ""))
    inf_msg = edit_and_load(inf_gas)
    check("infinite gas value rejected", inf_msg is not None and "gas" in inf_msg, f"(got {inf_msg})")
    check("bad decision enum rejected", "verdict.decision" in (edit_and_load(bad_decision) or ""))
    p1.write_text(orig, encoding="utf-8")  # restore
    check("restored record valid again", A.load_record(p1).execution_status == "completed")

    print("== invariant 9 + ID non-reuse (list + allocate) ==")
    # corrupt record 4 (left in_progress by failed finish) and create dir without record
    (storage / "inspection-000004" / "audit.json").write_text("{ not json", encoding="utf-8")
    (storage / "inspection-000005").mkdir()
    listing = A.list_inspections(storage)
    check("listing does not crash", isinstance(listing, list) and len(listing) == 5, str(listing))
    by_id = {e["record_id"]: e for e in listing}
    check("corrupt record skipped with error", by_id["inspection-000004"]["ok"] is False and "FORMAT_ERROR" in by_id["inspection-000004"]["error"])
    check("missing record reported", by_id["inspection-000005"]["ok"] is False)
    check("good records listed ok", by_id["inspection-000001"]["ok"] and by_id["inspection-000001"]["execution_status"] == "completed")
    check("in_progress listed", by_id["inspection-000002"]["execution_status"] == "in_progress")
    check("listing sorted", [e["record_id"] for e in listing] == sorted((e["record_id"] for e in listing), key=lambda s: int(s.split("-")[1])))
    raises("load_record on corrupt still fails hard", A.load_record, storage / "inspection-000004" / "audit.json",
           contains="invalid JSON")

    # ID never reused: next allocation is 000006 even though 4/5 have no valid records
    rid, path = A.allocate_inspection_id(storage)
    check("next id skips corrupt/empty dirs (no reuse)", rid == "inspection-000006", rid)
    check("allocate creates dir", path.is_dir())

    print("== record_id never reused across 'restarts' ==")
    rid2, _ = A.allocate_inspection_id(storage)
    check("subsequent allocation increments", rid2 == "inspection-000007", rid2)

    print("== invariant 5 docstring: completed != correct ==")
    check("gates state not_evaluated explicit at begin", all(
        getattr(rec.gates, g).state == "not_evaluated" for g in A.GATE_NAMES))
    final_loaded = A.load_record(p1)
    check("completed record still carries failed gate",
          final_loaded.execution_status == "completed" and final_loaded.gates.manifest_crosscheck.state == "failed")

    print("== tamper evidence: body edit invalidates the stored digest ==")
    tampered = json.loads(p1.read_text(encoding="utf-8"))
    tampered["inputs"]["truck_id"] = "HACKED-TRUCK"
    p1.write_text(json.dumps(tampered, indent=2), encoding="utf-8")
    try:
        A.load_record(p1)
        check("hand-edited record body is rejected on load", False, "loaded without error")
    except A.AuditError:
        check("hand-edited record body is rejected on load", True)

    tampered2 = json.loads(p1.read_text(encoding="utf-8"))
    # restore truck_id, tamper the verdict decision instead
    tampered2["inputs"]["truck_id"] = rec.inputs.truck_id
    tampered2["verdict"]["decision"] = "reject"
    p1.write_text(json.dumps(tampered2, indent=2), encoding="utf-8")
    try:
        A.load_record(p1)
        check("tampered verdict is rejected on load", False, "loaded without error")
    except A.AuditError:
        check("tampered verdict is rejected on load", True)
    # restore the pristine record for subsequent checks
    A._atomic_write_json(p1, json.loads(json.dumps(final_loaded.model_dump(mode="json"))))

    print("== failed finish on nonexistent record ==")
    raises("finish unknown record", A.finish_record, storage, "inspection-999999", "failed", "2099-01-01T02:15:41Z",
           {"name": "lynceus", "version": "0.1.0"}, inputs, ai_outputs, engine_outputs, verdict, gates,
           contains="not found")

    print("== cleanup-on-failed-begin (pattern 29) ==")
    before = set(p.name for p in storage.iterdir())
    try:
        A.begin_record(storage, {"name": "lynceus", "version": "0.1.0"}, trav_inputs, input_digests)
        check("begin with bad inputs raises", False)
    except A.AuditError:
        after = set(p.name for p in storage.iterdir())
        check("empty dir cleaned up on failed begin", before == after, f"before={before} after={after}")

    shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n{PASS} passed, {FAIL} failed")



    assert FAIL == 0, f"{FAIL} invariant checks failed"