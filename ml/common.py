"""Shared helpers: benchmark manifest, held-out file list, RealWaste zip, metrics."""

from __future__ import annotations

import csv
import importlib.util
import io
import zipfile
from pathlib import Path

import _env

ZIP = _env.DATA / "zip" / "realwaste.zip"
MANIFEST = _env.BENCH / "manifest.csv"
BENCH_IMAGES = _env.BENCH / "images"

#: RealWaste folder -> detector class (Miscellaneous Trash is not used).
CLASS_OF = {
    "Metal": "metal",
    "Glass": "glass",
    "Food Organics": "organic",
    "Vegetation": "organic",
    "Paper": "paper",
    "Cardboard": "paper",
    "Plastic": "plastic",
    "Textile Trash": "textile",
}
CLASSES = ["metal", "glass", "organic", "paper", "plastic", "textile"]
ESCALATE = {"glass", "organic"}


def _prepare_module():
    path = _env.BENCH / "prepare_images.py"
    spec = importlib.util.spec_from_file_location("lynceus_prepare_images", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def manifest() -> list[dict]:
    with MANIFEST.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def benchmark_zip_names(zf: zipfile.ZipFile) -> set[str]:
    """Zip member names of the 80 benchmark images (the held-out set)."""
    mod = _prepare_module()
    chosen = mod.select(zf)
    names = {n for files in chosen.values() for n in files}
    slugs = {mod.slug(n) for n in names}
    expected = {row["image"] for row in manifest()}
    if slugs != expected:
        raise SystemExit(f"select() does not reproduce manifest: {sorted(slugs ^ expected)[:5]}")
    return names


def training_members(zf: zipfile.ZipFile) -> list[tuple[str, str]]:
    """(zip member, RealWaste category) for every usable non-benchmark image."""
    held = benchmark_zip_names(zf)
    out = []
    for name in zf.namelist():
        parts = name.split("/")
        if len(parts) < 2 or parts[-2] not in CLASS_OF:
            continue
        if not name.lower().endswith((".jpg", ".jpeg")) or name in held:
            continue
        out.append((name, parts[-2]))
    return sorted(out)


def load_zip_image(zf: zipfile.ZipFile, name: str):
    from PIL import Image

    return Image.open(io.BytesIO(zf.read(name))).convert("RGB")


def metal_report(rows: list[dict], flag_key: str = "metal_flag") -> dict:
    """rows: dicts with category + boolean flag. Recall over Metal, false flags elsewhere."""
    per_cat: dict[str, list[int]] = {}
    for r in rows:
        c = per_cat.setdefault(r["category"], [0, 0])
        c[0] += bool(r[flag_key])
        c[1] += 1
    tp = per_cat.get("Metal", [0, 0])[0]
    n_metal = per_cat.get("Metal", [0, 0])[1]
    fp = sum(v[0] for k, v in per_cat.items() if k != "Metal")
    n_other = sum(v[1] for k, v in per_cat.items() if k != "Metal")
    return {
        "metal_recall": f"{tp}/{n_metal}",
        "metal_recall_pct": round(100 * tp / max(n_metal, 1), 1),
        "false_flags": f"{fp}/{n_other}",
        "false_flag_rate_pct": round(100 * fp / max(n_other, 1), 1),
        "metal_precision_pct": round(100 * tp / max(tp + fp, 1), 1),
        "flags_by_category": {k: f"{v[0]}/{v[1]}" for k, v in per_cat.items()},
    }
