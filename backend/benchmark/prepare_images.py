"""Select the benchmark images from the RealWaste zip, deterministically.

One-off preparation tool (Pillow is needed only here, never at runtime)::

    python -I backend/benchmark/prepare_images.py <realwaste.zip> [out_dir]

Selection rule: within each category, sort the file names by their trailing
number, then take every k-th image starting from the first, where
k = floor(category_size / quota). Images are read straight from the zip
(never extracted or executed). A file already <= 200 KB is copied byte for
byte; a larger one is re-encoded as JPEG (quality stepped down) at its
original pixel size. The manifest lists the categories round-robin so a run
that stops early still covers every class.
"""

from __future__ import annotations

import csv
import io
import re
import sys
import zipfile
from pathlib import Path

#: category -> (expected verdict, quota). Total 80: 20 reject, 20 escalate, 40 accept.
QUOTAS = {
    "Metal": ("reject", 20),
    "Glass": ("escalate", 7),
    "Food Organics": ("escalate", 7),
    "Vegetation": ("escalate", 6),
    "Paper": ("accept", 10),
    "Cardboard": ("accept", 10),
    "Plastic": ("accept", 10),
    "Textile Trash": ("accept", 10),
}
MAX_BYTES = 200 * 1024
MIN_LONG_SIDE = 512


def _number(name: str) -> int:
    match = re.search(r"(\d+)\.jpe?g$", name, re.IGNORECASE)
    return int(match.group(1)) if match else 0


def select(zf: zipfile.ZipFile) -> dict[str, list[str]]:
    by_cat: dict[str, list[str]] = {c: [] for c in QUOTAS}
    for name in zf.namelist():
        parts = name.split("/")
        if len(parts) >= 2 and parts[-2] in by_cat and name.lower().endswith((".jpg", ".jpeg")):
            by_cat[parts[-2]].append(name)
    chosen: dict[str, list[str]] = {}
    for cat, (_, quota) in QUOTAS.items():
        files = sorted(by_cat[cat], key=lambda n: (_number(n), n))
        if len(files) < quota:
            raise SystemExit(f"{cat}: only {len(files)} images, need {quota}")
        step = len(files) // quota
        chosen[cat] = [files[i * step] for i in range(quota)]
    return chosen


def fit(data: bytes) -> tuple[bytes, bool]:
    """Bytes <= MAX_BYTES; second value is True when re-encoded."""
    if len(data) <= MAX_BYTES:
        return data, False
    from PIL import Image

    image = Image.open(io.BytesIO(data)).convert("RGB")
    if max(image.size) < MIN_LONG_SIDE:
        raise SystemExit("source image below the 512 px floor")
    for quality in (90, 85, 80, 75, 70, 60):
        buf = io.BytesIO()
        image.save(buf, "JPEG", quality=quality, optimize=True)
        if buf.tell() <= MAX_BYTES:
            return buf.getvalue(), True
    raise SystemExit("could not fit an image under 200 KB at >= 512 px")


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", Path(name).stem.lower()).strip("_") + ".jpg"


def main(argv: list[str]) -> None:
    zip_path = Path(argv[1])
    out_dir = Path(argv[2]) if len(argv) > 2 else Path(__file__).resolve().parent / "images"
    out_dir.mkdir(parents=True, exist_ok=True)
    rows: list[tuple[str, str, str]] = []
    reencoded = 0
    with zipfile.ZipFile(zip_path) as zf:
        chosen = select(zf)
        per_cat = {}
        for cat, names in chosen.items():
            exp = QUOTAS[cat][0]
            per_cat[cat] = []
            for name in names:
                data, changed = fit(zf.read(name))
                reencoded += changed
                fname = slug(name)
                (out_dir / fname).write_bytes(data)
                per_cat[cat].append((fname, cat, exp))
    for i in range(max(len(v) for v in per_cat.values())):
        for cat in QUOTAS:
            if i < len(per_cat[cat]):
                rows.append(per_cat[cat][i])
    manifest = out_dir.parent / "manifest.csv"
    with manifest.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(["image", "category", "expected"])
        writer.writerows(rows)
    print(f"{len(rows)} images, {reencoded} re-encoded -> {out_dir}; manifest {manifest}")


if __name__ == "__main__":
    main(sys.argv)
