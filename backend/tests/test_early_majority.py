"""Early majority: two agreeing vision reads decide once the third has had
its grace window.  No network: ``VLLMClient._chat_once`` is scripted per
call, and every read whose timing matters is released by an event from
inside the vote itself (never by a sleep racing the grace window)."""

from __future__ import annotations

import base64
import concurrent.futures
import json
import threading
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from lynceus import audit, decision, pipeline, waybill
from lynceus.api import create_app
from lynceus.config import LYNCEUS_STORAGE_DIR_ENV, get_settings
from lynceus.pipeline import VLLMClient

PHOTO = base64.b64encode(b"\xff\xd8\xff\xe0load").decode("ascii")
CONFIRMED_FIELDS = waybill.values_of(waybill.SAMPLE_FIELDS)
_LLM_JSON = '{"reasoning": "ok", "crosscheck_notes": "consistent", "confidence": 0.8}'
#: How long a gated read waits for its event before giving up (a test bug).
_GATE_S = 10.0
#: Generous: a read released by the vote's own grace event arrives at once.
_LONG_GRACE = "30"
#: Short: the late read is held past it on purpose.
_SHORT_GRACE = "0.2"


def _vlm_json(hard):
    return json.dumps(
        {
            "contamination": "x",
            "moisture": 0.1,
            "hard_contaminants": hard,
            "light_contaminants": [],
            "confidence": 0.8,
            "locations": [],
        }
    )


class _Vote:
    """Events from inside :meth:`VLLMClient._vote_reads`: ``grace`` once it
    waits on a grace timeout (a majority agreed), ``error`` once it has seen
    a failed read, ``two_seen`` once it has seen two reads answer."""

    def __init__(self, monkeypatch):
        self.grace = threading.Event()
        self.error = threading.Event()
        self.two_seen = threading.Event()
        seen: set = set()
        real_wait = concurrent.futures.wait

        def watched(fs, timeout=None, return_when=concurrent.futures.ALL_COMPLETED):
            if timeout is not None:
                self.grace.set()
            done, pending = real_wait(fs, timeout=timeout, return_when=return_when)
            if any(f.exception() is not None for f in done):
                self.error.set()
            seen.update(f for f in done if f.exception() is None)
            if len(seen) >= 2:
                self.two_seen.set()
            return done, pending

        monkeypatch.setattr(pipeline, "wait", watched)

    def release(self):
        self.grace.set()
        self.error.set()
        self.two_seen.set()


class _Script:
    """The n-th vision call (in arrival order) answers ``reads[n]``: a hard
    set or an exception, once its ``gate`` event (if any) is set."""

    def __init__(self, reads):
        self.reads = reads
        self.lock = threading.Lock()
        self.calls = 0

    def install(self, monkeypatch):
        # A plain function, so it binds as a method of VLLMClient.
        def chat_once(client, base_url, model, messages, max_tokens=512):
            return self.answer(messages)

        monkeypatch.setattr(VLLMClient, "_chat_once", chat_once)

    def answer(self, messages):
        if "image_url" not in json.dumps(messages):
            return _LLM_JSON
        with self.lock:
            spec = self.reads[self.calls]
            self.calls += 1
        if spec.get("gate") is not None:
            spec["gate"].wait(_GATE_S)
        if "error" in spec:
            raise spec["error"]
        return _vlm_json(spec["hard"])


@pytest.fixture()
def vote(monkeypatch):
    watch = _Vote(monkeypatch)
    yield watch
    watch.release()  # never leave a scripted read blocked past the test


@pytest.fixture()
def held():
    gate = threading.Event()
    yield gate
    gate.set()


def _vlm(monkeypatch, reads, grace):
    monkeypatch.setenv("VLM_VOTES", "3")
    monkeypatch.setenv("VLM_VOTE_GRACE_S", grace)
    monkeypatch.setenv("VLM_MODEL", "vlm-a")
    monkeypatch.setenv("VLM_FALLBACK_MODELS", "vlm-b")
    _Script(reads).install(monkeypatch)
    started = time.perf_counter()
    result = VLLMClient(settings=get_settings()).vlm(PHOTO)
    return result, time.perf_counter() - started


def _free_read_slots() -> int:
    taken = 0
    while pipeline._VLM_READ_SLOTS.acquire(blocking=False):
        taken += 1
    for _ in range(taken):
        pipeline._VLM_READ_SLOTS.release()
    return taken


# ---------------------------------------------------------------------------
# The vote
# ---------------------------------------------------------------------------


def test_two_agreeing_reads_decide_when_the_third_is_late(monkeypatch, vote, held):
    result, took = _vlm(
        monkeypatch,
        [{"hard": []}, {"hard": []}, {"hard": ["metal"], "gate": held}],
        _SHORT_GRACE,
    )
    assert took < _GATE_S / 2  # decided long before the held read could answer
    assert (result["votes_used"], result["third_read"]) == (2, "late")
    assert [v["hard"] for v in result["votes"]] == [[], []]
    assert result["detected"]["hard_contaminants"] == []
    assert result["model"] == "vlm-a"
    # The late read gave its read slot back: the next truck can read at once.
    assert _free_read_slots() == pipeline._VLM_READ_SLOT_COUNT


def test_a_minority_hard_sighting_in_the_grace_window_counts(monkeypatch, vote):
    result, _ = _vlm(
        monkeypatch,
        [{"hard": []}, {"hard": []}, {"hard": ["metal"], "gate": vote.grace}],
        _LONG_GRACE,
    )
    assert (result["votes_used"], result["third_read"]) == (3, "arrived")
    assert sorted(v["hard"] for v in result["votes"]) == [[], [], ["metal"]]
    assert result["detected"]["hard_contaminants"] == []  # the majority
    # R1: the rules still see the read the majority dropped.
    assert decision.vote_split(result) == {"metal": (1, 3)}


def test_agreeing_on_a_hard_item_also_decides_early(monkeypatch, vote, held):
    result, _ = _vlm(
        monkeypatch,
        [{"hard": ["metal"]}, {"hard": ["metal"]}, {"hard": [], "gate": held}],
        _SHORT_GRACE,
    )
    assert (result["votes_used"], result["third_read"]) == (2, "late")
    assert result["detected"]["hard_contaminants"] == ["metal"]


def test_disagreeing_first_reads_wait_for_the_third(monkeypatch, vote):
    result, _ = _vlm(
        monkeypatch,
        [{"hard": []}, {"hard": ["metal"]}, {"hard": ["metal"], "gate": vote.two_seen}],
        "0",
    )
    assert not vote.grace.is_set()  # no grace window was ever opened
    assert "votes_used" not in result and "third_read" not in result
    assert len(result["votes"]) == 3
    assert result["detected"]["hard_contaminants"] == ["metal"]  # 2 of 3


def test_a_third_read_failing_in_the_grace_window_is_stated(monkeypatch, vote):
    error = httpx.HTTPStatusError("503", request=None, response=None)
    result, _ = _vlm(
        monkeypatch,
        [{"hard": []}, {"hard": []}, {"error": error, "gate": vote.grace}],
        _LONG_GRACE,
    )
    # A majority already agreed: no fallback model, the failure is recorded.
    assert result["model"] == "vlm-a" and "fallback_from" not in result
    assert (result["votes_used"], result["third_read"]) == (2, "failed")


def test_a_failure_before_any_majority_still_fails_the_model(monkeypatch, vote):
    error = httpx.HTTPStatusError("503", request=None, response=None)
    result, _ = _vlm(
        monkeypatch,
        [
            {"error": error},
            {"hard": [], "gate": vote.error},
            {"hard": [], "gate": vote.error},
            {"hard": []},
            {"hard": []},
            {"hard": []},
        ],
        _LONG_GRACE,
    )
    assert result["model"] == "vlm-b"
    assert result["fallback_from"][0].startswith("vlm-a: HTTPStatusError")


def test_zero_grace_decides_on_the_agreeing_reads_at_once(monkeypatch, vote, held):
    result, took = _vlm(
        monkeypatch, [{"hard": []}, {"hard": []}, {"hard": [], "gate": held}], "0"
    )
    assert took < _GATE_S / 2
    assert (result["votes_used"], result["third_read"]) == (2, "late")


@pytest.mark.parametrize(
    ("raw", "grace"),
    [(None, 4.0), ("1.5", 1.5), ("0", 0.0), ("-3", 0.0), ("500", 90.0), ("x", 4.0), ("nan", 4.0)],
)
def test_vote_grace_env_is_clamped(monkeypatch, raw, grace):
    if raw is None:
        monkeypatch.delenv("VLM_VOTE_GRACE_S", raising=False)
    else:
        monkeypatch.setenv("VLM_VOTE_GRACE_S", raw)
    assert get_settings().vlm_vote_grace_s == grace


# ---------------------------------------------------------------------------
# Stream, caveat, audit and rules
# ---------------------------------------------------------------------------


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv(LYNCEUS_STORAGE_DIR_ENV, str(tmp_path))
    monkeypatch.setattr(pipeline, "safe_detect", lambda *a, **k: None)
    monkeypatch.setattr(
        pipeline, "resolve_clients", lambda payload, settings=None: VLLMClient(settings)
    )
    monkeypatch.setenv("VLM_VOTES", "3")
    monkeypatch.delenv("VLM_FALLBACK_MODELS", raising=False)
    return TestClient(create_app())


def _stream(client, monkeypatch, reads, grace):
    monkeypatch.setenv("VLM_VOTE_GRACE_S", grace)
    _Script(reads).install(monkeypatch)
    resp = client.post(
        "/inspect/stream",
        json={"photo_base64": PHOTO, "waybill_fields": CONFIRMED_FIELDS, "weight_kg": 16340},
    )
    assert resp.status_code == 200, resp.text
    events = [json.loads(line) for line in resp.text.splitlines()]
    assert events[-1]["event"] == "result", events[-1]
    vision_done = [e for e in events if e.get("stage") == "vision" and e["status"] == "done"]
    return vision_done[0]["data"], events[-1]["data"]


def test_late_third_read_is_streamed_sealed_and_caveated(
    client, tmp_path, monkeypatch, vote, held
):
    vision, result = _stream(
        client,
        monkeypatch,
        [{"hard": []}, {"hard": []}, {"hard": ["metal"], "gate": held}],
        _SHORT_GRACE,
    )
    assert (vision["votes_used"], vision["third_read"]) == (2, "late")
    rec = audit.load_record(tmp_path / result["record_id"] / audit.RECORD_FILENAME)
    assert (rec.ai_outputs.vlm.votes_used, rec.ai_outputs.vlm.third_read) == (2, "late")
    assert len(rec.ai_outputs.vlm.votes) == 2
    caveats = rec.engine_outputs.recommendation.caveats
    assert any("2 of 3 reads (third late)" in c for c in caveats), caveats


def test_minority_metal_in_the_grace_window_holds_the_truck(
    client, tmp_path, monkeypatch, vote
):
    vision, result = _stream(
        client,
        monkeypatch,
        [{"hard": []}, {"hard": []}, {"hard": ["metal"], "gate": vote.grace}],
        _LONG_GRACE,
    )
    assert (vision["votes_used"], vision["third_read"]) == (3, "arrived")
    assert result["verdict"]["decision"] == audit.Decision.ESCALATE_HUMAN
    assert decision.VOTE_SPLIT_MARKER in json.dumps(result)
    rec = audit.load_record(tmp_path / result["record_id"] / audit.RECORD_FILENAME)
    assert not any("third" in c for c in rec.engine_outputs.recommendation.caveats)


def test_old_records_without_early_majority_fields_still_load():
    vlm = audit.VLMOutput(
        model="m", model_version="m", raw_output_sha256="sha256:" + "0" * 64,
        detected={}, confidence=0.8,
    )
    assert vlm.votes_used is None and vlm.third_read is None
    with pytest.raises(Exception):
        audit.VLMOutput(
            model="m", model_version="m", raw_output_sha256="sha256:" + "0" * 64,
            detected={}, confidence=0.8, third_read="maybe",
        )
