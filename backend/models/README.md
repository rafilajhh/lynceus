# Bundled detector model

`lynceus-yolo26s-realwaste.onnx` is the CPU object detector behind `lynceus.detector`: the
second opinion next to the vision-language model, and the only AI left running when the
shared AMD endpoint is down (detector-only degraded mode, which always holds the truck for a
human).

| | |
|---|---|
| File | `lynceus-yolo26s-realwaste.onnx`, 38.2 MB, sha256 `d80f89be053ca77cddeba47b4c8c3e0f0c48baae1840e9e2ec86bfd234a3781c` |
| Source | `ml/weights/yolo26s_realwaste.onnx`, copied byte for byte |
| Architecture | Ultralytics YOLO26s, fine-tuned (`ml/train.py`) |
| Export | fp32, opset 18, input 1×3×640×640, `nms=False`: NMS-free end-to-end output `(1, 300, 6)` = x0, y0, x1, y1, conf, cls in letterboxed pixels |
| Classes (ONNX metadata) | metal, glass, organic, paper, plastic, textile |
| Gate mapping | metal → hard contaminant `metal`; glass → `glass`, organic → `organic_residue` (light); paper, plastic, textile are RDF feedstock and never flag a load |
| Runtime | onnxruntime + numpy + Pillow; no torch, no Ultralytics at run time. CPUExecutionProvider by default; `DETECTOR_PROVIDERS=DmlExecutionProvider` runs it on an AMD Radeon (DirectML), see below |

## Licences

These weights are **not** covered by the repository's MIT licence; `NOTICE` in this directory
is the binding statement (including the offer of corresponding source in `ml/` and what
commercial use requires).

* **Ultralytics (AGPL-3.0).** YOLO26, the training code and the exporter are AGPL-3.0, and these
  weights are derived from Ultralytics' pretrained YOLO26s. `lynceus.detector` is our own decoder
  and does not import Ultralytics, but serving these weights inside a network service carries
  AGPL-3.0 source-availability obligations unless an Ultralytics Enterprise licence is held.
* **RealWaste (CC BY-NC-SA 4.0 treated as binding).** Training data: RealWaste by Single,
  Iranmanesh and Raad (University of Wollongong), UCI ML Repository id 908,
  DOI 10.24432/C5SS4G. The UCI page states CC BY 4.0, but the README inside the dataset zip
  states CC BY-NC-SA 4.0. Until the authors clarify, the stricter terms (non-commercial,
  share-alike) are treated as binding for the dataset and, conservatively, for these weights.
  See `backend/benchmark/images/ATTRIBUTION.md`.

## How it was measured

Held-out protocol: the 80 benchmark images (`backend/benchmark/manifest.csv`: 20 Metal,
20 escalate, 40 accept) were excluded from training by name (`ml/common.py` re-runs the
benchmark selection on the same zip and asserts an exact match). Training used the remaining
4,177 images of the same 8 RealWaste classes, with YOLOE pseudo-boxes (no human box labels).

On those 80 images, with the image-level rule "metal if any metal box has conf ≥ t":

| t | Metal recall | False metal flags |
|---|---|---|
| 0.05 | 20/20 | 0/60 |
| 0.10 | 18/20 | 0/60 |
| 0.25 (default `DETECTOR_HARD_CONF`) | 18/20 | 0/60 |
| 0.50 | 16/20 | 0/60 |

The two misses at 0.25: `metal_313.jpg` (a paper-wrapped composite drinks canister, predicted
paper 0.76) and `metal_664.jpg` (a white-painted metal bucket, predicted glass 0.19).
CPU latency, ONNX: p50 ≈ 154 ms (6 intra-op threads, laptop under background load).

### On an AMD Radeon GPU (DirectML)

The same file through the production decoder (`lynceus.detector._Model`: letterbox,
inference, box decode) on the 80 benchmark images, onnxruntime-directml 1.24.4, Ryzen 5 8645HS
laptop (`ml/results/bench_dml_lynceus-yolo26s-realwaste.json`):

| Provider | Device | p50 | p90 | mean |
|---|---|---|---|---|
| DmlExecutionProvider | AMD Radeon 760M iGPU (device_id 0) | 27.9 ms | 31.4 ms | 28.5 ms |
| CPUExecutionProvider | Ryzen 5 8645HS, 2 intra-op threads | 262.7 ms | 292.0 ms | 265.7 ms |

The two agree: 80/80 images with the same top label, max top-confidence difference 0.0.
Reproduce (Windows, a venv with `onnxruntime-directml`, numpy and Pillow):

    python ml/bench_dml.py --onnx backend/models/lynceus-yolo26s-realwaste.onnx

**Read these numbers as optimistic.** The thresholds were read off this same 80-image test set
(there is no calibration split), and training and test photos come from the same RealWaste
sessions: one item per frame on the same concrete floor. Nothing here shows the detector works
on a truck bed of mixed RDF; calibrate `DETECTOR_HARD_CONF` / `DETECTOR_LIGHT_CONF` on gate
photos before trusting it there.

Fusion what-if on the recorded 2026-10-13 MiniCPM-V run (`python -m benchmark.rescore --hybrid`,
summary in `backend/benchmark/results/2026-10-16.hybrid-rescore.summary.json`): the same
80 VLM outputs with the detector fused in. The decision rule never lets the detector reject or
accept on its own; it can only hold a truck for a human.

| Variant (thresholds 0.25) | Clean loads accepted | Review rate | Metal rejected | Metal accepted | Escalate recall | Verdict = expected |
|---|---|---|---|---|---|---|
| VLM only | 35/40 | 21/80 | 19/20 (precision 0.90) | 1 | 17/20 | 71/80 |
| Hybrid, light escalation on | 35/40 | 24/80 | 19/20 (precision 0.90) | 0 | 19/20 | 73/80 |
| Hybrid, light escalation off | 35/40 | 22/80 | 19/20 (precision 0.90) | 0 | 17/20 | 71/80 |
| Detector-only degraded | 0/40 | 80/80 | 0/20 | 0 | 20/20 | 20/80 |

The detector changes three verdicts: `metal_40.jpg` (VLM accepted it; now held for review),
`glass_121.jpg` and `food_organics_117.jpg` (VLM accepted; light escalation holds them). The
`DETECTOR_HARD_CONF` sweep (0.05, 0.1, 0.25, 0.5) moves no verdict on these images. Degraded
mode holds every truck by design; its hold reasons would list metal on 18/20 Metal images,
glass/organic on 19/20 escalate images, and nothing on 40/40 accept images. Running
`lynceus.detector` itself over
the images (`--run-detector`) gives the same verdicts in every variant as the Ultralytics
detections in `ml/results/`.

## Reproduce

Everything is in `ml/` (see `ml/README.md`): `fetch_realwaste.py`, `build_dataset.py`,
`train.py --model yolo26s.pt`, `eval_finetuned.py --nms-free`, then
`export_onnx.py --weights ml/runs/yolo26s_realwaste/weights/best.pt --out yolo26s_realwaste.onnx`
and copy `ml/weights/yolo26s_realwaste.onnx` here under this name.

## Configuration

* `DETECTOR_MODEL_PATH`: unset = this bundled file when it exists (source checkout); set to an
  empty string to turn the detector off. The container sets it to
  `/app/backend/models/lynceus-yolo26s-realwaste.onnx`.
* `DETECTOR_HARD_CONF` (default 0.25), `DETECTOR_LIGHT_CONF` (default 0.25),
  `DETECTOR_ESCALATE_LIGHT` (default 1).
* `DETECTOR_THREADS` (default 2): onnxruntime intra-op threads per run; at most two runs at
  once. Photos over 40 MP are refused before decoding, JPEGs are decoded at a reduced scale
  (no smaller than 1280 px a side), and a Pillow decompression-bomb warning is an error.
* `DETECTOR_PROVIDERS` (default `CPUExecutionProvider`): onnxruntime execution providers,
  comma-separated, in preference order. Providers this onnxruntime build lacks are skipped with
  a warning, the CPU is always the last resort, and a GPU session that fails to load falls
  back to the CPU (the detector is never turned off for it). Windows + AMD Radeon: install
  `onnxruntime-directml` instead of `onnxruntime` and set `DmlExecutionProvider`. Linux + AMD
  Instinct/Radeon with ROCm: an onnxruntime build with `MIGraphXExecutionProvider` /
  `ROCMExecutionProvider`. The container image stays on CPU onnxruntime.
* `DETECTOR_DEVICE_ID` (default 0): the GPU index passed to DirectML / ROCm / MIGraphX
  (on the test laptop 0 is the Radeon 760M, 1 an NVIDIA dGPU).
* The result's `runtime` names the provider actually used: `onnxruntime-cpu`,
  `onnxruntime-directml`, `onnxruntime-rocm` or `onnxruntime-migraphx`; startup logs it.
* Every detector result (and the audit record) carries the file's `model_sha256` and the
  `thresholds` it was judged with; the reported `model` is the file name without `lynceus-`.
