# Riset: Dataset Publik Foto Sampah (MSW / Kontaminan / RDF-Feedstock) untuk 3 Varian Demo Lynceus

> Riset web read-only (13 Okt 2026). Tujuan: kandidat dataset foto tumpukan sampah MSW / konveyor / limbah dengan kontaminan terlihat (logam, batu, ban, e-waste) untuk varian demo HIJAU (muatan bersih) / KUNING (organik/lembap) / MERAH (kontaminan keras terlihat).
> Setiap angka dan klaim diverifikasi dari sumber primer (halaman dataset/paper/GitHub/Zenodo/UCI) pada tanggal riset.

---

## (a) Ringkasan kandidat (tabel)

| # | Nama | URL langsung | Jumlah gambar | Kelas label (persis) | Lisensi eksplisit | Format |
|---|------|--------------|--------------:|----------------------|-------------------|--------|
| 1 | **RealWaste** | https://archive.ics.uci.edu/dataset/908/realwaste | 4.752 (524×524) | Cardboard (461), Food Organics (411), Glass (420), Metal (790), Miscellaneous Trash (495), Paper (500), Plastic (921), Textile Trash (318), Vegetation (436) | **CC BY 4.0** (eksplisit di halaman UCI, "sharing and adaptation for any purpose with credit") | Folder-per-kelas JPG (klasifikasi), download zip 656,6 MB |
| 2 | **TrashBox** | https://github.com/nikhilvenkatkumsetty/TrashBox (mirror data: https://github.com/vanessaxlee/trashbox) | 17.785 (train; test/val "will be updated soon") | Medical waste (2.010: syringe, gloves, masks, medicines), E-Waste (2.883: chips, laptops/smartphones, appliances, wires/cables), Plastic (2.669), Paper (2.695), Metal (2.586: cans, construction scrap, spray cans), Glass (2.528), Cardboard (2.414) | **Tidak eksplisit — TANDAI** (repo data tidak membawa file LICENSE; hanya CITATION.cff; kategori lisensi di AgaMiko review = "?") | Folder-per-kelas JPG (klasifikasi) |
| 3 | **TACO** (Trash Annotations in Context) | https://github.com/pedropro/TACO · http://tacodataset.org/ | 1.500 (4.784 anotasi; versi paper 2020) | 60 kategori / 28 super-kategori (lihat §b) — a.l. Scrap metal, Battery, Broken glass, Glass jar/bottle, Food waste, Drink/Food can, Corrugated carton, Normal paper, Plastic bag & wrapper | Anotasi **CC BY 4.0**; gambar: lisensi per-gambar dari Flickr (bervariasi, tercantum per-file di annotations.json; default CC BY 4.0 bila kosong) | **COCO** JSON instance-segmentation + bbox |
| 4 | **DroneWaste v1.0** | https://doi.org/10.5281/zenodo.17045559 · https://github.com/lucamora/dronewaste | 4.993 (5.135 anotasi, 17 site dumping) | 20 kategori (kode EWC): Rubble, Construction and demolition materials, Asphalt milling, Excavation materials, Appliances, Electronic equipment, Furniture, Metal barrels, Plastic packaging, Wood, Pallets, Scrap, Plastic, Vehicles, **Tyres**, Paper, Foundry (slag), Asbestos, Textile, Mixed items | Record Zenodo ditandai **Open**; lisensi eksplisit SPDX tidak dicantumkan pada record — **TANDAI: konfirmasi langsung via info/README sebelum pakai komersial** (kode repo MIT) | COCO JSON (mask+bbox), images.tar.gz 3,9 GB |
| 5 | **ZeroWaste** (CVPR 2022) | https://github.com/dbash/zerowaste · dataset: https://doi.org/10.5281/zenodo.4899926 | 4.503 labeled (+6.212 unlabeled, +1.410 weakly) | 4 kelas sem-seg: {Salvage, Background, LD film recyclable, HD film non-recyclable} — konteks **konveyor pabrik daur ulang** ("before/after" dari belt) | Dataset **CC BY-NC 4.0** (NonCommercial — perhatian untuk demo komersial/pitch) | COCO JSON instance-segmentation |
| 5b | **Roboflow Universe `waste_datasets`** (basis PLAN saat ini) | https://universe.roboflow.com/trash-kupyl/waste_datasets | 2.872 | Kelas tidak terverifikasi per 13 Okt (halaman 403/bot-block saat riset; mAP@50 48,6% menandakan deteksi multi-kelas) | CC BY 4.0 | Roboflow export (YOLO/COCO) |
| 5c | **Kaggle `mostafaabla/garbage-classification`** | https://www.kaggle.com/datasets/mostafaabla/garbage-classification | 15.150 | battery, biological, brown-glass, cardboard, clothes, green-glass, metal, paper, plastic, shoes, trash, white-glass (12 kelas) | **Tidak eksplisit — TANDAI** (data card tidak mencantumkan lisensi) | Folder-per-kelas JPG |
| 5d | **TrashNet** (Stanford CS 229) | https://github.com/garythung/trashnet · HF: https://huggingface.co/datasets/garythung/trashnet | 2.527 (512×384) | glass (501), paper (594), cardboard (403), plastic (482), metal (410), trash (137) | **MIT** (repo; sitasi diminta) | ZIP folder-per-kelas (dataset-resized.zip; original ~3,5 GB) |

---

## (b) Detail verifikasi per kandidat

### 1. RealWaste (UCI ML Repo) — konteks landfill asli ⭐ kandidat utama

- **URL**: https://archive.ics.uci.edu/dataset/908/realwaste (DOI 10.24432/C5SS4G)
- **Jumlah**: 4.752 gambar berwarna 524×524, ditangkap di **point of reception lingkungan landfill asli** (bukan studio) — paling dekat dengan konteks foto muatan truk Lynceus.
- **Kelas + jumlah per kelas** (dari halaman UCI, verbatim): Cardboard: 461, Food Organics: 411, Glass: 420, Metal: 790, Miscellaneous Trash: 495, Paper: 500, Plastic: 921, Textile Trash: 318, Vegetation: 436.
- **Lisensi**: CC BY 4.0 (eksplisit: "allows sharing and adaptation of the datasets for any purpose, provided appropriate credit").
- **Format**: zip folder-per-kelas (realwaste-main/RealWaste/<Kelas>/), 656,6 MB; paper pendamping MDPI Information 14(12):633.
- **Catatan demo**: Metal (790) & Glass (420) → kontaminan keras; Food Organics + Vegetation (847) → organik; Paper/Cardboard/Plastic bersih → HIJAU. **Satu dataset, 3 varian.**

### 2. TrashBox (FRUCT conference) — kontaminan keras lengkap (e-waste + medical)

- **URL**: https://github.com/nikhilvenkatkumsetty/TrashBox (repo resmi menurut AgaMiko review & PDF deskripsi; mirror data yang saya verifikasi file-by-file: https://github.com/vanessaxlee/trashbox).
- **Jumlah**: 17.785 gambar train (test/val belum dirilis).
- **Kelas + jumlah**: Medical waste 2.010, E-Waste 2.883, Plastic 2.669, Paper 2.695, Metal 2.586, Glass 2.528, Cardboard 2.414 — dengan subkelas (mis. metal = beverage cans, construction scrap, spray cans, food grade cans; e-waste = chips, laptops/smartphones, appliances, wires/cables).
- **Lisensi**: **TIDAK EKSPLISIT — TANDAI** (tidak ada LICENSE di repo; hanya CITATION.cff yang meminta sitasi paper FRUCT). Gunakan hanya setelah konfirmasi penulis bila dipakai di aset publik.
- **Format**: folder-per-kelas JPG, langsung dari repo GitHub.
- **Catatan demo**: E-Waste (2.883) + Medical (2.010) + Metal (2.586) = kontaminan terlihat untuk MERAH; jumlah terbesar untuk kelas kontaminan di semua kandidat.

### 3. TACO — anotasi COCO terkaya + taksonomi hingga broken glass/battery/scrap metal

- **Jumlah**: 1.500 gambar, 4.784 anotasi (paper v2, 2020); dataset tumbuh via crowdsourcing (server live menunjukkan 715+2.404 images in pipeline saat riset).
- **Kelas**: taksonomi 28 super/60 kategori (daftar lengkap di http://takodataset.org/taxonomy). Kelas relevan per varian:
  - **MERAH**: Scrap metal, Battery, Broken glass, Glass jar, Glass bottle, Metal bottle cap, Metal lid, Aerosol, Drink can, Food can, Pop tab, Shoe, Rope.
  - **HIJAU**: Corrugated carton, Normal paper, Magazine paper, Paper bag, Clear plastic bottle, Drink carton, Paper cup/straw.
  - **KUNING**: Food waste; Tissues (paper basah/lembap).
  - Context tags Litter/Not-litter & scene tags (trash/vegetation/dirt) untuk filter foto "tumpukan" vs "objek tunggal".
- **Lisensi**: anotasi CC BY 4.0; **gambar per-file dari Flickr dengan lisensi bervariasi** (tercantum di annotations.json per image + URL asal) — untuk demo cukup pilih subset gambar berlisensi CC.
- **Format**: COCO JSON (instance segmentation polygon) + CSV URL.
- **Catatan demo**: bbox/mask per objek memungkinkan komposit kontaminan onto tumpukan (teknik ZeroWasteAug: paste TACO crops onto frames).

### 4. DroneWaste v1.0 — tumpukan/dumping asli 17 site, kelas berkode EWC

- **URL**: dataset https://doi.org/10.5281/zenodo.17045559 · kode MIT https://github.com/lucamora/dronewaste · preprint https://zenodo.org/records/17288038 (PERIVALLON EU Horizon)
- **Jumlah**: 4.993 gambar, 5.135 anotasi, 17 dumpsite, 20 kategori EWC.
- **Kelas (verbatim info.txt)**: Rubble (12.61 Soils), Construction and demolition materials (12.11), Asphalt milling (12.12), Excavation materials (12.31), Appliances (08.21), Electronic equipment (08.23), Furniture (10.11), Metal barrels (06.31), Plastic packaging (07.41), Wood (07.53), Pallets (07.51), Scrap (06.11 ferrous), Plastic (07.42), Vehicles (08.12), **Tyres (07.31)**, Paper (07.2), Foundry slag (12.42), **Asbestos (12.21)**, Textile (07.6), Mixed items (10.2).
- **Lisensi**: record ditandai "Open"; **SPDX eksplisit tidak dicantumkan** — TANDAI (cek info.txt/README versi terbaru sebelum publikasi; review AgaMiko menulis CC BY 4.0).
- **Format**: COCO JSON (mask+bbox) + images.tar.gz 3,9 GB.
- **Catatan demo**: kelas **Rubble/Excavation materials** = "batu" kontaminan; **Tyres, Scrap, Metal barrels, Asbestos, Appliances/Electronic equipment** = MERAH berat; Mixed items untuk KUNING (campuran). Sudut pandang aerial/drone — cocok untuk narasi "foto muatan dari atas (dump truck bed)".

### 5. ZeroWaste (CVPR 2022) — konveyor pabrik daur ulang (konteks RDF-feedstock persis)

- **URL**: https://github.com/dbash/zerowaste · data https://doi.org/10.5281/zenodo.4899926
- **Jumlah**: 4.503 labeled + 6.212 unlabeled + 1.410 weakly-labeled.
- **Kelas**: sem-seg 4 kelas {Salvage, Background, LD film recyclable, HD film non-recyclable}; subset weakly berlabel image-level binary "before/after" belt.
- **Lisensi**: dataset **CC BY-NC 4.0** — NonCommercial; kode repo MIT.
- **Format**: COCO JSON instance-seg.
- **Catatan demo**: satu-satunya dataset dengan **foto konveyor MRF (material recovery facility) asli** — konteks "RDF feedstock di belt" untuk narasi MERAH (kontaminan di belt) tapi **tidak bisa dipakai untuk aset publik/komersial** demo karena NC; aman untuk internal eksperimen/paper.
- **Kelas lokakarya tambahan**: zero-shot komposit (ZeroWasteAug) sudah tersedia: crops TACO di-paste ke frame ZeroWaste — pola siap tiru untuk membangun muatan sintetis MERAH.

### 5b. Roboflow Universe `waste_datasets` (basis PLAN saat ini)

- **URL**: https://universe.roboflow.com/trash-kupyl/waste_datasets
- **Jumlah**: 2.872 gambar, 2 versi dataset, mAP@50 48,6% (model terlatih di atasnya).
- **Kelas**: belum terverifikasi per 13 Okt 2026 (halaman memblok fetch bot; perlu login manual browser untuk lihat tab "Classes").
- **Lisensi**: CC BY 4.0 (tercantum di halaman Universe).
- **Format**: Roboflow export multi-format (YOLO/COCO/VOC) — paling mudah dipakai di pipeline demo.
- **Status**: tetap basis PLAN (§6 Day 5) selama verifikasi manual kelas sukses; kalau kelasnya tak memuat metal/glass/biological, ganti/ambah RealWaste.

### 5c. Kaggle `mostafaabla/garbage-classification` (12 classes)

- **URL**: https://www.kaggle.com/datasets/mostafaabla/garbage-classification
- **Jumlah**: 15.150 gambar (≈1.260/kelas × 12).
- **Kelas (12)**: battery, biological, brown-glass, cardboard, clothes, green-glass, metal, paper, plastic, shoes, trash, white-glass.
- **Lisensi**: **TIDAK EKSPLISIT — TANDAI** (data card tanpa lisensi; sumber gambar mixed scraped).
- **Format**: folder-per-kelas JPG.
- **Catatan demo**: kelas biological → KUNING; metal/battery/3 varian glass → MERAH; cardboard/paper/plastic → HIJAU. Lisensi tak jelas → jadikan kandidat cadangan, bukan aset utama.

### 5d. TrashNet (Stanford CS 229) — baseline klasik, lisensi MIT eksplisit

- **URL**: https://github.com/garythung/trashnet · download dataset: https://huggingface.co/datasets/garythung/trashnet
- **Jumlah**: 2.527 gambar (512×384, diambil iPhone 5S/SE/7 Plus di atas papan poster putih).
- **Kelas (6) + jumlah**: glass (501), paper (594), cardboard (403), plastic (482), metal (410), trash (137).
- **Lisensi**: repo **MIT** (file LICENSE eksplisit); diminta sitasi repo bila pakai dataset.
- **Format**: ZIP folder-per-kelas (dataset-resized.zip / dataset-original.zip ~3,5 GB via HF/GDrive); mirror Kaggle `asdasdasasdas/garbage-classification` (2.467 gambar).
- **Catatan demo**: kelas terkontaminasi-objek-tunggal (bukan tumpukan) → cocok untuk foto muatan "potret bahan bersih" varian HIJAU (cardboard/paper/plastic) dan potret kontaminan MERAH (metal 410, glass 501); kelas trash (137) campuran → KUNING. Latar putih studio membuat VLM mudah mengklasifikasi, tapi kurang realistis untuk foto gerbang — gunakan sebagai suplemen, bukan foto utama.

---

## (c) Pemetaan eksplisit varian HIJAU / KUNING / MERAH

| Varian demo | Sumber foto kelas (dataset → kelas) | Alasan |
|---|---|---|
| 🟢 **HIJAU** — muatan bersih (RDF-grade) | **RealWaste** → Cardboard (461), Paper (500), Plastic (921); **TrashNet** → cardboard (403), paper (594), plastic (482) | Karton/kertas/plastik bersih di atas ambang fuel-grade; tanpa kontaminan keras; lisensi CC BY 4.0 / MIT aman |
| 🟡 **KUNING** — organik/lembap/campuran | **RealWaste** → Food Organics (411) + Vegetation (436); **TrashNet** → trash (137); **Kaggle mostafaabla** → biological (~1.260); **TACO** → Food waste; **DroneWaste** → Mixed items (10.2) | Gambar organik terlihat lembap/campur; klaim dry vs tampak basah; KUNING = escalate w/ caveat, bukan reject |
| 🔴 **MERAH** — kontaminan keras terlihat | **RealWaste** → Metal (790) + Glass (420); **TrashBox** → E-Waste (2.883), Medical (2.010), Metal (2.586), Glass (2.528); **TACO** → Scrap metal, Battery, Broken glass, Aerosol, Can; **DroneWaste** → Tyres, Scrap, Rubble, Metal barrels, Asbestos, Appliances, Electronic equipment | Logam/batu/ban/e-waste di antara sampah = ancaman shredder/kiln (US$28.000/jam); MERAH boleh over-reject |

**Rekomendasi final untuk Day 5**: kombinasi **RealWaste (utama, CC BY 4.0, konteks landfill)** untuk ketiga varian + **TrashBox e-waste/medical** untuk penguat MERAH (verifikasi lisensi dulu / gunakan hanya sebagai referensi prompt) + **TACO crops** untuk komposit kontaminan ke foto muatan; DroneWaste opsional untuk narasi "view dari atas truk". ZeroWaste hanya riset internal (NC).

---

## (d) Catatan kualitas lisensi

- **Aman publik (lisensi eksplisit permissive)**: RealWaste (CC BY 4.0), TrashNet (MIT), TACO anotasi (CC BY 4.0 — saring gambar per lisensi Flickr), Roboflow waste_datasets (CC BY 4.0), Drinking Waste Classification (CC0).
- **Perlu konfirmasi/tandai**: TrashBox (tanpa LICENSE), DroneWaste (record "Open" tanpa SPDX), Kaggle mostafaabla (tanpa data-card license), spot-garbage GINI (CC0 tapi scraped Bing — per hati-hati provenance).
- **NonCommercial — jangan untuk aset publik demo**: ZeroWaste dataset (CC BY-NC 4.0), Cigarette butt dataset (educational NC).
- Pola umum: dataset klasifikasi folder-per-kelas (RealWaste, TrashBox, TrashNet, Kaggle) enak untuk VLM demo langsung; dataset deteksi COCO (TACO, DroneWaste, ZeroWaste) lebih baik untuk grounding/box kontaminan.
