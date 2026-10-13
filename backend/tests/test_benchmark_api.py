"""GET /benchmark/latest and /benchmark/manifest.csv — static benchmark results."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from lynceus import api

FRAMING = "component validation on public RealWaste images — not field data from a plant"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "_BENCHMARK_DIR", tmp_path)
    (tmp_path / "results").mkdir()
    return TestClient(api.create_app()), tmp_path


def _write(results, name, body):
    (results / name).write_text(json.dumps(body), encoding="utf-8")


def test_latest_returns_newest_summary_with_framing(client):
    c, root = client
    _write(root / "results", "2026-10-13.summary.json", {"n": 1, "date": "2026-10-13"})
    _write(root / "results", "2026-10-14.summary.json", {"n": 80, "date": "2026-10-14"})
    _write(root / "results", "2026-10-14.jsonl", {"ignored": True})
    body = c.get("/benchmark/latest").json()
    assert body["n"] == 80 and body["date"] == "2026-10-14"
    assert body["framing"] == FRAMING


def test_latest_is_404_when_no_run_exists(client):
    c, _ = client
    r = c.get("/benchmark/latest")
    assert r.status_code == 404
    assert r.json()["detail"]["error"] == "no_benchmark"


def test_latest_skips_an_unreadable_newest_file(client):
    c, root = client
    _write(root / "results", "2026-10-13.summary.json", {"n": 5})
    (root / "results" / "2026-10-14.summary.json").write_text("{not json", encoding="utf-8")
    assert c.get("/benchmark/latest").json()["n"] == 5


def test_manifest_csv_is_served(client):
    c, root = client
    (root / "manifest.csv").write_text("image,category,expected\na.jpg,Metal,reject\n", encoding="utf-8")
    r = c.get("/benchmark/manifest.csv")
    assert r.status_code == 200 and "a.jpg,Metal,reject" in r.text
    assert r.headers["content-type"].startswith("text/csv")
