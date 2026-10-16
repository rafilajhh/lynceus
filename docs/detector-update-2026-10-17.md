# Detector update: the RealWaste + TACO YOLO26s (2026-10-17)

What branch `feat/detector-taco` changes, why, what the numbers are and how sure we are of them,
and how to check or undo each part. Written for the reviewer of the PR; the model card with every
table is `backend/models/README.md`. The hybrid gate itself (detector as second opinion,
degraded mode, VLM fallback chain) is already on `main`; this branch replaces the model and fixes
what the review of the combined code found.

## Ringkasan untuk Rafi (Bahasa Indonesia)

**Apa yang berubah.**

1. **Model detektor baru** `backend/models/lynceus-yolo26s-realwaste-taco.onnx` menggantikan
   `lynceus-yolo26s-realwaste.onnx`. Arsitekturnya sama (YOLO26s, CPU, ~0,2 detik per foto). Bedanya
   data latih: model lama hanya RealWaste (satu barang di lantai beton); model baru RealWaste +
   TACO (foto sampah dunia nyata yang berantakan, kotak digambar manusia). Dilatih di Colab.
2. **Threshold default** jadi hard 0,35 / light 0,05 (dulu 0,25 / 0,25). Dipilih otomatis oleh
   aturan di data val, bukan disetel ke benchmark. Nilainya sekarang hanya ada di satu tempat:
   `config.DEFAULT_DETECTOR_HARD_CONF` / `DEFAULT_DETECTOR_LIGHT_CONF`.
3. **Perbaikan kode dari review** (detail di bagian 4). Yang menyentuh kodemu:
   * `VLM_VOTES` sekarang dibatasi **1..3** (dulu 1..4). Read vote berbagi slot global
     `_VLM_READ_SLOTS` = 3, satu di bawah 4 slot keluar (`_OUTBOUND_SLOTS`), jadi panggilan waybill,
     assist, dan shift selalu kebagian slot walau dua inspeksi sedang vote bersamaan.
   * Kalau satu read vote gagal, model itu langsung dianggap gagal (tidak menunggu 2 read lain
     sampai timeout), lalu chain pindah ke model fallback seperti biasa.
   * 429 yang sudah habis retry dan 401/403 (key ditolak) **menghentikan** fallback chain: semua
     model memakai key yang sama, jadi mencoba model lain hanya membuang budget 90 detik.
   * `_vote_majority`: satu read yang menyebut "metal" dua kali tetap dihitung satu suara; entri
     yang bukan string diabaikan, tidak bikin crash.
   * Request demo (`demo_case`) hanya memakai slot detektor yang sedang kosong, jadi traffic demo
     tanpa login tidak bisa membuat inspeksi sungguhan menunggu.

Detektor tetap **hanya bisa menahan truk untuk dicek manusia**, tidak pernah accept atau reject
sendiri. Tidak ada perubahan skema database atau API; record lama tetap terbaca dan tetap
menyebut model lama.

**Hasil utama: TACO test** (150 foto yang tidak pernah dipakai melatih; dijalankan lewat decoder
produksi `lynceus.detector`):

| | Model baru (0,35/0,05) | Model lama, default (0,25/0,25) | Model lama, pilihan val-nya (0,15/0,30) |
|---|---|---|---|
| Foto berisi logam yang tertangkap | **12/29** (41 %) | 2/29 (7 %) | 2/29 |
| Foto tanpa logam yang ditandai logam | 6/121 (5 %) | 0/121 | 1/121 |
| Foto bersih yang ditahan karena glass/organic | **8/112** | 27/112 | 23/112 |
| Foto bersih yang ditahan karena alasan apa pun | **12/112** | 27/112 | 24/112 |

* Kenaikan logam +34,5 poin persen, interval 95 % [+13,8; +55,2], McNemar p = 0,006: **nyata**.
* Alarm logam palsu naik dari 0 ke 6: ini **regresi nyata** (p = 0,031), bukan noise. Keenam
  foto itu tidak punya label logam di TACO (karton minuman, botol kaca, plastik, puntung rokok).
  Efeknya: truk ditahan untuk dicek, tidak pernah ditolak.
* Meski begitu, total foto bersih yang ditahan tetap turun (12 vs 27 dari 112).

**Apakah hasilnya bocor?** TACO dibagi per nomor gambar, jadi foto dari sesi yang sama bisa ada
di train dan test. Kami cek: hanya 2 foto test yang hampir identik dengan foto train/val, dan 2
yang mirip tetangganya di sesi yang sama (3 foto total). Tanpa ketiganya hasilnya tetap:
logam 10/27 vs 2/27, p = 0,022. Yang tidak bisa disingkirkan: fotografer, lokasi, dan kamera TACO
test sama dengan train. Jadi TACO test "di luar domain RealWaste", belum "di luar domain TACO".

**Di 80 gambar benchmark** (dalam domain) keduanya sama: logam 18/20, 0 alarm palsu. Di replay
hybrid run 2026-10-13: metal lolos tetap 0, review naik 24/80 → 26/80 karena threshold light
0,05 ikut menahan 2 muatan bersih (`cardboard_1`, `textile_trash_280`). Kalau ingin lebih
sedikit tahanan: naikkan `DETECTOR_LIGHT_CONF` atau set `DETECTOR_ESCALATE_LIGHT=0`.

**Yang perlu kamu tahu / putuskan.**

* **Bukan foto gerbang.** Tidak ada angka di sini dari truk sungguhan. Threshold harus
  dikalibrasi ulang di beberapa ratus foto gerbang sebelum dipercaya di pabrik.
* **Light 0,05 adalah nilai terendah di grid**, jadi aturan "ambil yang terendah" langsung
  mengambil lantai; hard 0,35 vs 0,30 ditentukan oleh satu foto TACO val. Dua-duanya rapuh.
* **Data val juga dipakai saat training** (early stop, pilih epoch terbaik), jadi "tidak pernah
  dilatih" benar, tapi val bukan data yang sama sekali tak tersentuh.
* **YOLO26m** dari run Colab yang sama masih training. Ia hanya menggantikan model ini kalau
  menang di val dengan aturan yang sama dan lolos cek yang sama (bagian 6).
* Catatan lama yang masih berlaku: read vote yang ditinggal saat chain gagal tetap memegang slot
  sampai deadline; fallback ke stub bisa accept (perilaku lama); model VLM utama tidak dicek
  terhadap `VLM_BENCHMARKED_MODELS`. Semua sudah ada sebelum branch ini.

**Rollback cepat:** bagian 7.

## 1. What the detector does (unchanged, on `main`)

| Vision model says | Detector sees (at/above its threshold) | Verdict |
|---|---|---|
| metal, confidently | metal | reject (detector gate: passed, "agrees") |
| no metal | metal ≥ `DETECTOR_HARD_CONF` | **escalate_human** (never reject) |
| no glass/organic | glass/organic ≥ `DETECTOR_LIGHT_CONF` | **escalate_human** while `DETECTOR_ESCALATE_LIGHT=1` |
| anything | nothing, or only paper/plastic/textile | the vision model's verdict stands |
| unavailable (`LYNCEUS_ALLOW_STUB_FALLBACK=0`) | anything | `detector_only_degraded`: always escalate_human, findings listed |

Every record stores the detector's boxes, `model`, `runtime` (`onnxruntime-cpu`), latency, the
weights' `model_sha256` and the `thresholds` used, so records from the two models stay apart.

## 2. The new model

| | |
|---|---|
| File | `backend/models/lynceus-yolo26s-realwaste-taco.onnx`, sha256 `c84f795a…20bf5405` |
| Trained | Colab GPU, `ml/colab_train.sh`: YOLO26s from `yolo26s.pt`; early stop (patience 25) after 66 epochs, best epoch 41; cosine LR, seed 0, deterministic, Ultralytics 8.4.177 |
| Data | RealWaste train (YOLOE-26l pseudo-boxes) + TACO train, 1,200 images (human boxes) |
| Not trained on | RealWaste val (416), TACO val (150), TACO test (150), the 80 benchmark images. val was used for early stopping and checkpoint choice |
| Thresholds | hard 0.35, light 0.05: the rule in `ml/eval_val.py`, committed before this model was trained |
| CPU latency | p50 218 ms, p90 233 ms (2 threads, Ryzen 5 8645HS laptop); previous model 231 ms / 398 ms |

Checks run on the received checkpoint before use: its pickle imports only torch/ultralytics
classes, its recorded val mAP (0.7108) matches our local val (0.7121), and its training
arguments match `colab_train.sh`.

## 3. Results and how sure we are

All files in `ml/results/` unless noted.

| Check | New | Previous | File |
|---|---|---|---|
| val mAP50 / mAP50-95 (not like for like, see below) | 0.712 / 0.642 | 0.519 / 0.466 | `val_yolo26s_e26l.json`, `val_prod_yolo26s.json` |
| TACO test metal recall | 12/29 | 2/29 | `decoder_*.json` |
| TACO test false metal | 6/121 | 0/121 | `decoder_*.json` |
| TACO test false escalate on clean | 8/112 | 27/112 | `decoder_*.json` |
| 80 benchmark: metal / false metal | 18/20 / 0/60 | 18/20 / 0/60 | `finetuned_summary_*_nmsfree.json` |
| Decoder vs Ultralytics verdict, 80 images | 80/80 | 80/80 | `decoder_*.json` |
| Hybrid replay: metal accepted / review / verdict = expected | 0 / 26/80 / 71/80 | 0 / 24/80 / 73/80 | `backend/benchmark/results/2026-10-16.hybrid-rescore.realwaste-taco.summary.json` |

* **val mAP is not like for like.** The RealWaste val boxes come from YOLOE-26l, the labeller
  this model was trained on; the previous model scores 0.777 on its own labeller's boxes. The
  image-level TACO rows are the fair comparison.
* **Statistics** (`taco_robustness.py`, `taco_test_robustness.json`): paired per image,
  bootstrap 95 % intervals, exact McNemar. Metal recall +34.5 pp [+13.8, +55.2], p = 0.006.
  False escalate on clean −17.0 pp [−26.8, −7.1], p = 0.001. False metal +5.0 pp [+1.7, +9.1],
  p = 0.031: a regression, stated as one. Glass/organic recall (11 images) and every benchmark
  difference (80 images) are too small to call.
* **Comparator.** Both previous-model columns are shown: its shipped defaults (0.25/0.25) and
  its own val pick by the same rule (0.15/0.30). The gain holds against either.
* **Leakage** (`check_leakage.py`, `leakage_check.json`): 2 of 150 TACO test images have a
  near-duplicate in TACO train/val (dHash Hamming ≤ 10), 2 a same-scene neighbour in the same
  batch (≤ 16); 3 in all. Without them: metal 10/27 vs 2/27, p = 0.022; at a looser cut (≤ 20,
  140 images) 9/24 vs 2/24, p = 0.039.
* **Wording.** "Not trained on" rather than "held out" for val; the threshold rule was committed
  before this model was trained, but the previous model had already been scored on both test sets
  when the per-source caps were written.

## 4. Code changes from the review

Three reviews (code, security, statistics) ran on the combined branch; nothing critical or high.
What was fixed:

| Area | Change | Files |
|---|---|---|
| Outbound slots | Vote reads share `_VLM_READ_SLOTS` (3) under the 4 outbound slots; `VLM_VOTES` clamped 1..3 | `pipeline.py`, `config.py` |
| Fail fast | A failed vote read fails the model at once (`FIRST_EXCEPTION`); the others end at the deadline and are dropped | `pipeline.py` |
| Chain stops | `RateLimitSpentError` (all 429 retries spent) and 401/403 end the fallback chain | `pipeline.py` |
| Vote input | Each read's contaminants counted once; non-string entries ignored | `pipeline.py` |
| Demo traffic | `demo_case` requests take only an idle detector slot, in `run_inspection` and the API's early degraded probe | `pipeline.py`, `api.py`, `detector.py` |
| Image input | Pillow opens JPEG/PNG only; PNG capped at 16 MP; phone MPO photos decoded at reduced scale like JPEG | `detector.py` |
| One source of truth | Threshold defaults in `config`, imported by `decision`; deploy env leaves them commented | `config.py`, `decision.py`, `deploy/lynceus.env.example` |
| Replay | Sweep always includes the shipped default; resolved-path compare; wording | `benchmark/rescore.py` |
| TACO fetch | https only, host allowlist, 40 MB cap; `meta.json` maps names to TACO files | `ml/fetch_taco.py` |
| Reproducibility | `ultralytics==8.4.177` pinned | `ml/setup_env.py` |

Known and left as is (all predate this branch): an abandoned vote read keeps its slot until the
deadline; the stub fallback can accept; the primary VLM is not checked against
`VLM_BENCHMARKED_MODELS`; error texts can include the endpoint URL; the UI has no AGPL §13 source
link.

## 5. Files

| Area | Files |
|---|---|
| Weights and card | `backend/models/lynceus-yolo26s-realwaste-taco.onnx` (replaces `lynceus-yolo26s-realwaste.onnx`), `NOTICE`, `README.md` |
| Runtime and rules | `backend/src/lynceus/detector.py`, `decision.py`, `pipeline.py`, `api.py`, `config.py` |
| Tests | `backend/tests/test_detector.py`, `test_pipeline_client.py`, `test_benchmark_rescore.py` |
| Replay | `backend/benchmark/rescore.py`, `results/2026-10-16.hybrid-rescore.realwaste-taco.summary.json` (the previous model's summary is kept) |
| Training and evaluation | `ml/` (`fetch_taco.py`, `eval_val.py`, `eval_decoder.py`, `check_leakage.py`, `taco_robustness.py`, `setup_env.py`, `results/`) |
| Config | `.env.example`, `deploy/lynceus.env.example`, `Dockerfile`, `README.md` |
| Web | `web/components/workspace/photo-evidence.tsx` (comments only) |

## 6. Check it yourself

From `backend/` (Windows paths; use `.venv/bin/python` on Linux):

```bash
.venv/Scripts/python -m pytest -q
.venv/Scripts/python -m benchmark.rescore --source benchmark/results/2026-10-13.jsonl --hybrid --run-detector --out ../hybrid-check.json
```

From the repo root, after `ml/fetch_taco.py` (train, val and test; the decoder needs only the
backend venv, the leakage check the `ml/` venv):

```bash
backend/.venv/Scripts/python ml/eval_decoder.py --ultralytics ml/results/finetuned_yolo26s_e26l_nmsfree.json
ml/.venv/Scripts/python ml/check_leakage.py --taco-only
backend/.venv/Scripts/python ml/taco_robustness.py
```

The previous model's rows come from the same `eval_decoder.py` with
`--onnx <old file> --hard 0.25 --light 0.25 --ultralytics ml/results/finetuned_yolo26s_realwaste_nmsfree.json`.

## 7. Roll back or tune

* Detector off: `DETECTOR_MODEL_PATH=` (empty). A vision-model outage then returns HTTP 503 again
  when `LYNCEUS_ALLOW_STUB_FALLBACK=0`.
* Previous weights: `git restore --source=cc626fe -- backend/models/lynceus-yolo26s-realwaste.onnx`
  (binary-safe; PowerShell `>` redirection would corrupt the file), then
  `DETECTOR_MODEL_PATH=<that file> DETECTOR_HARD_CONF=0.25 DETECTOR_LIGHT_CONF=0.25`.
* Fewer manual checks: raise `DETECTOR_LIGHT_CONF` or set `DETECTOR_ESCALATE_LIGHT=0`. On val,
  0.10 cuts false escalations on clean TACO images from 7/114 to 2/114 and keeps 97.6 %
  RealWaste glass/organic recall, but TACO glass/organic recall drops from 3/9 to 2/9
  (`ml/results/val_yolo26s_e26l.json`, `sweep`). Prefer choosing it on your own gate photos.
* Fewer false metal holds: raise `DETECTOR_HARD_CONF`; check the TACO test rows
  (`decoder_lynceus-yolo26s-realwaste-taco.json`) for what it costs in metal recall.

## 8. Limits and next steps

* No result here comes from gate imagery. Calibrate on a few hundred labelled gate photos before
  relying on the thresholds.
* 41 % TACO metal recall is a large gain over 7 %, not a solved problem.
* YOLO26m: evaluate with the same rule, the same decoder rows, the same leakage and paired
  statistics, before it replaces this file.
* Licences: the weights are AGPL-3.0-derived (Ultralytics) and trained on RealWaste
  (CC BY-NC-SA 4.0 treated as binding) and TACO (annotations CC BY 4.0): evaluation and
  non-commercial use only (`backend/models/NOTICE`).
