# Bundled detector model

`lynceus-yolo26m-realwaste-taco.onnx` is the CPU object detector behind `lynceus.detector`: the
second opinion next to the vision-language model, and the only AI left running when the
shared AMD endpoint is down (detector-only degraded mode, which always holds the truck for a
human). It replaced `lynceus-yolo26s-realwaste-taco.onnx` (same data, smaller model) on
2026-10-17, which had replaced `lynceus-yolo26s-realwaste.onnx` the same day. The
comparisons below say why; to roll back, point `DETECTOR_MODEL_PATH` (and the
thresholds) at the earlier file.

| | |
|---|---|
| File | `lynceus-yolo26m-realwaste-taco.onnx`, 81.7 MB, sha256 `1774f838b8db6053d692d325d4d9b395ce31c51bbb2e198a22d3c1445888418a` |
| Source | `ml/weights/yolo26m_e26l.onnx` (`ml/export_onnx.py` from the Colab run `yolo26m_e26l`, `best.pt`), copied byte for byte |
| Architecture | Ultralytics YOLO26m, fine-tuned from `yolo26m.pt` (`ml/colab_train.sh`, batch 16; cosine LR; seed 0 and deterministic by Ultralytics 8.4.177 defaults) |
| Training state | **Unfinished.** The run's 2 h cap set a 41-epoch budget; Colab's GPU quota ended it after epoch 25. `best.pt` is epoch 21 (Ultralytics' own pick by val fitness). The cosine schedule did not reach its end and the last-10-epoch no-mosaic phase never ran |
| Training data | RealWaste train split with YOLOE-26l pseudo-boxes, plus TACO train (1,200 images) with human boxes (`ml/build_dataset.py --with-taco`); the same data as the YOLO26s it replaced |
| Export | fp32, opset 18, input 1×3×640×640, `nms=False`: NMS-free end-to-end output `(1, 300, 6)` = x0, y0, x1, y1, conf, cls in letterboxed pixels |
| Classes (ONNX metadata) | metal, glass, organic, paper, plastic, textile |
| Gate mapping | metal → hard contaminant `metal`; glass → `glass`, organic → `organic_residue` (light); paper, plastic, textile are RDF feedstock and never flag a load |
| Default thresholds | `DETECTOR_HARD_CONF` 0.35, `DETECTOR_LIGHT_CONF` 0.05, picked on the val split (below); the same values the rule picked for the YOLO26s |
| Runtime | onnxruntime + numpy + Pillow; no torch, no Ultralytics at run time. CPU-only (`CPUExecutionProvider`) |

## Licences

These weights are **not** covered by the repository's MIT licence; `NOTICE` in this directory
is the binding statement (including the offer of corresponding source in `ml/` and what
commercial use requires).

* **Ultralytics (AGPL-3.0).** YOLO26, the training code and the exporter are AGPL-3.0, and these
  weights are derived from Ultralytics' pretrained YOLO26m. `lynceus.detector` is our own decoder
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

## How it was chosen

Three splits, each with its own job.

| Split | Images | Used for |
|---|---|---|
| val: RealWaste val (every 10th image per class) + TACO val (image id % 10 = 8) | 416 + 150 | early stopping and checkpoint choice during training, then the thresholds and the model |
| TACO test (image id % 10 = 9): real-world litter scenes, human boxes, 29 hold metal | 150 | out-of-domain check |
| RealWaste benchmark (`backend/benchmark/manifest.csv`: 20 Metal, 20 escalate, 40 accept) | 80 | in-domain check, and the hybrid replay |

None of them was trained on; val was used for early stopping and checkpoint choice, so it is
not untouched. The 80 benchmark images are excluded from training by name; the TACO split is by
image id.

**Threshold rule** (`ml/eval_val.py`): the hard threshold is the lowest t whose false-metal rate
is ≤ 2 % on RealWaste and ≤ 5 % on TACO; the light threshold is the lowest t whose false-escalate
rate on clean images is ≤ 5 % on RealWaste and ≤ 10 % on TACO. The rule was committed before
either RealWaste+TACO model was trained (the per-source caps were written after the RealWaste-only
model had been scored on both test sets). For this model it gives hard 0.35 (at 0.30 RealWaste
false metal is 8/339, over the 2 % cap) and light 0.05, the lowest value on the grid, so the light
cap never bound.

**Model rule** (`ml/select_model.py`, written before training): rank by val metal recall at the
model's own hard threshold, then val light recall, then val mAP50-95; the winner ships, and the
test sets are read only afterwards, without changing the choice. Ranking
(`ml/results/selection.json`):

| val, Ultralytics predict | YOLO26m `best.pt` (epoch 21) | YOLO26s (previous) | YOLO26m `last.pt` (epoch 25) |
|---|---|---|---|
| Thresholds picked (hard / light) | 0.35 / 0.05 | 0.35 / 0.05 | 0.50 / 0.20 |
| Metal recall, pooled | **0.815** | 0.722 | 0.759 |
| Metal recall, RealWaste / TACO | 69/77 / **19/31** | 68/77 / 10/31 | 66/77 / 16/31 |
| False metal, RealWaste / TACO | 6/339 / 3/119 | 4/339 / 3/119 | 1/339 / 3/119 |
| Glass/organic recall, RealWaste / TACO | 123/124 / 5/9 | 123/124 / 3/9 | 121/124 / 1/9 |
| False escalate on clean, RealWaste / TACO | 8/215 / 11/114 | 5/215 / 7/114 | 9/215 / 2/114 |
| mAP50 / mAP50-95 | 0.719 / 0.636 | 0.712 / 0.642 | 0.715 / 0.631 |

The win is the TACO val metal row (19/31 vs 10/31); it costs more false escalations on clean
images. The mAP numbers are not like for like with the RealWaste-only model (its val boxes come
from the labeller these models were trained on).

## What the test sets say (read once, after the choice)

### TACO test (150 images), through `lynceus.detector` itself

`ml/eval_decoder.py` (per-image rows in `ml/results/decoder_*.json`) and paired statistics from
`ml/taco_robustness.py`: bootstrap 95 % interval of the change and exact McNemar p.

| | YOLO26m (this) | YOLO26s (previous) | RealWaste-only (first), 0.25 / 0.25 |
|---|---|---|---|
| Metal recall | **14/29** (48 %) | 12/29 (41 %) | 2/29 (7 %) |
| False metal flags | 4/121 (3.3 %) | 6/121 (5.0 %) | 0/121 |
| Glass/organic recall | 2/11 | 3/11 | 1/11 |
| False escalate on clean images | 14/112 (12.5 %) | **8/112** (7.1 %) | 27/112 (24.1 %) |
| Clean images held for any reason | 16/112 | 12/112 | 27/112 |

* **Against the YOLO26s it replaced, nothing is significant**
  (`ml/results/taco_test_robustness_m_vs_s.json`): metal +2 images (+6.9 pp [−10.3, +24.1],
  p = 0.69), false metal −2 (p = 0.69), false escalate on clean +6 (+5.4 pp [−1.8, +12.5],
  p = 0.21). On this test set the two are indistinguishable; the val rule chose this one.
* **Against the RealWaste-only model** (`taco_test_robustness_m_vs_previous.json`): metal 14/29 vs
  2/29, +41.4 pp [+24.1, +58.6], p = 0.0005; false escalate on clean −11.6 pp [−22.3, −0.9],
  p = 0.041; false metal 4/121 vs 0/121, p = 0.13.
* **Leakage.** The same 3 TACO test images with a near-duplicate or same-scene shot in TACO
  train/val (`ml/check_leakage.py`) were dropped: metal 12/27 vs 10/27 (YOLO26s, p = 0.69) and vs
  2/27 (RealWaste-only, p = 0.002). Every test photo still shares photographers and places with
  TACO train.
* Ultralytics predict on the same images: 15/29, 5/121, 2/11, 11/112
  (`ml/results/val_yolo26m_e26l_tacotest.json`); the decoder and Ultralytics agree on the
  detector verdict for 80/80 benchmark images.

### 80 benchmark images

Image-level rule "metal if any metal box has conf ≥ t", from the per-image
`ml/results/finetuned_yolo26m_e26l_nmsfree.json`:

| t | YOLO26m metal recall | false metal | YOLO26s metal recall | false metal |
|---|---|---|---|---|
| 0.05 | 20/20 | 4/60 | 18/20 | 3/60 |
| 0.25 | 20/20 | 1/60 | 18/20 | 0/60 |
| 0.35 (default) | **20/20** | 1/60 (`plastic_645.jpg`) | 18/20 | 0/60 |
| 0.50 | 19/20 | 0/60 | 17/20 | 0/60 |

On 80 images neither difference is measurable.

### CPU latency

`lynceus.detector` end to end (decode, letterbox, onnxruntime, box decode), 2 intra-op threads,
the 80 benchmark images twice after a warm-up, laptop Ryzen 5 8645HS: **p50 635 ms, p90 676 ms**,
against 214 ms / 227 ms for the YOLO26s in the same run, about 3× slower. The detector runs beside
the vision and waybill calls (several seconds on the shared endpoint), so a gate verdict does not
wait longer; in detector-only degraded mode the hold comes about 0.4 s later.

### Fusion what-if on the recorded 2026-10-13 MiniCPM-V run

`python -m benchmark.rescore --hybrid --run-detector` (summary in
`backend/benchmark/results/2026-10-17.hybrid-rescore.realwaste-taco-m.summary.json`):

| Variant | Clean loads accepted | Review rate | Metal rejected | Metal accepted | Escalate recall | Verdict = expected |
|---|---|---|---|---|---|---|
| VLM only | 35/40 | 21/80 | 19/20 (precision 0.90) | 1 | 17/20 | 71/80 |
| Hybrid, RealWaste-only model, 0.25 / 0.25 | 35/40 | 24/80 | 19/20 | 0 | 19/20 | 73/80 |
| Hybrid, YOLO26s, 0.35 / 0.05 | 33/40 | 26/80 | 19/20 | 0 | 19/20 | 71/80 |
| **Hybrid, this model, 0.35 / 0.05** | 34/40 | 25/80 | 19/20 | 0 | 19/20 | 72/80 |
| Hybrid, this model, light escalation off | 35/40 | 22/80 | 19/20 | 0 | 17/20 | 71/80 |
| Detector-only degraded | 0/40 | 80/80 | 0/20 | 0 | 20/20 | 20/80 |

The detector holds `metal_40.jpg` (metal the vision model accepted), `glass_121.jpg` and
`food_organics_117.jpg` (correct escalations), and one clean load, `cardboard_231.jpg`; the
YOLO26s held two clean loads (`cardboard_1.jpg`, `textile_trash_280.jpg`).

**Read all of this as:** the val rule picked YOLO26m on cluttered-scene metal; the test sets
cannot tell it from the YOLO26s, and both are far ahead of the RealWaste-only model out of domain.
It is 3× slower on the CPU and twice the file size, and its training was cut short. Nothing here
comes from gate imagery: calibrate the thresholds on gate photos before trusting them.

## Reproduce

Everything is in `ml/` (see `ml/README.md` and `ml/COLAB_TRAINING.md`). From the Colab
checkpoint at `ml/runs/yolo26m_e26l_colab/weights/best.pt`:

    ml/.venv/Scripts/python ml/eval_val.py --weights ml/runs/yolo26m_e26l_colab/weights/best.pt --data ml/data/val_mix/data.yaml --tag yolo26m_e26l
    ml/.venv/Scripts/python ml/select_model.py yolo26s_e26l yolo26m_e26l yolo26m_e26l_last
    ml/.venv/Scripts/python ml/eval_val.py --weights ... --data ml/data/taco/data.yaml --split test --hard 0.35 --light 0.05 --tag yolo26m_e26l_tacotest
    ml/.venv/Scripts/python ml/eval_finetuned.py --weights ... --nms-free --tag yolo26m_e26l
    ml/.venv/Scripts/python ml/export_onnx.py --weights ... --out yolo26m_e26l.onnx

then copy `ml/weights/yolo26m_e26l.onnx` here under this name and run (backend venv):

    backend/.venv/Scripts/python ml/eval_decoder.py --ultralytics ml/results/finetuned_yolo26m_e26l_nmsfree.json
    backend/.venv/Scripts/python ml/taco_robustness.py --new ml/results/decoder_lynceus-yolo26m-realwaste-taco.json --old ml/results/decoder_lynceus-yolo26s-realwaste-taco.json --old-val-pick 0.35 0.05 --out ml/results/taco_test_robustness_m_vs_s.json
    backend/.venv/Scripts/python ml/taco_robustness.py --new ml/results/decoder_lynceus-yolo26m-realwaste-taco.json --old-val-pick 0.15 0.30 --out ml/results/taco_test_robustness_m_vs_previous.json

Without `--out` the script writes `ml/results/taco_test_robustness.json`, the YOLO26s vs
RealWaste-only report.

## Configuration

* `DETECTOR_MODEL_PATH`: unset = this bundled file when it exists (source checkout); set to an
  empty string to turn the detector off. The container sets it to
  `/app/backend/models/lynceus-yolo26m-realwaste-taco.onnx`.
* `DETECTOR_HARD_CONF` (default 0.35), `DETECTOR_LIGHT_CONF` (default 0.05),
  `DETECTOR_ESCALATE_LIGHT` (default 1). The defaults live in one place
  (`config.DEFAULT_DETECTOR_HARD_CONF` / `DEFAULT_DETECTOR_LIGHT_CONF`); leave the variables
  unset so a model update brings its own thresholds.
* `DETECTOR_THREADS` (default 2): onnxruntime intra-op threads per run; at most two runs at
  once, and a run waits up to 30 s for a slot (scripted demo requests never wait and hold at most
  one of the two, so a live inspection always keeps one). Only JPEG (including phone MPO) and PNG
  are decoded. Photos over 40 MP (PNG: 16 MP, which has no reduced-scale decode) are refused
  before decoding, JPEGs are decoded at a reduced scale (no smaller than 1280 px a side), and
  Pillow's own decompression-bomb error is a refusal (the 40 MP cap sits below Pillow's warning
  limit).
* The detector runs on the CPU (`CPUExecutionProvider`); the container image ships CPU
  onnxruntime. The result's `runtime` names the provider actually used
  (`onnxruntime-cpu`); startup logs it.
* Every detector result (and the audit record) carries the file's `model_sha256` and the
  `thresholds` it was judged with; the reported `model` is the file name without `lynceus-`
  (`yolo26m-realwaste-taco`). Records written by earlier models keep their name, digest and
  thresholds, so records from the three models stay distinguishable.
