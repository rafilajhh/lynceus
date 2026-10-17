"""AMD inference API: the measured Token Factory run, live telemetry, eval card.

Routes (all behind ``auth.require_auth``):

    GET /benchmark/amd — ``{measured, live, eval}``:
        ``measured`` the newest ``benchmark/results/*.amd-throughput.json``
        (``null`` before any run), ``live`` p50/p95 vision and detector
        latency over the last 50 completed live inspections, ``eval`` the
        eval card and fusion-lift table from the committed benchmark
        summaries (``null`` when they are missing).

Read-only and file-backed: no model is called.
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends

from lynceus import amd_bench, auth
from lynceus.config import get_settings

router = APIRouter()

#: Completed live inspections the telemetry window covers.
LIVE_WINDOW = 50


@router.get("/benchmark/amd")
def get_amd_benchmark(_user: str | None = Depends(auth.require_auth)) -> Dict[str, Any]:
    from lynceus import api  # the app's benchmark dir (LYNCEUS_BENCHMARK_DIR)

    results = api._BENCHMARK_DIR / "results"
    return {
        "measured": amd_bench.latest(results),
        "live": amd_bench.live_telemetry(get_settings().storage_dir, LIVE_WINDOW),
        "eval": amd_bench.eval_card(results),
    }
