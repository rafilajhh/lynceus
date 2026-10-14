# Checklist Compliance & Submission — Lynceus

> Event: **AMD Developer Hackathon Act III** (lablab.ai, `amd-developer-hackathon-act-iii`)
> Deadline submit: **18 Oktober 2026**. Timeline internal tim: 12–17 Oktober.
> Cara pakai: kolom `[ ]` dicentang saat item selesai; kolom **PJ** (penanggung jawab) dan **Kapan** diisi tim di awal sprint.

---

## 1. Syarat Administratif (dengan deadline)

| [ ] | Item | Detail / Link | PJ | Kapan | Deadline |
|---|---|---|---|---|---|
| [ ] | Enroll di lablab.ai | Event: `amd-developer-hackathon-act-iii` di lablab.ai | ___ | ___ | ASAP (hari pertama) |
| [ ] | Daftar AMD AI Developer Program (ADP) | https://developer.amd.com/ai-developer-program/ — approval cloud credit 2–3 hari kerja, jangan ditunda | ___ | ___ | H-6 (12 Okt) — approval bisa makan 2–3 hari |
| [ ] | Klaim kredit $100 ADP | Login developer.amd.com → Member Perks → Request Cloud Credits; **kedaluwarsa 30 hari setelah aktivasi** — aktifkan hanya saat siap pakai GPU. Alternatif: 25 jam direct ADC (~$50, 10 hari) | ___ | ___ | Setelah ADP approve, sebelum 14 Okt |
| [ ] | Join Discord lablab.ai + connect ke profil | Wajib untuk koordinasi panitia & pengumuman; connect akun Discord ke profil lablab.ai | ___ | ___ | 12–13 Okt |
| [ ] | Buat tim di platform lablab.ai | 1–6 orang; pastikan semua anggota sudah enroll sebelum di-invite | ___ | ___ | 13–14 Okt |
| [ ] | Kartu kredit valid untuk ADC | Pembuatan akun ADC (amd.digitalocean.com) butuh kartu kredit valid; kredit hangus jika kartu invalid | ___ | ___ | Sebelum create VM pertama |
| [ ] | Snapshot kontak panitia | Screenshot kanal Discord untuk troubleshooting submission (manual submission butuh persetujuan panitia) | ___ | ___ | 14 Okt |

**Catatan kredit GPU** (dari `research/amd-gpu-stack.md` §1.2): kredit hanya berlaku untuk MI300X; VM **tetap ditagih walau dimatikan** — destroy instance setelah selesai; storage snapshot tidak ditanggung kredit.

---

## 2. Submission Wajib

| [ ] | Item | Batas / Spesifikasi | Usulan isi | PJ | Kapan |
|---|---|---|---|---|---|
| [ ] | Project title | **≤50 karakter** | Lihat opsi judul di bawah | ___ | ___ |
| [ ] | Short description | **≤255 karakter** | Lihat draf di bawah | ___ | ___ |
| [ ] | Long description | **≥100 kata** | Lihat draf (~129 kata) di bawah | ___ | ___ |
| [ ] | Technology & category tags | Daftar tag platform | AMD Token Factory, DeepSeek-V4.1-Flash (VLM), DeepSeek-V4-Flash (LLM), Vision-Language Model, FastAPI, Python, Predictive Maintenance, Waste-to-Energy, Computer Vision | ___ | ___ |
| [ ] | Cover image | 16:9, PNG/JPG | Desain dengan logo Lynceus + visual gerbang inspeksi; ekspor 1920×1080 | ___ | ___ |
| [ ] | Video demo | **MP4, <5 menit, <300MB** | Skenario: problem → demo live → impact (lihat §3 kriteria Presentation) | ___ | ___ |
| [ ] | Slide presentation | PDF | 10–12 slide: problem, market, arsitektur, demo, roadmap | ___ | ___ |
| [ ] | Public GitHub repo | Publik + **README run-able dari fresh clone tanpa API key ter-commit** | Repo utama Lynceus; kunci via env var / `.env.example` | ___ | ___ |
| [ ] | Demo application | Platform + **live URL** yang bisa diakses juri | Deploy demo di VM ADC / hosting publik; URL stabil hingga penjurian selesai | ___ | ___ |

### Usulan judul (≤50 karakter — jumlah aktual dihitung)

| # | Judul | Karakter |
|---|---|---|
| A | Lynceus: AI Gatekeeper untuk Bahan Bakar RDF | 44 |
| B | Lynceus — Inspeksi AI di Pintu Masuk Kiln | 41 |
| C | Lynceus: VLM Inspeksi Sampah di AMD ROCm | 40 |

> Rekomendasi: **opsi A** — menyebut fungsi (gatekeeper) dan domain (RDF/bahan bakar alternatif) sekaligus.

### Usulan short description (≤255 karakter — jumlah aktual dihitung)

| # | Draf | Karakter |
|---|---|---|
| A | Inspeksi gerbang: foto, teks manifes ketikan operator, berat dan gas dianalisis dengan DeepSeek-V4.1-Flash (VLM) + DeepSeek-V4-Flash (LLM) di AMD Token Factory. Verdict rule-based disimpan dalam file lokal tamper-evident ber-SHA-256. | 233 |
| B | Gerbang RDF: DeepSeek-V4.1-Flash (VLM) + DeepSeek-V4-Flash (LLM) di AMD Token Factory menganalisis foto dan teks surat jalan manual; engine menerbitkan verdict dengan audit SHA-256 tamper-evident. | 196 |

> Rekomendasi: **opsi A** — memuat angka bisnis (US$28.000/jam) yang langsung menjawab kriteria Business Value.

### Draf long description (≥100 kata)

> Lynceus adalah gerbang inspeksi AI di pintu masuk fasilitas pengolahan bahan bakar alternatif. Setiap truk sampah difoto, operator mengetik teks surat jalan secara manual (tanpa OCR), dan data timbangan serta gas dikumpulkan. Gas berasal dari digital twin kecuali gateway sensor dikonfigurasi. Analisis foto memakai DeepSeek-V4.1-Flash (VLM), sedangkan analisis teks surat jalan memakai DeepSeek-V4-Flash (LLM), keduanya melalui AMD Token Factory, bukan model self-hosted. Hasilnya bukan sekadar deteksi: engine keputusan berbasis regulasi memberi verdict accept, escalate, atau reject, dan setiap keputusan tersimpan dalam file audit lokal tamper-evident ber-SHA-256 yang bisa diperiksa ulang. Dampak bisnisnya konkret: satu kontaminan logam yang lolos dapat menghentikan kiln semen, dengan downtime senilai US$28.000–125.000 per jam menurut riset industri. Biaya mencegah lewat inspeksi otomatis jauh lebih murah daripada satu jam kiln mati. Tim kami membangun layer AI AMD, fusion multi-modal, dan antarmuka web di atas engine open-source MIT kami sendiri.

---

## 3. Kriteria Penilaian → Bukti

| Kriteria | Apa yang dicari juri | Bukti yang harus kita siapkan | Status | PJ |
|---|---|---|---|---|
| **Application of Technology** | Integrasi model AMD dalam *working product* | (1) Endpoint AMD Token Factory live: DeepSeek-V4.1-Flash (VLM) + DeepSeek-V4-Flash (LLM), `curl` smoke test terdokumentasi; (2) diagram arsitektur di slide + README; (3) log inferensi nyata (timestamp, model identity, latency per request) | [ ] | ___ |
| **Presentation** | Video <5 menit: problem → demo → impact; plus market analysis & future plans | Script video 4 menit: 0:00–0:40 problem (downtime kiln), 0:40–3:00 demo live inspeksi truk → verdict → audit record, 3:00–4:00 impact + market + roadmap. Slide memuat market analysis & future plans eksplisit | [ ] | ___ |
| **Business Value** | Angka dampak & biaya cegah vs biaya rugi | Downtime **US$28.000/jam** (shutdown kiln semen AS; 68% akibat maintenance terlewat) dan **US$125.000/jam** (survey ABB/Sapio 3.215 responden) — sumber lengkap di `research/demo-assets.md` §(a). Pitch andalan: satu shredder RDF industri ratusan juta rupiah vs satu jam kiln mati ±Rp450 juta → inspeksi otomatis = "biaya cegah" yang jauh lebih murah | [ ] | ___ |
| **Originality** | Bukan chatbot generik | AI vision + **decision engine berbasis regulasi** (ISO 21640, EN 15359) + **audit trail tamper-evident (file lokal) ber-SHA-256** (pola engine: snapshot beku, refuse-to-answer, gates closed-enum — lihat `research/audit-provenance.md`). Fusion multi-modal: foto + teks manifes ketikan operator + berat + gas | [ ] | ___ |

**Checklist bukti:**

| [ ] | Bukti dirender di slide + video (bukan hanya ada di repo) | ___ | ___ |
| [ ] | Log inferensi & smoke test endpoint disimpan sebagai file bukti di repo | ___ | ___ |

---

## 4. Etika & Eligibility

**Keterbukaan basis engine — WAJIB, tidak bisa dinegosiasikan:**

| [ ] | Item | Detail | PJ | Kapan |
|---|---|---|---|---|
| [ ] | README menyatakan provenance engine | Kalimat wajib (atau padanan): *"Decision engine Lynceus dibangun untuk Lynceus. Yang dibangun dalam hackathon ini: layer AI AMD Token Factory (DeepSeek-V4.1-Flash VLM + DeepSeek-V4-Flash LLM), fusion multi-modal (foto/teks surat jalan manual/berat/gas), dan antarmuka web."* | ___ | ___ |
| [ ] | Pitch/video menyatakan hal yang sama | Slide provenance + 1 kalimat di voice-over video | ___ | ___ |
| [ ] | Tidak ada API key / secret ter-commit | Audit `git log -p` + scan repo; kunci hanya via env var / `.env.example` tanpa nilai riil | ___ | ___ |
| [ ] | Lisensi repo MIT | File `LICENSE` di root repo | ___ | ___ |
| [ ] | Klaim sesuai batas | Semua angka bisnis di pitch punya sumber (`research/demo-assets.md` §a); tidak ada klaim benchmark yang tidak kita ukur sendiri | ___ | ___ |

---

## 5. Timeline Internal (6 hari) & Deadline Submit

| Tanggal | Fokus | Deliverable hari itu | Status | PJ |
|---|---|---|---|---|
| 12 Okt (Sen) | Administratif + ADP credit request | Enroll lablab.ai, daftar ADP, Discord, skeleton repo | [ ] | ___ |
| 13 Okt (Sel) | Tim + akses AMD Token Factory | Tim terbentuk di platform, endpoint DeepSeek-V4.1-Flash (VLM) + DeepSeek-V4-Flash (LLM) diuji dengan kunci tim | [ ] | ___ |
| 14 Okt (Rab) | Pipeline inti | Endpoint inspeksi end-to-end (foto → verdict → audit record) | [ ] | ___ |
| 15 Okt (Kam) | Web + demo data | UI demo siap, dataset demo + manifes contoh terpasang | [ ] | ___ |
| 16 Okt (Jum) | Asset submission | Video direkam, slide selesai, README fresh-clone tested | [ ] | ___ |
| 17 Okt (Sab) | **Hardening + pre-submit** | Live URL stabil, semua field form terisi, jalankan Final Gate (§6) | [ ] | ___ |
| **18 Okt** | **DEADLINE SUBMIT (batas akhir)** | Submit terjadwal H-1 sore — lihat catatan di bawah; hari ini hanya buffer | [ ] | ___ |

**Usulan jam submit:** Submit di **sore H-1 (17 Okt, ±16:00–18:00)** setelah Final Gate lolos — menyisakan satu malam penuh untuk perbaikan jika form/platform bermasalah, tanpa perlu manual submission.

**Manual submission (LAST RESORT):** Hanya tersedia **6 jam setelah event berakhir** dan **wajib persetujuan panitia** (via Discord lablab.ai). Jangan direncanakan; ini mitigasi kalau platform error di hari-H. Kontak panitia secepatnya jika terjadi.

---

## 6. Pre-Submit Final Gate (±10 menit sebelum klik Submit)

Urutan verifikasi — kerjakan berurutan, **jangan klik Submit sebelum semua ✅**:

| # | [ ] | Verifikasi | Cara cek | PJ |
|---|---|---|---|---|
| 1 | [ ] | Demo URL hidup dari luar | Buka dari **incognito** + koneksi berbeda (HP tethering); bukan hanya dari mesin tim | ___ |
| 2 | [ ] | Video format benar | MP4, durasi **<5 menit**, ukuran **<300MB** — cek properti file, tonton full untuk glitch | ___ |
| 3 | [ ] | Semua field form terisi | Title ≤50, short desc ≤255, long desc ≥100 kata, tags, link repo, link video, link slide, link demo | ___ |
| 4 | [ ] | Repo publik | Buka URL repo di incognito tanpa login GitHub | ___ |
| 5 | [ ] | README tested fresh-clone | Clone ke folder kosong baru, ikuti README step-by-step, jalankan tanpa API key ter-commit (env var saja) | ___ |
| 6 | [ ] | Screenshot konfirmasi submit | Setelah klik Submit, simpan screenshot + nomor/tanggal sebagai bukti | ___ |

**Jika ada item gagak:** jangan submit; perbaiki dulu. Waktu aman tersedia karena submit dijadwalkan H-1 sore. Jika deadlock di hari terakhir → hubungi panitia via Discord (lihat §5 manual submission).

---

## Referensi internal

- `docs/research/demo-assets.md` — angka business value + sumber, standar RDF, pitch andalan
- `docs/research/amd-gpu-stack.md` — stack vLLM/ROCm/MI300X, kredit ADC/ADP, langkah deploy
- `docs/research/audit-provenance.md` — pola audit trail & provenance engine
- `docs/research/engine-map.md` — peta komponen engine
