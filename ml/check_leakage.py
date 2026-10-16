"""Held-out sanity check: are any training images near-duplicates of the 80 benchmark images?

    ml/.venv/Scripts/python ml/check_leakage.py

RealWaste was shot item by item, so neighbouring file numbers may show the same
object. For every benchmark image we compute a 64-bit difference hash (dHash)
and find the closest training image by Hamming distance (0 = identical layout,
<= 10 is usually a near-duplicate). When ml/data/taco exists, the TACO test
split is checked against TACO train + val the same way.
Writes ml/results/leakage_check.json.
"""

from __future__ import annotations

import json
import zipfile

import numpy as np

import _env
import common


def dhash(img, size: int = 8) -> np.ndarray:
    g = np.asarray(img.convert("L").resize((size + 1, size)), dtype=np.int16)
    return (g[:, 1:] > g[:, :-1]).ravel()


def main() -> None:
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
    hist = {f"<={k}": sum(o["hamming"] <= k for o in out) for k in (0, 4, 8, 10, 12)}
    result = {"hash": "dHash 64-bit", "benchmark_images": len(out), "nearest_hamming_cumulative": hist,
              "closest": sorted(out, key=lambda o: o["hamming"])[:15]}

    # TACO (ml/fetch_taco.py): its test split against its train + val images.
    taco = _env.DATA / "taco" / "images"
    if (taco / "test").is_dir():
        pool = sorted((taco / "train").glob("*.jpg")) + sorted((taco / "val").glob("*.jpg"))
        pool_hash = np.stack([dhash(Image.open(p)) for p in pool])
        tout = []
        for p in sorted((taco / "test").glob("*.jpg")):
            dist = (pool_hash != dhash(Image.open(p))).sum(axis=1)
            j = int(dist.argmin())
            tout.append({"image": p.name, "nearest_train": pool[j].name, "hamming": int(dist[j])})
        result["taco_test"] = {
            "images": len(tout),
            "nearest_hamming_cumulative": {f"<={k}": sum(o["hamming"] <= k for o in tout) for k in (0, 4, 8, 10, 12)},
            "closest": sorted(tout, key=lambda o: o["hamming"])[:15],
        }
    (_env.RESULTS / "leakage_check.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(json.dumps(result, indent=1))


if __name__ == "__main__":
    main()
