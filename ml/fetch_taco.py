"""Task 1b: TACO (real litter photos, human-drawn boxes) in the Lynceus classes.

    python ml/fetch_taco.py [--workers 16] [--splits train,val,test]

RealWaste shows one item on a concrete floor; TACO shows cluttered real scenes
with several objects, closer to a mixed load. The official 1,500 images and
4,784 annotations (github.com/pedropro/TACO, CC BY 4.0) are mapped to the six
detector classes (CLASS_MAP); cigarettes and "unlabeled litter" are dropped.
Images come from their Flickr 640-px copies, or from the original (EXIF-rotated
upright, shrunk to MAX_SIDE) where no 640-px copy is listed. An image whose
upright shape does not match the annotation's width/height is skipped.

Split by image id: id % 10 == 8 -> val, == 9 -> test (out-of-domain test set,
scored once after model selection), else train.
Writes ml/data/taco/{images,labels}/{train,val,test}, ml/data/taco/data.yaml
and ml/results/taco_stats.json.
"""

from __future__ import annotations

import argparse
import io
import json
import threading
import time
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

import _env
import common

ANN_URL = "https://raw.githubusercontent.com/pedropro/TACO/master/data/annotations.json"
OUT = _env.DATA / "taco"
#: Longest side kept on disk; training runs at 640, so larger only costs disk and decode time.
MAX_SIDE = 1280

#: TACO category name -> detector class. Anything not listed is dropped.
CLASS_MAP = {
    # metal (hard contaminant)
    "Aluminium foil": "metal", "Battery": "metal", "Aluminium blister pack": "metal",
    "Metal bottle cap": "metal", "Food Can": "metal", "Aerosol": "metal", "Drink can": "metal",
    "Metal lid": "metal", "Pop tab": "metal", "Scrap metal": "metal",
    # glass
    "Glass bottle": "glass", "Broken glass": "glass", "Glass cup": "glass", "Glass jar": "glass",
    # organic
    "Food waste": "organic",
    # paper / cardboard
    "Toilet tube": "paper", "Other carton": "paper", "Egg carton": "paper", "Drink carton": "paper",
    "Corrugated carton": "paper", "Meal carton": "paper", "Pizza box": "paper", "Paper cup": "paper",
    "Magazine paper": "paper", "Tissues": "paper", "Wrapping paper": "paper", "Normal paper": "paper",
    "Paper bag": "paper", "Plastified paper bag": "paper", "Paper straw": "paper",
    # plastic
    "Carded blister pack": "plastic", "Other plastic bottle": "plastic", "Clear plastic bottle": "plastic",
    "Plastic bottle cap": "plastic", "Disposable plastic cup": "plastic", "Foam cup": "plastic",
    "Other plastic cup": "plastic", "Plastic lid": "plastic", "Other plastic": "plastic",
    "Plastic film": "plastic", "Six pack rings": "plastic", "Garbage bag": "plastic",
    "Other plastic wrapper": "plastic", "Single-use carrier bag": "plastic", "Polypropylene bag": "plastic",
    "Crisp packet": "plastic", "Spread tub": "plastic", "Tupperware": "plastic",
    "Disposable food container": "plastic", "Foam food container": "plastic",
    "Other plastic container": "plastic", "Plastic glooves": "plastic", "Plastic utensils": "plastic",
    "Squeezable tube": "plastic", "Plastic straw": "plastic", "Styrofoam piece": "plastic",
    # textile
    "Rope & strings": "textile", "Shoe": "textile",
}


def split_of(image_id: int) -> str:
    return {8: "val", 9: "test"}.get(image_id % 10, "train")


def fetch(url: str, tries: int = 3) -> bytes | None:
    for i in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                return r.read()
        except Exception:  # noqa: BLE001 - network flake, retry then give up
            time.sleep(1 + 2 * i)
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--splits", default="train,val,test", help="comma-separated subset to fetch")
    a = ap.parse_args()
    wanted = set(a.splits.split(","))
    from PIL import Image, ImageOps

    ann = json.loads(fetch(ANN_URL) or b"{}")
    if not ann.get("images"):
        raise SystemExit(f"could not read {ANN_URL}")
    cats = {c["id"]: c["name"] for c in ann["categories"]}
    unknown = sorted({n for n in cats.values() if n not in CLASS_MAP})
    by_image: dict[int, list] = {}
    for x in ann["annotations"]:
        by_image.setdefault(x["image_id"], []).append(x)
    for split in ("train", "val", "test"):
        (OUT / "images" / split).mkdir(parents=True, exist_ok=True)
        (OUT / "labels" / split).mkdir(parents=True, exist_ok=True)

    stats = Counter()
    lock = threading.Lock()

    def count(key: str) -> None:
        with lock:
            stats[key] += 1

    def one(img: dict) -> None:
        split = split_of(img["id"])
        if split not in wanted:
            return
        stem = f"taco_{img['id']:04d}"
        dest = OUT / "images" / split / f"{stem}.jpg"
        if dest.is_file():
            data, how = dest.read_bytes(), "cached"
        elif img.get("flickr_640_url"):
            data, how = fetch(img["flickr_640_url"]), "640"
        else:  # about a third have no 640-px copy: fetch the original and shrink it
            data, how = fetch(img["flickr_url"]), "original"
        if data is None:
            count("download_failed")
            return
        try:
            pic = Image.open(io.BytesIO(data))
            pic.draft("RGB", (2 * MAX_SIDE, 2 * MAX_SIDE))  # JPEG DCT scaling: ~1/4 the memory of a full decode
            # TACO boxes are drawn on the upright (EXIF-rotated) photo.
            pic = ImageOps.exif_transpose(pic).convert("RGB")
        except Exception:  # noqa: BLE001
            count("unreadable")
            return
        w, h = pic.size
        aw, ah = img["width"], img["height"]
        if abs(w / h - aw / ah) > 0.03 * (aw / ah):
            count("orientation_mismatch_skipped")
            return
        if how != "cached":
            if max(w, h) > MAX_SIDE:
                pic.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
            buf = io.BytesIO()
            pic.save(buf, "JPEG", quality=92)  # no EXIF: upright pixels, nothing left to rotate
            data = buf.getvalue()
            count(f"source:{how}")
        lines = []
        for x in by_image.get(img["id"], []):
            cls = CLASS_MAP.get(cats[x["category_id"]])
            if cls is None:
                count("box_dropped:" + cats[x["category_id"]])
                continue
            bx, by, bw, bh = x["bbox"]
            x0, y0 = max(0.0, bx / aw), max(0.0, by / ah)
            x1, y1 = min(1.0, (bx + bw) / aw), min(1.0, (by + bh) / ah)
            if x1 - x0 <= 0 or y1 - y0 <= 0:
                continue
            lines.append(f"{common.CLASSES.index(cls)} {(x0 + x1) / 2:.6f} {(y0 + y1) / 2:.6f} "
                         f"{x1 - x0:.6f} {y1 - y0:.6f}")
            count(f"{split}:box:{cls}")
        dest.write_bytes(data)
        (OUT / "labels" / split / f"{stem}.txt").write_text("\n".join(lines) + ("\n" if lines else ""))
        count(f"{split}:images")
        if any(l.startswith(f"{common.CLASSES.index('metal')} ") for l in lines):
            count(f"{split}:images_with_metal")

    with ThreadPoolExecutor(a.workers) as pool:
        for i, _ in enumerate(pool.map(one, ann["images"]), 1):
            if i % 250 == 0:
                print(f"{i}/{len(ann['images'])}", flush=True)

    names = "\n".join(f"  {i}: {c}" for i, c in enumerate(common.CLASSES))
    (OUT / "data.yaml").write_text(
        f"path: {OUT.as_posix()}\ntrain: images/train\nval: images/val\ntest: images/test\nnames:\n{names}\n",
        encoding="utf-8")
    out = {"source": "TACO official annotations (CC BY 4.0), Flickr 640-px images",
           "unmapped_categories": unknown, "stats": dict(sorted(stats.items()))}
    (_env.RESULTS / "taco_stats.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
