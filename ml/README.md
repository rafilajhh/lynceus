# Lynceus detector track (`ml/`)

This folder holds an object detector that could run as a CPU-only first stage in front of the
VLM gate. It flags metal (reject) and glass/organics (escalate) from one photo.
It contains scripts, small JSON results, and a Colab notebook. Weights, data, venv and caches are
git-ignored (`ml/.venv/`, `ml/.cache/`, `ml/data/`, `ml/runs/`, `ml/weights/`).

**Read the caveats section before using any number below.** Every result comes from 80 RealWaste
photos. Each photo shows one item on the same concrete floor. A truck bed at a cement-plant gate is
a different domain.

## Update 2026-10-17: the retrained detector is in production

The Colab run (`colab_train.sh`, run `yolo26s_e26l`: YOLO26s on RealWaste pseudo-boxes + TACO
human boxes) replaced the bundled model. It is `backend/models/lynceus-yolo26s-realwaste-taco.onnx`
with defaults hard 0.35 / light 0.05, both picked on val by the rule in `eval_val.py`.
Full model card: `backend/models/README.md`; plain-language summary and rollback:
`docs/detector-update-2026-10-17.md`.

| | New (0.35 / 0.05) | Previous (0.25 / 0.25, its shipped defaults) |
|---|---|---|
| val mAP50 (RealWaste val + TACO val) | **0.712** | 0.519 |
| TACO test metal recall (production decoder) | **12/29** | 2/29 |
| TACO test false escalate on clean images | **8/112** | 27/112 |
| TACO test false metal flags | 6/121 | 0/121 |
| 80 benchmark: metal recall / false metal | 18/20 / 0/60 | 18/20 / 0/60 |
| Hybrid replay: metal accepted / review rate / verdict = expected | 0 / 26/80 / 71/80 | 0 / 24/80 / 73/80 |

Better out of domain, the same in domain, with two extra manual checks on the 80 benchmark
images from the low light threshold. YOLO26m from the same run is still training; it replaces
this one only if it wins on val by the same rule.

## Update 2026-10-16: val calibration, out-of-domain check

**Thresholds on a val split, not the test set.** `eval_val.py` scores the production model
(`yolo26s_realwaste`) at image level on the 416-image val split. These images were never trained
on, and they are not the 80 benchmark images. Full sweep: `results/val_yolo26s_realwaste_e26s.json`.

| t | Metal recall | False metal flags | Glass/organic recall | False escalate (clean) |
|---|---|---|---|---|
| 0.05 | 96.1 % | 0.9 % | 100 % | 7.0 % |
| 0.25 (its default then) | 85.7 % | 0.3 % | 95.2 % | 2.8 % |

Because the detector can only hold a truck for a human, a lower hard threshold costs little.

**Out of domain, the production model mostly fails.** We scored it on the TACO test split: 150
real-world litter photos with human-drawn boxes, of which 29 hold metal.
Result file: `results/val_prod_yolo26s_tacotest_local.json`, scored on CPU.

| t (hard / light) | Metal recall | False metal flags | mAP50 | False escalate (clean) |
|---|---|---|---|---|
| 0.05 / 0.1 | **13.8 % (4/29)** | 3.3 % | 0.044 | 40.2 % |

The in-domain 18/20 says the model learned RealWaste, which is one item on a concrete floor. It
does not hold for cluttered scenes. That is caveat 1 below, now measured.

**The fix (trained since; see the 2026-10-17 update above).** `COLAB_TRAINING.md` and
`colab_train.sh` run the new training:
- data: RealWaste pseudo-labelled with YOLOE-26l, plus TACO train/val with human boxes
  (`fetch_taco.py`);
- models: YOLO26s, m and l, with the production model as the baseline;
- selection on val only (`select_model.py`), then one read each of the RealWaste benchmark and the
  TACO test split.

## Results (80 held-out benchmark images: 20 Metal, 20 escalate, 40 accept)

Image-level metal rule: flag metal if any metal box has `conf >= t`. The rule is the same for every
model. For zero-shot, the metal labels are metal can, metal scrap, metal sheet, metal pipe,
aluminium foil and gas cylinder. Tyre, battery and rock are prompted but do not count as metal.
Zero-shot rows use Ultralytics' default `predict` (one-to-many head + NMS).

| Model | t | Metal recall | False metal flags (of 60) | Metal precision | Gate verdict correct |
|---|---|---|---|---|---|
| YOLOE-26s zero-shot, contaminant prompts | 0.10 | 17/20 | 26/60 | 39.5 % | n/a |
| YOLOE-26s zero-shot, contaminant prompts | 0.20 | 11/20 | 10/60 | 52.4 % | n/a |
| YOLOE-26s zero-shot, + distractor prompts | 0.10 | 14/20 | 13/60 | 51.9 % | n/a |
| YOLOE-26s zero-shot, + distractor prompts | 0.20 | 8/20 | 6/60 | 57.1 % | n/a |
| YOLOE-26m zero-shot, contaminant prompts | 0.20 | 15/20 | 28/60 | 34.9 % | n/a |
| **YOLO26s fine-tuned, NMS-free head (as exported)** | 0.10 | **18/20** | **0/60** | 100 % | 78/80 |
| YOLO26s fine-tuned, NMS-free head | 0.25 | 18/20 | 0/60 | 100 % | 77/80 |
| YOLO26s fine-tuned, NMS-free head | 0.50 | 16/20 | 0/60 | 100 % | 75/80 |
| YOLO26s fine-tuned, one-to-many head + NMS | 0.25 | 17/20 | 0/60 | 100 % | 77/80 |
| YOLO26s fine-tuned ONNX via `onnx_infer.py` | 0.25 | 18/20 | 0/60 | 100 % | n/a |

Zero-shot false flags by category at t=0.1 (contaminant prompts): Glass 5/7, Food Organics 3/7,
Vegetation 1/6, Paper 3/10, Cardboard 5/10, Plastic 5/10, Textile 4/10.
Zero-shot YOLOE does not work as a metal gate on these photos. No threshold gives both useful
recall and a tolerable false-flag rate. The full sweeps are in `results/zeroshot_summary_*.json`.

Fine-tuned YOLO26s, NMS-free, t=0.25:

* Escalate view (any glass/organic box): Glass 7/7, Food Organics 6/7, Vegetation 6/6.
  Paper, Cardboard, Plastic and Textile get 0 of 40 escalate flags.
* Gate view (reject if metal, else escalate if glass/organic, else accept): 77/80 correct.
  The 3 errors are 1 metal→accept, 1 metal→escalate and 1 food-organics→accept.
* Top-1 class confusion:
  * Metal: metal 18, paper 1, glass 1.
  * Textile: textile 8, paper 2.
  * Every other category is correct (cardboard maps to `paper` by design).
* Missed metal items:
  * `metal_313.jpg`: a paper-wrapped composite drinks canister, predicted paper 0.76.
  * `metal_664.jpg`: a white-painted metal bucket, predicted glass 0.19.

  Both are plausible failure modes at a real gate as well.
* Fine-tune val split (416 images, pseudo-boxes): mAP50 0.892, mAP50-95 0.830. Plastic is the
  weakest class (mAP50 0.73).

ONNX export (`ml/weights/yolo26s_realwaste.onnx`):

* fp32, opset 18, input 640×640, NMS-free output `(1, 300, 6)`. File size 38.2 MB.
* onnxruntime 1.31 CPUExecutionProvider on a Ryzen 5 8645HS. Latency includes file open,
  letterbox and decode, over the 80 images.
* p50 is **154 ms** with 6 intra-op threads and 218-292 ms with ORT default threads.
  The laptop was under about 70 % background CPU load, so treat these as upper bounds.
* Parity with Ultralytics on 5 images: every box matched at IoU >= 0.9 with the same label.
  The largest confidence difference was 0.0006.
* For comparison, the zero-shot YOLOE-26s exported with baked prompts
  (`yoloe26s_contaminants.onnx`, 41.8 MB) runs at a p50 of 421 ms.

### Recommendation

Use the fine-tuned YOLO26s (`yolo26s_realwaste.onnx`) as the detector stage, with these limits:

* Treat it as an in-domain metal/escalate pre-filter that sends cases to the VLM. It is not a
  standalone verdict.
* Calibrate t on gate photos first. The 0.1 to 0.25 band above was read off the test set itself,
  so it is optimistic.

Zero-shot YOLOE is not usable as a metal gate at this point. With 14-17 of 20 metal recalled, it
also false-flags 13 to 26 of the 60 non-metal images.

## Caveats (honest limits)

1. **In-domain test.** Training and benchmark images come from the same RealWaste photo sessions:
   the same floor, the same camera and one item per frame. The 18/20 with 0/60 result shows the
   model learned RealWaste. It does not show the model works on a truck load of mixed RDF. Expect
   a large drop on real gate imagery until the model is fine-tuned on that imagery.
2. **Weak labels.** The boxes come from YOLOE pseudo-labels, not from human annotation (see the
   protocol below). Box quality is unverified, and image-level class accuracy is what was
   measured.
3. **Thresholds picked on the test set.** The sweep is reported in full so this choice is visible.
   No threshold was tuned on a separate split.
4. **Small n.** With 20 metal images, one miss moves recall by 5 points. A 95 % Wilson interval on
   18/20 is roughly 70-97 %. At t=0.05 the NMS-free model reaches 20/20 with 0/60 false metal
   flags, but it also escalates 2 accept items. That is exactly the kind of test-set threshold
   picking this caveat warns against.
5. **Near-duplicates.** Benchmark files and training files are different photos.
   `check_leakage.py` computes a dHash nearest neighbour for each benchmark image:
   * No exact duplicates were found.
   * The closest matches (Hamming 4-7) are mostly different objects on the same floor, often from
     another class.
   * A visual spot check of the closest same-class pairs and of numeric neighbours (for example
     `metal_508` against `Metal_507/509`, `paper_251` against `Paper_252/292`) showed different
     items.

   This was a spot check, not proof.

## Held-out protocol

`common.benchmark_zip_names()` loads `backend/benchmark/prepare_images.py` and calls its `select()`
on the same RealWaste zip. It then asserts that the slugged names exactly equal the 80 rows of
`backend/benchmark/manifest.csv`, and those 80 zip members are excluded from training.

The training pool:

* 4177 images from the 8 benchmark classes. Miscellaneous Trash is unused.
* Mapped to 6 detector classes: metal, glass, organic (Food Organics + Vegetation),
  paper (Paper + Cardboard), plastic, textile.
* Every 10th image per class, sorted by name, goes to val: 3761 train and 416 val.

Pseudo-boxes (`build_dataset.py`, stats in `results/pseudo_label_stats.json`): YOLOE-26s runs on
each image with text prompts for all six materials. The box is chosen in this order:

1. the most confident box whose prompt belongs to the folder's class (2005 images);
2. otherwise the largest box of any prompt, which is the salient object (1949 images);
3. otherwise the whole frame with a 2 % margin (223 images).

The label is always the folder class.

## Reproduce (Windows, from the repo root)

Every script imports `_env.py`. It pins pip, torch, HF, Ultralytics and temp caches under
`ml/.cache` and points Ultralytics' working directory at `ml/weights`.

```
python -m venv ml/.venv
ml/.venv/Scripts/python ml/setup_env.py            # torch 2.6 cu124 + ultralytics 8.4.x, onnx, onnxruntime
python -I ml/fetch_realwaste.py                     # ~690 MB zip -> ml/data/zip/realwaste.zip (read in place)
ml/.venv/Scripts/python ml/eval_zeroshot.py --model yoloe-26s-seg.pt     # task 1 (~1 min on RTX 3050)
ml/.venv/Scripts/python ml/build_dataset.py --model yoloe-26s-seg.pt     # pseudo-labels (~3 min)
ml/.venv/Scripts/python ml/check_leakage.py
ml/.venv/Scripts/python ml/train.py --model yolo26s.pt --epochs 40 --batch 16 --hours 1.0
ml/.venv/Scripts/python ml/eval_finetuned.py --nms-free                 # and without --nms-free
ml/.venv/Scripts/python ml/export_onnx.py --weights ml/runs/yolo26s_realwaste/weights/best.pt --out yolo26s_realwaste.onnx
ml/.venv/Scripts/python ml/bench_onnx.py --onnx yolo26s_realwaste.onnx --pt ml/runs/yolo26s_realwaste/weights/best.pt --threads 6
ml/.venv/Scripts/python ml/onnx_infer.py ml/weights/yolo26s_realwaste.onnx backend/benchmark/images/metal_1.jpg
```

On Linux, use `ml/.venv/bin/python`. On Colab, use `colab_finetune.ipynb` or
`bash ml/colab_train.sh`. Either one runs the full RealWaste + TACO pipeline, as described in
`COLAB_TRAINING.md`.

Training ran on an RTX 3050 6 GB Laptop GPU with batch 16, imgsz 640, workers 2 and AMP. It used
about 4.8 GB of GPU memory. The 1 h time cap stopped it at 28 epochs, about 2.1 min per epoch.

## Files

| File | Purpose |
|---|---|
| `_env.py`, `common.py` | Cache pinning; manifest, held-out list, zip access, metal metrics |
| `setup_env.py`, `fetch_realwaste.py` | Dependencies; dataset download |
| `eval_zeroshot.py` | Task 1: YOLOE-26 text-prompt baseline and threshold sweep |
| `build_dataset.py`, `check_leakage.py`, `train.py`, `eval_finetuned.py` | Task 2 |
| `export_onnx.py`, `bench_onnx.py`, `onnx_infer.py` | Task 3; `onnx_infer.py` needs only onnxruntime + numpy + Pillow |
| `fetch_taco.py` | TACO download and mapping to the 6 classes; id-based train/val/test split |
| `eval_val.py`, `select_model.py` | Image-level val scoring per source, val-only thresholds and model selection |
| `colab_train.sh`, `COLAB_TRAINING.md`, `colab_finetune.ipynb` | One-command Colab GPU run and its rules |
| `eval_decoder.py` | Production decoder (`lynceus.detector`, ONNX) on the TACO test split, and its verdict vs Ultralytics on the 80 images; backend venv only |
| `results/val_<tag>.json`, `results/val_<tag>_tacotest*.json` | Val sweeps and selected thresholds; TACO test at those thresholds |
| `results/decoder_*.json` | `eval_decoder.py` output per ONNX model |
| `results/zeroshot_yoloe.json` | Per-image YOLOE-26s detections (contaminant prompts, conf >= 0.05, normalised xyxy) |
| `results/zeroshot_yoloe_distractors.json`, `results/zeroshot_yoloe_26m-seg*.json` | Other prompt sets and the m model |
| `results/finetuned_yolo26s_realwaste[_nmsfree].json` | Per-image fine-tuned detections |
| `results/*summary*.json`, `results/onnx_bench_*.json` | Sweeps, confusion, latency, parity |
| `results/pseudo_label_stats.json`, `results/leakage_check.json`, `results/train_*_results.csv` | Data provenance and the training curve |

## Licences and provenance

* **RealWaste.** By Single, Iranmanesh and Raad (University of Wollongong). UCI ML Repository id
  908, DOI 10.24432/C5SS4G. The two licence statements disagree:
  * the UCI page states **CC BY 4.0**;
  * the README inside the zip (`realwaste-main/README.md`) states **CC BY-NC-SA 4.0**.

  Until the authors clarify, treat the stricter terms (non-commercial, share-alike) as binding for
  the dataset and, conservatively, for weights trained on it. See
  `backend/benchmark/images/ATTRIBUTION.md`.
* **Ultralytics** (YOLO26, YOLOE-26, training and export code) is **AGPL-3.0**. Shipping the
  pretrained or fine-tuned weights inside a network service triggers AGPL source-availability
  obligations unless an Ultralytics Enterprise licence is bought. `onnx_infer.py` is our own code
  and does not import Ultralytics, but the weights are still Ultralytics-derived.
* The MobileCLIP2 text encoder (`mobileclip2_b.ts`) is downloaded by YOLOE for prompt embedding.
  It is needed only for the zero-shot path, not for the fine-tuned ONNX.
* **TACO** (Proença and Simões, github.com/pedropro/TACO): annotations are **CC BY 4.0**. The
  photos are hosted on Flickr. `fetch_taco.py` downloads them at run time; no TACO image is
  committed.
