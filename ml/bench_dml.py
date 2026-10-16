"""Task 3c: the production decoder on AMD Radeon (DirectML) vs the CPU.

    ml/.cache/dml/Scripts/python ml/bench_dml.py --onnx backend/models/lynceus-yolo26s-realwaste.onnx

Needs a venv with ``onnxruntime-directml`` (Windows; any DirectX 12 GPU, here
the Radeon 760M iGPU of the Ryzen 5 8645HS), numpy and Pillow. Loads the
production ``lynceus.detector._Model`` twice: CPUExecutionProvider and
DmlExecutionProvider. Runs both on the 80 benchmark images, checks the boxes
agree, and times each run (decode + letterbox + inference + box decode).
Writes ml/results/bench_dml_<model>.json.
"""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import sys
import time
from pathlib import Path

ML = Path(__file__).resolve().parent
REPO = ML.parent
sys.path.insert(0, str(REPO / "backend" / "src"))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--onnx", default=str(REPO / "backend" / "models" / "lynceus-yolo26s-realwaste.onnx"))
    ap.add_argument("--threads", type=int, default=2)
    ap.add_argument("--warmup", type=int, default=5)
    a = ap.parse_args()

    import onnxruntime as ort
    from PIL import Image

    from lynceus import detector as det

    path = str(Path(a.onnx).resolve())
    images = sorted((REPO / "backend" / "benchmark" / "images").glob("*.jpg"))
    runs: dict[str, dict] = {}
    for prov in ("CPUExecutionProvider", "DmlExecutionProvider"):
        if prov not in ort.get_available_providers():
            continue
        model = det._Model(path, a.threads)
        if prov != "CPUExecutionProvider":
            opts = ort.SessionOptions()
            # DirectML wants sequential execution and no memory pattern.
            opts.enable_mem_pattern = False
            opts.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
            model.session = ort.InferenceSession(path, sess_options=opts, providers=[prov, "CPUExecutionProvider"])
        used = model.session.get_providers()[0]
        pics = [det._decode(p.read_bytes()) for p in images]
        for img in pics[: a.warmup]:
            model(img, 0.05)
        times, outs = [], []
        for img in pics:
            t0 = time.perf_counter()
            outs.append(model(img, 0.05))
            times.append(1000 * (time.perf_counter() - t0))
        times.sort()
        runs[prov] = {"provider_used": used, "p50_ms": round(statistics.median(times), 1),
                      "p90_ms": round(times[int(0.9 * len(times))], 1), "mean_ms": round(statistics.mean(times), 1),
                      "outputs": outs}

    agree = None
    if len(runs) == 2:
        cpu, dml = (runs[p]["outputs"] for p in ("CPUExecutionProvider", "DmlExecutionProvider"))
        top = lambda o: (o[0]["label"], o[0]["confidence"]) if o else (None, 0.0)  # noqa: E731
        same_label = sum(top(c)[0] == top(d)[0] for c, d in zip(cpu, dml))
        max_conf_diff = max(abs(top(c)[1] - top(d)[1]) for c, d in zip(cpu, dml))
        agree = {"images": len(cpu), "same_top_label": same_label, "max_top_conf_diff": round(max_conf_diff, 4)}
    out = {"onnx": Path(a.onnx).name, "images": len(images), "cpu": platform.processor(),
           "ort": ort.__version__, "threads": a.threads,
           "runs": {p: {k: v for k, v in r.items() if k != "outputs"} for p, r in runs.items()},
           "agreement": agree}
    dest = ML / "results" / f"bench_dml_{Path(a.onnx).stem}.json"
    dest.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
