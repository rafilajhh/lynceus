"""Seed the demo ledger: three demo cases, or a 36-truck sample shift.

Design review finding 2: the default storage dir filled up with dozens of
smoke-test records — the same truck rejected 9× whose "prevented" losses
were summed into an inflated aggregate.  This script replaces that noise
with a clean, honest demo history: exactly three records, one per demo
case, each with a distinct truck and figure.

Usage (from ``backend/``)::

    python scripts/seed_demo.py            # add 3 records (append-only)
    python scripts/seed_demo.py --reset    # wipe old inspection-* records first
    python scripts/seed_demo.py --reset --shift   # 36-truck sample shift instead

``--shift`` writes a scripted 8-hour shift: 36 trucks from five suppliers
with distinct profiles (clean, wet-prone, metal offender, one short-weight
ticket, new), each with waybill fields shaped like ``POST /waybill/read``, a
simulated weighbridge ticket and the AI-generated demo photos as evidence
bytes, all with photo provenance ``"sample"`` so the shift report labels it
"Sample shift - scripted data".  The ops loop is seeded too: supervisor
resolutions on most holds (two overriding the AI), lab results on the trucks
risk-based sampling picks, and template supplier notices on rejects.
Arrival times and gate durations are scripted: a scripted clock replaces the
wall clock while seeding, and the shift ends at the current time.

The AI layer is pinned to the offline stub (no network, deterministic), so
the seeded verdicts are always ACCEPT / ESCALATE_HUMAN / REJECT.  The
storage dir follows the same environment contract as the API
(``LYNCEUS_STORAGE_DIR``, default ``./runs``); the reset only ever deletes
``inspection-*`` directories — any other structure in the storage dir is
left untouched.
"""

from __future__ import annotations

import argparse
import base64
import os
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Make ``import lynceus`` work when run as ``python scripts/seed_demo.py``.
_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from lynceus import audit, followups, impact, suppliers, waybill, weighbridge  # noqa: E402
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


# ---------------------------------------------------------------------------
# Sample shift (--shift)
# ---------------------------------------------------------------------------

SHIFT_HOURS = 8
#: Plant receiving the fuel (the sample waybill's destination).
_DESTINATION = "PLTSa Rorotan, Jakarta Utara"
_REMARKS = "Muatan RDF fluff dari hasil proses pemilahan sampah."
_DEMO_DIR = Path(__file__).resolve().parents[2] / "web" / "public" / "demo"
#: AI-generated demo photos per stub story (web/public/demo/README.md).
_PHOTOS = {
    "green": ("t-clean-1.jpg", "t-clean-2.jpg"),
    "amber": ("t-ambiguous-1.jpg", "t-ambiguous-2.jpg"),
    "red": ("t-metal-1.jpg", "t-metal-2.jpg"),
}
#: Scripted gate time per truck in seconds, cycled: inside the live range of
#: three concurrent vision reads (12-38 s, docs/research/token-factory-probe.md).
_SHIFT_DURATIONS_S = (14, 17, 13, 21, 16, 24, 15, 19, 13, 27, 18, 15)
_ACTORS = {"resolution": "sample-supervisor", "lab_result": "sample-lab",
           "notice": "sample-procurement"}
_LAB_NAME = "Site laboratory (sample)"

CLEAN, WET, METAL, SHORT, NEW = (
    "CV Sumber Bersih",
    "PT Daur Ulang Jaya",
    "PT. Hijau Lestari Transport",
    "UD Sinar Abadi",
    "CV Berkah Energi Baru",
)

#: Five suppliers with distinct profiles.  ``moisture`` is what their
#: waybills declare; ``labs`` is the cycle of lab results (moisture %, NCV
#: MJ/kg as received, chlorine % dry, ash %) their sampled loads get, set
#: against the example contract (moisture <= 20 %, NCV >= 12.6, Cl <= 1.0 %):
#: SBI Cilacap receives 22.6-24.2 % moisture and 12-17 % ash in practice.
SUPPLIERS = {
    CLEAN: {  # clean, low risk
        "origin": "TPS 3R Ciracas, Jakarta Timur", "shipper": "TPS 3R Ciracas",
        "plates": ("B 9412 SBR", "B 9415 SBR", "B 9031 UJK"),
        "drivers": ("Agus Santoso", "Dedi Kurniawan", "Hendra Wijaya"),
        "moisture": 17, "net": 14_200,
        "labs": ((14.6, 15.4, 0.42, 12.4), (18.6, 14.3, 0.47, 13.1)),
    },
    WET: {  # wet-prone: moisture breaches at the lab
        "origin": "TPST Burangkeng, Bekasi", "shipper": "TPST Burangkeng",
        "plates": ("B 9264 DUJ", "B 9270 DUJ", "B 9388 FRT"),
        "drivers": ("Rudi Hartono", "Joko Susilo", "Bambang Purnomo"),
        "moisture": 19, "net": 13_600,
        "labs": ((24.5, 12.1, 0.55, 16.2), (22.6, 12.9, 0.61, 15.4),
                 (26.0, 11.8, 0.5, 16.9), (19.5, 13.2, 0.58, 14.8)),
    },
    METAL: {  # metal offender: declaration conflicts, notices, breach fees
        "origin": "TPST Bantargebang, Bekasi", "shipper": "TPST Bantargebang",
        "plates": ("B 9730 KXW", "B 9651 HLT", "B 9744 KXW"),
        "drivers": ("Slamet Riyadi", "Wahyu Nugroho", "Eko Prasetyo"),
        "moisture": 18, "net": 16_100,
        "labs": ((18.5, 13.4, 0.86, 14.1), (19.0, 13.1, 0.74, 14.6)),
    },
    SHORT: {  # one short-weight ticket (B 9118 TRQ, scale +7.2 %)
        "origin": "MRF Cakung, Jakarta Timur", "shipper": "MRF Cakung",
        "plates": ("B 9124 TRQ", "B 9001 RDF", "B 9133 TRQ"),
        "drivers": ("Supriyadi", "Andi Saputra", "Yusuf Hidayat"),
        "moisture": 20, "net": 15_000,
        "labs": ((19.6, 13.8, 0.62, 13.5), (19.2, 13.5, 0.66, 13.9)),
    },
    NEW: {  # new supplier
        "origin": "TPS 3R Kalibata, Jakarta Selatan", "shipper": "TPS 3R Kalibata",
        "plates": ("B 9907 BEB",),
        "drivers": ("Rahmat Hidayat",),
        "moisture": 16, "net": 12_800,
        "labs": ((16.5, 15.2, 0.35, 12.0),),
    },
}


def _t(case, supplier, *, plate=None, expect=None, resolve=None, notice=False,
       angle=False, waybill_photo=False):
    """One scripted truck.  ``resolve`` = (decision, note, hand-check minutes)."""
    return {"case": case, "supplier": supplier, "plate": plate, "expect": expect,
            "resolve": resolve, "notice": notice, "angle": angle,
            "waybill_photo": waybill_photo}


#: The 36 trucks in arrival order.  Verdicts come from the real pipeline with
#: the offline stub AI (green clean, amber wet, red metal): 27 accept,
#: 6 hold, 3 reject.  Resolutions close all but the last hold; two of them
#: override the AI (a sorted-out metal tray, a tyre found on a spot check).
SHIFT_PLAN = [
    _t("green", CLEAN),
    _t("green", SHORT),
    _t("green", WET),
    _t("red", METAL, notice=True, angle=True,
       resolve=("reject", "Confirmed: metal trays on top of the load. Refused, not tipped.", 4)),
    _t("green", CLEAN),
    _t("amber", WET, angle=True,
       resolve=("sort_then_accept", "Grab sample taken; wet fraction sent to the drying bay.", 6)),
    _t("green", METAL),
    _t("green", SHORT),
    _t("green", CLEAN, resolve=("accept", "Spot check from the platform: clean, as the AI said.", 3)),
    _t("green", WET),
    _t("green", SHORT, plate="B 9118 TRQ", expect="escalate_human",
       resolve=("accept", "Re-weighed on the second bridge; waybill net corrected to the scale ticket.", 5)),
    _t("green", METAL),
    _t("amber", WET,
       resolve=("reject", "Free liquid draining from the bed; refused for kiln feed.", 8)),
    _t("green", CLEAN),
    _t("red", METAL, plate="B 9723 KXW", notice=True, angle=True, waybill_photo=True,
       resolve=("reject", "Metal confirmed from the platform. Refused; supplier to collect.", 4)),
    _t("green", SHORT),
    _t("green", NEW),
    _t("green", CLEAN),
    _t("green", WET),
    _t("amber", SHORT,
       resolve=("sort_then_accept", "Wet layer at the tailgate; tipped to the pre-sort line.", 5)),
    _t("green", METAL,
       resolve=("sort_then_accept", "Spot check found a tyre under the top layer; pulled at the sorting bay.", 7)),
    _t("green", CLEAN),
    _t("green", SHORT),
    _t("amber", WET, resolve=("accept", "Grab sample looked within spec; accepted.", 4)),
    _t("green", METAL),
    _t("green", CLEAN),
    _t("red", METAL, notice=True,
       resolve=("sort_then_accept", "Single aluminium tray on top; removed at the sorting bay, rest accepted.", 6)),
    _t("green", SHORT),
    _t("green", WET),
    _t("green", NEW),
    _t("green", CLEAN),
    _t("green", SHORT),
    _t("amber", WET, angle=True),  # still open: the supervisor has not decided yet
    _t("green", CLEAN),
    _t("green", SHORT),
    _t("green", METAL),
]


class ScriptedClock:
    """Stands in for ``audit.now_utc`` while the sample shift is seeded."""

    def __init__(self, start: datetime) -> None:
        self.current = start

    def __call__(self) -> str:
        return self.current.strftime("%Y-%m-%dT%H:%M:%SZ")


def _b64(name: str) -> str:
    return base64.b64encode((_DEMO_DIR / name).read_bytes()).decode("ascii")


def shift_payloads(day: datetime | None = None) -> list[dict]:
    """The scripted ``/inspect`` payloads, in arrival order.

    Waybill fields are plain values shaped like ``POST /waybill/read``; the
    weight is the simulated weighbridge ticket for the declared net
    (``weighbridge.reading``), so ``B 9118 TRQ`` weighs 7.2 % over its
    waybill and every other plate within 1.5 %.
    """
    day = day or datetime.now(timezone.utc)
    date = day.strftime("%Y-%m-%d")
    seen: dict[str, int] = {}
    payloads = []
    for i, truck in enumerate(SHIFT_PLAN):
        profile = SUPPLIERS[truck["supplier"]]
        k = seen.get(truck["supplier"], 0)
        seen[truck["supplier"]] = k + 1
        plate = truck["plate"] or profile["plates"][k % len(profile["plates"])]
        if truck["waybill_photo"]:
            fields = waybill.values_of(waybill.SAMPLE_FIELDS)
            read = {"confidence": waybill.overall_confidence(waybill.SAMPLE_FIELDS),
                    "model": waybill.STUB_MODEL}
        else:
            net = profile["net"] + (i * 379) % 2_400
            tare = 14_000 + (sum(map(ord, plate)) * 37) % 3_000
            fields = {
                "document_no": f"{8100 + i:06d}",
                "plate": plate,
                "date": date,
                "origin": profile["origin"],
                "destination": _DESTINATION,
                "carrier": truck["supplier"],
                "shipper": profile["shipper"],
                "driver": profile["drivers"][k % len(profile["drivers"])],
                "reference_no": f"DO-{day.strftime('%y%m%d')}-{201 + i:04d}",
                "gross_kg": tare + net,
                "tare_kg": tare,
                "net_kg": net,
                "load_type": "RDF fluff",
                "moisture_pct": profile["moisture"],
                "remarks": _REMARKS,
            }
            read = {"confidence": round(0.86 + (i % 5) * 0.02, 2), "model": "scripted-sample"}
        ticket = weighbridge.reading(plate, fields["net_kg"])
        photos = _PHOTOS[truck["case"]]
        main, other = (photos[0], photos[1]) if i % 2 == 0 else (photos[1], photos[0])
        payload = {
            "demo_case": truck["case"],
            "truck_id": plate,
            "supplier": truck["supplier"],
            "photo_base64": _b64(main),
            "photo_filename": main,
            "waybill_fields": fields,
            "waybill_read": {**read, "provenance": "sample", "latency_ms": None,
                             "edited_fields": []},
            "weight_kg": ticket["net_kg"],
            "weight_source": weighbridge.WEIGHT_SOURCE,
            "declared_weight_kg": fields["net_kg"],
        }
        if truck["angle"]:
            payload["extra_photos_base64"] = [_b64(other)]
            payload["extra_photo_filenames"] = [other]
        if truck["waybill_photo"]:
            payload["waybill_image_base64"] = _b64("waybill-1.jpg")
            payload["waybill_photo_filename"] = "waybill-1.jpg"
        payloads.append(payload)
    return payloads


def _expected(truck: dict) -> str:
    return truck["expect"] or EXPECTED_VERDICTS[truck["case"]]


def seed_shift(storage_dir: Path, end: datetime | None = None) -> int:
    """Write the sample shift and its follow-ups; 0, or 1 when a verdict is off-script.

    Each truck arrives on a scripted clock spread over the last
    ``SHIFT_HOURS`` hours and goes through the real ``/inspect`` path
    (``_run_inspection_with_audit``); the clock advances by the truck's
    scripted gate time while the (offline stub) pipeline runs.  Then, as the
    gate would: the supervisor's resolution, a lab result when the supplier's
    risk-based sampling picks this truck and the load was tipped, and a
    template supplier notice on scripted rejects.  Follow-ups are sealed
    through :mod:`lynceus.followups` (never the network).
    """
    end = end or datetime.now(timezone.utc).replace(microsecond=0)
    # The first truck 15 min into the shift, so the whole plan stays inside an
    # 8 h window ending at "now" for a while after seeding (the dashboard's
    # shift window), and the last truck still arrives before ``end``.
    start = end - timedelta(hours=SHIFT_HOURS) + timedelta(minutes=15)
    step = (timedelta(hours=SHIFT_HOURS) - timedelta(minutes=30)) / len(SHIFT_PLAN)
    clock = ScriptedClock(start)
    gate_seconds = {"value": 0}
    real_now, real_run = audit.now_utc, pipeline_mod.run_inspection
    lab_cycle = {name: 0 for name in SUPPLIERS}
    counts = {"resolution": 0, "lab_result": 0, "notice": 0}

    def timed_run(*args, **kwargs):
        result = real_run(*args, **kwargs)
        clock.current += timedelta(seconds=gate_seconds["value"])
        return result

    audit.now_utc = clock
    pipeline_mod.run_inspection = timed_run
    try:
        print(f"seeding sample shift ({len(SHIFT_PLAN)} trucks) into {storage_dir}")
        for i, (truck, payload) in enumerate(zip(SHIFT_PLAN, shift_payloads(end))):
            arrival = start + step * i + timedelta(minutes=(i * 7) % 11)
            clock.current = arrival
            gate_seconds["value"] = _SHIFT_DURATIONS_S[i % len(_SHIFT_DURATIONS_S)]
            sampling = suppliers.sampling_for(
                storage_dir, truck["supplier"], payload["waybill_fields"]
            )
            request = InspectRequest.model_validate(payload)
            response = _run_inspection_with_audit(
                request, get_settings(), photo_provenance="sample"
            )
            record_id = response.get("record_id")
            decision = (response.get("verdict") or {}).get("decision")
            print(
                f"  {record_id}  {payload['truck_id']:<11} "
                f"{truck['supplier']:<28} -> {decision}"
            )
            if decision != _expected(truck):
                print(
                    f"ERROR: expected verdict '{_expected(truck)}' for "
                    f"{payload['truck_id']} ('{truck['case']}'), got '{decision}'",
                    file=sys.stderr,
                )
                return 1
            audit.load_record(storage_dir / record_id / audit.RECORD_FILENAME)

            tipped = decision == "accept"
            if truck["resolve"]:
                verdict, note, minutes = truck["resolve"]
                clock.current = arrival + timedelta(minutes=3 + i % 5)
                followups.append_resolution(
                    storage_dir, record_id, verdict, note=note,
                    hand_check_minutes=minutes, actor=_ACTORS["resolution"],
                )
                counts["resolution"] += 1
                tipped = verdict in ("accept", "sort_then_accept")
            if sampling["sample_this_truck"] and tipped:
                labs = SUPPLIERS[truck["supplier"]]["labs"]
                moisture, ncv, chlorine, ash = labs[lab_cycle[truck["supplier"]] % len(labs)]
                lab_cycle[truck["supplier"]] += 1
                clock.current = arrival + timedelta(minutes=45)
                followups.append_lab(
                    storage_dir, record_id, moisture_pct=moisture, ncv_mj_kg=ncv,
                    chlorine_pct=chlorine, ash_pct=ash, lab=_LAB_NAME,
                    actor=_ACTORS["lab_result"],
                )
                counts["lab_result"] += 1
            if truck["notice"]:
                clock.current = arrival + timedelta(minutes=12)
                followups.append_notice(
                    storage_dir, record_id, actor=_ACTORS["notice"], client=None
                )
                counts["notice"] += 1
    finally:
        audit.now_utc, pipeline_mod.run_inspection = real_now, real_run
    print(
        f"done: sample shift seeded (photo provenance 'sample'): "
        f"{counts['resolution']} resolutions, {counts['lab_result']} lab results, "
        f"{counts['notice']} notices"
    )
    return 0


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
        "--shift",
        action="store_true",
        help="seed the 36-truck sample shift (with follow-ups) instead of the three demo cases",
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

    if args.shift:
        return seed_shift(storage_dir)

    print(f"seeding 3 demo record(s) into {storage_dir}")
    for payload in SEED_RECORDS:
        response = seed_one(payload)
        record_id = response.get("record_id")
        decision = (response.get("verdict") or {}).get("decision")
        expected = EXPECTED_VERDICTS[payload["demo_case"]]
        print(
            f"  {record_id}  {payload['truck_id']:<10} "
            f"{payload['demo_case']:<6} -> {decision}"
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
