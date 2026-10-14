# PLAN.md — Rencana Penuh Pengembangan Lynceus (A–Z)

> Dokumen rencana hackathon AMD Act 3. Semua angka kunci berasal dari file riset di `docs/`:
> `research/demo-assets.md` (business value & aset demo), `research/engine-map.md` (pemetaan engine),
> `research/amd-gpu-stack.md` (stack AI di AMD GPU), `research/audit-provenance.md` (audit & provenance).

---

## 1. Ringkasan Eksekutif

**Lynceus** adalah sistem inspeksi pintu gerbang bahan bakar alternatif (RDF/refuse-derived fuel) berbasis AI yang mengakses model melalui AMD Token Factory. Ketika truk sampah tiba di pabrik semen atau PLTSa, operator mengunggah foto muatan, mengetik teks surat jalan secara manual (tanpa OCR), serta memasukkan berat timbangan dan data gas — Lynceus memadukan **VLM (MiniCPM-V-4.7-35B-A3B)** untuk deteksi kontaminan visual dan estimasi basah/kering, **LLM (DeepSeek-V4-Flash)** untuk membaca surat jalan dan crosscheck klaim vs observasi, serta **engine rule-based Lynceus** untuk scoring suitability dan rekomendasi rute — semuanya menghasilkan verdict **HIJAU/KUNING/MERAH** beserta alasan, confidence, dan **audit record tamper-evident (file lokal)** dalam hitungan detik. Track 1: Intelligent Industry. Value proposition: satu jam kiln mati = **US$28.000** (±Rp450 juta) — inspeksi otomatis Lynceus adalah "biaya cegah" yang jauh lebih murah daripada satu kontaminan logam/batu yang lolos ke shredder bernilai ratusan juta rupiah dan mematikan kiln.

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
│  Foto muatan (kamera gerbang)   Surat jalan (teks ketikan operator → LLM)                          │
│  Berat (weighbridge, kg)        Gas (digital twin: virtual_sensor step_response)           │
└──────────────┬─────────────────────────────────────────────────────────────────────────────┘
               │  (semua input dibekukan + digest SHA-256 sebelum AI berjalan — snapshot beku)
               ▼
┌─────────────────────────── FUSION LAYER ───────────────────────────────────────────────────┐
│  Normalisasi input → struktur Input truk (truck_id, photo, manifest, weight_kg, gas_ppm)    │
│  Struktur data tunggal untuk AI & engine; missing inputs dilaporkan, tidak ditebak          │
└──────────────┬───────────────────────────────────────┬─────────────────────────────────────┘
               ▼                                       ▼
┌───────── VLM (Token Factory) ──────────┐   ┌───────── LLM (Token Factory) ──────────┐
│  MiniCPM-V-4.7-35B-A3B via Token Factory    │   │  DeepSeek-V4-Flash via Token Factory       │
│  • deteksi kontaminan visual        │   │  • baca surat jalan (field: jenis,  │
│    (logam, batu, ban, e-waste)      │   │    asal, berat klaim, kualitas)     │
│  • estimasi basah/kering visual     │   │  • crosscheck klaim manifest vs     │
│  • klasifikasi jenis sampah         │   │    observasi VLM + berat + gas      │
│  • output JSON terstruktur + conf.  │   │  • reasoning tersimpan + prompt hash│
└──────────────┬───────────────────────┘   └──────────────┬──────────────────────┘
               └──────────────────┬───────────────────────┘
                                  ▼
┌───────── ENGINE LYNCEUS (rule-based, pure Python) ───────────────────────────────────────┐
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
┌───────── AUDIT RECORD (skema audit engine) ───────────────────────────────────────────────────┐
│  audit-NNN.json tamper-evident (file lokal): format_version, record_id, execution_status, timestamps UTC,    │
│  inputs (digest SHA-256 per input), ai_outputs (model identity + prompt hash),             │
│  engine_outputs, verdict, gates, digest — atomic write, finalisasi single-shot             │
└──────────────┬─────────────────────────────────────────────────────────────────────────────┘
               ▼
┌───────── WEB DASHBOARD OPERATOR ───────────────────────────────────────────────────────────┐
│  Tiket verdict: warna + penjelasan + confidence + alasan + caveats + audit link            │
└────────────────────────────────────────────────────────────────────────────────────────────┘
```

Detail skema audit record: `docs/research/audit-provenance.md` §(b).

---

## 4. Engine Keputusan

### 4.1 Transparansi

**Engine keputusan** adalah bagian dari Lynceus, dikembangkan sebagai library di backend (`backend/src/lynceus_engine/`). Bersama layer VLM/LLM di AMD GPU, fusion layer, decision engine verdict truk, dan web app operator, semuanya dibangun untuk hackathon ini.

### 4.2 Tabel nasib module (dari `research/engine-map.md`)

| Module engine | Nasib | Penggunaan di Lynceus |
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
| `casegen.py`, `container.py`, `geometry.py`, `mesh.py`, `runner.py`, `post.py`, `scenario.py`, `project.py`, `history.py` | **Dibuang** (kode IO/Qt/CFD tidak dibawa) | Konsep audit `history.py` diadopsi ulang sebagai skema audit record Lynceus (lihat `research/audit-provenance.md`) |

### 4.3 Perubahan spesifik

1. **Engine jadi library di backend**: engine keputusan di-vendor ke dalam repo; backend FastAPI mengekspos `POST /assess` yang membungkus `assess_batch` (dipakai terverifikasi: `assess_batch(preset('mixed-msw'), tonnage_t=12.0, moisture=0.45, age_h=72.0)` → fase II, CH₄ kumulatif 0,471 kg / 0,657 m³, rekomendasi composting 0,51 > rdf 0,46).
2. **i18n string**: rule/caveat/reason berbahasa Inggris hardcode → i18n key, frontend memformat.
3. **Redaksi caveat CFD**: caveat "mesh independence" (flag `screening=True`) diganti redaksi web-friendly — hasil Lynceus adalah *screening estimate*, bukan hasil tervalidasi lab (pola classification screening/validated engine).

---

## 5. Stack Teknologi (dari `research/amd-gpu-stack.md`)

| Komponen | Pilihan | Justifikasi |
|---|---|---|
| Backend | **FastAPI** (Python) | Serialize `asdict` engine Lynceus; endpoint `POST /assess`; OpenAI-compatible client ke AMD Token Factory |
| Frontend | **Next.js/React** (alternatif sederhana: Vite+React SPA, atau FastAPI + Jinja/HTMX bila waktu sempit) | Dashboard operator: upload, tiket verdict, audit view |
| Serving AI | **AMD Token Factory** | Endpoint bersama OpenAI-compatible pada GPU AMD, bukan self-hosted MI300X |
| VLM | **MiniCPM-V-4.7-35B-A3B** | Analisis foto muatan melalui AMD Token Factory |
| LLM | **DeepSeek-V4-Flash** | Analisis teks surat jalan ketikan operator dan crosscheck |
| Benchmark acuan | Ukur request end-to-end pada AMD Token Factory | Angka benchmark Qwen self-hosted tidak mewakili deployment ini |
| Quantization (bila perlu) | Dikelola penyedia endpoint | Tidak ada konfigurasi quantization self-hosted pada demo |
| Kredit | Akses AMD Token Factory dengan kunci tim | Kredit VM ADC bukan prasyarat demo |

Konfigurasi deploy: arahkan endpoint OpenAI-compatible VLM dan LLM ke AMD Token Factory, pilih `MiniCPM-V-4.7-35B-A3B` (VLM) dan `DeepSeek-V4-Flash` (LLM), lalu pasang kunci tim melalui environment variable. Tidak perlu menjalankan vLLM atau menyediakan VM MI300X.

---

## 6. Alur Demo (end-to-end < 10 detik per truk)

1. Truk tiba di gerbang; operator buka demo URL di dashboard Lynceus.
2. Operator upload: **foto muatan** + **teks surat jalan ketikan operator** (tanpa OCR) + input **berat** (kg); gas dihasilkan digital twin `virtual_sensor`.
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
- **Deliverable**: repo GitHub (struktur monorepo: `backend/`, `web/`, `docs/`); akses AMD Token Factory dan kunci tim disiapkan; akun lablab.ai, ADP, Discord tim disiapkan; skeleton web (Next.js/Vite) dengan halaman upload + hasil stub; README initial.
- **Acceptance**: smoke test endpoint AMD Token Factory berhasil; skeleton web jalan di localhost; semua anggota tim punya akses repo + Token Factory + Discord.
- **Risiko**: approval kredit ADP butuh 2–3 hari kerja → **Mitigasi**: ajukan Day 1 pagi; gunakan kredit 25 jam ADC sebagai jembatan; kartu kredit valid disiapkan sejak awal.

### Day 2 — Integrasi Engine Keputusan
- **Deliverable**: Engine keputusan jadi bagian backend; endpoint `POST /assess` (input truk → `assess_batch` → JSON); unit test pada contoh terverifikasi (mixed-msw, 12 t, moisture 0,45, age 72 h → composting 0,51).
- **Acceptance**: `curl POST /assess` mengembalikan JSON lengkap (suitability + recommendation + missing) sesuai skema; test hijau; i18n key untuk string `recommend` dirancang.
- **Risiko**: mismatch asumsi engine vs input truk → **Mitigasi**: mapping layer eksplisit input truk → composition/moisture/tonnage; unit test konversi.

### Day 3 — Pipeline VLM+LLM di AMD
- **Deliverable**: integrasi MiniCPM-V-4.7-35B-A3B (VLM) + DeepSeek-V4-Flash (LLM) melalui AMD Token Factory; prompt VLM (deteksi kontaminan + estimasi basah/kering + klasifikasi) dan prompt LLM (ekstraksi surat jalan + crosscheck); parsing JSON output terstruktur (schema + retry/repair); smoke test foto & dokumen nyata.
- **Acceptance**: request pipeline tunggal (foto + teks surat jalan) mengembalikan JSON valid dengan confidence dengan latensi end-to-end yang diukur pada AMD Token Factory; prompt disimpan dan di-hash.
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

1. **Demo URL jalan < 10 detik per truk** — upload → tiket verdict tampil (target, bukan hasil benchmark; ukur latensi end-to-end AMD Token Factory).
2. **Verdict + alasan + audit tampil** — setiap tiket menampilkan warna, penjelasan (reasoning VLM/LLM + rule engine), confidence, caveats, dan link audit record yang lolos validasi loader strict.
3. **3 varian demo** — hijau/kuning/merah berjalan konsisten (≥3x run berturut-turut per varian).
4. **Video demo < 5 menit** — mencakup alur end-to-end dan pitch business value.
5. **README run-able** — orang lain bisa clone → setup → deploy (AMD Token Factory + backend + web) mengikuti README tanpa bantuan tim.
