"""Task 3e: is the TACO test gain robust to leakage from TACO train/val?

    python ml/taco_robustness.py [--new ml/results/decoder_<new>.json] [--old ml/results/decoder_<old>.json]

TACO is split by image id (fetch_taco.py), so the same scene can sit in train and
test: consecutive shots of one batch, or a near-identical photo. This re-scores the
TACO test split on four subsets:

* all          every test image;
* no_near_dup  drops test images whose nearest TACO train/val image has dHash
               Hamming <= 10 (ml/check_leakage.py ``taco_test.rows``);
* no_adjacent  drops test images with a train/val image within 2 places in the
               same TACO batch (file order from ml/data/taco/meta.json) at dHash
               Hamming <= 16: the same scene shot again. (Batch order alone flags
               every test image: the id split puts train shots next to each one.)
* strict       both exclusions (plus the strict subset at cuts 12 and 20).

Both models are read from the production decoder's per-image rows
(ml/eval_decoder.py), at the thresholds each one ships with, plus the previous
model at its own val pick. Per metric: count, Wilson 95% interval, and for the
paired change new - old the difference, a paired bootstrap 95% interval
(10,000 resamples, seed 0) and the exact two-sided McNemar p.
Stdlib only. Writes ml/results/taco_test_robustness.json.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import re
from pathlib import Path

ML = Path(__file__).resolve().parent
RESULTS = ML / "results"
NEAR_DUP_MAX = 10
ADJACENT_MAX = 2
#: A batch neighbour this close is likely the same scene shot again; set before
#: any robustness number was read. 12 and 20 are reported as a sensitivity check.
ADJACENT_HAMMING_MAX = 16
SENSITIVITY_CUTS = (12, 20)

#: (name, decoder file key, hard, light). The previous model ships 0.25/0.25; its
#: own val pick (eval_val.py, same rule) was hard 0.15 / light 0.30.
COMPARATORS = (
    ("new@0.35/0.05", "new", 0.35, 0.05),
    ("previous@0.25/0.25 (shipped)", "old", 0.25, 0.25),
    ("previous@0.15/0.30 (its val pick)", "old", 0.15, 0.30),
)


def wilson(k: int, n: int, z: float = 1.959964) -> list[float] | None:
    if n == 0:
        return None
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return [round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4)]


def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact McNemar: binomial(b + c, 0.5) on the discordant pairs."""
    n = b + c
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, i) for i in range(min(b, c) + 1)) / 2 ** n
    return round(min(1.0, 2 * tail), 4)


def bootstrap_diff(a: list[bool], b: list[bool], reps: int = 10_000) -> list[float] | None:
    """Paired percentile bootstrap 95% interval of mean(a) - mean(b)."""
    n = len(a)
    if n == 0:
        return None
    rng = random.Random(0)
    diffs = []
    for _ in range(reps):
        idx = [rng.randrange(n) for _ in range(n)]
        diffs.append(sum(a[i] - b[i] for i in idx) / n)
    diffs.sort()
    return [round(diffs[int(0.025 * reps)], 4), round(diffs[int(0.975 * reps) - 1], 4)]


def hits(rows: list[dict], hard: float, light: float) -> dict[str, dict[str, bool]]:
    """Per metric, image -> whether the detector fired, on that metric's population."""
    out: dict[str, dict[str, bool]] = {k: {} for k in
                                       ("metal_recall", "false_metal", "light_recall",
                                        "false_escalate_clean", "any_hold_clean")}
    for r in rows:
        metal_hit, light_hit = r["top_metal"] >= hard, r["top_light"] >= light
        if r["metal"]:
            out["metal_recall"][r["image"]] = metal_hit
        else:
            out["false_metal"][r["image"]] = metal_hit
        if r["light"]:
            out["light_recall"][r["image"]] = light_hit
        if not r["metal"] and not r["light"]:
            out["false_escalate_clean"][r["image"]] = light_hit
            # Clean images held for any reason (metal or light), as the gate sees it.
            out["any_hold_clean"][r["image"]] = metal_hit or light_hit
    return out


def batch_neighbours(meta: dict[str, str], test_names: set[str]) -> dict[str, list[str]]:
    """Per test image (``taco_XXXX.jpg``), the non-test images within ADJACENT_MAX
    places in the same TACO batch (file order). The split is by image id, so
    nearly every test image has such neighbours: shots of the same session."""
    by_batch: dict[str, list[tuple[str, str]]] = {}
    for name, file_name in meta.items():
        if not file_name:
            continue
        batch, _, leaf = file_name.rpartition("/")
        by_batch.setdefault(batch, []).append((leaf, name))
    neighbours: dict[str, list[str]] = {}
    for members in by_batch.values():
        members.sort(key=lambda m: [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", m[0])])
        names = [f"{n}.jpg" for _, n in members]
        for i, n in enumerate(names):
            if n in test_names:
                window = names[max(0, i - ADJACENT_MAX): i + ADJACENT_MAX + 1]
                neighbours[n] = [m for m in window if m != n and m not in test_names]
    return neighbours


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--new", default=str(RESULTS / "decoder_lynceus-yolo26s-realwaste-taco.json"))
    ap.add_argument("--old", default=str(RESULTS / "decoder_lynceus-yolo26s-realwaste.json"))
    ap.add_argument("--leakage", default=str(RESULTS / "leakage_check.json"))
    a = ap.parse_args()

    decoders = {k: json.loads(Path(p).read_text(encoding="utf-8")) for k, p in (("new", a.new), ("old", a.old))}
    rows = {k: d["taco_test_rows"] for k, d in decoders.items()}
    if {r["image"] for r in rows["new"]} != {r["image"] for r in rows["old"]}:
        raise SystemExit("the two decoder files cover different TACO test images")
    test_names = {r["image"] for r in rows["new"]}

    leak = json.loads(Path(a.leakage).read_text(encoding="utf-8"))["taco_test"]
    if {r["image"] for r in leak["rows"]} != test_names:
        raise SystemExit("leakage_check.json covers different TACO test images; rerun check_leakage.py")
    near_dup = {r["image"] for r in leak["rows"] if r["hamming"] <= NEAR_DUP_MAX}
    if any(r.get("neighbour_hamming", "missing") == "missing" for r in leak["rows"]):
        raise SystemExit("leakage_check.json has no neighbour_hamming; rerun check_leakage.py")

    def same_scene(cut: int) -> set[str]:
        return {r["image"] for r in leak["rows"]
                if r["neighbour_hamming"] is not None and r["neighbour_hamming"] <= cut}

    adjacent = same_scene(ADJACENT_HAMMING_MAX)
    subsets = {
        "all": test_names,
        "no_near_dup": test_names - near_dup,
        "no_adjacent": test_names - adjacent,
        "strict": test_names - near_dup - adjacent,
        # Sensitivity of the strict subset to the same-scene cut (not a second pick).
        **{f"strict_cut{cut}": test_names - near_dup - same_scene(cut) for cut in SENSITIVITY_CUTS},
    }
    per = {name: hits(rows[key], hard, light) for name, key, hard, light in COMPARATORS}
    new_name = COMPARATORS[0][0]

    hams = sorted(r["neighbour_hamming"] for r in leak["rows"] if r["neighbour_hamming"] is not None)
    report: dict = {
        "rule": {"near_dup": f"dHash Hamming <= {NEAR_DUP_MAX} to any TACO train/val image",
                 "adjacent": (f"a TACO train/val image within {ADJACENT_MAX} places in the same batch "
                              f"at dHash Hamming <= {ADJACENT_HAMMING_MAX} (likely the same scene)"),
                 "pool": leak.get("pool_images")},
        "neighbour_hamming": {"test_images_with_batch_neighbours": len(hams),
                              "min": hams[0] if hams else None,
                              "median": hams[len(hams) // 2] if hams else None,
                              "cumulative": {f"<={k}": sum(h <= k for h in hams) for k in (8, 10, 12, 16, 20, 24)}},
        "excluded": {"near_dup": len(near_dup), "adjacent": len(adjacent),
                     "either": len(near_dup | adjacent)},
        "near_dup_images": sorted(near_dup),
        "adjacent_images": sorted(adjacent),
        "subsets": {},
    }
    for sname, keep in subsets.items():
        block: dict = {"images": len(keep)}
        for metric in per[new_name]:
            mblock: dict = {}
            for name, *_ in COMPARATORS:
                vals = [v for img, v in per[name][metric].items() if img in keep]
                k, n = sum(vals), len(vals)
                mblock[name] = {"count": f"{k}/{n}", "rate": round(k / n, 4) if n else None,
                                "wilson95": wilson(k, n)}
            for name, *_ in COMPARATORS[1:]:
                imgs = sorted(img for img in per[new_name][metric] if img in keep)
                x = [per[new_name][metric][i] for i in imgs]
                y = [per[name][metric][i] for i in imgs]
                b = sum(xi and not yi for xi, yi in zip(x, y))
                c = sum(yi and not xi for xi, yi in zip(x, y))
                mblock[f"new_minus[{name}]"] = {
                    "diff": round((sum(x) - sum(y)) / len(x), 4) if x else None,
                    "bootstrap95": bootstrap_diff(x, y),
                    "discordant_new_only/old_only": f"{b}/{c}",
                    "mcnemar_exact_p": mcnemar_exact(b, c),
                }
            block[metric] = mblock
        report["subsets"][sname] = block

    dest = RESULTS / "taco_test_robustness.json"
    dest.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps({"excluded": report["excluded"],
                      **{s: {m: {k: v.get("count", v.get("diff")) for k, v in mv.items()}
                             if isinstance(mv, dict) else mv for m, mv in b.items()}
                         for s, b in report["subsets"].items()}}, indent=1))


if __name__ == "__main__":
    main()
