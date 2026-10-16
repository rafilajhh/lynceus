"""Task 3d: the production decoder (lynceus.detector, ONNX) on the TACO test split and the 80 benchmark images.

    backend/.venv/Scripts/python ml/eval_decoder.py [--onnx backend/models/X.onnx --hard 0.35 --light 0.05]
        [--ultralytics ml/results/finetuned_<tag>_nmsfree.json]

eval_val.py scores the Ultralytics .pt; this scores what the backend actually runs: the
bundled ONNX through lynceus.detector (Pillow decode, letterbox, onnxruntime, box decode).
Defaults: the backend's own settings (DETECTOR_MODEL_PATH, DETECTOR_HARD_CONF,
DETECTOR_LIGHT_CONF). Needs only the backend venv (onnxruntime, numpy, Pillow) and the
TACO test split from fetch_taco.py. --ultralytics also checks, per benchmark image, that the
decoder's detector verdict matches the Ultralytics detections.
Writes ml/results/decoder_<model>.json.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ML = Path(__file__).resolve().parent
REPO = ML.parent
sys.path.insert(0, str(REPO / "backend" / "src"))

METAL, LIGHT = {"metal"}, {"glass", "organic"}


def _top(boxes: list[dict], labels: set, key: str) -> float:
    return max((b[key] for b in boxes if b["label"] in labels), default=0.0)


def _verdict(boxes: list[dict], key: str, hard: float, light: float) -> str:
    if _top(boxes, METAL, key) >= hard:
        return "reject"
    return "escalate" if _top(boxes, LIGHT, key) >= light else "accept"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--onnx", default=None, help="default: the backend's DETECTOR_MODEL_PATH / bundled model")
    ap.add_argument("--hard", type=float, default=None)
    ap.add_argument("--light", type=float, default=None)
    ap.add_argument("--ultralytics", default=None, help="ml/results/finetuned_*_nmsfree.json to compare with")
    a = ap.parse_args()
    for flag, env in ((a.onnx, "DETECTOR_MODEL_PATH"), (a.hard, "DETECTOR_HARD_CONF"), (a.light, "DETECTOR_LIGHT_CONF")):
        if flag is not None:
            os.environ[env] = str(Path(flag).resolve()) if env == "DETECTOR_MODEL_PATH" else str(flag)

    from lynceus import detector
    from lynceus.config import get_settings

    s = get_settings()
    if not detector.enabled(s):
        raise SystemExit("detector disabled: no model, or onnxruntime/numpy/Pillow missing")
    hard, light = s.detector_hard_conf, s.detector_light_conf
    taco = ML / "data" / "taco"
    rows = []
    for img in sorted((taco / "images" / "test").glob("*.jpg")):
        label = taco / "labels" / "test" / f"{img.stem}.txt"
        ids = {int(l.split()[0]) for l in label.read_text().splitlines() if l.strip()} if label.is_file() else set()
        boxes = detector.detect(img.read_bytes(), s, min_conf=0.05)["boxes"]
        rows.append({"metal": 0 in ids, "light": bool(ids & {1, 2}),
                     "top_metal": _top(boxes, METAL, "confidence"), "top_light": _top(boxes, LIGHT, "confidence")})
    if not rows:
        raise SystemExit(f"no TACO test images under {taco} (run ml/fetch_taco.py --splits test)")

    def count(xs: list[dict], key: str, t: float) -> str:
        return f"{sum(x[key] >= t for x in xs)}/{len(xs)}"

    metal = [r for r in rows if r["metal"]]
    other = [r for r in rows if not r["metal"]]
    clean = [r for r in rows if not r["metal"] and not r["light"]]
    out = {
        "onnx": Path(s.detector_model_path).name,
        "model_sha256": detector.detect((REPO / "backend" / "benchmark" / "images" / "metal_1.jpg").read_bytes(),
                                        s)["model_sha256"],
        "thresholds": {"hard": hard, "light": light},
        "taco_test": {"images": len(rows),
                      "metal_recall": count(metal, "top_metal", hard),
                      "false_metal": count(other, "top_metal", hard),
                      "light_recall": count([r for r in rows if r["light"]], "top_light", light),
                      "false_escalate_clean": count(clean, "top_light", light)},
    }
    if a.ultralytics:
        ultra = {d["image"]: d["boxes"] for d in json.loads(Path(a.ultralytics).read_text(encoding="utf-8"))}
        same = 0
        for name, ub in ultra.items():
            ob = detector.detect((REPO / "backend" / "benchmark" / "images" / name).read_bytes(), s, min_conf=0.05)
            same += _verdict(ub, "conf", hard, light) == _verdict(ob["boxes"], "confidence", hard, light)
        out["benchmark_verdict_vs_ultralytics"] = f"{same}/{len(ultra)}"
    dest = ML / "results" / f"decoder_{Path(s.detector_model_path).stem}.json"
    dest.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
