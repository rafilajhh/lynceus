"""Task 3b: CPU latency of the ONNX detector + parity of ml/onnx_infer.py with Ultralytics.

    ml/.venv/Scripts/python ml/bench_onnx.py --onnx yolo26s_realwaste.onnx --pt ml/runs/yolo26s_realwaste/weights/best.pt

* Latency: onnxruntime CPUExecutionProvider, per image over the 80 benchmark
  images, timed from file open through letterbox, inference and decode (one
  warm-up run first). Reports p50/p90 and mean.
* Parity: on 5 images, every Ultralytics box (conf >= 0.25) must have an ONNX
  box with the same label and IoU >= 0.9 (and vice versa); conf deltas reported.
* Metal rule on the ONNX outputs (t = --metal-t) to confirm the decoder scores
  the same as the .pt model.
Writes ml/results/onnx_bench_<stem>.json.
"""

from __future__ import annotations

import argparse
import json
import platform
import time
from pathlib import Path

import _env
import common
from onnx_infer import Detector


def iou(a, b) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--onnx", required=True)
    ap.add_argument("--pt", required=True)
    ap.add_argument("--yoloe", action="store_true")
    ap.add_argument("--metal-labels", default="metal")
    ap.add_argument("--metal-t", type=float, default=0.25)
    ap.add_argument("--threads", type=int, default=0)
    a = ap.parse_args()

    onnx_path = Path(a.onnx) if Path(a.onnx).is_absolute() else _env.WEIGHTS / a.onnx
    pt = Path(a.pt)
    if not pt.is_absolute():
        pt = (_env.REPO / pt) if (_env.REPO / pt).exists() else (_env.WEIGHTS / pt)
    rows = common.manifest()
    det = Detector(str(onnx_path), threads=a.threads)
    paths = [str(common.BENCH_IMAGES / r["image"]) for r in rows]

    det(paths[0])  # warm-up
    times, outputs = [], []
    for p in paths:
        t0 = time.perf_counter()
        outputs.append(det(p, conf=0.05))
        times.append(time.perf_counter() - t0)
    s = sorted(times)
    latency = {"p50_ms": round(1000 * s[len(s) // 2], 1), "p90_ms": round(1000 * s[int(len(s) * 0.9)], 1),
               "mean_ms": round(1000 * sum(s) / len(s), 1)}

    metal = set(a.metal_labels.split(","))
    flags = [{"category": r["category"],
              "metal_flag": any(d.label in metal and d.conf >= a.metal_t for d in out)}
             for r, out in zip(rows, outputs)]
    onnx_metal = common.metal_report(flags)

    _env.yolo_setup()
    if a.yoloe:
        from eval_zeroshot import METAL, OTHER_HARD
        from ultralytics import YOLOE

        model = YOLOE(str(pt))
        prompts = METAL + OTHER_HARD
        model.set_classes(prompts, model.get_text_pe(prompts))
    else:
        from ultralytics import YOLO

        model = YOLO(str(pt))
    parity = []
    for p in paths[:5]:
        res = model.predict(p, conf=0.25, imgsz=640, verbose=False, device="cpu",
                            nms=False if det.end2end else None)[0]
        ref = [(res.names[int(c)], float(cf), xy) for xy, cf, c in
               zip(res.boxes.xyxyn.tolist(), res.boxes.conf.tolist(), res.boxes.cls.tolist())]
        mine = [(d.label, d.conf, d.box) for d in det(p, conf=0.25)]
        matched, deltas = 0, []
        for lab, cf, box in ref:
            best = max((iou(box, b) for l2, _, b in mine if l2 == lab), default=0.0)
            if best >= 0.9:
                matched += 1
                deltas.append(min(abs(cf - c2) for l2, c2, b in mine if l2 == lab and iou(box, b) >= 0.9))
        parity.append({"image": Path(p).name, "ultralytics_boxes": len(ref), "onnx_boxes": len(mine),
                       "matched_iou>=0.9": matched,
                       "max_conf_delta": round(max(deltas), 4) if deltas else None,
                       "ultralytics_top": [(l, round(c, 3)) for l, c, _ in ref[:3]],
                       "onnx_top": [(l, round(c, 3)) for l, c, _ in mine[:3]]})

    result = {"onnx": onnx_path.name, "size_mb": round(onnx_path.stat().st_size / 1e6, 1),
              "provider": "CPUExecutionProvider", "cpu": platform.processor(),
              "intra_op_threads": a.threads or "ort default",
              "latency_incl_preprocess": latency, "metal_rule_t": a.metal_t,
              "onnx_metal_report": onnx_metal, "parity_vs_ultralytics": parity}
    (_env.RESULTS / f"onnx_bench_{onnx_path.stem}.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(json.dumps(result, indent=1))


if __name__ == "__main__":
    main()
