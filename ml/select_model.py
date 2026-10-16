"""Task 2e: pick the detector from the val split only (before any test-set read).

    python ml/select_model.py TAG [TAG ...]

Reads ml/results/val_<TAG>.json (eval_val.py) for each candidate and ranks by,
in order: val metal recall (pooled over RealWaste and TACO val) at the model's
own hard threshold (higher), val
light recall at its light threshold (higher), val mAP50-95 (higher). Writes
ml/results/selection.json with the ranking, the winner and its thresholds.
The 80-image benchmark (eval_finetuned.py) is scored only after this file exists.
"""

from __future__ import annotations

import json
import sys

import _env


def main(tags: list[str]) -> None:
    rows = []
    for tag in tags:
        path = _env.RESULTS / f"val_{tag}.json"
        if not path.is_file():
            print(f"skip {tag}: {path.name} missing")
            continue
        v = json.loads(path.read_text(encoding="utf-8"))
        s = v["at_selected"]
        rows.append({"tag": tag, "metal_recall": s["metal_recall"], "metal_false_rate": s["metal_false_rate"],
                     "light_recall": s["light_recall"], "light_false_rate_clean": s["light_false_rate_clean"],
                     "map50_95": v["map50_95"], "hard_threshold": v["hard_threshold"],
                     "light_threshold": v["light_threshold"],
                     "metal_recall_by_source": {src: b["hard"]["metal_recall"]
                                                for src, b in v.get("at_selected_by_source", {}).items()}})
    if not rows:
        raise SystemExit("no candidates")
    rows.sort(key=lambda r: (r["metal_recall"], r["light_recall"], r["map50_95"]), reverse=True)
    out = {"rule": "rank by val metal recall @ hard t, then val light recall @ light t, then val mAP50-95",
           "ranking": rows, "winner": rows[0]["tag"],
           "thresholds": {"hard": rows[0]["hard_threshold"], "light": rows[0]["light_threshold"]}}
    (_env.RESULTS / "selection.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main(sys.argv[1:])
