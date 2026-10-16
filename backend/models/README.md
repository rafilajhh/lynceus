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
| Architecture | Ultralytics YOLO26s, fine-tuned from `yolo26s.pt` (`ml/colab_train.sh`: early stop with patience 25 stopped it after 66 epochs, best epoch 41; cosine LR, seed 0, deterministic, Ultralytics 8.4.177) |
| Training data | RealWaste train split with YOLOE-26l pseudo-boxes, plus TACO train (1,200 images) with human boxes (`ml/build_dataset.py --with-taco`) |
| Export | fp32, opset 18, input 1×3×640×640, `nms=False`: NMS-free end-to-end output `(1, 300, 6)` = x0, y0, x1, y1, conf, cls in letterboxed pixels |
| Classes (ONNX metadata) | metal, glass, organic, paper, plastic, textile |
| Gate mapping | metal → hard contaminant `metal`; glass → `glass`, organic → `organic_residue` (light); paper, plastic, textile are RDF feedstock and never flag a load |
| Default thresholds | `DETECTOR_HARD_CONF` 0.35, `DETECTOR_LIGHT_CONF` 0.05, picked on the val split (below) |
| Runtime | onnxruntime + numpy + Pillow; no torch, no Ultralytics at run time. CPU-only (`CPUExecutionProvider`) |

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

Three splits, each with its own job.

| Split | Images | Used for |
|---|---|---|
| val: RealWaste val (every 10th image per class) + TACO val (image id % 10 = 8) | 416 + 150 | early stopping and checkpoint choice during training, then the thresholds |
| TACO test (image id % 10 = 9): real-world litter scenes, human boxes, 29 hold metal | 150 | out-of-domain check |
| RealWaste benchmark (`backend/benchmark/manifest.csv`: 20 Metal, 20 escalate, 40 accept) | 80 | in-domain check, and the hybrid replay |

None of them was trained on. val is **not** an untouched split, though: training used it to stop
early and keep the best epoch, and the thresholds were then picked on it. The 80 benchmark images
are excluded from training by name (`ml/common.py` re-runs the benchmark selection and asserts an
exact match); the TACO split is by image id.

**Threshold rule** (`ml/eval_val.py`): the hard threshold is the lowest t whose false-metal rate
is ≤ 2 % on RealWaste and ≤ 5 % on TACO; the light threshold is the lowest t whose false-escalate
rate on clean images is ≤ 5 % on RealWaste and ≤ 10 % on TACO. For this model that gives
hard 0.35, light 0.05 (`ml/results/val_yolo26s_e26l.json`). The rule was committed before this
model was trained; the per-source caps were written after the previous model had already been
scored on both test sets, so they are not blind to those sets. Two things to know about the
picks: light 0.05 is the lowest value on the grid (and the detector's own output floor), so the
cap never bound and the rule simply took the floor; and hard 0.35 rather than 0.30 was decided by
a single TACO val image.

**val** (566 images), Ultralytics predict:

| | This model (0.35 / 0.05) | Previous model (its val pick 0.15 / 0.30) |
|---|---|---|
| mAP50 / mAP50-95 | 0.712 / 0.642 | 0.519 / 0.466 |
| Metal recall, RealWaste | 68/77 (88 %) | 70/77 (91 %) |
| False metal, RealWaste | 4/339 (1.2 %) | 1/339 (0.3 %) |
| Metal recall, TACO | **10/31 (32 %)** | 0/31 |
| False metal, TACO | 3/119 (2.5 %) | 4/119 (3.4 %) |
| Glass/organic recall, RealWaste | 123/124 | 115/124 |
| False escalate on clean, TACO | 7/114 (6.1 %) | 11/114 (9.6 %) |

The mAP rows are not like for like: the RealWaste val boxes are YOLOE-26l pseudo-boxes, the same
labeller this model was trained on. The previous model, trained on another labeller's boxes,
scores 0.777 mAP50 on its own labeller's val boxes. Read the image-level rows instead.

### TACO test (150 images), through `lynceus.detector` itself

`ml/eval_decoder.py` (per-image rows in `ml/results/decoder_*.json`), paired statistics from
`ml/taco_robustness.py` (`ml/results/taco_test_robustness.json`). Brackets: Wilson 95 %
interval per count; for the change, a paired bootstrap 95 % interval and the exact McNemar p
against the previous model at its shipped defaults.

| | This model (0.35 / 0.05) | Previous, shipped (0.25 / 0.25) | Previous, its val pick (0.15 / 0.30) | Change vs shipped |
|---|---|---|---|---|
| Metal recall | **12/29** (41 %) [26, 59] | 2/29 (7 %) [2, 22] | 2/29 | **+34.5 pp** [+13.8, +55.2], p = 0.006 |
| False metal flags | 6/121 (5.0 %) [2.3, 10.4] | 0/121 [0, 3.1] | 1/121 | **+5.0 pp** [+1.7, +9.1], p = 0.031 |
| Glass/organic recall | 3/11 | 1/11 | 1/11 | +18 pp [−18, +55], p = 0.63 |
| False escalate on clean images | **8/112** (7.1 %) [3.7, 13.5] | 27/112 (24.1 %) [17.1, 32.8] | 23/112 | **−17.0 pp** [−26.8, −7.1], p = 0.001 |
| Clean images held for any reason (metal or glass/organic) | 12/112 (10.7 %) | 27/112 (24.1 %) | 24/112 | −13.4 pp [−23.2, −2.7], p = 0.020 |

* **Metal recall is the gain**, and it is large: 11 metal images newly caught, 1 lost.
* **False metal is a real regression.** The previous model raised none; this one raises 6 on
  121 non-metal images (p = 0.031; against the previous model's val pick it is 6 vs 1, p = 0.13).
  None of the six has a metal label in TACO: a drink carton, a glass bottle, plastic items and
  cigarette butts. A false metal flag holds the truck for a human; it never rejects one.
* **Fewer clean loads held overall**, even counting those six: 12/112 vs 27/112.
* Glass/organic recall rests on 11 images; the change is not significant.

**Leakage check.** TACO is split by image id, so the same scene can sit in train and test.
`ml/check_leakage.py` hashes every TACO test image (64-bit dHash) against all 1,350 TACO train
and val images, and separately against the train/val shots within two places in the same TACO
batch (same session). Only 2 test images have a near-duplicate (Hamming ≤ 10) and 2 a same-scene
neighbour (≤ 16); 3 in all. Without them (147 images) the result holds: metal recall 10/27 vs
2/27, +29.6 pp [+11.1, +48.1], p = 0.022; false metal 6/120 vs 0/120, p = 0.031; false escalate
on clean 8/111 vs 27/111, p = 0.001. With a looser same-scene cut (≤ 20, 140 images left) the
metal gain is 9/24 vs 2/24, p = 0.039. What this check cannot rule out is that every test photo
shares photographers, places and cameras with training photos; TACO test is out of domain for
RealWaste, not for TACO.

Ultralytics predict on the same images gives 13/29, 6/121, 3/11 and 7/112 for this model
(`ml/results/val_yolo26s_e26l_tacotest.json`); the one-image differences come from Pillow vs
OpenCV resizing. 41 % metal recall in cluttered scenes is better, not good: a truck bed of mixed
RDF is still a different domain, so the detector stays a second opinion that can only hold a truck.

### 80 benchmark images

Image-level rule "metal if any metal box has conf ≥ t"
(`ml/results/finetuned_summary_yolo26s_e26l_nmsfree.json`):

| t | Metal recall | False metal flags |
|---|---|---|
| 0.05 | 18/20 | 3/60 |
| 0.25 | 18/20 | 0/60 |
| 0.35 (default) | 18/20 | 0/60 |
| 0.50 | 17/20 | 0/60 |

The previous model also scored 18/20 with 0/60 at 0.25; on 80 images neither difference is
measurable. The decoder and Ultralytics agree on the detector verdict for 80/80 images, for both
models.

### CPU latency

`lynceus.detector` end to end (Pillow decode with JPEG draft, letterbox, onnxruntime, box decode),
2 intra-op threads (the default), the 80 benchmark images twice after a warm-up, on a laptop
Ryzen 5 8645HS: **p50 218 ms, p90 233 ms**; the previous model on the same run 231 ms / 398 ms.
Same architecture, same cost.

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
of the 0.05 light threshold the val rule picked. An operator who prefers fewer holds sets
`DETECTOR_LIGHT_CONF` higher (or `DETECTOR_ESCALATE_LIGHT=0`), ideally after calibrating on
their own gate photos.

## Reproduce

Everything is in `ml/` (see `ml/README.md` and `ml/COLAB_TRAINING.md`):
`bash ml/colab_train.sh` on a Colab GPU (fetches RealWaste and TACO, pseudo-labels, trains,
selects on val), then locally `ml/eval_val.py`, `ml/eval_finetuned.py --nms-free`,
`ml/export_onnx.py --weights ml/runs/yolo26s_e26l/weights/best.pt --out yolo26s_e26l.onnx`,
copy `ml/weights/yolo26s_e26l.onnx` here under this name, then `ml/eval_decoder.py`,
`ml/check_leakage.py` and `ml/taco_robustness.py`.

## Configuration

* `DETECTOR_MODEL_PATH`: unset = this bundled file when it exists (source checkout); set to an
  empty string to turn the detector off. The container sets it to
  `/app/backend/models/lynceus-yolo26s-realwaste-taco.onnx`.
* `DETECTOR_HARD_CONF` (default 0.35), `DETECTOR_LIGHT_CONF` (default 0.05),
  `DETECTOR_ESCALATE_LIGHT` (default 1). The defaults live in one place
  (`config.DEFAULT_DETECTOR_HARD_CONF` / `DEFAULT_DETECTOR_LIGHT_CONF`); leave the variables
  unset so a model update brings its own thresholds.
* `DETECTOR_THREADS` (default 2): onnxruntime intra-op threads per run; at most two runs at
  once, and a run waits up to 30 s for a slot (scripted demo requests take only an idle slot, so
  they never delay a live inspection). Only JPEG (including phone MPO) and PNG are decoded.
  Photos over 40 MP (PNG: 16 MP, which has no reduced-scale decode) are refused before decoding,
  JPEGs are decoded at a reduced scale (no smaller than 1280 px a side), and a Pillow
  decompression-bomb warning is an error.
* The detector runs on the CPU (`CPUExecutionProvider`); the container image ships CPU
  onnxruntime. The result's `runtime` names the provider actually used
  (`onnxruntime-cpu`); startup logs it.
* Every detector result (and the audit record) carries the file's `model_sha256` and the
  `thresholds` it was judged with; the reported `model` is the file name without `lynceus-`.
  Records written by the previous model keep its name (`yolo26s-realwaste`), digest and
  thresholds, so old and new records stay distinguishable.
