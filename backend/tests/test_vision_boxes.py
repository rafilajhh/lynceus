"""Contaminant localisation: strict box validation (Task 4)."""

from __future__ import annotations

import math

import pytest
from fastapi.testclient import TestClient

from lynceus import pipeline
from lynceus.api import create_app
from lynceus.config import LYNCEUS_STORAGE_DIR_ENV, get_settings
from lynceus.vision_boxes import ZONES, parse_locations

_LIVE_PAYLOAD = {
    "truck_id": "B-9174-KT",
    "photo_base64": "c3R1Yi1waG90bw==",
    "manifest_text": "Declared weight: 18,400 kg. Moisture declared: 10% (dry).",
    "weight_kg": 18500,
    "waste_stream": "rdf-feedstock",
    "moisture": 0.095,
    "age_h": 5,
}


def _loc(box, label="metal", **extra):
    return {"label": label, "box": box, **extra}


def test_zones_are_a_third_grid():
    assert set(ZONES) == {
        "top-left", "top", "top-right", "left", "center", "right",
        "bottom-left", "bottom", "bottom-right",
    }
    assert ZONES["center"] == (1 / 3, 1 / 3, 2 / 3, 2 / 3)
    assert ZONES["top-left"] == (0.0, 0.0, 1 / 3, 1 / 3)
    assert ZONES["bottom-right"] == (2 / 3, 2 / 3, 1.0, 1.0)


def test_valid_box_kept():
    out = parse_locations([_loc([0.1, 0.2, 0.5, 0.6])], "box")
    assert out == [{"label": "metal", "x0": 0.1, "y0": 0.2, "x1": 0.5, "y1": 0.6}]


def test_inverted_box_dropped():
    assert parse_locations([_loc([0.5, 0.5, 0.4, 0.6])], "box") == []


def test_out_of_range_box_dropped_not_clamped():
    assert parse_locations([_loc([0, 0, 1.3, 1])], "box") == []
    assert parse_locations([_loc([-0.1, 0.1, 0.5, 0.5])], "box") == []


def test_non_dict_entry_dropped():
    assert parse_locations(["abc"], "box") == []
    assert parse_locations([None, 3, [0.1, 0.1, 0.5, 0.5]], "box") == []


@pytest.mark.parametrize(
    "bad",
    [None, "nonsense", 5, {"label": "metal"}, [], "abc"],
)
def test_non_list_raw_gives_empty(bad):
    assert parse_locations(bad, "box") == []
    assert parse_locations(bad, "zone") == []


def test_bad_box_values_dropped():
    for box in (
        [0.1, 0.1, 0.5],            # wrong length
        [0.1, 0.1, 0.5, 0.5, 0.9],  # wrong length
        ["a", "b", "c", "d"],
        [True, False, True, True],  # bools are not coordinates
        [math.nan, 0.1, 0.5, 0.5],
        [0.1, 0.1, math.inf, 0.5],
        "0.1,0.1,0.5,0.5",
        None,
    ):
        assert parse_locations([_loc(box)], "box") == [], box


def test_max_boxes_caps_output():
    raw = [_loc([0.1, 0.1, 0.3, 0.3]) for _ in range(50)]
    assert len(parse_locations(raw, "box")) == 8
    assert len(parse_locations(raw, "box", max_boxes=3)) == 3


def test_tiny_area_dropped():
    # 0.02 x 0.02 = 0.0004 < min_area 0.0025
    assert parse_locations([_loc([0.1, 0.1, 0.12, 0.12])], "box") == []
    # 0.1 x 0.1 = 0.01 >= min_area: kept
    assert len(parse_locations([_loc([0.1, 0.1, 0.2, 0.2])], "box")) == 1


def test_full_frame_box_dropped():
    # Ruling 7: MiniCPM-V returned [0,0,1,1] "textile" on a clean load 3/3.
    assert parse_locations([_loc([0, 0, 1, 1], label="textile")], "box") == []
    assert parse_locations([_loc([0.02, 0.02, 0.98, 0.98])], "box") == []  # 0.9216
    assert len(parse_locations([_loc([0.1, 0.1, 0.9, 0.9])], "box")) == 1  # 0.64


def test_full_frame_box_with_valid_zone_dropped_entirely():
    # Ruling 14: oversize box drops the entry; no zone fallback.
    raw = [{"label": "textile", "box": [0, 0, 1, 1], "zone": "center"}]
    assert parse_locations(raw, "box") == []


def test_huge_int_coordinate_is_garbage_not_a_crash():
    huge = 10**400
    assert parse_locations([_loc([0, 0, huge, 1])], "box") == []
    assert parse_locations([_loc([-huge, 0, 0.5, 0.5])], "box") == []
    # Malformed (not oversize) box still falls back to its zone.
    out = parse_locations([_loc([0, 0, huge, 1], zone="center")], "box")
    assert len(out) == 1 and out[0]["x0"] == 1 / 3


def test_max_area_is_a_parameter():
    raw = [_loc([0.0, 0.0, 1.0, 1.0])]
    assert parse_locations(raw, "box", max_area=1.0) == [
        {"label": "metal", "x0": 0.0, "y0": 0.0, "x1": 1.0, "y1": 1.0}
    ]


def test_zone_mode_uses_zone_keys():
    out = parse_locations([{"label": "metal", "zone": "center"}], "zone")
    assert out == [
        {"label": "metal", "x0": 1 / 3, "y0": 1 / 3, "x1": 2 / 3, "y1": 2 / 3}
    ]


def test_zone_mode_ignores_box():
    assert parse_locations([_loc([0.1, 0.1, 0.5, 0.5])], "zone") == []


def test_unknown_zone_dropped():
    assert parse_locations([{"label": "metal", "zone": "middle"}], "zone") == []
    assert parse_locations([{"label": "metal", "zone": 3}], "zone") == []


def test_box_mode_falls_back_to_zone_per_entry():
    raw = [
        _loc([0.5, 0.5, 0.4, 0.6], zone="top-left"),  # bad box -> zone
        _loc([0.6, 0.6, 0.9, 0.9], zone="top-left"),  # good box wins
        {"label": "rock"},                             # nothing usable
    ]
    out = parse_locations(raw, "box")
    assert [(o["x0"], o["y0"]) for o in out] == [(0.0, 0.0), (0.6, 0.6)]


def test_labels_normalised_and_required():
    raw = [
        _loc([0.1, 0.1, 0.5, 0.5], label="  Metal "),
        _loc([0.1, 0.1, 0.5, 0.5], label=""),
        _loc([0.1, 0.1, 0.5, 0.5], label="   "),
        _loc([0.1, 0.1, 0.5, 0.5], label=7),
        {"box": [0.1, 0.1, 0.5, 0.5]},
    ]
    assert [o["label"] for o in parse_locations(raw, "box")] == ["metal"]


# ---------------------------------------------------------------------------
# Pipeline wiring
# ---------------------------------------------------------------------------


def test_vlm_prompt_asks_for_locations():
    assert '"locations"' in pipeline._VLM_PROMPT
    assert "top-left|top|top-right|left|center|right|bottom-left|bottom|bottom-right" in (
        pipeline._VLM_PROMPT
    )


def test_stub_red_returns_metal_zone_center():
    out = pipeline.StubAIClients(demo_case="red").vlm(None)
    assert out["localisation"] == "zone"
    assert out["boxes"] == [
        {"label": "metal", "x0": 1 / 3, "y0": 1 / 3, "x1": 2 / 3, "y1": 2 / 3}
    ]


@pytest.mark.parametrize("case", ["green", "amber"])
def test_stub_clean_cases_have_no_boxes(case):
    out = pipeline.StubAIClients(demo_case=case).vlm(None)
    assert out["boxes"] == []


def _live_with_reply(monkeypatch, reply_json, mode=None):
    if mode:
        monkeypatch.setenv("LOCALISATION_MODE", mode)
    monkeypatch.setenv("VLLM_VLM_URL", "https://developer.amd.com.cn/radeon/api/v1")
    monkeypatch.setenv("VLLM_LLM_URL", "https://developer.amd.com.cn/radeon/api/v1")
    live = pipeline.VLLMClient(settings=get_settings())
    monkeypatch.setattr(pipeline.VLLMClient, "_chat_once", lambda self, *a, **k: reply_json)
    monkeypatch.setattr(pipeline, "resolve_clients", lambda payload, settings=None: live)
    return live


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv(LYNCEUS_STORAGE_DIR_ENV, str(tmp_path))
    monkeypatch.setattr(pipeline, "_vlm_reachable", lambda *a, **k: False)
    return TestClient(create_app())


_BASE = (
    '"contamination": "metal tray", "moisture": 0.1, "hard_contaminants": ["metal"], '
    '"light_contaminants": [], "reasoning": "ok", "crosscheck_notes": "consistent", '
    '"confidence": 0.8'
)


def test_inspect_with_garbage_locations_completes(client, monkeypatch):
    _live_with_reply(monkeypatch, "{" + _BASE + ', "locations": "nonsense"}')
    resp = client.post("/inspect", json=_LIVE_PAYLOAD)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["provenance"] == "live"
    assert body["ai_outputs"]["vlm"]["boxes"] == []
    assert body["ai_outputs"]["vlm"]["localisation"] == "box"


def test_inspect_live_box_mode_returns_validated_boxes(client, monkeypatch):
    locs = (
        '[{"label": "Metal", "box": [0.06, 0.09, 0.96, 0.84], "zone": "center"},'
        ' {"label": "textile", "box": [0, 0, 1, 1]},'
        ' {"label": "rock", "box": [0.5, 0.5, 0.4, 0.6]}]'
    )
    _live_with_reply(monkeypatch, "{" + _BASE + ', "locations": ' + locs + "}")
    resp = client.post("/inspect", json=_LIVE_PAYLOAD)
    assert resp.status_code == 200, resp.text
    vlm = resp.json()["ai_outputs"]["vlm"]
    assert vlm["localisation"] == "box"
    # Full-frame textile and inverted rock (no zone) dropped.
    assert vlm["boxes"] == [
        {"label": "metal", "x0": 0.06, "y0": 0.09, "x1": 0.96, "y1": 0.84}
    ]


def test_inspect_full_frame_box_with_zone_yields_no_boxes(client, monkeypatch):
    locs = '[{"label": "textile", "box": [0, 0, 1, 1], "zone": "center"}]'
    _live_with_reply(monkeypatch, "{" + _BASE + ', "locations": ' + locs + "}")
    resp = client.post("/inspect", json=_LIVE_PAYLOAD)
    assert resp.status_code == 200, resp.text
    vlm = resp.json()["ai_outputs"]["vlm"]
    assert vlm["localisation"] == "box"
    assert vlm["boxes"] == []


def test_inspect_with_huge_int_coordinate_completes(client, monkeypatch):
    locs = '[{"label": "metal", "box": [0, 0, ' + "9" * 400 + ', 1]}]'
    _live_with_reply(monkeypatch, "{" + _BASE + ', "locations": ' + locs + "}")
    resp = client.post("/inspect", json=_LIVE_PAYLOAD)
    assert resp.status_code == 200, resp.text
    assert resp.json()["provenance"] == "live"  # not a stub fallback
    assert resp.json()["ai_outputs"]["vlm"]["boxes"] == []


def test_inspect_live_zone_mode(client, monkeypatch):
    locs = '[{"label": "metal", "zone": "bottom-left", "box": [0.1, 0.1, 0.2, 0.2]}]'
    _live_with_reply(monkeypatch, "{" + _BASE + ', "locations": ' + locs + "}", mode="zone")
    resp = client.post("/inspect", json=_LIVE_PAYLOAD)
    vlm = resp.json()["ai_outputs"]["vlm"]
    assert vlm["localisation"] == "zone"
    assert vlm["boxes"] == [
        {"label": "metal", "x0": 0.0, "y0": 2 / 3, "x1": 1 / 3, "y1": 1.0}
    ]


def test_inspect_stub_red_exposes_boxes(client):
    payload = dict(_LIVE_PAYLOAD, demo_case="red")
    resp = client.post("/inspect", json=payload)
    assert resp.status_code == 200, resp.text
    vlm = resp.json()["ai_outputs"]["vlm"]
    assert vlm["localisation"] == "zone"
    assert [b["label"] for b in vlm["boxes"]] == ["metal"]
