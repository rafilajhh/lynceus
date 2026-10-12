"""Seed the demo ledger with one green / amber / red inspection record.

Design review finding 2: the default storage dir filled up with dozens of
smoke-test records — the same truck rejected 9× whose "prevented" losses
were summed into an inflated aggregate.  This script replaces that noise
with a clean, honest demo history: exactly three records, one per demo
case, each with a distinct truck and figure.

Usage (from ``backend/``)::

    python scripts/seed_demo.py            # add 3 records (append-only)
    python scripts/seed_demo.py --reset    # wipe old inspection-* records first

The AI layer is pinned to the offline stub (no network, deterministic), so
the seeded verdicts are always ACCEPT / ESCALATE_HUMAN / REJECT.  The
storage dir follows the same environment contract as the API
(``LYNCEUS_STORAGE_DIR``, default ``./runs``); the reset only ever deletes
``inspection-*`` directories — any other structure in the storage dir is
left untouched.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

# Make ``import lynceus`` work when run as ``python scripts/seed_demo.py``.
_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from lynceus import audit, impact  # noqa: E402
from lynceus import pipeline as pipeline_mod  # noqa: E402
from lynceus.api import InspectRequest, _run_inspection_with_audit  # noqa: E402
from lynceus.config import LYNCEUS_STORAGE_DIR_ENV, get_settings  # noqa: E402

# One truck per demo story — varied IDs so the ledger reads like a real day
# at the gate, never the same plate repeated (finding 2).
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

#: One seed record per demo case: green → ACCEPT, amber → ESCALATE_HUMAN,
#: red → REJECT (weights/streams mirror the API test payloads so the stub
#: verdicts are the documented story ones).
SEED_RECORDS = [
    {
        "truck_id": "B-9174-KT",
        "demo_case": "green",
        "manifest_text": _GREEN_MANIFEST,
        "weight_kg": 18500,
        "waste_stream": "rdf-feedstock",
        "moisture": 0.095,
        "age_h": 5,
    },
    {
        "truck_id": "DK-4418-WR",
        "demo_case": "amber",
        "manifest_text": _AMBER_MANIFEST,
        "weight_kg": 11450,
        "waste_stream": "organic-rich",
        "moisture": 0.57,
        "age_h": 76,
    },
    {
        "truck_id": "F-7702-TS",
        "demo_case": "red",
        "manifest_text": _RED_MANIFEST,
        "weight_kg": 19300,  # weighbridge far above the declared 15,500 kg
        "waste_stream": "mixed-msw",
        "moisture": 0.14,
        "age_h": 8,
    },
]

#: demo_case → expected verdict (the scripted stub story).
EXPECTED_VERDICTS = {
    "green": "accept",
    "amber": "escalate_human",
    "red": "reject",
}


def reset_storage(storage_dir: Path) -> int:
    """Delete every ``inspection-*`` directory; return how many went."""
    removed = 0
    if not storage_dir.is_dir():
        return 0
    for entry in sorted(storage_dir.iterdir()):
        if entry.is_dir() and entry.name.startswith("inspection-"):
            shutil.rmtree(entry)
            removed += 1
    return removed


def seed_one(payload: dict) -> dict:
    """Run one inspection through the same audit path as POST /inspect."""
    request = InspectRequest.model_validate(payload)
    return _run_inspection_with_audit(request, get_settings())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Seed the demo ledger (green/amber/red, one each)."
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="delete existing inspection-* records in the storage dir first",
    )
    parser.add_argument(
        "--storage-dir",
        default=None,
        help=(
            "target storage dir (default: $%s or ./runs)"
            % LYNCEUS_STORAGE_DIR_ENV
        ),
    )
    args = parser.parse_args(argv)

    # Deterministic offline AI: never probe a live endpoint while seeding.
    pipeline_mod._vlm_reachable = lambda *a, **k: False

    if args.storage_dir:
        # ``_run_inspection_with_audit`` reads the dir through
        # ``get_settings()`` per call — propagate the CLI target via the
        # same environment contract the API itself uses.
        os.environ[LYNCEUS_STORAGE_DIR_ENV] = str(Path(args.storage_dir))

    settings = get_settings()
    storage_dir = Path(args.storage_dir or settings.storage_dir)
    storage_dir.mkdir(parents=True, exist_ok=True)

    if args.reset:
        removed = reset_storage(storage_dir)
        print(f"reset: removed {removed} old inspection record(s) in {storage_dir}")

    print(f"seeding 3 demo record(s) into {storage_dir}")
    for payload in SEED_RECORDS:
        response = seed_one(payload)
        record_id = response.get("record_id")
        decision = (response.get("verdict") or {}).get("decision")
        expected = EXPECTED_VERDICTS[payload["demo_case"]]
        print(
            f"  {record_id}  {payload['truck_id']:<10} "
            f"{payload['demo_case']:<6} → {decision}"
        )
        if decision != expected:
            print(
                f"ERROR: expected verdict '{expected}' for demo_case "
                f"'{payload['demo_case']}', got '{decision}'",
                file=sys.stderr,
            )
            return 1
        audit.load_record(storage_dir / record_id / audit.RECORD_FILENAME)

    print("done: ledger seeded with one green, one amber, one red record")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
