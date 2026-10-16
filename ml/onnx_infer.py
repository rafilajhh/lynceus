"""Standalone ONNX reference decoder for the Lynceus detector stage.

Dependencies: onnxruntime, numpy, Pillow (no torch, no ultralytics).

    python ml/onnx_infer.py ml/weights/<model>.onnx image.jpg [more.jpg ...]

Pipeline: RGB -> letterbox to the model's square input (grey 114 padding, as
Ultralytics does) -> float32 NCHW / 255 -> onnxruntime (CPU) -> decode.
Two output layouts are handled:
  * end-to-end / NMS-free (YOLO26 exported with nms=False): (1, K, 6) rows of
    x0,y0,x1,y1,conf,cls in letterboxed pixels (YOLOE-seg exports append 32 mask
    coefficients and a second proto output; both are ignored);
  * classic (YOLO11 style): (1, 4 + nc, N) cx,cy,w,h + class scores -> class-aware NMS.
Boxes are mapped back through the letterbox and returned normalised to 0..1 of
the original image.
"""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass

import numpy as np
import onnxruntime as ort
from PIL import Image


@dataclass
class Detection:
    label: str
    conf: float
    box: tuple[float, float, float, float]  # x0, y0, x1, y1, normalised


class Detector:
    def __init__(self, path: str, threads: int = 0):
        opts = ort.SessionOptions()
        if threads:
            opts.intra_op_num_threads = threads
        self.session = ort.InferenceSession(path, opts, providers=["CPUExecutionProvider"])
        inp = self.session.get_inputs()[0]
        self.input_name = inp.name
        self.size = int(inp.shape[2]) if isinstance(inp.shape[2], int) else 640
        meta = self.session.get_modelmeta().custom_metadata_map
        names = ast.literal_eval(meta["names"]) if "names" in meta else {}
        self.names = {int(k): v for k, v in names.items()}
        shape = self.session.get_outputs()[0].shape
        # (1, K, 6[+32 mask coefs]) has K > columns; the classic layout is (1, 4 + nc, 8400).
        self.end2end = len(shape) == 3 and shape[2] < shape[1]

    def letterbox(self, img: Image.Image) -> tuple[np.ndarray, float, float, float]:
        w, h = img.size
        r = min(self.size / h, self.size / w)
        nw, nh = round(w * r), round(h * r)
        dw, dh = (self.size - nw) / 2, (self.size - nh) / 2
        left, top = round(dw - 0.1), round(dh - 0.1)
        if (nw, nh) != (w, h):
            img = img.resize((nw, nh), Image.BILINEAR)
        canvas = Image.new("RGB", (self.size, self.size), (114, 114, 114))
        canvas.paste(img, (left, top))
        x = np.asarray(canvas, dtype=np.float32).transpose(2, 0, 1)[None] / 255.0
        return np.ascontiguousarray(x), r, left, top

    def __call__(self, image: Image.Image | str, conf: float = 0.25, iou: float = 0.7) -> list[Detection]:
        img = Image.open(image) if isinstance(image, str) else image
        img = img.convert("RGB")
        w, h = img.size
        x, r, left, top = self.letterbox(img)
        out = self.session.run(None, {self.input_name: x})[0][0]
        if self.end2end:
            boxes, scores, classes = out[:, :4], out[:, 4], out[:, 5].astype(int)
            keep = scores >= conf
            boxes, scores, classes = boxes[keep], scores[keep], classes[keep]
        else:  # classic (4 + nc, N)
            pred = out.T
            cls_scores = pred[:, 4:4 + len(self.names)] if self.names else pred[:, 4:]
            classes = cls_scores.argmax(1)
            scores = cls_scores.max(1)
            keep = scores >= conf
            cxcywh, scores, classes = pred[keep, :4], scores[keep], classes[keep]
            boxes = np.concatenate([cxcywh[:, :2] - cxcywh[:, 2:] / 2, cxcywh[:, :2] + cxcywh[:, 2:] / 2], 1)
            idx = _nms(boxes + classes[:, None] * 4096.0, scores, iou)
            boxes, scores, classes = boxes[idx], scores[idx], classes[idx]
        boxes = (boxes - np.array([left, top, left, top], dtype=np.float32)) / r
        boxes = np.clip(boxes / np.array([w, h, w, h], dtype=np.float32), 0.0, 1.0)
        order = np.argsort(-scores)
        return [
            Detection(self.names.get(int(classes[i]), str(int(classes[i]))), float(scores[i]),
                      tuple(float(v) for v in boxes[i]))
            for i in order
        ]


def _nms(boxes: np.ndarray, scores: np.ndarray, iou: float) -> np.ndarray:
    order = np.argsort(-scores)
    keep = []
    area = (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1])
    while order.size:
        i = order[0]
        keep.append(i)
        xx0 = np.maximum(boxes[i, 0], boxes[order[1:], 0])
        yy0 = np.maximum(boxes[i, 1], boxes[order[1:], 1])
        xx1 = np.minimum(boxes[i, 2], boxes[order[1:], 2])
        yy1 = np.minimum(boxes[i, 3], boxes[order[1:], 3])
        inter = np.clip(xx1 - xx0, 0, None) * np.clip(yy1 - yy0, 0, None)
        ratio = inter / (area[i] + area[order[1:]] - inter + 1e-9)
        order = order[1:][ratio <= iou]
    return np.array(keep, dtype=int)


if __name__ == "__main__":
    det = Detector(sys.argv[1])
    for path in sys.argv[2:]:
        print(path)
        for d in det(path):
            print(f"  {d.label:<10} {d.conf:.3f} [{', '.join(f'{v:.3f}' for v in d.box)}]")
