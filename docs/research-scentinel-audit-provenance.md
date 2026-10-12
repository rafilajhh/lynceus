# Riset Provenance & Audit: Pola Scentinel yang Layak Diadopsi Lynceus

**Status:** riset read-only — tidak ada perubahan kode.
**Sumber:** `scentinel/src/scentinel/core/history.py` (2097 baris), `scentinel/src/scentinel/core/project.py` (85 baris), `scentinel/src/scentinel/core/recommend.py` (174 baris), `scentinel/docs/ARCHITECTURE.md` §19–28.
**Tujuan:** pola manifest run, snapshot beku, quality gates eksplisit, dan refuse-to-answer di Scentinel → struktur audit record Lynceus untuk inspeksi truk (foto, manifest teks, berat, gas) → keputusan AI (VLM/LLM + confidence) → verdict & rekomendasi.

---

## (a) Tabel Pola → Sumber → Padanan Lynceus

| # | Pola (Scentinel) | Sumber (file:baris) | Padanan Lynceus |
|---|---|---|---|
| 1 | **Satu manifest immutable per run** (`run.json` dalam `run-NNN/`); tidak ada indeks sentral — manifest per-run *adalah* history, index tak bisa divergen | `history.py:1-13`, `ARCHITECTURE.md` §19:234-238 | Satu `audit-NNN.json` immutable per inspeksi truk, disimpan di folder inspeksinya; catat foto/berkas bukti dalam record yang sama |
| 2 | **Ditulis dua kali, atomik**: `incomplete` sebelum kerja dimulai → diganti via sibling temp `.tmp` + `os.replace()`; crash meninggalkan record `incomplete` yang jujur, bukan tanpa record atau sukses palsu | `history.py:3-7`, `:188-189`, `:598-646`, `:1195-1210`; `ARCHITECTURE.md` §20:239-243 | `in_progress` sebelum inferensi AI dimulai → terminal (`completed`/`failed`/`cancelled`) setelah verdict; atomic write mencegah record setengah-tertulis |
| 3 | **Format versioning eksplisit** `RUN_FORMAT_VERSION = 10` dengan changelog per versi di komentar; versi lama **ditolak** (bukan salah-baca); project file versi 1 dimigrasi hanya bila aman | `history.py:67-102`, `project.py:13-17,54-60` | `AUDIT_FORMAT_VERSION`; penambahan field (mis. hasil OCR baru, model versi baru) bump versi; reader lama menolak, bukan salah-tafsir |
| 4 | **Pemisahan empat hal yang mudah tercampur**: requested inputs (`project`) / applied physics (`applied_physics`) / execution outcome (`execution_status`) / evidence quality (`quality`) | `history.py:24-37` | Pemisahan: inputs truk (foto, manifest, berat, gas) / model & prompt yang dipakai / outcome pipeline AI / confidence & verification gates |
| 5 | **Snapshot input beku** (`snapshot_project()`): copy dalam-dalam project sebelum run; run membaca snapshot, bukan model live editor — klik viewport mid-run tak bisa mengubah klaim record | `history.py:559-595`, `:620`; `ARCHITECTURE.md` §24:256-260 | Foto, manifest teks, berat, dan gas reading dibekukan (copy + digest) sebelum diproses AI; input live (mis. re-timbang, edit manifest) tak bisa mengubah record yang sedang berjalan |
| 6 | **Readings divalidasi terhadap snapshot beku** (bukan model live): id, koordinat, urutan, gas keys harus cocok persis; ketidakcocokan = `HistoryError` keras; exit-0 tanpa readings → `failed` + `NO_READINGS_ERROR`; dicek ulang saat `load_run()` agar manifest yang di-edit tangan tak bisa menyelundupkan readings asing | `history.py:186`, `:672-677`, `:726-743`, `:1087-1128`, `:1450-1453`; `ARCHITECTURE.md` §25:261-268 | Output AI divalidasi terhadap input yang dibekukan: foto yang diproses harus foto yang dicatat (digest), truck_id harus cocok, field output harus menjawab input yang sama; dicek ulang saat load |
| 7 | **Finalisasi single-shot**: `finish_run()` menolak manifest yang sudah terminal di disk — manifest terminal tidak pernah ditulis ulang; `incomplete` tidak boleh membawa `finished_at`/outcome/results/digest | `history.py:683-685`, `:714-722`, `:1403-1421` | Record verdict tidak pernah ditulis ulang; koreksi = record baru yang mereferensikan record lama |
| 8 | **Digest SHA-256 atas input yang dihasilkan** (`case_input_digest`, format `sha256:<64 hex>` divalidasi regex); "requested" vs "applied" dipisah — digest berubah saat konstanta yang diterapkan berubah walau input UI sama; menutupi *hanya* input yang dihasilkan, bukan output solver yang menimpanya | `history.py:29-30`, `:193`, `:431-433`, `:1017-1040`, `:1741-1748`; `ARCHITECTURE.md` §26:269-281 | `sha256` atas setiap input truk (foto, manifest teks, berat, gas) — foto yang sama selalu menghasilkan digest sama; verifikasi integritas bukti saat audit ulang |
| 9 | **Portabilitas path**: hanya path relatif ke run dir yang disimpan, workstation path ditolak | `history.py:679-685`, `:1171-1192` | Hanya path relatif dalam folder inspeksi; record tetap portabel saat arsip dipindahkan |
| 10 | **Alokasi ID dari filesystem** (bukan memori): `mkdir(exist_ok=False)` pada `run-NNN` berikutnya; directory yang match ikut dihitung walau manifest-nya korup, jadi ID tak pernah dipakai dua kali walau aplikasi restart | `history.py:104-110`, `:846-869`; `ARCHITECTURE.md` §19:234-238 | `inspection-NNN` dari scan filesystem; ID inspeksi tak pernah terpakai dua kali walau crash/restart |
| 11 | **Enum tertutup untuk status** (`incomplete/succeeded/failed/cancelled`), `succeeded` = outcome proses murni; validasi strict saat decode (jenis, rentang, non-finite ditolak) | `history.py:112-118`, `:787-807`, `:2063-2075` | `in_progress/completed/failed/cancelled` — `completed` berarti pipeline AI selesai bersih, **bukan** klaim AI benar |
| 12 | **`finished_at` wajib saat terminal, dilarang saat `incomplete`**; timestamp harus timezone-aware, ISO 8601 UTC `Z`, format regex-divalidasi | `history.py:191-192`, `:1213-1217`, `:2090-2097` | Waktu inspeksi UTC ISO 8601; record terminal wajib punya timestamp selesai |
| 13 | **Kegagalan menyebut stage**: `failed_stage` (meshing/casegen/solver/post), `exit_code`, `error` — kegagalan bisa di-staging, bukan opaque | `history.py:174-183`, `:279-294`, `:726-743` | Kegagalan pipeline AI menyebut stage: `capture`, `ocr`, `vlm`, `llm`, `verification`, plus exit code / pesan error API |
| 14 | **"Refuse to answer when inputs missing"**: `recommend()` mengembalikan `insufficient=True` + daftar `missing` saat input tak cukup (tonnage 0, route tak bisa diskor), bukan rekomendasi yang dibangun dari data absen — "rekomendasi di atas data absen adalah output paling merusak" | `recommend.py:1-13`, `:39-54`, `:73-117` | AI Lynceus wajib refuse: bila foto blur/manifest tak terbaca/timbangan gagal → verdict `refuse_insufficient_input` + daftar field yang hilang, **bukan** suitability spekulatif |
| 15 | **Rekomendasi menyertakan alasan & input**: `reasons`, `caveats`, `inputs`, `alternative`, `actionable` property — reviewer bisa membantah reasoning, bukan sekadar assertion | `recommend.py:1-13`, `:39-54`, `:139-173` | LLM reasoning, keterbatasan, dan skor runner-up disimpan; keputusan bisa di-audit dan dibantah berdasarkan reasoning |
| 16 | **Least-bad option tetap direkomendasikan dengan shortfall dinyatakan** — "no recommendation is not an actionable answer for a load that physically exists" | `recommend.py:119-129` | Truk harus ditindaklanjuti walau skor rendah: rekomendasi tetap diberi dengan caveat skor, bukan di-deny |
| 17 | **Quality gates eksplisit, closed-enum, tidak pernah di-infer dari exit code**: `convergence` / `mesh_independence` / `mass_balance` / `experimental_validation`, dengan `not_evaluated`/`not_run` yang di-*stated*; consumer yang memfilter `succeeded` saja tak bisa merender run unverified sebagai verified | `history.py:137-172`, `:496-533`, `:1066-1084`; `ARCHITECTURE.md` §27:282-287 | Gates per keputusan AI: `vlm_confidence`, `ocr_confidence`, `manifest_crosscheck`, `gas_plausibility`, `weight_plausibility` — pipeline selesai ≠ klaim benar; state gate `not_evaluated` eksplisit |
| 18 | **Classification + uncertainty statement** bawaan (`screening_estimate` + kalimat ketidakpastian mesh) — "empty never means passed" | `history.py:137-144`, `:294-305` | Setiap verdict membawa klasifikasi (`screening`/`validated`) + pernyataan ketidakpastian; hasil AI tanpa validasi silang tidak boleh tampil sebagai validated |
| 19 | **Model identity + versi aplikasi di manifest**: `application: {name, version}`; environment (container image, solver, mesh cells) direkam | `history.py:120-121`, `:312-317`, `:279-294`, `:1312-1324` | Model identity VLM/LLM (nama, versi, endpoint) + versi Lynceus direkam per inspeksi — hasil dari model berbeda tidak bisa dibandingkan tanpa info ini |
| 20 | **Validation re-checked at load, not only write-time**: `load_run()` menerapkan validasi yang sama dengan write; hand-edited manifest tak bisa menyelundup readings/gates asing | `history.py:787-807`, `:1450-1473` | Loader audit record memvalidasi ulang digest input, cocok-matching inputs→outputs, enum gates; manifest hasil edit tangan ditolak keras |
| 21 | **Provenance per angka**: manual = `user input` tanpa sitasi fabrikasi; auto = sitasi AP-42 yang di-resolve sekali saat run start dan dibekukan (`resolved_ppmv`) agar perubahan default belakangan tak menulis-ulang run lama; generation chemistry dipersist, bukan di-recompute saat read | `history.py:128-135`, `:331-337`, `:361-364`, `:882-973` | Setiap input bernilai (berat, gas ppm) mencatat provenance (sensor/timbangan/OCR/manual) + nilai yang di-resolve dan dibekukan; nilai model tidak di-recompute saat read |
| 22 | **Request vs modelled (ventilation)**: `{requested_on, modelled:false}`; reader menolak `modelled:true`; konsumer tak bisa mengelompokkan berdasarkan faktor yang tak termodelkan | `history.py:346-358`, `:1670-1688`; `ARCHITECTURE.md` §28:288-292 | Field "klaim manifest" vs "terverifikasi": teks yang di-OCR tapi belum cross-check dicatat `claimed, verified:false` |
| 23 | **Screening vs validated, stated**: `classification: screening_estimate` + uncertainty wajib; recommendation punya flag `screening` yang hanya boleh dimatikan oleh caller dengan bukti convergence | `history.py:137-144`, `:294-305`; `recommend.py:66-72,100-104` | Verdict AI tanpa validasi eksperimental = `screening`; upgrade ke `validated` hanya dengan bukti gate terukur |
| 24 | **Unit eksplisit di nama field** (`ppmv`, `_m`, `_kg_per_h`, `concentration_unit`) + satu titik konversi (UI konversi volume-fraction→ppmv sekali, manifest menyimpan nilai yang sama dengan tabel UI — displayed dan persisted tak bisa drift) | `history.py:18-22`, `:123-126`; `ARCHITECTURE.md` §21:244-246 | Nama field berunit: `weight_kg`, `gas_ppm`, `timestamp_utc`; konversi sekali di satu tempat sehingga UI dan audit record menampilkan angka yang sama |
| 25 | **Kegagalan mengubah status jadi failed + alasan**: exit-0 tapi readings tak cocok → `succeeded` di-downgrade `failed` + `NO_READINGS_ERROR` (bukan exit-0 opaque) | `history.py:735-743`, `:1443-1448` | Pipeline AI "selesai" tapi output tak cocok input → `failed` dengan alasan eksplisit, bukan sukses palsu |
| 26 | **Malformed manifest tidak menggagalkan listing** (skip, bukan crash) saat `list_runs()`; `load_run()` langsung tetap error keras | `history.py:9-13`, `:810-822` | Listing inspeksi = scan folder `audit-NNN.json`; record korup di-skip dengan error tercatat, tidak crash |
| 27 | **Strict decode + typed rebuild**: setiap field divalidasi (exact keys, jenis, enum, regex digest/timestamp, angka finite); `HistoryError` menyebut manifest+field; bad record tidak pernah diam-diterima | `history.py:787-807`, `:1369-2097` | Loader audit strict: field tak boleh missing/extra, digest/timestamp regex-validated, angka finite; error menyebut record+field |
| 28 | **Error prefix konsisten** untuk rejection readings (`NO_READINGS_ERROR` sebagai prefix) agar greppable | `history.py:186`, `:1098-1102` | Prefix error konsisten per kelas kegagalan audit (mis. `INPUT_MISMATCH`) agar bisa di-grep/di-telemetry |
| 29 | **Directory cleanup saat manifest gagal ditulis**: folder yang baru direserve tapi masih kosong dihapus best-effort — tidak ada run tanpa record | `history.py:643-645`, `:871-879` | Folder inspeksi baru yang record-nya gagal ditulis dibersihkan bila masih kosong — tidak ada inspeksi tanpa record |
| 30 | **Dual-write: encode→decode→write** — payload divalidasi dengan decoder strict *sebelum* ditulis ke disk; writer tak bisa menulis manifest yang reader-nya sendiri akan tolak | `history.py:640-642`, `:781-783` | Audit record di-encode, divalidasi ulang dengan loader strict, baru ditulis — record yang ditulis selalu lolos validasi |
| 31 | **Rekomendasi mencantumkan angka input yang dipakai** (`inputs: {tonnage, moisture, age_h}`) — angka yang sama tampil di record dan di alasan rekomendasi | `recommend.py:79,114,172` | LLM reasoning mencantumkan nilai input aktual (berat, gas ppm) yang jadi dasar keputusan |

*(Baris merujuk versi file saat riset; `history.py` berjumlah 2097 baris — angka 1938 baris pada deskripsi tugas mencerminkan perubahan minor.)*

### Catatan analisis pola manifest run (poin tugas 1)

Struktur field top-level manifest Scentinel (`history.py:195-207`) — 11 kunci dengan urutan stabil:
`format_version`, `run_id`, `execution_status`, `started_at_utc`, `finished_at_utc`, `application{name,version}`, `project{name,geometry,scenario,sensors}`, `applied_physics{…, case_input_digest}`, `execution{…, exit_code, failed_stage, error, solver_termination}`, `results{concentration_unit, sensor_readings}`, `quality{classification, uncertainty, convergence, …, validation_metrics}`.

Empat pemisahan kunci (`history.py:24-37`):
1. **requested inputs** (`project`) — yang diminta pengguna;
2. **applied physics** (`applied_physics`) — setting numerik yang benar-benar dipakai case + digest SHA-256 input case;
3. **execution outcome** (`execution_status`/`execution`) — exit bersih ≠ convergence/verification/validation;
4. **evidence quality** (`quality`) — klasifikasi screening + closed-enum gates + metric verification/validation terpisah.

Versioning: `RUN_FORMAT_VERSION = 10` (`history.py:67-102`) — setiap bump versi didokumentasikan dengan alasan *mengapa versi lama tidak bisa dibaca ulang* (mis. "a version 4 record has one `ch4_kg` and cannot say whether it was cumulative or a rate"). Versi tidak kompatibel **ditolak**, bukan salah-tafsir.

Atomic write (`history.py:1195-1210`): tulis ke sibling temp `.run.json.tmp` → `os.replace()` → cleanup best-effort. Gagal replace meninggalkan manifest valid sebelumnya utuh.

### Peta penanganan failure (dari history.py)

| Situasi kegagalan | Penanganan Scentinel | Sumber |
|---|---|---|
| Crash sebelum finalisasi | Manifest tetap `incomplete` di disk (jujur), bukan hilang | `history.py:3-7`, `:624-645` |
| Gagal tulis manifest awal | Folder run dihapus bila masih kosong; error propagate | `history.py:643-645`, `:871-879` |
| Exit-0 tanpa readings | Downgrade `succeeded`→`failed` + `NO_READINGS_ERROR` | `history.py:735-743` |
| Readings tak cocok snapshot beku | `HistoryError` keras; readings asing tak pernah dipersist | `history.py:726-734`, `:1087-1128` |
| Manifest terminal di-finalisasi ulang | Ditolak — finalisasi single-shot | `history.py:714-722` |
| Manifest korup/malformed saat list | Di-skip (listing tidak crash), tapi `load_run` langsung error | `history.py:810-822` |
| Solver gagal / dibatalkan | `failed_stage` + `exit_code` + `error` persist | `history.py:653-658` |
| Konstanta yang diterapkan berubah (input UI sama) | Digest berubah → ketidakcocokan terdeteksi | `ARCHITECTURE.md` §26:269-281 |

---

## (b) Draf Skema JSON Audit Record Lynceus

Desain mengikuti pola Scentinel: append-only, atomic-write, four-way separation, closed enums, stated-not-inferred gates, digest per input, refuse-to-answer.

```jsonc
{
  // === Identitas & lifecycle ===
  "format_version": 1,                    // AUDIT_FORMAT_VERSION; bump = reject old readers (pola RUN_FORMAT_VERSION, history.py:67-102)
  "record_id": "inspection-000123",       // dialokasikan dari filesystem, tak pernah reuse (history.py:104-110, :846-869)
  "execution_status": "completed",        // closed enum: in_progress | completed | failed | cancelled (history.py:112-118)
  "started_at_utc": "2026-10-13T02:15:00Z",   // ISO 8601 UTC 'Z', timezone-aware wajib (history.py:191-192, :1213-1217)
  "finished_at_utc": "2026-10-13T02:15:41Z",  // wajib saat terminal, null saat in_progress (history.py:2090-2097)

  // === Aplikasi & model identity ===
  "application": { "name": "lynceus", "version": "0.1.0" },   // pola ApplicationRecord (history.py:120-121, :312-317)

  // === Inputs truk (dibekukan sebelum AI berjalan; pola snapshot_project, history.py:559-595) ===
  "inputs": {
    "truck_id": "B-9174-KT",              // identitas truk, divalidasi cocok di seluruh record
    "photo": {
      "filename": "photo_0001.jpg",       // path relatif dalam folder record (pola portabilitas, history.py:1171-1192)
      "sha256": "sha256:<64-hex>",        // digest beku; regex-divalidasi (history.py:193, :1741-1748)
      "captured_at_utc": "2026-10-13T02:14:52Z",
      "provenance": "gate_camera"         // sumber; tak ada sitasi fabrikasi (history.py:133-135)
    },
    "manifest_text": {
      "source": "paper_manifest_ocr",     // provenance: OCR vs manual entry
      "raw_text_sha256": "sha256:<64-hex>",   // digest teks mentah hasil OCR
      "extracted_fields": {               // field yang berhasil diekstrak; missing = null, bukan dihilangkan
        "waste_type": "organik",
        "origin": "TPA Suwung",
        "declared_weight_kg": 4200.0      // unit eksplisit di nama field (pola history.py:18-22, :123-126)
      },
      "ocr_confidence": 0.91              // confidence OCR per dokumen
    },
    "weight": {
      "value_kg": 4185.0,
      "source": "weighbridge",            // provenance per angka (pola gas_sources provenance)
      "measured_at_utc": "2026-10-13T02:14:55Z"
    },
    "gas": {
      "readings_ppm": { "ch4": 15.2, "co2": 850.0 },   // unit di nama field (ppm)
      "source": "portable_sensor",        // provenance sensor
      "measured_at_utc": "2026-10-13T02:14:58Z"
    }
  },

  // === AI outputs (dipisah dari engine; pola four-way separation, history.py:24-37) ===
  "ai_outputs": {
    "vlm": {
      "model": "qwen2.5-vl-7b",           // model identity + versi (pola container_image/solver, history.py:279-294)
      "model_version": "2026-09-01",
      "raw_output_sha256": "sha256:<64-hex>",  // digest output mentah VLM
      "detected": { "visual_waste_type": "organik", "contamination_visible": true },
      "confidence": 0.87                   // closed range 0..1, angka finite
    },
    "llm": {
      "model": "llama-3.1-8b-instruct",
      "model_version": "2026-08-15",
      "prompt_sha256": "sha256:<64-hex>",      // digest prompt yang dipakai — reproducibility
      "raw_output_sha256": "sha256:<64-hex>",
      "reasoning": "Foto menunjukkan dominasi sisa organik rumah tangga…",  // reasoning tersimpan (pola reasons, recommend.py:139-150)
      "confidence": 0.82
    }
  },

  // === Engine outputs (rule-based, dipisah dari AI outputs) ===
  "engine_outputs": {
    "suitability": {
      "classification": "acceptable",      // closed enum domain Lynceus
      "score": 0.74,                      // angka finite, unit-less score
      "rule": "organik < 60% kontaminasi, gas dalam rentang"   // rule yang memproduksi skor (pola best.rule, recommend.py:140)
    },
    "recommendation": {
      "actionable": true,                 // pola actionable property (recommend.py:52-54)
      "route": "accept_processing",       // closed enum route
      "headline": "Diterima untuk proses komposting.",
      "insufficient": false,              // refuse-to-answer flag (recommend.py:49-50)
      "missing": [],                      // daftar field hilang saat insufficient (recommend.py:50, :73-117)
      "caveats": ["moisture 58%: drying prerequisite"],
      "alternative": "rejection scores 0.31 (margin 0.43)"   // pola alternative (recommend.py:159-165)
    }
  },

  // === Verdict & gates (stated, never inferred; pola quality, history.py:137-172) ===
  "verdict": {
    "decision": "accept",                 // closed enum: accept | reject | refuse_insufficient_input | escalate_human
    "decided_at_utc": "2026-10-13T02:15:40Z",
    "classification": "screening_estimate",  // screening vs validated — stated, empty ≠ passed (history.py:137-144)
    "uncertainty": "Keputusan AI tanpa validasi eksperimental silang; gunakan untuk triase."
  },
  "gates": {
    // closed enum per gate: not_evaluated | not_run | passed | failed (history.py:150-172)
    "vlm_confidence":        { "state": "passed",   "value": 0.87, "threshold": 0.80 },
    "ocr_confidence":        { "state": "passed",   "value": 0.91, "threshold": 0.75 },
    "manifest_crosscheck":   { "state": "failed",   "reason": "waste_type konflik: manifest 'organik' vs VLM 'campuran'" },
    "gas_plausibility":      { "state": "passed",   "value": 15.2, "unit": "ppm", "target": "< 50 ppm ch4" },
    "weight_plausibility":   { "state": "not_evaluated", "reason": "tidak ada rentang referensi untuk truck class ini" }
  },

  // === Digest & provenance ===
  "digest": {
    "record_sha256": "sha256:<64-hex>",       // digest atas canonical serialization record (tanpa field ini)
    "input_digests": {                         // pola case_input_digest per-input (history.py:431-433, :1017-1040)
      "photo": "sha256:<64-hex>",
      "manifest_text": "sha256:<64-hex>",
      "prompt": "sha256:<64-hex>"
    },
    "algorithm": "sha256"
  }
}
```

### Field minimal (12+ berlabel)

| Field | Label / makna | Sumber pola Scentinel |
|---|---|---|
| `format_version` | Versi skema record; versi lama ditolak | `history.py:67-102` |
| `record_id` | ID inspeksi unik, dialokasikan dari filesystem, tak reuse | `history.py:104-110, 846-869` |
| `execution_status` | `in_progress/completed/failed/cancelled`; `completed` = outcome proses, bukan klaim kebenaran | `history.py:112-118` |
| `started_at_utc` / `finished_at_utc` | Waktu mulai/selesai UTC, wajib saat terminal | `history.py:2090-2097` |
| `application` | Nama + versi aplikasi penulis record | `history.py:120-121, 312-317` |
| `inputs.truck_id` | Identitas truk, divalidasi konsisten di seluruh record | — |
| `inputs.photo` | Foto + digest + provenance + waktu capture | `history.py:128-135, 1741-1748` |
| `inputs.manifest_text` | Teks manifest hasil OCR + digest + field terekstrak + confidence | `history.py:128-135, 251` |
| `inputs.weight` | Nilai berat (kg) + provenance weighbridge/manual + waktu | `history.py:18-22, 331-337` |
| `inputs.gas` | Pembacaan gas (ppm) + provenance sensor + waktu | `history.py:123-126` |
| `ai_outputs.vlm` | Deteksi visual + model identity + confidence | `history.py:279-294` |
| `ai_outputs.llm` | Reasoning + model identity + prompt digest + confidence | `recommend.py:139-150` |
| `engine_outputs.suitability` | Klasifikasi rule-based + skor + rule string | `recommend.py:140-150` |
| `engine_outputs.recommendation` | Route + headline + insufficient/missing + caveats + alternative | `recommend.py:39-54, 73-117, 159-165` |
| `verdict` | Keputusan final closed-enum + classification + uncertainty | `history.py:137-144, 294-305` |
| `gates` | Closed-enum per gate, stated-not-inferred, `not_evaluated` eksplisit | `history.py:146-172, 1066-1084` |
| `digest` | SHA-256 atas record + per-input | `history.py:431-433, 1017-1040` |

### Aturan invarian yang menyertainya (dari pola Scentinel)

1. **Ditulis dua kali, atomik** (pola §20): `audit-NNN.json` dalam `in_progress` sebelum inferensi, diganti via temp sibling + `os.replace()`; crash meninggalkan `in_progress` yang jujur.
2. **Finalisasi single-shot**: record terminal tak bisa di-finalisasi ulang; koreksi = record baru.
3. **Input dibekukan sebelum AI berjalan** (pola §24): digest input dicatat di `begin`; output divalidasi terhadap input beku di `finish`.
4. **Refuse-to-answer**: `verdict.decision = refuse_insufficient_input` + `missing[]` ketika input tak cukup — tidak pernah suitability spekulatif (pola `recommend.py:9-12`).
5. **`completed` ≠ benar**: consumer yang memfilter harus membaca `gates`, bukan `execution_status` saja (pola §27).
6. **Validasi ulang saat load** (pola `load_run`): digest, matching inputs→outputs, enum gates, timestamp regex — manifest edit-tangan ditolak keras.
7. **Encode→decode→write**: payload divalidasi loader strict sebelum ditulis (pola `history.py:640-642, 781-783`).
8. **Path relatif saja** (pola §22): record portabel dengan folder buktinya.
9. **No central index** (pola §19): listing = scan folder; record korup di-skip dengan error, tidak crash.
10. **Angka finite, enum tertutup, unit di nama field** (pola strict decode): `allow_nan=False`, timestamp UTC `Z`, digest `sha256:<64hex>` regex.
