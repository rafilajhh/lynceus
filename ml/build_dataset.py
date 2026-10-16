"""Task 2a: weakly supervised YOLO dataset from RealWaste (benchmark 80 held out).

    ml/.venv/Scripts/python ml/build_dataset.py [--model yoloe-26s-seg.pt] [--with-taco]

RealWaste has image-level labels only. For every non-benchmark image of the 8
used folders, YOLOE-26 (text prompts for all materials) proposes boxes and the
pseudo-box is:
  1. the highest-confidence box whose prompt maps to the folder's class, else
  2. the largest box of any prompt (the salient object), else
  3. the whole frame (2% margin).
The label is always the folder's class. Every 10th image per class (sorted by
name) goes to val. Output: ml/data/yolo/{images,labels}/{train,val}, data.yaml,
and ml/results/pseudo_label_stats.json.
"""

from __future__ import annotations

import argparse
import json
import shutil
import zipfile
from collections import Counter

import _env
import common

PROMPTS = {
    "metal": ["metal can", "metal scrap", "metal sheet", "metal pipe", "aluminium foil", "metal object"],
    "glass": ["glass bottle", "glass jar", "broken glass"],
    "organic": ["food waste", "fruit", "vegetable", "leaves", "plant"],
    "paper": ["paper", "cardboard box", "cardboard", "newspaper"],
    "plastic": ["plastic bottle", "plastic bag", "plastic container", "plastic wrapper"],
    "textile": ["cloth", "clothing", "fabric"],
}
OUT = _env.DATA / "yolo"
BATCH = 16


def main(model_name: str, with_taco: bool = False) -> None:
    _env.yolo_setup()
    from ultralytics import YOLOE

    flat = [p for c in common.CLASSES for p in PROMPTS[c]]
    prompt_class = {p: c for c in common.CLASSES for p in PROMPTS[c]}
    model = YOLOE(str(_env.WEIGHTS / model_name))
    model.set_classes(flat, model.get_text_pe(flat))

    if OUT.exists():
        shutil.rmtree(OUT)
    for split in ("train", "val"):
        (OUT / "images" / split).mkdir(parents=True)
        (OUT / "labels" / split).mkdir(parents=True)

    zf = zipfile.ZipFile(common.ZIP)
    members = common.training_members(zf)
    by_cls: dict[str, list[str]] = {}
    for name, folder in members:
        by_cls.setdefault(common.CLASS_OF[folder], []).append(name)
    split_of = {}
    for cls, names in by_cls.items():
        for i, n in enumerate(sorted(names)):
            split_of[n] = "val" if i % 10 == 9 else "train"

    source = Counter()
    per_split = Counter()
    for start in range(0, len(members), BATCH):
        chunk = members[start:start + BATCH]
        imgs = [common.load_zip_image(zf, n) for n, _ in chunk]
        results = model.predict(imgs, conf=0.1, imgsz=640, verbose=False)
        for (name, folder), res in zip(chunk, results):
            cls = common.CLASS_OF[folder]
            boxes = list(zip(res.boxes.xyxyn.tolist(), res.boxes.conf.tolist(), res.boxes.cls.tolist()))
            own = [b for b in boxes if prompt_class[res.names[int(b[2])]] == cls]
            if own:
                box, how = max(own, key=lambda b: b[1])[0], "own_class"
            elif boxes:
                box, how = max(boxes, key=lambda b: (b[0][2] - b[0][0]) * (b[0][3] - b[0][1]))[0], "largest"
            else:
                box, how = [0.02, 0.02, 0.98, 0.98], "full_frame"
            source[f"{cls}:{how}"] += 1
            source[how] += 1
            x0, y0, x1, y1 = box
            split = split_of[name]
            per_split[f"{split}:{cls}"] += 1
            stem = f"{folder.replace(' ', '_').lower()}_{name.rsplit('/', 1)[-1].rsplit('.', 1)[0].split('_')[-1]}"
            (OUT / "images" / split / f"{stem}.jpg").write_bytes(zf.read(name))
            (OUT / "labels" / split / f"{stem}.txt").write_text(
                f"{common.CLASSES.index(cls)} {(x0 + x1) / 2:.6f} {(y0 + y1) / 2:.6f} {x1 - x0:.6f} {y1 - y0:.6f}\n"
            )
        if start % (BATCH * 25) == 0:
            print(f"{start + len(chunk)}/{len(members)}", flush=True)

    if with_taco:
        # Real cluttered scenes with human-drawn boxes (ml/fetch_taco.py). Its test
        # split stays out: it is the out-of-domain test set.
        taco = _env.DATA / "taco"
        if not (taco / "data.yaml").is_file():
            raise SystemExit("run ml/fetch_taco.py first")
        for split in ("train", "val"):
            for img in sorted((taco / "images" / split).glob("*.jpg")):
                shutil.copyfile(img, OUT / "images" / split / img.name)
                shutil.copyfile(taco / "labels" / split / f"{img.stem}.txt",
                                OUT / "labels" / split / f"{img.stem}.txt")
                per_split[f"{split}:taco_images"] += 1

    names = "\n".join(f"  {i}: {c}" for i, c in enumerate(common.CLASSES))
    (OUT / "data.yaml").write_text(
        f"path: {OUT.as_posix()}\ntrain: images/train\nval: images/val\nnames:\n{names}\n", encoding="utf-8"
    )
    stats = {"model": model_name, "images": len(members), "with_taco": with_taco,
             "box_source": dict(sorted(source.items())),
             "split": dict(sorted(per_split.items())), "held_out_benchmark": 80}
    (_env.RESULTS / "pseudo_label_stats.json").write_text(json.dumps(stats, indent=1), encoding="utf-8")
    print(json.dumps(stats, indent=1))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="yoloe-26s-seg.pt")
    ap.add_argument("--with-taco", action="store_true", help="add TACO train/val (run ml/fetch_taco.py first)")
    a = ap.parse_args()
    main(a.model, a.with_taco)
