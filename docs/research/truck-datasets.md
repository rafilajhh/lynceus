# Riset Dataset Publik: FOTO TRUK SAMPAH (garbage truck / waste collection vehicle)

Tanggal riset: 2026-10-13
Sumber yang disurvei: Roboflow Universe (via browser langsung, halaman statis diblokir 403), Kaggle, HuggingFace Datasets, Zenodo, Mendeley Data, GitHub.

> Kesimpulan singkat: **Belum ada dataset publik yang ideal** menampilkan *foto truk sampah yang memperlihatkan isi/muatan bak*. Temuan terbaik adalah deteksi kendaraan truk sampah (eksterior), bukan muatannya. Berikut dokumentasi lengkap kandidat.

---

## Kandidat 1 — Garbage Collection Truck Detection (Roboflow Universe)

| Atribut | Isi |
|---|---|
| **Nama** | Garbage Collection Truck Detection |
| **URL** | https://universe.roboflow.com/garbage-truck-detection/garbage-collection-truck-detection |
| **Jumlah gambar** | 498 |
| **Kelas label** | 1 kelas: `garbage_truck` |
| **Lisensi (persis tertulis)** | **CC BY 4.0** |
| **Format download** | Roboflow Universe standard export (YOLO / COCO / Pascal VOC dll. via "Fork Dataset"; butuh akun Roboflow) |
| **Sifat foto** | Frame video CCTV sudut tinggi di jalan (`clip_frente_*_mp4-*.jpg`). Truk terlihat dari atas, **tidak fokus pada isi bak/muatan**. |

**Penilaian kecocokan untuk varian warna:**
- **HIJAU**: Cukup baik sebagai *detektor kendaraan truk sampah* — tetapi sudut pandang CCTV dari atas, bukan dekat/kargo. Kecocokan untuk *klasifikasi warna muatan*: rendah.
- **KUNING**: Sama — kendaraan terlihat, muatan tidak.
- **MERAH**: Sama — kendaraan terlihat, muatan tidak.
- Catatan: dataset ini menempatkan truk sampah sebagai *satu kelas*, tanpa perbedaan warna.

---

## Kandidat 2 — Garbage truck by 1131307 (Roboflow Universe)

| Atribut | Isi |
|---|---|
| **Nama** | Garbage truck |
| **URL** | https://universe.roboflow.com/1131307/garbage-truck |
| **Jumlah gambar** | 25 (sangat kecil) |
| **Kelas label** | 1 kelas: `Garbage-truck` |
| **Lisensi (persis tertulis)** | **CC BY 4.0** |
| **Format download** | Roboflow Universe export (YOLO / COCO / VOC) |
| **Sifat foto** | 25 gambar close-up/foto truk sampah eksterior (preview thumbnail menunjukkan truk sampah kartun/foto). Terlalu sedikit untuk training serius. |

**Penilaian kecocokan untuk varian warna:**
- **HIJAU/KUNING/MERAH**: Tidak cukup data (25 gambar, 1 kelas). Hanya cocok untuk demo/POC kecil atau augmentasi.

---

## Kandidat 3 — Vehicle Classification V2 (Roboflow Universe)

| Atribut | Isi |
|---|---|
| **Nama** | Vehicle Classification V2 |
| **URL** | https://universe.roboflow.com/vehicle-classfication/vehicle-classification-v2 |
| **Jumlah gambar** | 3.678 (instance segmentation, 21 kelas kendaraan) |
| **Kelas label** | 21 kelas termasuk: Bus, Van, Motorbike, Ambulance, SUV, Cyclist, Pickup, Sedan, Trailer, Box Truck, Bus: Small, Concrete Mixer, Construction Equipment, Fire Truck, **Garbage Truck**, Hatchback, Pickup: Utility, Tow Truck, Tractor Trailer, Truck: 2-Axle, Truck: Multi-Axle |
| **Lisensi (persis tertulis)** | **CC BY 4.0** |
| **Format download** | Roboflow Universe export; juga mirror di HuggingFace: `LibreYOLO/vehicles-q0x2v` (Roboflow 100 benchmark) |
| **Sifat foto** | Instance segmentation tampak samping/atas dari kendaraan jalan raya. **Bukan fokus pada muatan bak**. |

**Penilaian kecocokan untuk varian warna:**
- **HIJAU/KUNING/MERAH**: Tidak ada perbedaan warna — semua truk sampah = 1 kelas. Berguna untuk *memisahkan* garbage truck dari kendaraan lain, bukan untuk warna/muatan.

---

## Kandidat 4 — "Truck Load Classified Dataset" & varian muatan truk (Roboflow Universe) — *cadangan pola*

| Atribut | Isi |
|---|---|
| **Nama** | Truck Load Classified Dataset (New Workspace), serta "Truck load Detection" (New Workspace, 867 img), "truck load detection" (truck workspace, 688 img, instance segmentation) |
| **URL** | https://universe.roboflow.com/search?q=truck+load (masing-masing: pencarian di situs) |
| **Jumlah gambar** | 6.460 (classified), 867 (load), 688 (segmentation) |
| **Kelas label** | `Empty-truck` / `truck load` (New Workspace classified); `empty`/`0-25`/`25-50`/`50-75`/`75-100`/`empty bucket`/`full bucket`/`partially loaded` (meghanas) |
| **Lisensi** | **license unclear — jangan dipakai tanpa konfirmasi** (halaman tidak menampilkan lisensi eksplisit untuk beberapa workspace; standar Roboflow default CC BY 4.0, namun harus diverifikasi per-dataset) |
| **Format download** | Roboflow Universe export |
| **Sifat foto** | Ini adalah **polaritas terdekat dengan kebutuhan**: deteksi apakah truk terisi atau kosong. Namun pada truk *umum* (pasir/agregat), bukan truk sampah. |

**Penilaian kecocokan:**
- Berguna sebagai **referensi desain label** (empty / partially loaded / fully loaded) untuk truk sampah. Tidak secara langsung memenuhi syarat foto truk sampah.

---

## Kandidat 5 — Truck Image Dataset (Zenodo, Universidade de São Paulo) — *fallback akademik*

| Atribut | Isi |
|---|---|
| **Nama** | Truck Image Dataset |
| **URL** | https://zenodo.org/records/17128113 |
| **Jumlah gambar** | 1.053 gambar truk (727 nyata + 326 sintetik dari Euro Truck Simulator 2) |
| **Kelas label** | Truck, Axle, Tandem, Tridem (anotasi berorientasi *poros roda*, bukan muatan) |
| **Lisensi (persis tertulis)** | **CC BY 4.0** (field `license: cc-by-4.0` pada record Zenodo) |
| **Format download** | Trucks.zip (979 MB), JPG + anotasi LabelMe JSON |
| **Sifat foto** | Tampak samping truk jalan raya Brasil untuk deteksi as roda — **bukan truk sampah, tidak menampilkan muatan**. |

**Penilaian kecocokan:** Rendah untuk tujuan kita (fokus as roda, bukan truk sampah atau muatan). Tercatat sebagai contoh dataset akademik "truk" yang tidak cocok.

---

## Sumber lain yang disurvei & dinyatakan TIDAK cocok

- **Kaggle**: Semua hit adalah dataset *sampah per-item* (klasifikasi plastic/paper/metal/organik), tidak ada dataset foto truk sampah. Contoh: `asdasdasasdas/garbage-classification`, `sumn2u/garbage-classification-v2`, `quangtheng/garbage-classification-6-classes-775class`, dll.
- **HuggingFace**: Tidak ada dataset gambar truk sampah. Yang ada: klasifikasi sampah (`omasteam/waste-garbage-management-dataset`, MIT, imagefolder 10K-100K), deteksi sampah (`keremberke/garbage-object-detection`), dan dataset truk umum (`beethogedeon/Trucks-Detection-Yolov8`, CC BY 3.0, <1K; `XieTenghu1/TruckV2X`, MIT, untuk kooperatif trucking, bukan truk sampah).
- **UAVVaste / DroneWaste / TACO / TrashNet / StreetView-Waste**: Dataset *sampah* (aerial/ground litter), bukan kendaraan pengangkut.
- **City open data**: tidak ditemukan dataset foto truk sampah; yang tersedia biasanya data sensor/IoT pengangkutan (contoh: "Annotated IoT Dataset of Waste Collection Events", MDPI Data 2026 — sensor dari kendaraan, bukan foto).

---

## Rekomendasi praktis

1. **Untuk baseline deteksi "ada/tidak truk sampah"**: gunakan **Kandidat 1** (498 img, CC BY 4.0) digabung **Kandidat 3** (subkelas Garbage Truck dari 3.678 img). Keduanya CC BY 4.0, langsung dapat dipakai dengan atribusi.
2. **Untuk kebutuhan "memperlihatkan isi/muatan bak"**: *tidak ditemukan dataset publik yang langsung cocok*. Opsi yang realistis:
   - Mengambil video CCTV/sudut tinggi truk sampah sendiri (mengikuti pola Kandidat 1) dan melabeli empty/partial/full, mengacu pada pola label Kandidat 4.
   - Scrape video YouTube/pengawasan truk sampah (perhatikan hak cipta — lisensi konten tidak jelas, **jangan dipakai tanpa konfirmasi**).
3. **Catatan legal**: Semua kandidat Roboflow di atas menampilkan lisensi eksplisit di halaman dataset (CC BY 4.0). Untuk dataset tanpa lisensi eksplisit (mis. hasil scrape web, sebagian Kaggle), berlabel: **license unclear — jangan dipakai tanpa konfirmasi**.

---

## Addendum (2026-10-14, English): licence check for a separate "truck-bed slice"

**Method.** Licences were read from machine-readable metadata, not from page text: the Zenodo REST API (`https://zenodo.org/api/records/<id>`), the Hugging Face API (`https://huggingface.co/api/datasets/<id>`) and the Wikimedia Commons API (`LicenseShortName` of each file). No image was downloaded. Roboflow Universe pages returned HTTP 403 to both WebFetch and curl from this environment on 2026-10-14, so the Roboflow licences of candidates 1 to 4 above **could not be re-verified** and stay "as reported on 2026-10-13".

### Usable now (licence verified on 2026-10-14)

| Source | What it shows | Count | Licence | URL | Fit for a truck-bed slice |
|---|---|---|---|---|---|
| Wikimedia Commons, *Waste collection trucks in Indonesia* | Open dump and arm-roll waste trucks (DLHKP Kebumen), some unloading at a TPA; judged from file titles only, contents not inspected | 24 files | 23 CC BY-SA 4.0, 1 CC BY 2.0 (per file) | https://commons.wikimedia.org/wiki/Category:Waste_collection_trucks_in_Indonesia | Best Indonesian match. Small evaluation set, not training |
| Wikimedia Commons, *Non-compacting waste collection trucks* | Open-body waste trucks, mixed countries | 42 files | CC BY-SA 3.0 ×18, CC BY-SA 4.0 ×7, public domain ×7, CC BY 3.0 ×3, CC BY-SA 2.0 ×3, CC0 ×2, CC BY 2.0 ×1, CC BY-SA 3.0 de ×1 | https://commons.wikimedia.org/wiki/Category:Non-compacting_waste_collection_trucks | Evaluation; how many show the load from above is not checked |
| Wikimedia Commons, *Refuse-derived fuel* | RDF fluff, bales and pellets (material, not trucks) | 11 files | CC BY-SA 4.0 ×6, CC BY-SA 3.0 ×3, public domain ×2 | https://commons.wikimedia.org/wiki/Category:Refuse-derived_fuel | Reference images of clean RDF |
| Zenodo, *Remondis Contamination Dataset (RCD)* | Frames from cameras on waste collection trucks: bins and truck hoppers, boxes on plastic bags | 1,125 images (640×480), 1,851 boxes | CC BY 4.0 (record) | https://zenodo.org/records/8248169 | Closest "load seen from above" set, but its record says part of the images come from "open source online resources", so per-image provenance is unclear |
| Zenodo, *TSQ-2024* | 120 LiDAR scans of truck passes, empty or loaded with sand, as 16-bit depth images | 120 scans | CC BY 4.0 | https://zenodo.org/records/13645341 | Empty versus loaded bed (fill level); not photos, no contaminants |
| Zenodo, *Construction and Demolition Waste Dataset* (YOLOv11) | Brick, concrete, plastic, steel reinforcement, timber on a lab conveyor | 1,630 images | CC BY 4.0 | https://zenodo.org/records/17447590 | Not a truck bed; source of concrete, brick and rebar examples for the hard-contaminant classes |
| Zenodo, *Truck Image Dataset* (candidate 5 above) | Side views of trucks for axle detection | 1,053 images | CC BY 4.0 (confirmed) | https://zenodo.org/records/17128113 | Not a truck bed |

For the CC BY and CC BY-SA files, keep a per-file attribution list (author, licence, URL). If the slice itself is published, the CC BY-SA files require it to be shared under the same licence.

### Not usable, or corrections

- **MMCDWaste** (Zenodo 17874659): 4,786 mixed C&D waste images under a CC BY 4.0 label, but the record's access is *restricted* and the files are not released yet. https://zenodo.org/records/17874659
- **UniqueData/wagons-images-classification** (Hugging Face): loaded and empty rail wagons, licence CC BY-NC-ND 4.0, which allows no commercial use and no derivatives. Not usable for the product or the pitch.
- **Correction to candidate 3.** `LibreYOLO/vehicles-q0x2v` on Hugging Face (CC BY 4.0, 4,058 images) is the Roboflow 100 "vehicles" set with 12 classes (big bus, big truck, bus-l-, bus-s-, car, mid truck, small bus, small truck, truck-l-, truck-m-, truck-s-, truck-xl-). It has no Garbage Truck class and is not a mirror of Vehicle Classification V2.
- **Roboflow hits found today** ("Dumptruck_loading_zone_cropped", https://universe.roboflow.com/eth-ly0hg/dumptruck_loading_zone_cropped; "Truck load Detection", https://universe.roboflow.com/amanul-haque/truck-load-detection-qrfwa): licence not verifiable from here (HTTP 403). Check in a logged-in browser before use.
- **HKU single-image construction-waste volume study** (2,914 truckloads at a Hong Kong sorting facility): seen only in a search-result summary; the repository page returned HTTP 403 and no public image release was found. Unverified.

### Recommendation

The only public photos of Indonesian waste-truck beds with a verified licence are the 24 Commons files. That is enough for a small, attributed evaluation slice and a demo, not for training. Real truck-bed training data has to come from a pilot gate, with consent (see `docs/operator-validation-kit.md`).
