"""Task 2c: score the fine-tuned detector on the 80 held-out benchmark images.

    ml/.venv/Scripts/python ml/eval_finetuned.py [--weights ml/runs/yolo26s_realwaste/weights/best.pt]

Views:
  * metal rule: metal-flag if any `metal` box has conf >= t (same rule as zero-shot);
  * escalate rule: any `glass`/`organic` box with conf >= t;
  * top-1 confusion: category -> class of the highest-confidence box (or `none`);
  * gate view: reject if metal, else escalate if glass/organic, else accept,
    compared with the manifest's expected verdict.
Writes ml/results/finetuned_<name>.json (per-image boxes) and finetuned_summary_<name>.json.
"""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter, defaultdict
from pathlib import Path

import _env
import common

THRESHOLDS = [0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.4, 0.5]


def verdict(boxes: list[dict], t: float) -> str:
    labels = {b["label"] for b in boxes if b["conf"] >= t}
    if "metal" in labels:
        return "reject"
    if labels & common.ESCALATE:
        return "escalate"
    return "accept"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", default=str(_env.RUNS / "yolo26s_realwaste" / "weights" / "best.pt"))
    ap.add_argument("--tag", default=None)
    ap.add_argument("--nms-free", action="store_true", help="use the YOLO26 one-to-one head (no NMS), as exported")
    a = ap.parse_args()
    weights = Path(a.weights).resolve()
    tag = (a.tag or weights.parent.parent.name) + ("_nmsfree" if a.nms_free else "")

    _env.yolo_setup()
    from ultralytics import YOLO

    model = YOLO(str(weights))
    rows = common.manifest()
    dets, times = [], []
    for row in rows:
        t0 = time.perf_counter()
        res = model.predict(str(common.BENCH_IMAGES / row["image"]), conf=0.05, imgsz=640, verbose=False,
                            nms=False if a.nms_free else None)[0]
        times.append(time.perf_counter() - t0)
        boxes = [
            {"label": res.names[int(c)], "conf": round(p, 4), "box": [round(v, 4) for v in xy]}
            for xy, p, c in zip(res.boxes.xyxyn.tolist(), res.boxes.conf.tolist(), res.boxes.cls.tolist())
        ]
        boxes.sort(key=lambda b: -b["conf"])
        dets.append({"image": row["image"], "category": row["category"], "expected": row["expected"], "boxes": boxes})
    (_env.RESULTS / f"finetuned_{tag}.json").write_text(json.dumps(dets, indent=1), encoding="utf-8")

    sweep = {}
    for t in THRESHOLDS:
        flags = [{"category": d["category"],
                  "metal_flag": any(b["label"] == "metal" and b["conf"] >= t for b in d["boxes"]),
                  "esc_flag": any(b["label"] in common.ESCALATE and b["conf"] >= t for b in d["boxes"])}
                 for d in dets]
        rep = common.metal_report(flags)
        rep["escalate_flags_by_category"] = common.metal_report(flags, "esc_flag")["flags_by_category"]
        gate = Counter((d["expected"], verdict(d["boxes"], t)) for d in dets)
        rep["gate_correct"] = f"{sum(v for (e, p), v in gate.items() if e == p)}/{len(dets)}"
        rep["gate_expected_vs_predicted"] = {f"{e}->{p}": v for (e, p), v in sorted(gate.items())}
        sweep[str(t)] = rep

    confusion: dict[str, Counter] = defaultdict(Counter)
    for d in dets:
        confusion[d["category"]][d["boxes"][0]["label"] if d["boxes"] else "none"] += 1
    times.sort()
    summary = {
        "weights": str(weights.relative_to(_env.REPO)) if weights.is_relative_to(_env.REPO) else str(weights),
        "gpu_latency_ms_p50": round(1000 * times[len(times) // 2], 1),
        "top1_confusion": {k: dict(v) for k, v in confusion.items()},
        "sweep": sweep,
    }
    (_env.RESULTS / f"finetuned_summary_{tag}.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(f"== {tag}  p50 {summary['gpu_latency_ms_p50']} ms (GPU, incl. pre/post)")
    for t, rep in sweep.items():
        print(f"t={t:<5} metal {rep['metal_recall']:>6} false {rep['false_flags']:>6} prec {rep['metal_precision_pct']:>5}% "
              f"gate {rep['gate_correct']}  metal-by-cat {rep['flags_by_category']}")
        print(f"        escalate-by-cat {rep['escalate_flags_by_category']}")
    print("top-1 confusion:")
    for k, v in summary["top1_confusion"].items():
        print(f"  {k:<14} {dict(v)}")


if __name__ == "__main__":
    main()
