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
