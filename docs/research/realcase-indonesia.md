# Riset Real-Case Indonesia untuk Demo Lynceus

> Tujuan: setiap angka demo (komposisi sampah, tonase RDF, muatan truk, field surat jalan, dampak Rp) harus bisa menjawab "dari mana". Setiap angka di bawah disertai URL sumber.
> Disusun: riset web Oktober 2026. Kurs acuan dari sumber masing-masing; untuk konversi USD→Rp baru gunakan kurs ~Rp 15.000–16.500/USD (kisaran kurs 2023–2026) dan sebutkan eksplisit saat dipakai di demo.

---

## 1. Komposisi MSW Indonesia (input WasteComposition engine)

### 1a. Studi #1 — SIPSN KLH/KLHK, data nasional 2025 (resmi pemerintah)

| Komponen | % berat (nasional 2025) |
|---|---|
| Sisa makanan (organik) | 40,77% |
| Plastik | 20,52% |
| Kayu–ranting | 13,13% |
| Kertas–karton | 11,40% |
| Logam | 3,11% |
| Kain | 2,51% |
| Kaca | 2,39% |
| Karet–kulit | 0,45% (sisa ke ~100%) |
| Lainnya | ~4,7% (sisa) |

- Sumber angka: GoodStats Data merujuk SIPSN Kementerian Lingkungan Hidup — https://data.goodstats.id/statistic/komposisi-sampah-nasional-2025-didominasi-sisa-makanan-pgp9R (artikel 21 Mei 2026); portal asli: https://sampahnasional.kemenlh.go.id/indikatif/public/data/komposisi
- Pembanding tahun sebelumnya (SIPSN 2023): sisa makanan 41,4% — https://mahasiswaindonesia.id/mengungkap-krisis-food-waste-di-perkotaan-bukti-data-dampak-nyata-dan-strategi-mitigasi-berkelanjutan
- Total timbulan nasional 2024 ≈ 34,0 juta ton/tahun; plastik 19,48% — https://ejournal.utp.ac.id/index.php/JPF/article/download/5702/520523285
- Konteks: 10,8 juta ton sampah plastik nasional; daur ulang plastik baru ~22% — pernyataan Menteri LH Hanif Faisol Nurofiq (GoodStats, URL di atas).

### 1b. Studi #2 — Damanhuri dkk. (ITB), bab Springer 2014 "Municipal Solid Waste Management in Indonesia"

Komposisi sampah Jakarta 2005 (survei SWM Jakarta Master Plan Review; % berat basah):

| Komponen | Jakarta 2005 | Jakarta 2001 (JCI survey) |
|---|---|---|
| Organik (garbage/daun) | 74,7% | 55,4% |
| Kertas | 8,3% | 20,6% |
| Plastik/styrofoam | 5,4% | 13,3% |
| Kayu | 3,8% | 0,1% |
| Tekstil | 3,2% | 0,6% |
| Karet/kulit | 0,6% | 0,2% |
| Logam | 1,4% | 1,1% |
| Kaca | 1,8% | 1,9% |
| Limbah konstruksi | 1,0% | 0,8% |
| B3 | — | 1,5% |
| Lainnya | 1,0% | 4,7% |

- Bandung (2 transfer station, Juli 2007): organik 60,1–63,6% (wet-weight), anorganik non-daur ulang ~32–34%, komponen daur ulang ~4–5,7% — Tabel 5 bab yang sama.
- Temuan umum studi ini: MSW Indonesia didominasi organik >55%-berat; kadar air MSW ~65%.
- Sumber teks lengkap (mirror bab Springer, DOI 10.1007/978-981-4451-73-4_8): https://pdfcoffee.com/municipal-solid-waste-management-in-indonesia-4-pdf-free.html

### 1c. Studi #3 (pembanding kota) — Komposisi Jakarta per sumber, Damanhuri

Jakarta 2005 per sumber (%): rumah tangga 51%, pasar 5%, sekolah 5%, komersial 26%, industri/instansi 9%, lainnya (jalan, drainase) 4% — Tabel 3 bab yang sama (URL sama dengan 1b).

**Catatan untuk engine Lynceus:** dua studi sengaja dibedakan — (a) SIPSN nasional 2025 sebagai "compositional baseline" modern untuk skenario nasional; (b) Damanhuri sebagai studi akademik dengan breakdown lengkap 9 kategori + data historis (1981–2005) untuk tren. Plastik nasional ~19–21% konsisten antar studi; organik 40–75% tergantung tahun/lokasi — parameter engine yang tepat adalah *range* + sumber eksplisit.

---

## 2. RDF co-processing di pabrik semen Indonesia (konteks demo)

### 2a. Semen Indonesia Group (SIG/SMGR) — angka group

| Parameter | Nilai | Sumber |
|---|---|---|
| Bahan bakar alternatif (AFR) 2023 | 559.625 ton (naik 27% dari 437.232 ton di 2022) | https://money.kompas.com/read/2024/04/25/100000626/smgr-gunakan-559.000-ton-bahan-bakar-alternatif-untuk-operasional-apa |
| Thermal Substitution Rate (TSR) 2023 | 7,27% | URL sama (pernyataan Corp. Sec. SMGR Vita Mahreyni, 24/3/2024) |
| RDF murni (MSW) di 3 pabrik SBI (Narogong, Cilacap, Tuban) 2023 | 30.061 ton | URL sama |
| SIG pelopor RDF industri semen sejak | 2020 | https://www.sig.id/sig-gandeng-resinergi-untuk-tingkatkan-penggunaan-bahan-bakar-alternatif-dari-sampah-perkotaan (10/1/2025) |
| MOU offtake RDF dengan RESINERGI | 6 Januari 2025 | URL sama |
| Biomassa sekam padi Pabrik Tuban | 400 ton/hari | https://money.kompas.com/read/2026/09/24/111000326/semen-indonesia-manfaatkan-400-ton-sekam-padi-per-hari-sebagai-bahan-bakar |

### 2b. RDF Gresik (TPST Belahanrejo & Ngipik) — konteks pabrik Gresik/Tuban

- Kerja sama SIG–Pemkab Gresik (kesepakatan 29 Feb 2024, rilis 4 Mar 2024): RDF dari TPST **Belahanrejo** dan **Ngipik** dikirim ke **Pabrik Tuban** sebagai substitusi batu bara.
- Spesifikasi per TPST: kapasitas kelola sampah 200 ton/hari; input mesin 20 ton/hari → output **3,8 ton/hari RDF anorganik + 9 ton/hari RDF organik**.
- Sumber: https://www.tribunnews.com/bisnis/2024/03/04/kejar-target-penurunan-emisi-pabrik-semen-kembali-dapat-pasokan-sampah-pengganti-batu-bara

### 2c. Solusi Bangun Indonesia (SBI, anak SIG) Cilacap — kasus RDF MSW pertama di Indonesia

| Parameter | Nilai | Sumber |
|---|---|---|
| Mulai investigasi RDF | 2013 (masih di grup Holcim) | https://www.switch-asia.eu/site/assets/files/4106/sbi_final.pdf (studi kasus EU SWITCH-Asia, 2024) |
| Pilot project | 2017; resmi diluncurkan 2020 | URL sama |
| Kapasitas kelola | 160 ton sampah/hari (≤58.000 ton/tahun) | URL sama |
| Output RDF | ~70 ton/hari (≤23.000 ton/tahun), ~50% berat input | URL sama |
| Nilai kalor RDF | ~3.000 kcal/kg | URL sama |
| Kadar air MSW (alasan pre-processing wajib) | 55–60% | URL sama |
| Subsidi pemerintah (PUPR+KLHK/DANIDA+Pemprov/Pemkab) | Rp 84 miliar (≈ EUR 4,9 juta) | URL sama |
| Harga jual RDF ke SBI | Rp 300.000/ton | URL sama |
| Pasokan tambahan dari Banyumas (pirolisis) | ~24 ton/hari sejak 2023 | URL sama |
| TSR SBI 2022 | 11,73%; AFR+AFR total termanfaatkan 1.582.844 ton (2022); target 1,4 juta ton limbah/tahun per 2030; reduksi CO2 29% vs baseline 2010 | https://solusibangunindonesia.com/wp-content/uploads/2025/03/SBI_SR_2022-Koreksi-1.pdf |
| TPST Cilacap (PUPR): RDF 60 ton/hari dibeli SBI sebagai offtaker | 60 ton/hari | https://ciptakarya.pu.go.id/berita-detail?13524 |

### 2d. RDF Bantargebang (DKI) & Indocement

| Parameter | Nilai | Sumber |
|---|---|---|
| Kapasitas produksi RDF TPST Bantargebang | 700 ton/hari | https://asi.or.id/id/pemprov-dki-mulai-jual-rdf-bantargebang-dibanderol-rp-360-000-per-ton (Kompas, 27/6/2023) |
| Kebutuhan offtaker (Indocement + SBI) | 2.500 ton/hari (pasokan baru 700) | URL sama |
| Harga jual | Rp 360.000/ton (= US$24; kurs implisit Rp 15.000/USD) | URL sama |
| Pengiriman perdana | 20 truk ≈ 80 ton RDF (27/6/2023) | URL sama |
| Indocement–UPST DKI: RDF Purchase Agreement Rorotan | 16 Desember 2025 (lanjutan kerja sama Bantargebang) | https://www.indocement.co.id/en/news-events/indocement-strengthens-sustainable-waste-management-through-rdf-utilization-at-rorotan-plant-jakarta |
| RDF Plant Rorotan, investasi | Rp 1,28 triliun | https://www.antarafoto.com/view/2457837/waste-processing-in-rdf-plant-rorotan-jakarta (25/2/2025) |
| Skala khas pemakaian RDF di tanur semen | ~5% dari total tonase bahan bakar | RDI 2024, https://dashboard.rdiglobal.org/storage/publications/file/OgidnCyQqXihV2iFnsOB2cDOTmjDRVkOZ9cSFMUM.pdf (Bab 3) |

### 2e. Kapasitas input/output tiga RDF plant (RDI 2024, untuk validasi model)

| Plant | Input sampah desain (tpd) | Input aktual (tpd) | Output RDF desain (tpd) | Output aktual (tpd) |
|---|---|---|---|---|
| Banyumas | 100 | 75 | 40 | 35 |
| Cilacap | 200 | 150 | 80 | 75 |
| Bantargebang | 2.200 | 950 | 700 (desain awal 950) | 400 |

- Sumber: RDI (2024) *Kajian Strategi Pembiayaan dan Analisis Ekonomi Proyek RDF dalam Pengelolaan Sampah di Indonesia*, Tabel III.2 — https://dashboard.rdiglobal.org/storage/publications/file/OgidnCyQqXihV2iFnsOB2cDOTmjDRVkOZ9cSFMUM.pdf

---

## 3. Kelas truk sampah Indonesia & berat muatan nyata

### 3a. Densitas sampah per jenis truk (Surabaya, jurnal terpublikasi)

| Jenis armada | Densitas sampah di bak | Kapasitas bak (studi) | Muatan nyata per trip | Sumber |
|---|---|---|---|---|
| Truk kompaktor | 742,44 kg/m³ | 10 m³ | ≈ 7,4 ton/trip | https://ejurnal.itats.ac.id/sntekpan/article/download/1267/1030 (Semnas SNTT VIII 2020, ITATS Surabaya; berat diukur jembatan timbang TPA Benowo) |
| Truk arm roll | 372,71 kg/m³ | 14 m³ (kontainer logam TPS) | ≈ 5,2 ton/trip | URL sama |
| Kompaktor (studi pembanding, Dianbudiyanto 2015) | 669,55 kg/m³ (faktor kompaksi 3,14) | — | — | dikutip di URL sama |
| Arm roll (studi pembanding, Dianbudiyanto 2015) | 471,44 kg/m³ (faktor kompaksi 2,34) | — | — | dikutip di URL sama |

Waktu operasional (Surabaya, studi yang sama): kompaktor 8,17 jam/hari; arm roll 8,5 jam/hari; waktu offroute 2,33 vs 2,7 jam. Ritasi dihitung per trip TPS→TPA.

### 3b. Kapasitas muatan truk sampah per jenis (industri otomotif)

| Jenis | Kapasitas muatan | Volume | Sumber |
|---|---|---|---|
| Front loader | 4 ton | ~30 m³ | https://astraudtrucks.co.id/berita/termasuk-kendaraan-besar-berapa-ton-muatan-truk-sampah-12-2024 |
| Side loader | ~14 ton (sampah padat) | ~22 m³ | URL sama |
| Rear loader | hingga 18 ton | 4,5–27 m³ | URL sama |
| Roll off (≈ arm roll) | ~10 ton per perjalanan | kontainer besar | URL sama |

### 3c. GVW / Muatan Sumbu Terberat (MST) — regulasi Indonesia

| Aturan | Isi kunci | Sumber |
|---|---|---|
| UU No. 22/2009 (LLAJ) Pasal 169 | larangan muatan melebihi dimensi/berat yang ditetapkan; denda maks Rp 500.000 | https://isuzuniaga.com/regulasi-muatan-sumbu-terberat-mst-dan-dampaknya-bagi-truk |
| PP No. 55/2012 | MST standar 8 ton/sumbu (jalan nasional kelas I boleh 10 ton) | URL sama |
| Permenhub PM 134/2015 | UPPKB / jembatan timbang jalan | URL sama |
| PP No. 30/2021 | pengawasan muatan berlebih & sanksi | URL sama |
| JBI tipikal 4×2 | 12–16 ton (payload efektif 5–8 ton) | URL sama (tabel konfigurasi) |
| JBI tipikal tronton 6×4 | 20–24 ton (payload 12–16 ton) | URL sama |
| Contoh nyata: truk 2 sumbu | tare 4.500 kg + muatan 6.000 kg → GVW 10.700 kg; sumbu belakang 7,49 ton (aman <8) | URL sama |
| Referensi dump truck global | single-axle 10–12 ton; tandem 14–18 ton | https://theupfitinsider.com/p/how-many-tons-can-a-dump-truck-haul |
| Faktor konversi DLH Lampung (2022) | 1 m³ sampah ≈ 2,67 ton; truck engkel 3 m³ ≈ 2 ton | https://dlh.lampungprov.go.id/pages/kapasitas-angkutan-kendaraan-2022 (halaman 403 saat diakses; angka dari cuplikan indeks pencarian — verifikasi ulang bila dipakai sebagai angka utama demo) |

**Angka demo yang direkomendasikan** (paling kuat sumbernya): arm roll 14 m³ × 372,71 kg/m³ ≈ **5,2 ton/trip**; kompaktor 10 m³ × 742,44 kg/m³ ≈ **7,4 ton/trip** (jurnal ITATS, diukur di jembatan timbang TPA Benowo).

---

## 4. Format surat jalan / timbangan sampah Indonesia (field lapangan)

### 4a. Field pencatatan di gerbang TPA (standar PUPR)

SOP Penerimaan Sampah di TPA (materi Rakernis Adipura 2019, Kementerian PUPR Ditjen Cipta Karya) — field yang dicatat petugas saat truk masuk:

1. Nomor polisi truk
2. Nama pengemudi
3. Waktu masuk TPA (jam)
4. Sumber sampah (asal TPS/kecamatan)
5. Berat sampah / volume sampah (sesuai volume bak truk; via **jembatan timbang**)
6. Pemeriksaan kondisi sampah (tolak B3, medis, industri)

- Sumber: https://bulelengkab.go.id/informasi/download/pengelolaan-tpa-yang-baik-landfill-52.pdf (slide "Bagan Alir Proses Penanganan Sampah di TPA", hlm. 13)
- Jembatan timbang tercantum sebagai fasilitas penunjang TPA wajar (slide 11). Truk yang boleh masuk: milik dinas atau berizin (truk swasta), non-B3/medis.
- Struktur petugas TPA menyebut eksplisit "Petugas Pencatat Sampah (1 orang)" dan "Petugas Pengatur Lalu Lintas Kendaraan di TPA" (slide 5).

### 4b. Praktik nyata penimbangan

- Berat sampah Surabaya diukur dengan **jembatan timbang TPA Benowo** → dasar perhitungan densitas (jurnal ITATS, URL di §3a).
- Form Neraca Sampah SIPSN (UPST DLH DKI): per TPS 3R dicatat **Organik ... kg, Anorganik ... kg, Lain-lain ... kg**, termasuk "Diangkut oleh jasa angkutan sampah yang berizin" — https://upstdlh.id/files/01-FNS%28FORM_NERACA_SAMPAH%29.pdf

### 4c. Format nomor polisi Indonesia (untuk field `plate_number`)

- Format umum: **[1–2 huruf kode wilayah] [1–4 angka] [1–3 huruf]**, contoh nyata di jurnal ITATS: `L 9282 AP`, `L 9820 NP`, `L 9424 NP`, `L 8057 QP` (L = Surabaya).
- Kode wilayah relevan untuk demo koridor semen Jawa: **W = Gresik/Sidoarjo**, **L = Surabaya**, **S = Bojonegoro/Mojokerto/Lamongan/Tuban** (pabrik Tuban), **R = Banyumas/Cilacap** (pabrik Cilacap), **B = Jakarta/Depok/Tangerang/Bekasi** (Bantargebang), **F = Bogor** (Narogong), **T = Karawang**.
- Sumber daftar kode: https://www.antaranews.com/berita/4661277/daftar-kode-huruf-plat-nomor-kendaraan-di%C2%A0seluruh-wilayah-indonesia
- (Catatan: format teknis TNKB diatur Korlantas Polri; ANTARA dipakai sebagai rujukan daftar kode.)

### 4d. Skeleton surat jalan demo (turunan dari sumber di atas)

```
SURAT JALAN / TIKET TIMBANG (RDF-MSW)
No. SJ      : SJ/RDF/2026/10/0001       Tanggal: __-__-____  Jam masuk: __:__
No. Polisi  : B 9282 AP (contoh: 1-2 huruf + 1-4 angka + 1-3 huruf)
Pengemudi   : ________  Sumber/Asal     : TPS ______ / TPST ______
Tujuan      : TPA ______ / Pabrik Semen ______ (RDF)
Bruto (kg)  : ________   Tarra (kg)     : ________
Netto (kg)  : Bruto - Tarra             Operator timbang: ________
Jenis muatan: MSW / RDF  Komposisi dominan: organik __% plastik __%
Verifikasi  : □ non-B3  □ non-medis  □ kadar air/nilai kalor (RDF)
```

Field bruto–tarra–netto mengikuti praktik jembatan timbang (UPPKB/TPA Benowo); field lain dari SOP PUPR §4a.

---

## 5. Angka dampak dalam Rupiah

### 5a. Downtime kiln semen

Belum ditemukan angka downtime kiln spesifik perusahaan Indonesia yang terpublikasi; benchmark internasional (dipakai dengan kurs eksplisit):

| Parameter | Nilai USD | ≈ Rupiah (kurs Rp 16.000/USD, harus dinyatakan di demo) | Sumber |
|---|---|---|---|
| Biaya jam idle kiln (rentang) | US$12.500–100.000/jam | Rp 200 juta–1,6 miliar/jam | https://oxmaint.com/industries/manufacturing-plant/predictive-maintenance-roi-cement-usa |
| Rata-rata unplanned shutdown (produsen AS) | ~US$28.000/jam lost clinker | ~Rp 450 juta/jam | https://oxmaint.ai/article/cement-plant-maintenance-cmms-system-guide |
| Kiln 5.000 tpd, emergency stop | US$38K–52K/jam | Rp 610–830 juta/jam | https://oxmaint.com/industries/cement-plant/cement-plant-emergency-maintenance-response-protocol |
| Reline refractory | material US$800.000–1,5 juta + shutdown 12–16 hari US$350–500rb | material Rp 12,8–24 miliar; shutdown Rp 5,6–8 miliar | https://oxmaint.com/industries/cement-plant/cement-kiln-refractory-maintenance-lining-life |
| Downtime per hari (continuous process) | >US$300.000/hari lost clinker | >Rp 4,8 miliar/hari | https://ifactoryapp.com/industries/cement-plant/cement-reliability-engineering-dashboard |
| Benchmark kiln besar (produksi) | 1.450°C, hingga 6.000 ton klinker/hari | — | https://oxmaint.com/industries/cement-plant/cement-rotary-kiln-maintenance-guide |

Konteks Indonesia yang bisa dikutip (bukan downtime, tapi pendukung): industri semen nasional terancam berhenti operasi saat krisis pasokan batu bara (Bisnis.com, Apr 2026) — https://www.bisnis.com/topic/8823/industri-semen

### 5b. Harga & biaya mesin shredder / RDF plant (RDI 2024, Lampiran 2 — RAB resmi)

| Komponen | Nilai | Sumber |
|---|---|---|
| Shredder (1 unit, masa ekonomi 5 tahun) | **Rp 350.000.000** | https://dashboard.rdiglobal.org/storage/publications/file/OgidnCyQqXihV2iFnsOB2cDOTmjDRVkOZ9cSFMUM.pdf (Lampiran 2A, Banyumas) |
| Bag opener | Rp 150–200 juta/unit (5 tahun) | URL sama |
| Mesin cacah plastik | Rp 500 juta (10 tahun) | URL sama |
| Dump truck (alat angkut RDF) | Rp 600 juta/unit (10 tahun) | URL sama |
| CAPEX total RDF Banyumas (100 tpd) | Rp 20,58 miliar | URL sama |
| CAPEX total RDF Cilacap (200 tpd) | Rp 71 miliar; pendanaan gabungan ±Rp 84 miliar (mesin Rp 44 M DANIDA + konstruksi Rp 27 M PUPR + infrastruktur Rp 10 M APBD Prov + lahan Rp 3 M APBD Kab.) | URL sama (Lampiran 2B/2C) |
| CAPEX total RDF Bantargebang | Rp 560,73 miliar (pendanaan tercatat Rp 1,07–1,14 triliun) | URL sama |
| RDF Plant Rorotan | Rp 1,28 triliun | https://www.antarafoto.com/view/2457837/waste-processing-in-rdf-plant-rorotan-jakarta |
| Benchmark India (≤100 tpd) | INR 125,4–153 juta CAPEX | URL RDI (Bab 3, MoHUA India 2018) |

### 5c. OPEX & biaya pemeliharaan (RDI 2024, Lampiran 3)

| Komponen | Banyumas | Cilacap | Bantargebang | Sumber |
|---|---|---|---|---|
| OPEX total/tahun | Rp 3,8 miliar | Rp 4,587 miliar | Rp 33,74 miliar | RDI Lampiran 3 (URL sama) |
| Perawatan dump truck/tahun | Rp 100 juta | Rp 600 juta | — | URL sama |
| Asumsi biaya pemeliharaan mesin (bila tak dilaporkan) | 7% dari CAPEX per tahun | 7% | 7% | RDI Tabel III.4 |
| Tenaga kerja | 98 orang, Rp 1,9 M/th | 32 orang, Rp 1,497 M/th | 324 orang, Rp 22,08 M/th | URL sama |
| Listrik | Rp 720 juta/th | Rp 1,44 M/th | 5 MW, Rp 10,2 M/th | URL sama |

### 5d. Harga & nilai ekonomi RDF (Rupiah)

| Item | Nilai | Sumber |
|---|---|---|
| Harga RDF Bantargebang | Rp 360.000/ton (US$24) | https://asi.or.id/id/pemprov-dki-mulai-jual-rdf-bantargebang-dibanderol-rp-360-000-per-ton |
| Harga RDF Cilacap (ke SBI) | Rp 300.000/ton | https://www.switch-asia.eu/site/assets/files/4106/sbi_final.pdf |
| Harga RDF Cilacap (RDI, aktual) | Rp 414.000/ton | RDI Tabel III.3 (URL RDI) |
| Harga RDF Banyumas & Bantargebang (RDI) | Rp 360.000/ton | URL RDI |
| Harga RDF Tangerang (ke SBI) | Rp 300.000/ton | https://banten.idntimes.com/news/banten/pemkot-tangerang-jual-sampah-rdf-rp300-ribu-per-ton-00-5f5kb-8rctsy |
| Harga RDF Kalsel (pasar, fluktuatif ikut USD) | ~Rp 450.000/ton | https://suarindonesia.com/sampah-low-value-plastik-ciki-cikian-jadi-bahan-bakar-pabrik-semen-di-kalsel |
| Pendapatan RDF Banyumas | Rp 327,6 juta/bulan; Rp 3,93 miliar/tahun (35 tpd) | RDI Tabel III.3 |
| Pendapatan RDF Cilacap | Rp 745,2 juta/bulan; Rp 8,94 miliar/tahun | URL RDI |
| Pendapatan RDF Bantargebang | Rp 2,376 miliar/bulan; Rp 28,5 miliar/tahun | URL RDI |
| Penghematan ops TPST per ton sampah dialihkan | Rp 58.000/ton | RDI Bab 3 (URL RDI) |
| Nilai penghematan lahan TPST | Rp 658.036/m² area timbunan | RDI Tabel III.4 |
| Biaya karbon (asumsi pajak karbon nasional) | Rp 30.000/ton CO2eq (harga perdagangan karbon internasional RI: Rp 96–144 ribu/ton) | URL RDI + https://www.tempo.co (dikutip RDI) |
| Kelayakan: NPV/IRR 10 th (diskonto 5%) | Banyumas IRR 32,27% B/C 2,79; Cilacap IRR 9,79% B/C 1,31; Bantargebang IRR 8,39% B/C 1,23 | RDI Tabel III.8 |

### 5e. Kontaminan → biaya (rantai kausal untuk demo)

- Kadar air MSW Indonesia 55–60% → RDF tidak bisa langsung dibakar, wajib MBT 21 hari (Cilacap) — biaya tersembunyi di OPEX di atas: https://www.switch-asia.eu/site/assets/files/4106/sbi_final.pdf
- Susut massa: RDF ≈ 50% berat input; 35% volume menguap; 15% inert dibuang (Cilacap) — URL sama.
- Komposisi menentukan nilai kalor: RDF ≈ nilai kalor batu bara kualitas rendah–menengah; RDF sampah baru > sampah lama (organik terurai) — RDI Bab 3 §3.3.2.
- Konsumsi RDF di tanur semen nasional baru ~5% kebutuhan bahan bakar; TSR SIG 7,27% (2023) → ruang skenario substitusi untuk engine demo (URL RDI + Kompas §2a).

---

## Ringkasan angka demo paling kuat (quick reference)

| Angka demo | Nilai | Dari mana |
|---|---|---|
| Komposisi organik nasional | 40,77% (2025) | SIPSN via GoodStats (§1a) |
| Komposisi plastik | 20,52% (2025) / 5,4% (Jakarta 2005, Damanhuri) | §1a/§1b |
| TSR SIG 2023 | 7,27% | Kompas (§2a) |
| RDF Gresik per TPST | 3,8 t/hari anorganik + 9 t/hari organik | Tribunnews (§2b) |
| Muatan arm roll | ~5,2 ton/trip (14 m³ × 372,71 kg/m³) | Jurnal ITATS (§3a) |
| Muatan kompaktor | ~7,4 ton/trip (10 m³ × 742,44 kg/m³) | Jurnal ITATS (§3a) |
| Field surat jalan | nopol, pengemudi, jam masuk, sumber, bruto/tarra/netto | SOP PUPR Adipura 2019 (§4a) |
| Harga RDF | Rp 300–450 ribu/ton | ASI/SWITCH-Asia/RDI (§5d) |
| Harga shredder | Rp 350 juta | RDI Lampiran 2 (§5b) |
| Downtime kiln | ~US$28 ribu/jam ≈ Rp 450 juta/jam (kurs harus dinyatakan) | oxmaint (§5a) |
