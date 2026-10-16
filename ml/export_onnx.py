"""Task 3a: export a detector to ONNX (imgsz 640, default opset) into ml/weights/.

    ml/.venv/Scripts/python ml/export_onnx.py --weights ml/runs/yolo26s_realwaste/weights/best.pt --out yolo26s_realwaste.onnx
    ml/.venv/Scripts/python ml/export_onnx.py --weights yoloe-26s-seg.pt --yoloe --out yoloe26s_contaminants.onnx

--yoloe bakes the zero-shot contaminant prompts (eval_zeroshot.METAL + OTHER_HARD)
into the graph, so the ONNX file needs no text encoder at runtime.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

import _env


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--yoloe", action="store_true")
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--with-nms-head", dest="nms_free", action="store_false",
                    help="export the raw one-to-many head instead of the NMS-free one")
    a = ap.parse_args()

    weights = Path(a.weights)
    if not weights.is_absolute():
        weights = (_env.REPO / weights) if (_env.REPO / weights).exists() else (_env.WEIGHTS / weights)
    _env.yolo_setup()
    if a.yoloe:
        from eval_zeroshot import METAL, OTHER_HARD
        from ultralytics import YOLOE

        model = YOLOE(str(weights))
        prompts = METAL + OTHER_HARD
        model.set_classes(prompts, model.get_text_pe(prompts))
    else:
        from ultralytics import YOLO

        model = YOLO(str(weights))
    # nms=False selects the NMS-free one-to-one head (output (1, 300, 6)); Ultralytics'
    # default (None) exports the raw one-to-many head that needs external NMS.
    exported = Path(model.export(format="onnx", imgsz=a.imgsz, simplify=True, nms=False if a.nms_free else None))
    dest = _env.WEIGHTS / a.out
    if exported.resolve() != dest.resolve():
        shutil.copyfile(exported, dest)
    print(f"{dest} {dest.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
