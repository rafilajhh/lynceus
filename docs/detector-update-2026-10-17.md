# Hybrid CV gate and the retrained detector (2026-10-17)

What branch `feat/hybrid-cv` adds to Lynceus, why, what the numbers are, and how to check or
undo each part. Written for the reviewer of the PR; the model card with every table is
`backend/models/README.md`.

## Ringkasan (Bahasa Indonesia)

**Apa ini.** Selain VLM di AMD Token Factory, Lynceus sekarang menjalankan detektor objek
YOLO26s sendiri (file ONNX di `backend/models/`) pada foto yang sama. Detektor ini "pendapat
kedua": kalau ia melihat logam yang tidak dikonfirmasi VLM, truk **ditahan untuk dicek manusia**
(escalate). Ia **tidak pernah** menerima atau menolak muatan sendirian. Kalau VLM mati, detektor
tetap jalan dan semua truk ditahan untuk manusia (mode `detector_only_degraded`), bukan error 503.

**Kenapa ganti model.** Model pertama hanya dilatih di RealWaste (satu barang di lantai beton).
Diuji pada foto sampah dunia nyata yang berantakan (TACO), ia hanya menemukan 2 dari 29 foto
berisi logam. Model baru dilatih di Colab dengan RealWaste + TACO.

**Hasil utama (TACO test, 150 foto yang tidak pernah dipakai melatih atau memilih):**

| | Model baru | Model lama |
|---|---|---|
| Foto berisi logam yang tertangkap | **12/29** | 2/29 |
| Foto bersih yang salah ditahan (glass/organic palsu) | **8/112** | 27/112 |
| Foto tanpa logam yang ditandai logam | 6/121 | 0/121 |

Di 80 gambar benchmark (dalam domain) keduanya setara: logam 18/20, 0 alarm palsu.

**Harga yang dibayar.** Threshold light 0,05 (dipilih oleh aturan di data val, bukan disetel ke
benchmark) membuat 2 muatan bersih di benchmark ikut ditahan (`cardboard_1`, `textile_trash_280`).
Review rate naik dari 24/80 ke 26/80; metal lolos tetap 0. Kalau ingin lebih sedikit tahanan,
naikkan `DETECTOR_LIGHT_CONF` atau set `DETECTOR_ESCALATE_LIGHT=0`.

**AMD.** Detektor bisa jalan di GPU AMD Radeon lewat ONNX Runtime DirectML:
`DETECTOR_PROVIDERS=DmlExecutionProvider` (butuh paket `onnxruntime-directml`). Di Radeon 760M
laptop: p50 44 ms vs 440 ms di CPU, jawaban identik di 80/80 gambar. Docker tetap CPU.

**Yang perlu Rafi tahu dari merge `main`.** Vote mayoritas VLM milikmu (`VLM_VOTES=3`) sekarang
berjalan **paralel** di dalam fallback chain, jadi 3 read memakan waktu kira-kira 1 read (kalau
berurutan, p95 3×27,9 s bisa melewati budget 90 s). Catatan: `_vote_majority` membuang kontaminan
yang hanya dilihat 1 dari 3 read; detektor menutup sebagian celah itu.

**Rollback cepat:** lihat bagian 7. Tidak ada perubahan skema database atau API yang memaksa
migrasi; record lama tetap terbaca.

## 1. What the detector does

The decision rules (`backend/src/lynceus/decision.py`) treat the detector as a second opinion:

| Vision model says | Detector sees (at/above its threshold) | Verdict |
|---|---|---|
| metal, confidently | metal | reject (detector gate: passed, "agrees") |
| no metal | metal ≥ `DETECTOR_HARD_CONF` | **escalate_human** (never reject) |
| no glass/organic | glass/organic ≥ `DETECTOR_LIGHT_CONF` | **escalate_human** while `DETECTOR_ESCALATE_LIGHT=1` |
| anything | nothing, or only paper/plastic/textile | the vision model's verdict stands |
| unavailable (`LYNCEUS_ALLOW_STUB_FALLBACK=0`) | anything | `detector_only_degraded`: always escalate_human, findings listed; refuse if a mandatory input is missing |

The detector never turns an accept into a reject or a reject into an accept. A vision answer
from a fallback model outside `VLM_BENCHMARKED_MODELS` cannot accept or reject either.

Every record stores the detector's boxes, `model`, `runtime` (`onnxruntime-cpu`,
`onnxruntime-directml`, ...), latency, the weights' `model_sha256` and the `thresholds` used.
The UI draws its boxes dashed with a "YOLO" tag, shows a sixth gate "Detector second opinion",
and a degraded banner when the vision model was down.

## 2. The new model

| | |
|---|---|
| File | `backend/models/lynceus-yolo26s-realwaste-taco.onnx`, sha256 `c84f795a…20bf5405` |
| Trained | Colab GPU, `ml/colab_train.sh`: YOLO26s from `yolo26s.pt`, 81 epochs (early stop, patience 25), cosine LR, seed 0, deterministic |
| Data | RealWaste train (3,761 images, YOLOE-26l pseudo-boxes) + TACO train (human boxes) |
| Held out | RealWaste val (416), TACO val (150), TACO test (150), the 80 benchmark images |
| Thresholds | hard 0.35, light 0.05: the rule in `ml/eval_val.py`, fixed before any test read |

Threshold rule: the lowest hard threshold whose false-metal rate on val is ≤ 2 % (RealWaste) and
≤ 5 % (TACO); the lowest light threshold whose false-escalate rate on clean val images is ≤ 5 % /
≤ 10 %. Checks run on the received checkpoint before use: its pickle imports only
torch/ultralytics classes, its recorded val mAP (0.7108) matches our local val (0.7121), and its
training arguments match `colab_train.sh`.

Results (all in `ml/results/`):

| Check | New | Previous | File |
|---|---|---|---|
| val mAP50 / mAP50-95 | 0.712 / 0.642 | 0.519 / 0.466 | `val_yolo26s_e26l.json`, `val_prod_yolo26s.json` |
| TACO test, production decoder: metal / false metal / false escalate clean | 12/29 / 6/121 / 8/112 | 2/29 / 0/121 / 27/112 | `decoder_*.json` |
| 80 benchmark: metal / false metal (t = default) | 18/20 / 0/60 | 18/20 / 0/60 | `finetuned_summary_*_nmsfree.json` |
| Decoder vs Ultralytics verdict, 80 images | 80/80 | 80/80 | `decoder_*.json` |
| DirectML vs CPU top label, 80 images | 80/80 | 80/80 | `bench_dml_*.json` |

Hybrid replay of the recorded 2026-10-13 MiniCPM-V run
(`backend/benchmark/results/2026-10-16.hybrid-rescore.realwaste-taco.summary.json`):

| | Clean accepted | Review | Metal accepted | Escalate recall | Verdict = expected |
|---|---|---|---|---|---|
| VLM only | 35/40 | 21/80 | 1 | 17/20 | 71/80 |
| + previous detector | 35/40 | 24/80 | 0 | 19/20 | 73/80 |
| + new detector | 33/40 | 26/80 | 0 | 19/20 | 71/80 |

Read it this way: on in-domain photos the new detector is as safe and slightly more cautious; on
cluttered photos (closer to a truck bed) it is far better. Neither set is gate imagery, so the
thresholds still need calibrating on real gate photos before anyone trusts them in a plant.

## 3. Running it on AMD

* CPU (default, Docker): nothing to do.
* AMD Radeon on Windows: `pip install onnxruntime-directml` in the backend venv (instead of
  `onnxruntime`), then `DETECTOR_PROVIDERS=DmlExecutionProvider` and, on a laptop with two GPUs,
  `DETECTOR_DEVICE_ID` (0 was the Radeon on ours). The startup log and every record name the
  runtime actually used; a GPU that fails to load falls back to the CPU.
* AMD Instinct/Radeon on Linux with ROCm: an onnxruntime build with `MIGraphXExecutionProvider`
  or `ROCMExecutionProvider`, set the same way (not measured here).

## 4. Merge with `main` (Rafi's commits)

* `VLM_VOTES` (default 3, clamped 1..4): the reads of one model run concurrently inside the
  fallback chain's single 90 s budget and share the process-wide outbound slots, so the Token
  Factory sees no more parallel calls than before. Any failed read fails that model, and the chain
  moves on as it did with one read.
* `_vote_majority` keeps a hard contaminant only when more than half the reads saw it. That makes
  verdicts stable, but a metal item seen by 1 of 3 reads is dropped; the detector second opinion
  is what still holds such a truck.
* Inspection detail panel: Rafi's one-column layout, plus the detector boxes on the photo and one
  line "Detector · model · runtime · ms".

## 5. Files

| Area | Files |
|---|---|
| Detector runtime and rules | `backend/src/lynceus/detector.py`, `decision.py`, `pipeline.py`, `api.py`, `config.py`, `audit.py` |
| Weights | `backend/models/lynceus-yolo26s-realwaste-taco.onnx` (replaces `lynceus-yolo26s-realwaste.onnx`), `NOTICE`, `README.md` |
| Replay | `backend/benchmark/rescore.py` (`--hybrid`, `--run-detector`) |
| Web | `web/components/workspace/photo-evidence.tsx`, `verdict-panel.tsx`, gate strip, detail panel |
| Training and evaluation | `ml/` (`colab_train.sh`, `fetch_taco.py`, `build_dataset.py`, `eval_val.py`, `select_model.py`, `eval_decoder.py`, `bench_dml.py`) |
| Config | `.env.example`, `deploy/lynceus.env.example`, `Dockerfile` |

## 6. Check it yourself

From `backend/` (Windows paths; use `.venv/bin/python` on Linux):

```bash
PYTHONPATH=src .venv/Scripts/python -m pytest -q
PYTHONPATH=src .venv/Scripts/python -m benchmark.rescore --source benchmark/results/2026-10-13.jsonl --hybrid --run-detector --out ../hybrid-check.json
```

From the repo root, after `ml/fetch_taco.py --splits test` (needs only the backend venv):

```bash
backend/.venv/Scripts/python ml/eval_decoder.py --ultralytics ml/results/finetuned_yolo26s_e26l_nmsfree.json
```

## 7. Roll back or tune

* Detector off: `DETECTOR_MODEL_PATH=` (empty). The gate then behaves as before this branch,
  and a vision-model outage returns HTTP 503 again when `LYNCEUS_ALLOW_STUB_FALLBACK=0`.
* Previous weights: `git restore --source=cc626fe -- backend/models/lynceus-yolo26s-realwaste.onnx`
  (a binary-safe restore; PowerShell `>` redirection would corrupt the file), then
  `DETECTOR_MODEL_PATH=<that file> DETECTOR_HARD_CONF=0.25 DETECTOR_LIGHT_CONF=0.25`.
* Fewer manual checks: raise `DETECTOR_LIGHT_CONF` or set `DETECTOR_ESCALATE_LIGHT=0`. On val,
  0.10 cuts false escalations on clean TACO images from 7/114 to 2/114 and keeps 97.6 %
  RealWaste glass/organic recall, but TACO glass/organic recall drops from 3/9 to 2/9
  (`ml/results/val_yolo26s_e26l.json`, `sweep`). Prefer choosing it on your own gate photos.

## 8. Limits and next steps

* No result here comes from gate imagery: RealWaste is one item on a floor, TACO is litter
  outdoors. Calibrate on a few hundred labelled gate photos before relying on the thresholds.
* TACO test metal recall of 41 % is a large gain over 7 %, not a solved problem.
* YOLO26m from the same Colab run is still training. It replaces this model only if it wins on
  val by the same rule, with the same checks (sections 2 and 6).
* Licences: the weights are AGPL-3.0-derived (Ultralytics) and trained on RealWaste
  (CC BY-NC-SA 4.0 treated as binding): evaluation and non-commercial use only
  (`backend/models/NOTICE`).
