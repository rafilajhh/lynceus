# PLAN.md — Rencana Penuh Pengembangan Lynceus (A–Z)

> Dokumen rencana hackathon AMD Act 3. Semua angka kunci berasal dari file riset di `docs/`:
> `research-demo-assets.md` (business value & aset demo), `research-scentinel-engine-map.md` (pemetaan engine),
> `research-amd-gpu-stack.md` (stack AI di AMD GPU), `research-scentinel-audit-provenance.md` (audit & provenance).

---

## 1. Ringkasan Eksekutif

**Lynceus** adalah sistem inspeksi pintu gerbang bahan bakar alternatif (RDF/refuse-derived fuel) berbasis AI yang berjalan penuh di GPU AMD Instinct MI300X. Ketika truk sampah tiba di pabrik semen atau PLTSa, operator mengunggah foto muatan, surat jalan, berat timbangan, dan data gas — Lynceus memadukan **VLM (Qwen2.5-VL-7B)** untuk deteksi kontaminan visual dan estimasi basah/kering, **LLM (Qwen2.5-7B-Instruct)** untuk membaca surat jalan dan crosscheck klaim vs observasi, serta **engine rule-based Scentinel** untuk scoring suitability dan rekomendasi rute — semuanya menghasilkan verdict **HIJAU/KUNING/MERAH** beserta alasan, confidence, dan **audit record immutable** dalam hitungan detik. Track: AI pada AMD GPU. Value proposition: satu jam kiln mati = **US$28.000** (±Rp450 juta) — inspeksi otomatis Lynceus adalah "biaya cegah" yang jauh lebih murah daripada satu kontaminan logam/batu yang lolos ke shredder bernilai ratusan juta rupiah dan mematikan kiln.

---

## 2. Masalah & User

### 2.1 Masalah

| # | Masalah | Angka | Sumber |
|---|---|---|---|
| 1 | Downtime tak terencana manufaktur global | **US$125.000/jam** (survey 3.215 responden, ABB/Sapio 2023) | https://new.abb.com/news/detail/107660/abb-survey-reveals-unplanned-downtime-costs-125000-per-hour |
| 2 | Shutdown kiln semen AS | **US$28.000/jam** (clinker hilang); 68% akibat maintenance terlewat | http://oxmaint.ai/article/cement-plant-maintenance-cmms-system-guide |
| 3 | Downtime pabrik semen umum | **US$10.000–40.000/jam** | https://www.cryotos.com/blog/how-to-reduce-downtime-in-cement-plants |
| 4 | Kiln idle pabrik 1 MTPA | **US$12.500–100.000/jam** | https://oxmaint.com/industries/manufacturing-plant/predictive-maintenance-roi-cement-usa |
| 5 | Kerusakan shredder akibat kontaminan | Kegagalan tube boiler akibat korosi/erosi & logam = penyebab downtime WtE paling umum; unit kecil mulai **±Rp20 juta**, unit industri RDF ratusan juta–miliar rupiah | https://www.osti.gov/biblio/128729 ; https://www.indotrading.com/surabaya/jual-mesin-pencacah |
| 6 | Penipuan supplier (klaim moisture/komposisi palsu) | Moisture tinggi menurunkan LHV as-received drastis (klaim 18 MJ/kg dry basis turun banyak pada moisture 35%); RDF spesifikasi umum kiln: NCV >14 MJ/kg, moisture <15%, Cl <0,8%, ash <15% | https://pmc.ncbi.nlm.nih.gov/articles/PMC13049024 ; https://www.osti.gov/biblio/20939472 |
| 7 | Insentif substitusi bahan bakar | RDF menghemat **US$0,134/ton semen** vs gas & batu bara; 11 pabrik semen Vietnam mengganti ±30% batu bara dengan bahan bakar alternatif | https://pmc.ncbi.nlm.nih.gov/articles/PMC13049024 ; https://ipen.org/wp-content/uploads/2024/11/summary_plastic_wastes_cgfed_final_nov18.pdf |

**Inti masalah:** verifikasi muatan hari ini manual, lambat, mudah ditipu, dan tidak terdokumentasi. Satu kontaminan logam/batu yang lolos → shredder rusak / kiln berhenti 1 jam = US$28.000 (±Rp450 juta) hilang, sementara kegagalan akibat kontaminan adalah penyebab downtime WtE paling umum.

### 2.2 User

**Operator gerbang pabrik semen / PLTSa** — orang yang setiap hari menerima truk sampah, memeriksa surat jalan manual, memutuskan terima/tolak, dan bertanggung jawab bila kontaminan lolos ke shredder. Kebutuhan: keputusan cepat (<10 detik), alasan yang bisa dipertanggungjawabkan (audit), dan bahasa yang jelas (verdict HIJAU/KUNING/MERAH, bukan skor mentah).

Standar ground truth demo: **ISO 21640:2021** (https://www.iso.org/standard/71309.html), **EN 15359:2011** (https://www.zkg.de/en/artikel/zkg_Solid_Recovered_Fuels_Specifications_and_classes-2067874.html), **ISO 21654:2021** (https://www.iso.org/standard/71319.html). Template surat jalan basis GOV.UK Duty of Care Transfer Note (https://www.gov.uk/government/publications/duty-of-care-waste-transfer-note-template).

---

## 3. Arsitektur Lynceus

```
┌─────────────────────────── INPUT (operator, via web dashboard) ───────────────────────────┐
│  Foto muatan (kamera gerbang)   Surat jalan (scan/foto → OCR/LLM)                          │
│  Berat (weighbridge, kg)        Gas (digital twin: virtual_sensor step_response)           │
└──────────────┬─────────────────────────────────────────────────────────────────────────────┘
               │  (semua input dibekukan + digest SHA-256 sebelum AI berjalan — snapshot beku)
               ▼
┌─────────────────────────── FUSION LAYER ───────────────────────────────────────────────────┐
│  Normalisasi input → struktur Input truk (truck_id, photo, manifest, weight_kg, gas_ppm)    │
│  Struktur data tunggal untuk AI & engine; missing inputs dilaporkan, tidak ditebak          │
└──────────────┬───────────────────────────────────────┬─────────────────────────────────────┘
               ▼                                       ▼
┌───────── VLM (AMD MI300X) ──────────┐   ┌───────── LLM (AMD MI300X) ──────────┐
│  Qwen2.5-VL-7B-Instruct via vLLM    │   │  Qwen2.5-7B-Instruct via vLLM       │
│  • deteksi kontaminan visual        │   │  • baca surat jalan (field: jenis,  │
│    (logam, batu, ban, e-waste)      │   │    asal, berat klaim, kualitas)     │
│  • estimasi basah/kering visual     │   │  • crosscheck klaim manifest vs     │
│  • klasifikasi jenis sampah         │   │    observasi VLM + berat + gas      │
│  • output JSON terstruktur + conf.  │   │  • reasoning tersimpan + prompt hash│
└──────────────┬───────────────────────┘   └──────────────┬──────────────────────┘
               └──────────────────┬───────────────────────┘
                                  ▼
┌───────── ENGINE SCENTINEL (rule-based, pure Python) ───────────────────────────────────────┐
│  pipeline.assess_batch → phase → generation (gas) → massbalance →                          │
│  suitability.assess (5 rute, fuel_grade EN 15359-style) → recommend.recommend              │
│  (actionable, reasons, caveats, missing, alternative; refuse bila insufficient)            │
└──────────────┬─────────────────────────────────────────────────────────────────────────────┘
               ▼
┌───────── DECISION ENGINE (fusion verdict) ─────────────────────────────────────────────────┐
│  HIJAU / KUNING / MERAH + confidence + daftar missing inputs + gate states                 │
│  (vlm_confidence, ocr_confidence, manifest_crosscheck, gas_plausibility, weight_plaus.)   │
│  Desain aman: MERAH boleh over-reject (jalur inspeksi manual); insufficient → refuse       │
└──────────────┬─────────────────────────────────────────────────────────────────────────────┘
               ▼
┌───────── AUDIT RECORD (skema Scentinel) ───────────────────────────────────────────────────┐
│  audit-NNN.json immutable: format_version, record_id, execution_status, timestamps UTC,    │
│  inputs (digest SHA-256 per input), ai_outputs (model identity + prompt hash),             │
│  engine_outputs, verdict, gates, digest — atomic write, finalisasi single-shot             │
└──────────────┬─────────────────────────────────────────────────────────────────────────────┘
               ▼
┌───────── WEB DASHBOARD OPERATOR ───────────────────────────────────────────────────────────┐
│  Tiket verdict: warna + penjelasan + confidence + alasan + caveats + audit link            │
└────────────────────────────────────────────────────────────────────────────────────────────┘
```

Detail skema audit record: `docs/research-scentinel-audit-provenance.md` §(b).

---

## 4. Adopsi Scentinel

### 4.1 Transparansi

**Engine Scentinel adalah proyek open-source (lisensi MIT) milik tim sendiri**, dikembangkan lebih lanjut selama hackathon ini sebagai library di backend Lynceus. Yang **baru** di Lynceus (bukan bagian Scentinel): layer VLM/LLM di AMD GPU, fusion layer, decision engine verdict truk, dan web app operator.

### 4.2 Tabel nasib module (dari `research-scentinel-engine-map.md`)

| Module Scentinel | Nasib | Penggunaan di Lynceus |
|---|---|---|
| `composition.py` | **Diambil utuh** | Basis domain model; `preset()` → dropdown stream di UI |
| `generation.py` | **Diambil utuh** | Kalkulasi emisi gas batch (CH₄/CO₂) — dipakai pipeline |
| `massbalance.py` | **Diambil utuh** | Massa kering per stream; endpoint material flow |
| `suitability.py` | **Diambil utuh** | Scoring engine verdict; `RouteScore.rule` + `inputs` → panel explainability |
| `recommend.py` | **Diubah** | Headline verdict user-facing; string Inggris hardcode → **i18n key**; caveats wajib tampil di UI |
| `pipeline.py` | **Diambil utuh** | `assess_batch` = inti endpoint backend `POST /assess`; serialize via `asdict` |
| `virtual_sensor.py` | **Diambil utuh** | Simulator digital-twin sensor gas untuk demo tanpa hardware; noise deterministik → reproducible |
| `gas_data.py` | **Diambil utuh** | Katalog gas AP-42 terkutib; `citation()` → tooltip provenance |
| `gas_defaults.py` | **Diambil utuh** (data generated, 780 ln) | Data default gas |
| `assessment.py` | **Diambil utuh** | Evaluasi gas readings vs threshold; endpoint gas screening report |
| `casegen.py`, `container.py`, `geometry.py`, `mesh.py`, `runner.py`, `post.py`, `scenario.py`, `project.py`, `history.py` | **Dibuang** (kode IO/Qt/CFD tidak dibawa) | Konsep audit `history.py` diadopsi ulang sebagai skema audit record Lynceus (lihat `research-scentinel-audit-provenance.md`) |

### 4.3 Perubahan spesifik

1. **Engine jadi library di backend**: Scentinel core dipasang sebagai dependency; backend FastAPI mengekspos `POST /assess` yang membungkus `assess_batch` (dipakai terverifikasi: `assess_batch(preset('mixed-msw'), tonnage_t=12.0, moisture=0.45, age_h=72.0)` → fase II, CH₄ kumulatif 0,471 kg / 0,657 m³, rekomendasi composting 0,51 > rdf 0,46).
2. **i18n string**: rule/caveat/reason berbahasa Inggris hardcode → i18n key, frontend memformat.
3. **Redaksi caveat CFD**: caveat "mesh independence" (flag `screening=True`) diganti redaksi web-friendly — hasil Lynceus adalah *screening estimate*, bukan hasil tervalidasi lab (pola classification screening/validated dari Scentinel).

---

## 5. Stack Teknologi (dari `research-amd-gpu-stack.md`)

| Komponen | Pilihan | Justifikasi |
|---|---|---|
| Backend | **FastAPI** (Python) | Serialize `asdict` engine Scentinel; endpoint `POST /assess`; OpenAI-compatible client ke vLLM |
| Frontend | **Next.js/React** (alternatif sederhana: Vite+React SPA, atau FastAPI + Jinja/HTMX bila waktu sempit) | Dashboard operator: upload, tiket verdict, audit view |
| Serving AI | **vLLM Docker `rocm/vllm`** di **AMD Developer Cloud, 1× MI300X** (192 GB HBM3) | First-class ROCm; Quick Start image vLLM tersedia langsung di ADC |
| VLM | **Qwen2.5-VL-7B-Instruct** (BF16) | Satu-satunya VLM dengan resep + benchmark resmi vLLM yang eksplisit menargetkan MI300X/MI325X/MI355X; kuat OCR/dokumen (DocVQA 95,7); ~17–24 GB |
| LLM | **Qwen2.5-7B-Instruct** | Keluarga Qwen2 terbukti di ROCm blog AMD; tokenizer/chat API konsisten dengan VLM |
| Benchmark acuan | Qwen2.5-VL-7B DP=4 di MI300X: **13,09 req/s; 1.455 tok/s output; TTFT mean 4,43 s; TPOT 58 ms** | Realistis untuk demo interaktif <10 s per truk |
| Quantization (bila perlu) | **FP8 via AMD Quark** | **AWQ/GPTQ/bitsandbytes INT8 ❌ tidak didukung vLLM di ROCm**; FP8 & GGUF ✅ |
| Kredit | ADC direct: 25 jam (~$50, 10 hari); **ADP: $100, 30 hari setelah aktivasi** | VM ditagih walau dimatikan — destroy setelah selesai |

Perintah deploy ringkas (dari riset §6): ADC droplet 1× MI300X image Quick Start vLLM → `vllm serve Qwen/Qwen2.5-VL-7B-Instruct --port 8000` (VLM) + `vllm serve Qwen/Qwen2.5-7B-Instruct --port 8001` (LLM), tuning `VLLM_ROCM_USE_AITER=1`, `VLLM_USE_TRITON_FLASH_ATTN=0`, `--num-scheduler-steps 10`.

---

## 6. Alur Demo (end-to-end < 10 detik per truk)

1. Truk tiba di gerbang; operator buka demo URL di dashboard Lynceus.
2. Operator upload: **foto muatan** + **surat jalan** (scan/foto) + input **berat** (kg); gas dihasilkan digital twin `virtual_sensor`.
3. Pipeline berjalan (freeze input → VLM deteksi kontaminan + estimasi basah/kering → LLM baca surat jalan + crosscheck → engine `assess_batch` → fusion verdict → audit record).
4. < 10 detik: dashboard menampilkan **tiket verdict** (HIJAU/KUNING/MERAH) + penjelasan + confidence + missing inputs + **link audit record**.

### Tiga varian muatan demo

| Varian | Input | Verdict yang diharapkan | Narasi demo |
|---|---|---|---|
| 🟢 HIJAU | Foto organik bersih, surat jalan lengkap & cocok, berat wajar, gas normal | ACCEPT — diterima, rekomendasi rute (mis. composting/RDF), confidence tinggi, semua gates passed | "Supplier jujur, proses lancar" |
| 🟡 KUNING | Foto campuran / moisture tinggi (klaim dry, tampak basah), surat jalan ada tapi 1 field konflik ringan | ESCALATE/KUNING — diterima dengan caveat (mis. drying prerequisite), gate `manifest_crosscheck: failed`/warning | "Klaim vs observasi beda — perlu penyesuaian, bukan penolakan" |
| 🔴 MERAH | Foto dengan kontaminan logam/batu terlihat, atau berat klaim jauh dari timbangan, atau moisture ekstrem | REJECT/MERAH — ditolak atau inspeksi manual, reasoning VLM/LLM ditampilkan, audit lengkap | "Satu kontaminan ini = 1 jam kiln mati = US$28.000" |

Basis foto: Roboflow Universe `waste_datasets` 2.872 gambar CC BY 4.0 (https://universe.roboflow.com/trash-kupyl/waste_datasets) + vehicle-detection Kaggle (https://www.kaggle.com/datasets/daudshah/vehicle-detection-dataset); fallback foto lapangan tim di TPS/TPA.

---

## 7. Rencana 6 Hari

### Day 1 — Setup
- **Deliverable**: repo GitHub (struktur monorepo: `backend/`, `web/`, `docs/`); instance ADC 1× MI300X dibuat (image Quick Start vLLM); klaim kredit ADP ($100) diajukan; akun lablab.ai, ADP, Discord tim disiapkan; skeleton web (Next.js/Vite) dengan halaman upload + hasil stub; README initial.
- **Acceptance**: `docker exec -it rocm bash` sukses via SSH dan `rocm-smi` menampilkan MI300X; skeleton web jalan di localhost; semua anggota tim punya akses repo + ADC + Discord.
- **Risiko**: approval kredit ADP butuh 2–3 hari kerja → **Mitigasi**: ajukan Day 1 pagi; gunakan kredit 25 jam ADC sebagai jembatan; kartu kredit valid disiapkan sejak awal.

### Day 2 — Integrasi Engine Scentinel
- **Deliverable**: Scentinel core jadi dependency backend; endpoint `POST /assess` (input truk → `assess_batch` → JSON); unit test pada contoh terverifikasi (mixed-msw, 12 t, moisture 0,45, age 72 h → composting 0,51).
- **Acceptance**: `curl POST /assess` mengembalikan JSON lengkap (suitability + recommendation + missing) sesuai skema; test hijau; i18n key untuk string `recommend` dirancang.
- **Risiko**: mismatch asumsi engine vs input truk → **Mitigasi**: mapping layer eksplisit input truk → composition/moisture/tonnage; unit test konversi.

### Day 3 — Pipeline VLM+LLM di AMD
- **Deliverable**: vLLM serve Qwen2.5-VL-7B (port 8000) + Qwen2.5-7B (port 8001) di ADC; prompt VLM (deteksi kontaminan + estimasi basah/kering + klasifikasi) dan prompt LLM (ekstraksi surat jalan + crosscheck); parsing JSON output terstruktur (schema + retry/repair); smoke test foto & dokumen nyata.
- **Acceptance**: request pipeline tunggal (foto + teks surat jalan) mengembalikan JSON valid dengan confidence dalam <10 s (acuan TTFT 4,43 s VLM 7B); prompt disimpan dan di-hash.
- **Risiko**: output model tidak valid JSON → **Mitigasi**: prompt ketat + constrained decoding/skema Pydantic + retry dengan pesan error; fallback parse parsial.

### Day 4 — Fusion, Verdict, Audit, Dashboard
- **Deliverable**: fusion layer (input → AI outputs → engine → verdict HIJAU/KUNING/MERAH + confidence + missing); audit record `audit-NNN.json` sesuai skema (atomic write, digest, gates); dashboard UI lengkap (upload, tiket verdict, penjelasan, audit view).
- **Acceptance**: run end-to-end 3 varian muatan menghasilkan verdict benar + audit record yang lolos validasi loader strict (encode→decode→write); UI menampilkan caveats dan confidence.
- **Risiko**: integrasi UI-backend serialization drift → **Mitigasi**: satu skema Pydantic dibagi FE/BE (OpenAPI generated types).

### Day 5 — Dataset Demo, Video, Pitch
- **Deliverable**: dataset foto demo final (Roboflow + foto lapangan, 3 varian); template surat jalan (basis GOV.UK Transfer Note); demo URL stabil (deployment publik); video demo direkam (<5 menit); PDF pitch deck.
- **Acceptance**: demo URL bisa diakses dari luar dan 3 varian muatan menghasilkan verdict yang benar secara konsisten (≥3x run berturut-turut); video & pitch final tersimpan di repo.
- **Risiko**: dataset foto tidak realistis → **Mitigasi**: kombinasikan foto lapangan tim sendiri di TPS/TPA (100% nyata, bebas lisensi).

### Day 6 — Buffer, Polish, Submit
- **Deliverable**: buffer untuk bug & risiko; polish UI/UX (copywriting verdict, tampilan audit); README run-able penuh (setup → deploy → demo); submit submission **lebih awal** dari deadline.
- **Acceptance**: submission terkirim minimal beberapa jam sebelum deadline; README di-clone fresh orang lain bisa menjalankan; semua checklist metrik sukses (§9) terpenuhi.
- **Risiko**: ADC down / kredit habis menjelang submit → **Mitigasi**: video cadangan + snapshot hasil 3 varian; submit awal; destroy VM hanya setelah submission aman.

---

## 8. Risiko & Mitigasi

| # | Risiko | Dampak | Mitigasi |
|---|---|---|---|
| 1 | ADC down / instance gagal saat demo | Demo live gagal total | Fallback endpoint cadangan + **video demo cadangan** yang direkam Day 5; hasil 3 varian di-snapshot |
| 2 | VLM salah deteksi kontaminan | Muatan buruk lolos / muatan baik ditolak | **Desain verdict aman: MERAH boleh over-reject** + jalur inspeksi manual; confidence & gates tampil eksplisit di tiket; verdict berlabel `screening_estimate` bukan `validated` |
| 3 | Caveat mesh-independence / screening disalahpahami juri | Kredibilitas ilmiah dipertanyakan | Redaksi caveat CFD diganti versi web-friendly: "hasil screening, bukan pengganti uji lab (ISO 21640/EN 15359)" |
| 4 | Dataset foto tidak realistis (stock/Roboflow) | Demo tidak meyakinkan | Tambah foto lapangan tim di TPS/TPA; anotasi kelas "truk sampah" dari basis Kaggle vehicle-detection |
| 5 | Waktu/kredit ADC habis (25 jam/$50 ADC; $100 ADP 30 hari; VM ditagih walau mati) | Instance mati sebelum demo | Klaim ADP Day 1; hemat GPU-jam (matikan inferensi saat dev, destroy VM setelah selesai); budget pemakaian per hari |
| 6 | Output VLM/LLM bukan JSON valid | Pipeline gagal mid-demo | Prompt ketat + Pydantic schema + retry/repair parse; fallback jawaban `insufficient` yang jujur, bukan nebak |
| 7 | Approval ADP tertunda (2–3 hari kerja) | Tidak ada GPU di awal minggu | Ajukan pagi Day 1; jembatan kredit ADC 25 jam; kartu kredit valid sejak pendaftaran |
| 8 | Integrasi engine–AI–UI terlambat (big-bang Day 4) | Fitur inti tidak teruji | Kontrak skema JSON (Pydantic) ditetapkan Day 2; integrasi bertahap dengan stub sejak Day 1 |

---

## 9. Metrik Sukses

1. **Demo URL jalan < 10 detik per truk** — upload → tiket verdict tampil (acuan benchmark: TTFT VLM 4,43 s di MI300X).
2. **Verdict + alasan + audit tampil** — setiap tiket menampilkan warna, penjelasan (reasoning VLM/LLM + rule engine), confidence, caveats, dan link audit record yang lolos validasi loader strict.
3. **3 varian demo** — hijau/kuning/merah berjalan konsisten (≥3x run berturut-turut per varian).
4. **Video demo < 5 menit** — mencakup alur end-to-end dan pitch business value.
5. **README run-able** — orang lain bisa clone → setup → deploy (ADC + vLLM + backend + web) mengikuti README tanpa bantuan tim.
