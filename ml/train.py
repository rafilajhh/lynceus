"""Task 2b: fine-tune YOLO26 on the pseudo-labelled RealWaste dataset.

    ml/.venv/Scripts/python ml/train.py [--model yolo26s.pt] [--epochs 40] [--batch 16] [--hours 1.0]
        [--patience 15] [--cos-lr] [--close-mosaic 10] [--cache none|disk|ram] [--name RUN]

Low-RAM laptop defaults: workers=2, no image caching. --hours caps wall time
(Ultralytics `time=`), which overrides --epochs when it is hit first.
"""

from __future__ import annotations

import argparse

import _env


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="yolo26s.pt")
    ap.add_argument("--epochs", type=int, default=40)
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--hours", type=float, default=1.0)
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--device", default="0")
    ap.add_argument("--name", default=None)
    ap.add_argument("--patience", type=int, default=15)
    ap.add_argument("--cos-lr", action="store_true")
    ap.add_argument("--close-mosaic", type=int, default=10)
    ap.add_argument("--cache", choices=["none", "disk", "ram"], default="none",
                    help="disk = decoded .npy next to each image (~1.2 MB each); eases a CPU-bound loader")
    a = ap.parse_args()

    _env.yolo_setup()
    from ultralytics import YOLO

    model = YOLO(str(_env.WEIGHTS / a.model))
    model.train(
        data=str(_env.DATA / "yolo" / "data.yaml"),
        imgsz=a.imgsz,
        epochs=a.epochs,
        time=a.hours if a.hours > 0 else None,
        batch=a.batch,
        workers=a.workers,
        device=a.device,
        cache=False if a.cache == "none" else a.cache,
        patience=a.patience,
        cos_lr=a.cos_lr,
        close_mosaic=a.close_mosaic,
        seed=0,
        project=str(_env.RUNS),
        name=a.name or a.model.replace(".pt", "") + "_realwaste",
        exist_ok=True,
        plots=True,
    )


if __name__ == "__main__":
    main()
