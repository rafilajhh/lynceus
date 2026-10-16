"""Pin every cache (pip, torch, HF, Ultralytics, temp) under ml/.cache.

Import this first in every ml/ script: the C: drive on the dev laptop is nearly
full, so nothing heavy may land in the user profile.
"""

from __future__ import annotations

import os
from pathlib import Path

ML = Path(__file__).resolve().parent
REPO = ML.parent
CACHE = ML / ".cache"
DATA = ML / "data"
RUNS = ML / "runs"
WEIGHTS = ML / "weights"
RESULTS = ML / "results"
BENCH = REPO / "backend" / "benchmark"

_DIRS = {
    "PIP_CACHE_DIR": CACHE / "pip",
    "TORCH_HOME": CACHE / "torch",
    "HF_HOME": CACHE / "hf",
    "YOLO_CONFIG_DIR": CACHE / "yolo",
    "TMP": CACHE / "tmp",
    "TEMP": CACHE / "tmp",
    "TMPDIR": CACHE / "tmp",
    "MPLCONFIGDIR": CACHE / "mpl",
}
for _key, _path in _DIRS.items():
    _path.mkdir(parents=True, exist_ok=True)
    os.environ[_key] = str(_path)
for _path in (DATA, RUNS, WEIGHTS, RESULTS):
    _path.mkdir(parents=True, exist_ok=True)

import tempfile  # noqa: E402

tempfile.tempdir = str(CACHE / "tmp")


def yolo_setup() -> None:
    """Keep Ultralytics downloads/runs under ml/ and turn off its analytics sync.

    Ultralytics drops some assets (text encoder, AMP-check weights) in the cwd or its
    `weights_dir` setting, so both point at ml/weights.
    """
    os.chdir(WEIGHTS)
    from ultralytics import settings

    settings.update(weights_dir=str(WEIGHTS), runs_dir=str(RUNS), datasets_dir=str(DATA), sync=False)
