"""Held-out sanity check: are any training images near-duplicates of the test images?

    ml/.venv/Scripts/python ml/check_leakage.py [--taco-only]

RealWaste was shot item by item, so neighbouring file numbers may show the same
object. For every benchmark image we compute a 64-bit difference hash (dHash)
and find the closest training image by Hamming distance (0 = identical layout,
<= 10 is usually a near-duplicate). When ml/data/taco exists, the TACO test
split is checked against TACO train + val the same way, and every test image's
nearest distance is kept (``taco_test.rows``) for ml/taco_robustness.py, with
``neighbour_hamming``: the distance to the closest train/val image within two
places in the same TACO batch (ml/data/taco/meta.json), i.e. the same session.
--taco-only skips the RealWaste part (no RealWaste zip needed) and keeps the
RealWaste block already in the results file.
Writes ml/results/leakage_check.json.
"""

from __future__ import annotations

import argparse
import json
import zipfile

import numpy as np

import _env
import common
import taco_robustness

THRESHOLDS = (0, 4, 8, 10, 12)


def dhash(img, size: int = 8) -> np.ndarray:
    from PIL import ImageOps

    # EXIF orientation applied: a rotated copy of the same photo hashes alike.
    g = np.asarray(ImageOps.exif_transpose(img).convert("L").resize((size + 1, size)), dtype=np.int16)
    return (g[:, 1:] > g[:, :-1]).ravel()


def realwaste_block() -> dict:
    from PIL import Image

    zf = zipfile.ZipFile(common.ZIP)
    train = common.training_members(zf)
    train_names = [n for n, _ in train]
    train_hash = np.stack([dhash(common.load_zip_image(zf, n)) for n in train_names])
    out = []
    for row in common.manifest():
        h = dhash(Image.open(common.BENCH_IMAGES / row["image"]))
        dist = (train_hash != h).sum(axis=1)
        j = int(dist.argmin())
        out.append({"image": row["image"], "nearest_train": train_names[j].rsplit("/", 1)[-1], "hamming": int(dist[j])})
    return {"hash": "dHash 64-bit", "benchmark_images": len(out),
            "nearest_hamming_cumulative": {f"<={k}": sum(o["hamming"] <= k for o in out) for k in THRESHOLDS},
            "closest": sorted(out, key=lambda o: o["hamming"])[:15]}


def taco_block() -> dict | None:
    """TACO (ml/fetch_taco.py): its test split against its train + val images."""
    from PIL import Image

    taco = _env.DATA / "taco" / "images"
    if not (taco / "test").is_dir():
        return None
    pool = sorted((taco / "train").glob("*.jpg")) + sorted((taco / "val").glob("*.jpg"))
    if not pool:
        return None
    pool_hash = np.stack([dhash(Image.open(p)) for p in pool])
    pool_index = {p.name: i for i, p in enumerate(pool)}
    tests = sorted((taco / "test").glob("*.jpg"))
    meta_file = _env.DATA / "taco" / "meta.json"
    neighbours = (taco_robustness.batch_neighbours(json.loads(meta_file.read_text(encoding="utf-8")),
                                                   {p.name for p in tests})
                  if meta_file.is_file() else {})
    rows = []
    for p in tests:
        dist = (pool_hash != dhash(Image.open(p))).sum(axis=1)
        j = int(dist.argmin())
        # Closest train/val shot within 2 places in the same TACO batch (same session).
        near = [int(dist[pool_index[n]]) for n in neighbours.get(p.name, []) if n in pool_index]
        rows.append({"image": p.name, "nearest_train": pool[j].name, "hamming": int(dist[j]),
                     "neighbour_hamming": min(near) if near else None})
    return {
        "images": len(rows),
        "pool_images": {"train": len(list((taco / "train").glob("*.jpg"))),
                        "val": len(list((taco / "val").glob("*.jpg")))},
        "nearest_hamming_cumulative": {f"<={k}": sum(o["hamming"] <= k for o in rows) for k in THRESHOLDS},
        "closest": sorted(rows, key=lambda o: o["hamming"])[:15],
        "rows": rows,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--taco-only", action="store_true", help="keep the RealWaste block already written")
    a = ap.parse_args()
    dest = _env.RESULTS / "leakage_check.json"
    if a.taco_only:
        previous = json.loads(dest.read_text(encoding="utf-8")) if dest.is_file() else {}
        result = {k: v for k, v in previous.items() if k != "taco_test"}
    else:
        result = realwaste_block()
    taco = taco_block()
    if taco is not None:
        result["taco_test"] = taco
    dest.write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(json.dumps({k: ({kk: vv for kk, vv in v.items() if kk != "rows"} if isinstance(v, dict) else v)
                      for k, v in result.items()}, indent=1))


if __name__ == "__main__":
    main()
