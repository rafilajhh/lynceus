"""Task 1: zero-shot YOLOE-26 (text prompts, no training) on the 80 benchmark images.

    ml/.venv/Scripts/python ml/eval_zeroshot.py [--model yoloe-26s-seg.pt]

Two prompt sets are scored:
  * ``contaminants``: the hard-contaminant prompts only (metal + tyre/battery/rock);
  * ``contaminants+distractors``: the same plus prompts for the accepted/escalated
    materials, so a box can be claimed by "paper" instead of "metal sheet".
Image-level rule: metal-flag if any metal-ish box has conf >= t.
Writes ml/results/zeroshot_yoloe*.json.
"""

from __future__ import annotations

import argparse
import json
import time

import _env
import common

METAL = ["metal can", "metal scrap", "metal sheet", "metal pipe", "aluminium foil", "gas cylinder"]
OTHER_HARD = ["tyre", "battery", "rock"]
DISTRACTORS = [
    "plastic bottle", "plastic bag", "plastic container", "cardboard box", "paper",
    "glass bottle", "glass jar", "food waste", "leaves", "cloth",
]
PROMPT_SETS = {
    "contaminants": METAL + OTHER_HARD,
    "contaminants+distractors": METAL + OTHER_HARD + DISTRACTORS,
}
THRESHOLDS = [0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.4, 0.5]
MIN_CONF = 0.05


def run(model_name: str) -> None:
    _env.yolo_setup()
    from ultralytics import YOLOE

    rows = common.manifest()
    summary = {"model": model_name, "rule": "metal_flag = any box with label in METAL and conf >= t", "sets": {}}
    for set_name, prompts in PROMPT_SETS.items():
        model = YOLOE(str(_env.WEIGHTS / model_name))
        model.set_classes(prompts, model.get_text_pe(prompts))
        dets, times = [], []
        for row in rows:
            path = str(common.BENCH_IMAGES / row["image"])
            t0 = time.perf_counter()
            res = model.predict(path, conf=MIN_CONF, imgsz=640, verbose=False)[0]
            times.append(time.perf_counter() - t0)
            boxes = []
            for xyxyn, conf, cls in zip(res.boxes.xyxyn.tolist(), res.boxes.conf.tolist(), res.boxes.cls.tolist()):
                boxes.append({
                    "label": res.names[int(cls)],
                    "conf": round(conf, 4),
                    "box": [round(v, 4) for v in xyxyn],
                })
            boxes.sort(key=lambda b: -b["conf"])
            dets.append({"image": row["image"], "category": row["category"], "boxes": boxes})
        suffix = "" if set_name == "contaminants" else "_distractors"
        if model_name != "yoloe-26s-seg.pt":
            suffix = "_" + model_name.replace(".pt", "").replace("yoloe-", "") + suffix
        out = _env.RESULTS / f"zeroshot_yoloe{suffix}.json"
        out.write_text(json.dumps(dets, indent=1), encoding="utf-8")

        sweep = {}
        for t in THRESHOLDS:
            flagged = [
                {"category": d["category"],
                 "metal_flag": any(b["label"] in METAL and b["conf"] >= t for b in d["boxes"]),
                 "hard_flag": any(b["label"] in METAL + OTHER_HARD and b["conf"] >= t for b in d["boxes"])}
                for d in dets
            ]
            rep = common.metal_report(flagged)
            rep["any_hard_contaminant"] = common.metal_report(flagged, "hard_flag")["flags_by_category"]
            sweep[str(t)] = rep
        times.sort()
        summary["sets"][set_name] = {
            "prompts": prompts,
            "detections_file": out.name,
            "gpu_latency_ms_p50": round(1000 * times[len(times) // 2], 1),
            "sweep": sweep,
        }
        print(f"\n== {model_name} / {set_name}  (p50 {summary['sets'][set_name]['gpu_latency_ms_p50']} ms)")
        for t, rep in sweep.items():
            print(f"t={t:<5} recall {rep['metal_recall']:>6}  false {rep['false_flags']:>6}  "
                  f"prec {rep['metal_precision_pct']:>5}%  {rep['flags_by_category']}")
    stem = model_name.replace(".pt", "")
    (_env.RESULTS / f"zeroshot_summary_{stem}.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="yoloe-26s-seg.pt")
    run(ap.parse_args().model)
