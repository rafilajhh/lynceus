# Riset: Aset Demo & Angka Business Value Lynceus

## (a) Angka Business Value (dengan sumber)

| # | Angka | Sumber |
|---|-------|--------|
| 1 | Downtime tak terencana manufaktur global: **US$125.000/jam** (survey 3.215 responden, ABB/Sapio 2023) | https://new.abb.com/news/detail/107660/abb-survey-reveals-unplanned-downtime-costs-125000-per-hour |
| 2 | Shutdown kiln semen AS: **US$28.000/jam** (clinker hilang); 68% akibat maintenance terlewat | http://oxmaint.ai/article/cement-plant-maintenance-cmms-system-guide |
| 3 | Downtime pabrik semen: **US$10.000–40.000/jam** | https://www.cryotos.com/blog/how-to-reduce-downtime-in-cement-plants |
| 4 | Kiln idle 1 MTPA: **US$12.500–100.000/jam** | https://oxmaint.com/industries/manufacturing-plant/predictive-maintenance-roi-cement-usa |
| 5 | Shredder/pencacah di pasar Indonesia: unit kecil mulai **±Rp20 juta**; unit industri RDF jauh lebih tinggi (ratusan juta–miliar) | https://www.indotrading.com/surabaya/jual-mesin-pencacah |
| 6 | RDF sebagai substitusi bahan bakar menghemat **US$0,134/ton semen** vs gas & batu bara; spesifikasi umum kiln: NCV >14 MJ/kg, moisture <15%, Cl <0,8%, ash <15% | https://pmc.ncbi.nlm.nih.gov/articles/PMC13049024 |
| 7 | 11 pabrik semen Vietnam mengganti **±30% batu bara** dengan bahan bakar alternatif | https://ipen.org/wp-content/uploads/2024/11/summary_plastic_wastes_cgfed_final_nov18.pdf |

Kontaminan & moisture: kegagalan tube boiler akibat korosi/erosi & logam = penyebab downtime utama WtE (https://www.osti.gov/biblio/128729); moisture tinggi menurunkan LHV as-received drastis (klaim 18 MJ/kg dry basis turun banyak pada moisture 35%); SRF berkualitas 15–18 MJ/kg (https://www.osti.gov/biblio/20939472).

## (b) Strategi Dataset Foto

- **Utama**: Roboflow Universe (CC BY 4.0) — `waste_datasets` 2.872 gambar (https://universe.roboflow.com/trash-kupyl/waste_datasets) + vehicle-detection Kaggle (https://www.kaggle.com/datasets/daudshah/vehicle-detection-dataset) sebagai basis kelas truk; anotasi ulang kelas "truk sampah". Format YOLO/COCO, lisensi aman.
- **Fallback**: foto lapangan tim sendiri di TPS/TPA (metode rujukan: StreetView-Waste, WACV 2026, https://openaccess.thecvf.com/content/WACV2026/papers/Paulo_StreetView-Waste_A_Multi-Task_Dataset_for_Urban_Waste_Management_WACV_2026_paper.pdf) — 100% nyata lokal, tanpa risiko lisensi.
- Catatan: **tidak ada dataset publik khusus "garbage truck" terbuka** — dataset waste berfokus pada objek sampah, bukan kendaraan.

## (c) Standar RDF (ground truth demo)

1. **ISO 21640:2021** — Solid recovered fuels, Specifications and classes; klasifikasi via NCV, Cl, Hg — https://www.iso.org/standard/71309.html
2. **EN 15359:2011** — spesifikasi bentuk/ukuran partikel, moisture, ash, NCV, Cl, logam berat — https://www.zkg.de/en/artikel/zkg_Solid_Recovered_Fuels_Specifications_and_classes-2067874.html
3. **ISO 21654:2021** — Determination of calorific value — https://www.iso.org/standard/71319.html

## (d) Template Surat Jalan / Manifes (basis: GOV.UK Duty of Care Transfer Note, https://www.gov.uk/government/publications/duty-of-care-waste-transfer-note-template)

- Nomor manifes & tanggal transfer
- Penghasil sampah: nama, alamat, ID perusahaan
- Pengangkut: nama, alamat, nomor lisensi angkut, nomor polisi kendaraan
- Penerima: nama, alamat, nomor izin fasilitas
- Deskripsi sampah: jenis/kode klasifikasi, bentuk fisik, jenis wadah
- Kuantitas: berat (ton) / volume (m³)
- Data kualitas RDF (opsional demo): % moisture, NCV (MJ/kg), % Cl, % ash
- Pernyataan waste hierarchy + tanda tangan pengirim & penerima

## Pitch Andalan

Satu shredder RDF industri bernilai ratusan juta rupiah, tapi cukup satu kontaminan logam/batu lolos — kiln berhenti 1 jam = kerugian US$28.000 (±Rp450 juta), dan kegagalan akibat kontaminan adalah penyebab downtime WtE paling umum. Inspeksi otomatis Lynceus di pintu masuk = "biaya cegah" yang jauh lebih murah dari satu jam kiln mati.
