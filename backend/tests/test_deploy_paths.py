"""Container path overrides: LYNCEUS_WEB_DIR / LYNCEUS_BENCHMARK_DIR and PORT."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from lynceus import api, main

SRC = str(Path(__file__).resolve().parents[1] / "src")


def test_dir_from_env_uses_override_else_default(monkeypatch, tmp_path):
    default = tmp_path / "default"
    monkeypatch.delenv("LYNCEUS_TEST_DIR", raising=False)
    assert api._dir_from_env("LYNCEUS_TEST_DIR", default) == default
    monkeypatch.setenv("LYNCEUS_TEST_DIR", "  ")
    assert api._dir_from_env("LYNCEUS_TEST_DIR", default) == default
    monkeypatch.setenv("LYNCEUS_TEST_DIR", str(tmp_path / "custom"))
    assert api._dir_from_env("LYNCEUS_TEST_DIR", default) == tmp_path / "custom"


def test_module_constants_follow_env_at_import(tmp_path):
    web, bench = tmp_path / "web", tmp_path / "bench"
    code = "import lynceus.api as a; print(a._WEB_DIR); print(a._BENCHMARK_DIR)"
    env = {**os.environ, "PYTHONPATH": SRC, "LYNCEUS_WEB_DIR": str(web), "LYNCEUS_BENCHMARK_DIR": str(bench)}
    out = subprocess.run(
        [sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True
    ).stdout.split("\n")
    assert Path(out[0]) == web and Path(out[1]) == bench


def test_main_port_from_env(monkeypatch):
    seen = {}
    monkeypatch.setattr(main.uvicorn, "run", lambda *a, **kw: seen.update(kw))
    monkeypatch.delenv("PORT", raising=False)
    main.main()
    assert seen["port"] == 8020 and seen["host"] == "0.0.0.0"
    monkeypatch.setenv("PORT", "9123")
    main.main()
    assert seen["port"] == 9123
