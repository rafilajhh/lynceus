# Bundled detector model

`lynceus-yolo26s-realwaste-taco.onnx` is the CPU object detector behind `lynceus.detector`: the
second opinion next to the vision-language model, and the only AI left running when the
shared AMD endpoint is down (detector-only degraded mode, which always holds the truck for a
human). It replaced `lynceus-yolo26s-realwaste.onnx` on 2026-10-17; see
`docs/detector-update-2026-10-17.md` for why, and how to roll back.

| | |
|---|---|
| File | `lynceus-yolo26s-realwaste-taco.onnx`, 38.2 MB, sha256 `c84f795aca8fb2126600efa69b9c62f8c3e8d22c2ff8262446d2c45620bf5405` |
| Source | `ml/weights/yolo26s_e26l.onnx` (`ml/export_onnx.py` from the Colab run `yolo26s_e26l`), copied byte for byte |
| Architecture | Ultralytics YOLO26s, fine-tuned from `yolo26s.pt` (`ml/colab_train.sh`: 81 epochs with early stop, cosine LR, seed 0, deterministic, Ultralytics 8.4.177) |
| Training data | RealWaste train split with YOLOE-26l pseudo-boxes, plus TACO train with human boxes (`ml/build_dataset.py --with-taco`) |
| Export | fp32, opset 18, input 1×3×640×640, `nms=False`: NMS-free end-to-end output `(1, 300, 6)` = x0, y0, x1, y1, conf, cls in letterboxed pixels |
| Classes (ONNX metadata) | metal, glass, organic, paper, plastic, textile |
| Gate mapping | metal → hard contaminant `metal`; glass → `glass`, organic → `organic_residue` (light); paper, plastic, textile are RDF feedstock and never flag a load |
| Default thresholds | `DETECTOR_HARD_CONF` 0.35, `DETECTOR_LIGHT_CONF` 0.05, picked on the val split (below) |
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
* **TACO (annotations CC BY 4.0).** Proença and Simões, github.com/pedropro/TACO. The photos are
  hosted on Flickr under their uploaders' licences; no TACO image is stored in this repository.

## How it was measured

Three splits, each with its own job. The thresholds were picked on val by a rule fixed before
any test read; the two test sets were read once, afterwards.

| Split | Images | Used for |
|---|---|---|
| val: RealWaste val (every 10th image per class) + TACO val (image id % 10 = 8) | 416 + 150 | picking the thresholds and the model |
| TACO test (image id % 10 = 9): real-world litter scenes, human boxes, 29 hold metal | 150 | out-of-domain check |
| RealWaste benchmark (`backend/benchmark/manifest.csv`: 20 Metal, 20 escalate, 40 accept) | 80 | in-domain check, and the hybrid replay |

None of them was trained on. The 80 benchmark images are excluded by name (`ml/common.py`
re-runs the benchmark selection and asserts an exact match); the TACO split is by image id.

**Threshold rule** (`ml/eval_val.py`): the hard threshold is the lowest t whose false-metal rate
is ≤ 2 % on RealWaste and ≤ 5 % on TACO; the light threshold is the lowest t whose false-escalate
rate on clean images is ≤ 5 % on RealWaste and ≤ 10 % on TACO. For this model that gives
hard 0.35, light 0.05 (`ml/results/val_yolo26s_e26l.json`).

**val** (566 images), Ultralytics predict:

| | This model (0.35 / 0.05) | Previous model (its val pick 0.15 / 0.30) |
|---|---|---|
| mAP50 / mAP50-95 | **0.712 / 0.642** | 0.519 / 0.466 |
| Metal recall, RealWaste | 68/77 (88 %) | 70/77 (91 %) |
| False metal, RealWaste | 4/339 (1.2 %) | 1/339 (0.3 %) |
| Metal recall, TACO | **10/31 (32 %)** | 0/31 |
| False metal, TACO | 3/119 (2.5 %) | 4/119 (3.4 %) |
| Glass/organic recall, RealWaste | 123/124 | 115/124 |
| False escalate on clean, TACO | 7/114 (6.1 %) | 11/114 (9.6 %) |

**TACO test** (150 images), through `lynceus.detector` itself (`ml/eval_decoder.py`,
`ml/results/decoder_*.json`):

| | This model (0.35 / 0.05) | Previous model at its shipped defaults (0.25 / 0.25) |
|---|---|---|
| Metal recall | **12/29 (41 %)** | 2/29 (7 %) |
| False metal flags | 6/121 (5.0 %) | 0/121 |
| Glass/organic recall | 3/11 | 1/11 |
| False escalate on clean images | **8/112 (7.1 %)** | 27/112 (24.1 %) |

Ultralytics predict on the same images gives 13/29, 6/121, 3/11 and 7/112 for this model
(`ml/results/val_yolo26s_e26l_tacotest.json`); the one-image differences come from Pillow vs
OpenCV resizing. 41 % metal recall in cluttered scenes is better, not good: a truck bed of mixed
RDF is still a different domain, so the detector stays a second opinion that can only hold a truck.

**80 benchmark images**, image-level rule "metal if any metal box has conf ≥ t"
(`ml/results/finetuned_summary_yolo26s_e26l_nmsfree.json`):

| t | Metal recall | False metal flags |
|---|---|---|
| 0.05 | 18/20 | 3/60 |
| 0.25 | 18/20 | 0/60 |
| 0.35 (default) | 18/20 | 0/60 |
| 0.50 | 17/20 | 0/60 |

The previous model also scored 18/20 with 0/60 at 0.25. The decoder and Ultralytics agree on
the detector verdict for 80/80 images.

### On an AMD Radeon GPU (DirectML)

The same file through the production decoder (`lynceus.detector._Model`: letterbox,
inference, box decode) on the 80 benchmark images, onnxruntime-directml 1.24.4, Ryzen 5 8645HS
laptop (`ml/results/bench_dml_lynceus-yolo26s-realwaste-taco.json`):

| Provider | Device | p50 | p90 |
|---|---|---|---|
| DmlExecutionProvider | AMD Radeon 760M iGPU (device_id 0) | 44.1 ms | 55.1 ms |
| CPUExecutionProvider | Ryzen 5 8645HS, 2 intra-op threads | 440.5 ms | 572.4 ms |

The two agree: 80/80 images with the same top label, max top-confidence difference 0.0. The
architecture is unchanged, so speed is too: run back to back on the same (busy) laptop, the
previous and this model both measured 44–57 ms on DirectML and 340–500 ms on the CPU. On a quiet
laptop the previous model measured 27.9 ms / 262.7 ms
(`ml/results/bench_dml_lynceus-yolo26s-realwaste.json`). Reproduce (Windows, a venv with
`onnxruntime-directml`, numpy and Pillow):

    python ml/bench_dml.py --onnx backend/models/lynceus-yolo26s-realwaste-taco.onnx

### Fusion what-if on the recorded 2026-10-13 MiniCPM-V run

`python -m benchmark.rescore --hybrid --run-detector` (summary in
`backend/benchmark/results/2026-10-16.hybrid-rescore.realwaste-taco.summary.json`): the same
80 VLM outputs with the detector fused in. The decision rule never lets the detector reject or
accept on its own; it can only hold a truck for a human.

| Variant | Clean loads accepted | Review rate | Metal rejected | Metal accepted | Escalate recall | Verdict = expected |
|---|---|---|---|---|---|---|
| VLM only | 35/40 | 21/80 | 19/20 (precision 0.90) | 1 | 17/20 | 71/80 |
| Hybrid, previous model, 0.25 / 0.25 | 35/40 | 24/80 | 19/20 | 0 | 19/20 | 73/80 |
| **Hybrid, this model, 0.35 / 0.05** | 33/40 | 26/80 | 19/20 | 0 | 19/20 | 71/80 |
| Hybrid, this model, light escalation off | 35/40 | 22/80 | 19/20 | 0 | 17/20 | 71/80 |
| Detector-only degraded | 0/40 | 80/80 | 0/20 | 0 | 20/20 | 20/80 |

On these in-domain images the new model is as safe as the previous one (no metal load accepted)
and costs two extra manual checks: the low light threshold holds `cardboard_1.jpg` (organic
0.07) and `textile_trash_280.jpg`, which the vision model accepted correctly. That is the price
of the 0.05 light threshold the val rule picked; on cluttered TACO scenes the same model raises
3.4× fewer false escalations than the previous one at its defaults. An operator who prefers fewer
holds sets `DETECTOR_LIGHT_CONF` higher (or `DETECTOR_ESCALATE_LIGHT=0`), ideally after
calibrating on their own gate photos.

## Reproduce

Everything is in `ml/` (see `ml/README.md` and `ml/COLAB_TRAINING.md`):
`bash ml/colab_train.sh` on a Colab GPU (fetches RealWaste and TACO, pseudo-labels, trains,
selects on val), then locally `ml/eval_val.py`, `ml/eval_finetuned.py --nms-free`,
`ml/export_onnx.py --weights ml/runs/yolo26s_e26l/weights/best.pt --out yolo26s_e26l.onnx`,
copy `ml/weights/yolo26s_e26l.onnx` here under this name, then `ml/eval_decoder.py`.

## Configuration

* `DETECTOR_MODEL_PATH`: unset = this bundled file when it exists (source checkout); set to an
  empty string to turn the detector off. The container sets it to
  `/app/backend/models/lynceus-yolo26s-realwaste-taco.onnx`.
* `DETECTOR_HARD_CONF` (default 0.35), `DETECTOR_LIGHT_CONF` (default 0.05),
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
  Records written by the previous model keep its name (`yolo26s-realwaste`), digest and
  thresholds, so old and new records stay distinguishable.
