"""Task 2d: image-level scores on the VAL split, for model and threshold selection.

    python ml/eval_val.py --weights RUN/weights/best.pt [--tag NAME]
    python ml/eval_val.py --weights ... --data ml/data/taco/data.yaml --split test --hard T --light T

The 80 benchmark images are the test set and are read once, after selection
(eval_finetuned.py). This script picks thresholds on the val split instead
(never trained on). An image's truth is the set of classes in its label file:
a RealWaste image has its folder's class, a TACO image (name ``taco_*``) every
class drawn in it. "Metal" = the image holds metal; "clean" = no metal, glass
or organic. Scores are reported per source and pooled.

Rule (committed before the RealWaste+TACO model was trained; the previous
RealWaste-only model had already been scored on both test sets when the
per-source caps were written): the hard (metal) threshold is the
lowest t in THRESHOLDS whose false-metal rate is <= MAX_FALSE[source] for
every source present; the light (glass/organic) threshold likewise with the
false-escalate rate on clean images (MAX_FALSE_LIGHT). --hard/--light skip the
search and score at given thresholds (the out-of-domain test after selection).
Writes ml/results/val_<tag>.json.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import _env
import common

THRESHOLDS = [0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4, 0.5, 0.6]
#: Cluttered TACO scenes hold metal look-alikes (caps, foil-lined packs), so they get more room.
MAX_FALSE = {"realwaste": 0.02, "taco": 0.05}
MAX_FALSE_LIGHT = {"realwaste": 0.05, "taco": 0.10}
VAL = _env.DATA / "yolo"


def rates(rows: list[dict], t: float) -> dict:
    metal = [r for r in rows if r["has_metal"]]
    other = [r for r in rows if not r["has_metal"]]
    light = [r for r in rows if r["has_light"]]
    clean = [r for r in rows if not r["has_metal"] and not r["has_light"]]
    frac = lambda xs, key: round(sum(r[key] >= t for r in xs) / len(xs), 4) if xs else None  # noqa: E731
    return {"n": len(rows), "n_metal": len(metal), "n_light": len(light), "n_clean": len(clean),
            "metal_recall": frac(metal, "metal"), "metal_false_rate": frac(other, "metal"),
            "light_recall": frac(light, "light"), "light_false_rate_clean": frac(clean, "light")}


def lowest_ok(per_t: dict, key: str, limits: dict) -> float:
    for t in THRESHOLDS:
        if all(per_t[str(t)][src][key] is None or per_t[str(t)][src][key] <= limits[src]
               for src in limits if src in per_t[str(t)]):
            return t
    return THRESHOLDS[-1]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", required=True)
    ap.add_argument("--tag", default=None)
    ap.add_argument("--data", default=str(VAL / "data.yaml"))
    ap.add_argument("--split", default="val", choices=["val", "test"])
    ap.add_argument("--hard", type=float, default=None, help="score at this metal threshold (no search)")
    ap.add_argument("--light", type=float, default=None, help="score at this light threshold (no search)")
    a = ap.parse_args()
    weights = Path(a.weights).resolve()
    data = str(Path(a.data).resolve())  # before yolo_setup(), which changes the working directory
    tag = a.tag or weights.parent.parent.name

    _env.yolo_setup()
    from ultralytics import YOLO

    model = YOLO(str(weights))
    root = Path(data).parent
    metal_id = common.CLASSES.index("metal")
    light_ids = {common.CLASSES.index(c) for c in common.ESCALATE}
    rows, times = [], []
    for img in sorted((root / "images" / a.split).glob("*.jpg")):
        label = root / "labels" / a.split / f"{img.stem}.txt"
        ids = {int(l.split()[0]) for l in label.read_text().splitlines() if l.strip()} if label.is_file() else set()
        t0 = time.perf_counter()
        res = model.predict(str(img), conf=0.05, imgsz=640, verbose=False, nms=False)[0]
        times.append(time.perf_counter() - t0)
        boxes = [(res.names[int(c)], float(p)) for p, c in zip(res.boxes.conf.tolist(), res.boxes.cls.tolist())]
        top = lambda labels: max((p for n, p in boxes if n in labels), default=0.0)  # noqa: E731
        rows.append({"image": img.name, "source": "taco" if img.name.startswith("taco_") else "realwaste",
                     "has_metal": metal_id in ids, "has_light": bool(ids & light_ids),
                     "metal": top({"metal"}), "light": top(common.ESCALATE)})

    sources = sorted({r["source"] for r in rows})
    sweep = {}
    for t in THRESHOLDS:
        sweep[str(t)] = {"pooled": rates(rows, t), **{s: rates([r for r in rows if r["source"] == s], t)
                                                       for s in sources}}
    hard = a.hard if a.hard is not None else lowest_ok(sweep, "metal_false_rate", MAX_FALSE)
    lt = a.light if a.light is not None else lowest_ok(sweep, "light_false_rate_clean", MAX_FALSE_LIGHT)
    at_hard, at_light = rates(rows, hard), rates(rows, lt)
    by_src = {s: {"hard": rates([r for r in rows if r["source"] == s], hard),
                  "light": rates([r for r in rows if r["source"] == s], lt)} for s in sources}

    metrics = model.val(data=data, split=a.split, imgsz=640, batch=8, workers=2, verbose=False, plots=False)
    times.sort()
    out = {
        "weights": str(weights.relative_to(_env.REPO)) if weights.is_relative_to(_env.REPO) else str(weights),
        "data": Path(data).relative_to(_env.REPO).as_posix() if Path(data).is_relative_to(_env.REPO) else data,
        "split": a.split, "images": len(rows),
        "per_source": {s: sum(r["source"] == s for r in rows) for s in sources},
        "map50": round(float(metrics.box.map50), 4),
        "map50_95": round(float(metrics.box.map), 4),
        "map50_per_class": {common.CLASSES[int(i)]: round(float(v), 4)
                            for i, v in zip(metrics.box.ap_class_index, metrics.box.ap50)},
        "rule": "given" if a.hard is not None else
                f"hard t = lowest with false-metal rate <= {MAX_FALSE} per source; light t = lowest with "
                f"false-escalate rate on clean images <= {MAX_FALSE_LIGHT} per source",
        "hard_threshold": hard,
        "light_threshold": lt,
        "at_selected": {"metal_recall": at_hard["metal_recall"], "metal_false_rate": at_hard["metal_false_rate"],
                        "light_recall": at_light["light_recall"],
                        "light_false_rate_clean": at_light["light_false_rate_clean"]},
        "at_selected_by_source": by_src,
        "gpu_latency_ms_p50": round(1000 * times[len(times) // 2], 1),
        "sweep": sweep,
    }
    (_env.RESULTS / f"val_{tag}.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items() if k != "sweep"}, indent=1))


if __name__ == "__main__":
    main()
