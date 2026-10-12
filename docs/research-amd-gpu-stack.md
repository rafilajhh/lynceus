# Riset Stack AI di AMD GPU untuk Lynceus

> Riset web (read-only), 13 Oktober 2026. Semua klaim disertai sumber resmi (AMD / vLLM / Hugging Face).
> Konteks target: Lynceus membutuhkan stack inferensi VLM (vision-language) + LLM yang berjalan di AMD Instinct GPU (ROCm), dengan opsi deploy di AMD Developer Cloud.

---

## 1. AMD Developer Cloud: Akses GPU Instance

### 1.1 Gambaran umum

- AMD Developer Cloud (ADC, https://devcloud.amd.com) memberi akses **AMD Instinct MI300X** (gfx942, 192 GB HBM3 per GPU) untuk developer/open-source contributor. Platform dijalankan bersama penyedia cloud pihak ketiga (login via DigitalOcean: `https://amd.digitalocean.com/login`). Sumber: [AMD — AI & HPC Cloud Access](https://www.amd.com/en/developer/resources/cloud-access.html) dan [How to Get Started on the AMD Developer Cloud](https://www.amd.com/en/developer/resources/technical-articles/2025/how-to-get-started-on-the-amd-developer-cloud-.html).
- Dua mode akses: **Pay-As-You-Go** (langsung, kartu kredit) atau **complimentary credit** (25 jam awal, perlu approval). Sumber: FAQ di [halaman Cloud Access](https://www.amd.com/en/developer/resources/cloud-access.html).
- Program lain di ekosistem yang sama (tidak jadi fokus Lynceus): Instinct Evaluation Program (MI325X/MI300X, untuk enterprise), AI & HPC Cluster (MI325/MI300X/MI250/MI210 + EPYC, akademik, hingga 1 tahun), Radeon Test Drive (W7800/W7900, 14 hari). Sumber: [tabel perbandingan resmi](https://www.amd.com/en/developer/resources/cloud-access.html).
- **Catatan GPU selain MI300X di ADC**: ADC hanya menyediakan MI300X. MI250/MI210 tersedia via program **AI & HPC Cluster** (akademik) — sumber: [tabel program cloud AMD](https://www.amd.com/en/developer/resources/cloud-access.html).

### 1.2 Batas / kredit

| Item | Nilai | Sumber |
|---|---|---|
| Kredit awal (direct request di ADC) | **25 jam GPU (~USD $50)**, habis dalam **10 hari sejak deposit** | [FAQ Cloud Access](https://www.amd.com/en/developer/resources/cloud-access.html) |
| Kredit via **AMD AI Developer Program (ADP)** | **$100** kredit AMD Developer Cloud, **kedaluwarsa 30 hari setelah aktivasi** | [developer.amd.com/ai-developer-program](https://developer.amd.com/ai-developer-program/) + [How to Claim AMD Cloud Credits](https://www.amd.com/en/developer/resources/technical-articles/2026/how-to-claim-amd-cloud-credits.html) |
| Alternatif ADP #2 | Fireworks AI **$50** (endpoint LLM terkelola di Instinct), 90 hari | [How to Claim AMD Cloud Credits](https://www.amd.com/en/developer/resources/technical-articles/2026/how-to-claim-amd-cloud-credits.html) |
| Aturan pemakaian | Kredit hanya untuk MI300X; 1 jam di VM 8×MI300X = 8 GPU-jam; VM **tetap ditagih walau dimatikan** (sampai di-destroy); volume/storage cadangan tidak ditanggung kredit | [FAQ Cloud Access](https://www.amd.com/en/developer/resources/cloud-access.html) |
| Cara klaim ADP | Login developer.amd.com → **Member Perks → Request Cloud Credits** → form (afiliasi, use case, profil publik) → approval 2–3 hari kerja | [How to Claim AMD Cloud Credits](https://www.amd.com/en/developer/resources/technical-articles/2026/how-to-claim-amd-cloud-credits.html) |

**Jawaban poin 5 (rotasi/kredensial):** Ya, ada **kredit $100 ADP** (AMD AI Developer Program). Berlaku **30 hari setelah aktivasi** di AMD Developer Cloud. Jalur ADC "klasik" (25 jam/~$50, 10 hari) masih berlaku sebagai alternatif. Keduanya butuh kartu kredit valid saat pembuatan akun; kredit hangus jika kartu invalid atau kredit habis (data di VM hilang). Sumber: [developer.amd.com](https://developer.amd.com/ai-developer-program/), [How to Claim](https://www.amd.com/en/developer/resources/technical-articles/2026/how-to-claim-amd-cloud-credits.html), [FAQ](https://www.amd.com/en/developer/resources/cloud-access.html).

### 1.3 Opsi image VM

Saat membuat VM ("GPU Droplet"): pilih **1× MI300X** atau **8× MI300X**, lalu pilih image — **Bare OS** (Ubuntu minimal, ROCm di-install sendiri) atau **Quick Start**: *Vanilla ROCm* atau *Quick Start Packages* dengan Docker pre-installed berisi **vLLM, SGLang, PyTorch, Megatron, JAX** + JupyterLab otomatis jalan. Akses: SSH `root@<Public-IP>`, Web Console, atau JupyterLab via browser IP publik + token. Sumber: [How to Get Started on the AMD Developer Cloud](https://www.amd.com/en/developer/resources/technical-articles/2025/how-to-get-started-on-the-amd-developer-cloud-.html).

---

## 2. vLLM di ROCm: Status Support & Instalasi

### 2.1 Status support

- vLLM mendukung GPU AMD secara resmi (ROCm merupakan platform first-class). GPU yang didukung: **MI200s (gfx90a), MI300 (gfx942), MI350 (gfx950), Radeon RX 7900/9000, Ryzen AI MAX/AI 300**; syarat ROCm ≥ 6.3 (MI350 butuh ROCm ≥ 7.0). Sumber: [vLLM docs — Installation/GPU](https://docs.vllm.ai/en/latest/getting_started/installation/gpu/).
- Versi vLLM terbaru yang didukung stack ROCm AI Ecosystem: **vLLM 0.29 / 0.27 / 0.23** (ROCm 10.1 / 10.0 / 7.14), Docker resmi `rocm/vllm` tersedia. Sumber: [ROCm AI Ecosystem — vLLM](https://rocm.docs.amd.com/projects/ai-ecosystem/en/latest/inference/vllm.html).
- ROCm kini platform first-class di ekosistem vLLM (vLLM-Omni, target MI300X/MI325X/MI350X/MI355X). Sumber: [ROCm blog — vLLM-Omni](https://rocm.blogs.amd.com/software-tools-optimization/vllm-omni/README.html).
- Catatan batasan di vLLM docs: **"ROCm version of vLLM supports Mistral and Mixtral only for context lengths up to 4096"** (Mistral/Mixtral terdaftar *partially supported* dengan alasan sliding-window attention). Sumber: [vLLM — Supported Models](https://docs.vllm.ai/en/stable/models/supported_models/).

### 2.2 Instalasi (ringkas)

**Opsi A — Docker (disarankan, paling stabil):**

```bash
# image resmi AMD; sesuaikan tag dengan versi ROCm di VM
docker pull rocm/vllm:rocm10.1.0_ubuntu24.04_py3.14-pytorch_2.13.0_vllm-0.29.0

docker run -it --rm \
  --device /dev/kfd --device /dev/dri \
  --network=host --ipc=host --group-add=video \
  --cap-add=SYS_PTRACE --security-opt seccomp=unconfined \
  -v <path/to/models>:/app/models \
  -e HF_HOME=/app/models \
  rocm/vllm:rocm10.1.0_ubuntu24.04_py3.14-pytorch_2.13.0_vllm-0.29.0 bash
```
Sumber: [ROCm AI Ecosystem — vLLM](https://rocm.docs.amd.com/projects/ai-ecosystem/en/latest/inference/vllm.html), [AMD — prebuilt ROCm vLLm Docker image](https://www.amd.com/en/developer/resources/technical-articles/how-to-use-prebuilt-amd-rocm-vllm-docker-image-with-amd-instinct-mi300x-accelerators.html), [Docker Hub rocm/vllm](https://hub.docker.com/r/rocm/vllm/tags).

**Opsi B — pip/uv (wheel resmi ROCm):**

```bash
# WAJIB Python 3.12 (jika tidak, pip akan diam-diam memasang wheel CUDA yang gagal di AMD GPU)
uv venv --python 3.12 --seed --managed-python && source .venv/bin/activate
uv pip install vllm --extra-index-url https://wheels.vllm.ai/rocm/ --upgrade
```
Sumber: [vLLM docs — Installation/GPU (AMD ROCm)](https://docs.vllm.ai/en/latest/getting_started/installation/gpu/). Wheel prebuilt tersedia untuk varian `rocm700`/`rocm721` (glibc ≥ 2.35).

**Di AMD Developer Cloud:** pilih image Quick Start "vLLM" — container Docker `rocm/vllm` sudah terpasang; masuk via `docker exec -it rocm bash`, dan JupyterLab contoh (mis. agen MCP + Pydantic AI) langsung tersedia. Sumber: [How to Get Started on ADC](https://www.amd.com/en/developer/resources/technical-articles/2025/how-to-get-started-on-the-amd-developer-cloud-.html).

### 2.3 Model yang terbukti berjalan di vLLM + ROCm

Bukti run-time paling kuat (dokumen resmi vLLM/AMD yang secara eksplisit menargetkan **MI300X/MI325X/MI355X**):

- **Qwen2.5-VL (3B/7B/72B)** — panduan resmi vLLM Recipes menyertakan tab **"AMD ROCm (MI300X, MI325X, MI355X)"** lengkap dengan perintah serve (`VLLM_ROCM_USE_AITER=1`), DP/TP, dan benchmark. Sumber: [vLLM Recipes — Qwen2.5-VL Usage Guide](https://docs.vllm.ai/projects/recipes/en/latest/Qwen/Qwen2.5-VL.html).
- **Qwen2-7B, Llama3-70B, Yi-34B** — blog resmi ROCm berisi inferensi & serving nyata di AMD GPU (`rocm/vllm` image). Sumber: [ROCm blog — Inferencing and serving with vLLM on AMD GPUs](https://rocm.blogs.amd.com/artificial-intelligence/vllm/README.html).
- **Llama 3.1 8B/70B/405B, Mixtral 8x7B/8x22B, Qwen2 7B/72B, Mistral 7B** (FP16 & FP8-KV) — benchmark terautomasi via AMD MAD di MI300X. Sumber: [AMD — prebuilt vLLM Docker MI300X](https://www.amd.com/en/developer/resources/technical-articles/how-to-use-prebuilt-amd-rocm-vllm-docker-image-with-amd-instinct-mi300x-accelerators.html).
- **Llama 3.1 70B & 405B** — vLLM official blog, benchmark vs TGI di 8×MI300X. Sumber: [vLLM blog — Serving LLMs on AMD MI300X](https://vllm.ai/blog/2024-10-23-vllm-serving-amd).
- **Qwen generasi terbaru (Qwen 3.8, MiniMax-H3, Kimi-K3)** — day-0 support di Instinct via SGLang/vLLM menunjukkan keluarga Qwen adalah jalur paling terawat di ROCm. Sumber: [ADP portal news](https://developer.amd.com/ai-developer-program/).
- **LLaVA-1.5/NeXT, InternVL 2/2.5/3/3.5** — arsitektur (`LlavaForConditionalGeneration`, `LlavaNextForConditionalGeneration`, `InternVLChatModel`) didukung native vLLM ([Supported Models](https://docs.vllm.ai/en/stable/models/supported_models/)); bukti spesifik-ke-ROCm lebih tipis dibanding Qwen2.5-VL (tidak ada tab/benchmark AMD khusus di docs resmi) — jadikan pilihan sekunder.

### 2.4 Tabel pilihan model

> VRAM = estimasi bobot BF16/FP16 (≈2 byte/param) + overhead KV cache; FP8 ≈ setengahnya. MI300X = 192 GB/GPU.

| Model | Jenis | Ukuran (param) | VRAM (BF16, kasar) | Status di ROCm/vLLM | Link bukti |
|---|---|---|---|---|---|
| **Qwen2.5-VL-7B-Instruct** | VLM | 8.3B | ~17–24 GB | ✅ Resep resmi vLLM dgn tab MI300X/MI325X/MI355X | [vLLM Recipes](https://docs.vllm.ai/projects/recipes/en/latest/Qwen/Qwen2.5-VL.html), [HF](https://huggingface.co/Qwen/Qwen2.5-VL-7B-Instruct) |
| **Qwen2.5-VL-72B-Instruct** | VLM | 72B+ViT 675M | ~150 GB → **TP=4** | ✅ Resep resmi (4×MI300X, BF16) | [vLLM Recipes](https://docs.vllm.ai/projects/recipes/en/latest/Qwen/Qwen2.5-VL.html) |
| **Qwen2-VL-7B/2B-Instruct** | VLM | 8B / 2.2B | ~17 GB / ~5 GB | ✅ Arsitektur `Qwen2VLForConditionalGeneration` didukung vLLM | [vLLM Supported Models](https://docs.vllm.ai/en/stable/models/supported_models/) |
| **InternVL3/2.5 (1B–14B)** | VLM | 1–14B | ~3–30 GB | ✅ Native vLLM (`InternVLChatModel`); bukti ROCm tipis | [vLLM Supported Models](https://docs.vllm.ai/en/stable/models/supported_models/) |
| **LLaVA-1.5-7B** | VLM | 7B | ~15 GB | ✅ Native vLLM (`LlavaForConditionalGeneration`) | [vLLM Supported Models](https://docs.vllm.ai/en/stable/models/supported_models/) |
| Llama-3.2-11B-Vision | VLM | 11B (encoder-decoder) | ~23 GB | ⚠️ **Tidak direkomendasikan**: `MllamaForConditionalGeneration` telah **dihapus dari vLLM sejak v0.10.2** (V0 deprecation); hanya jalan di vLLM ≤0.10.1 | [vLLM registry `_PREVIOUSLY_SUPPORTED_MODELS`](https://github.com/vllm-project/vllm/blob/main/vllm/model_executor/models/registry.py) |
| **Qwen2.5-7B-Instruct** | LLM | 7.6B | ~16 GB | ✅ Keluarga Qwen2 terbukti di blog ROCm | [ROCm blog vLLM](https://rocm.blogs.amd.com/artificial-intelligence/vllm/README.html) |
| **Qwen2.5-72B-Instruct** | LLM | 72.7B | ~150 GB → TP=4 | ✅ (Qwen2-72B dibenchmark MAD di MI300X) | [AMD prebuilt Docker article](https://www.amd.com/en/developer/resources/technical-articles/how-to-use-prebuilt-amd-rocm-vllm-docker-image-with-amd-instinct-mi300x-accelerators.html) |
| **Llama-3.1-8B/70B-Instruct** | LLM | 8B/70B | 16 GB / ~145 GB (TP=2/4) | ✅ Benchmark resmi AMD MAD + vLLM blog | [AMD](https://www.amd.com/en/developer/resources/technical-articles/how-to-use-prebuilt-amd-rocm-vllm-docker-image-with-amd-instinct-mi300x-accelerators.html), [vLLM blog](https://vllm.ai/blog/2024-10-23-vllm-serving-amd) |
| Llama-3.1-405B (FP8-KV) | LLM | 405B | ~210 GB FP8 → TP=4 | ✅ Contoh deploy resmi AMD di 4×MI300X | [AMD article](https://www.amd.com/en/developer/resources/technical-articles/how-to-use-prebuilt-amd-rocm-vllm-docker-image-with-amd-instinct-mi300x-accelerators.html) |
| Mistral-7B / Mixtral-8x7B/8x22B | LLM | 7B/47B/141B | 15/95/280 GB | ⚠️ Partially supported di ROCm — **context ≤ 4096** | [vLLM Supported Models note](https://docs.vllm.ai/en/stable/models/supported_models/) |

---

## 3. Benchmark inferensi nyata di MI300X

### 3.1 VLM — Qwen2.5-VL di MI300X (sumber: vLLM Recipes, benchmark `vllm bench serve`)

| Setup | Throughput | TTFT | TPOT |
|---|---|---|---|
| **Qwen2.5-VL-7B, DP=4** (VisionArena-Chat, 128 prompt) | **13.09 req/s; 1.455 tok/s output** | mean 4.43 s (median 4.75 s) | 58 ms |
| Qwen2.5-VL-7B, DP=4 (random 8K-in/1K-out) | 2.83 req/s; 2.581 tok/s output; 25.176 tok/s total | mean 10.9 s | 42 ms |
| **Qwen2.5-VL-72B, TP=4** (VisionArena-Chat) | 3.83 req/s; 437 tok/s output | mean 13.7 s | 172 ms |
| Qwen2.5-VL-72B, TP=4 (random 8K/1K) | 0.16 req/s; 147 tok/s output | mean 305 s (beban ekstrem) | 309 ms |

Sumber: [vLLM Recipes — Qwen2.5-VL](https://docs.vllm.ai/projects/recipes/en/latest/Qwen/Qwen2.5-VL.html) (angka di atas adalah hasil "Expected Output" resep; resep berlaku untuk stack MI300X/MI325X/MI355X).

**Kesimpulan kasar:** di MI300X, VLM 7B kelas Qwen2.5-VL realistis untuk interaktif (TTFT beberapa detik, ~20+ tok/s per stream); 72B cocok untuk batch/throughput, bukan latency-sensitif.

### 3.2 LLM — Llama 3.1 di 8×MI300X (sumber: vLLM official blog)

- **Llama 3.1 405B (BF16)**: vLLM mencapai **5.76 req/s** (dataset ShareGPT, 1000 QPS, config optimal) vs TGI 3.55 req/s; TTFT ~3.8× lebih cepat dari TGI di 16 QPS.
- **Llama 3.1 70B**: vLLM **1.8× throughput lebih tinggi dan 5.1× TTFT lebih cepat** dari TGI.
- Best-practices tuning MI300X (dari blog yang sama): `VLLM_USE_TRITON_FLASH_ATTN=0` (pakai CK Flash Attention), `--num-scheduler-steps 10–15`, `--max-num-seqs ≥512`, disable NUMA balancing, `NCCL_MIN_NCHANNELS=112`.

Sumber: [vLLM blog — Serving LLMs on AMD MI300X: Best Practices](https://vllm.ai/blog/2024-10-23-vllm-serving-amd).

---

## 4. Alternatif ringan bila VRAM terbatas

Konteks: dengan 1× MI300X (192 GB) VRAM sebenarnya melimpah untuk model 7–72B; skenario "terbatas" relevan jika Lynceus turun ke GPU lebih kecil (MI210 64 GB, Radeon 48 GB, atau budget kredit $100 ≈ ~33 jam GPU-jam tunggal).

### 4.1 Model kecil

| Model | Param | VRAM (BF16) | Catatan ROCm |
|---|---|---|---|
| **Qwen2.5-VL-3B-Instruct** | 3.75B | ~8–10 GB | Arsitektur sama (Qwen2_5_VL) — didukung | 
| Qwen2-VL-2B-Instruct | 2.2B | ~5 GB | `Qwen2VLForConditionalGeneration` didukung vLLM |
| Qwen2.5-3B / Qwen2.5-7B-Instruct (LLM) | 3–7.6B | 7–16 GB | Keluarga Qwen2 terbukti di ROCm blog |
| Llama-3.2-3B/1B (teks) | 1–3B | 3–7 GB | `LlamaForCausalLM` didukung |

Sumber: [vLLM Supported Models](https://docs.vllm.ai/en/stable/models/supported_models/). Pilihan vision kecil **yang masih aktif didukung** adalah keluarga Qwen-VL; **Llama-3.2-Vision (11B/90B) telah dihapus dari vLLM ≥0.10.2** (lihat §2.4), sehingga tidak disarankan sebagai basis Lynceus.

### 4.2 Quantization di ROCm

- **AWQ & GPTQ**: menurut [matriks resmi vLLM](https://docs.vllm.ai/en/stable/features/quantization/), kolom **AMD GPU = ❌** untuk AWQ, GPTQ, Marlin, bitsandbytes, INT8 llm-compressor — format int4 "populer" ini tidak didukung vLLM di ROCm.
- **Yang didukung di AMD GPU (✅)**: **FP8 (W8A8)** dan **GGUF** (matriks yang sama), plus **AMD Quark** sebagai jalur kuantisasi resmi AMD.
- **AMD Quark** (`pip install amd-quark`): kuantisasi FP8/INT8 weight+activation+KV-cache, skema INT4-FP8 (≈4× kompresi) untuk model sangat besar; model FP8 Quark (Llama, Mixtral, dll.) tersedia di [org AMD di HF](https://huggingface.co/collections/amd/quark-quantized-ocp-fp8-models-66db7936d18fcbaf95d4405c) dan langsung jalan di vLLM (`quantization='quark'`, `kv_cache_dtype='fp8'`). Sumber: [ROCm — Model quantization techniques](https://rocm.docs.amd.com/projects/ai-ecosystem/en/latest/optimization/model-quantization.html), [vLLM — AMD Quark](https://docs.vllm.ai/en/stable/features/quantization/quark/).
- **FP8 native di MI300X**: didukung (mis. `amd/Llama-3.1-405B-Instruct-FP8-KV`); FP8 menggandakan ruang efektif vs BF16. Sumber: [vLLM FP8 docs](https://docs.vllm.ai/en/v0.5.1/quantization/fp8.html), [AMD article](https://www.amd.com/en/developer/resources/technical-articles/how-to-use-prebuilt-amd-rocm-vllm-docker-image-with-amd-instinct-mi300x-accelerators.html).

**Implikasi untuk Lynceus:** untuk memperkecil jejak memori di ROCm, jalur yang benar adalah **model kecil (Qwen2.5-VL-3B/7B) + FP8 (Quark/native)** — bukan GPTQ/AWQ yang umum di ekosistem NVIDIA.

---

## 5. Rekomendasi stack final

### Stack yang direkomendasikan

| Komponen | Pilihan | Justifikasi |
|---|---|---|
| **VLM** | **Qwen2.5-VL-7B-Instruct** (BF16; opsional 3B untuk dev cepat) | Satu-satunya VLM dengan resep + benchmark resmi vLLM yang secara eksplisit menargetkan MI300X/MI325X/MI355X; kuat di OCR/dokumen (DocVQA 95.7), chart, grounding; Apache-2.0; single-GPU friendly (~17–24 GB) |
| **LLM** | **Qwen2.5-7B-Instruct** (scale-up: Qwen2.5-72B atau Llama-3.1-70B dengan TP) | Keluarga Qwen2 terbukti di ROCm blog AMD; tokenizer/chat API konsisten dengan VLM (kemudahan pipeline Lynceus); upgrade path 72B sudah teruji di MI300X |
| **Serving** | **vLLM** (Docker `rocm/vllm`, endpoint OpenAI-compatible) | First-class di ROCm; Docker resmi AMD teroptimasi (CK FlashAttention, TunableOp); Quick Start image vLLM tersedia langsung di ADC; 1.5–1.8× throughput vs TGI di MI300X |

Justifikasi ringkas: bukti end-to-end terkuat (resep resmi + angka benchmark nyata) ada di kombinasi **Qwen2.5-VL + vLLM + MI300X**, dengan Qwen2.5 (teks) sebagai LLM pendamping karena garis keturunan Qwen paling terawat di ROCm (day-0 support Qwen 3.8, benchmark Qwen2 di MAD). Endpoint OpenAI-compatible dari vLLM membuat Lynceus bisa memakai SDK standar dan menukar model tanpa ubah kode.

---

## 6. Langkah deploy konkret di AMD Developer Cloud

```bash
# ── 0. Persiapan ─────────────────────────────────────────────
# a. Daftar AMD AI Developer Program (developer.amd.com) → Member Perks
#    → Request Cloud Credits ($100, berlaku 30 hari setelah aktivasi)
# b. Buat akun ADC (amd.digitalocean.com) dengan kartu kredit valid.
# c. Catat HF_TOKEN untuk model gated (Qwen2.5 tidak gated, tapi siapkan).

# ── 1. Buat VM ──────────────────────────────────────────────
# Console ADC → pilih plan 1x MI300X → image:
#   "Quick Start > vLLM"  (Docker rocm/vllm + JupyterLab siap pakai)
#   atau "Quick Start > Vanilla ROCm" jika ingin kontrol versi.
# Tambahkan SSH key → Create GPU Droplet → catat Public IP.

# ── 2. Masuk ke instance ────────────────────────────────────
ssh root@<PUBLIC-IP>
rocm-smi                                # verifikasi 1x MI300X terlihat
docker exec -it rocm bash              # masuk container vLLM (image Quick Start)

# Jika Vanilla ROCm / ingin versi spesifik, jalankan container resmi:
docker run -it --rm --device /dev/kfd --device /dev/dri \
  --network=host --ipc=host --group-add=video \
  --cap-add=SYS_PTRACE --security-opt seccomp=unconfined \
  -v $HOME/models:/app/models -e HF_HOME=/app/models -e HF_TOKEN=$HF_TOKEN \
  rocm/vllm:rocm10.1.0_ubuntu24.04_py3.14-pytorch_2.13.0_vllm-0.29.0 bash

# ── 3. Tuning host (opsional, best-practice MI300X) ─────────
sh -c 'echo 0 > /proc/sys/kernel/numa_balancing'
export NCCL_MIN_NCHANNELS=112          # hanya relevan multi-GPU

# ── 4. Serve VLM (port 8000) ─────────────────────────────────
export VLLM_ROCM_USE_AITER=1            # aktifkan kernel AITER ROCm
vllm serve Qwen/Qwen2.5-VL-7B-Instruct \
  --host 0.0.0.0 --port 8000 \
  --max-model-len 32768 \
  --limit-mm-per-prompt '{"image":2,"video":0}' \
  --gpu-memory-utilization 0.92

# ── 5. Serve LLM (port 8001, proses/container lain) ──────────
VLLM_USE_TRITON_FLASH_ATTN=0 vllm serve Qwen/Qwen2.5-7B-Instruct \
  --host 0.0.0.0 --port 8001 \
  --max-model-len 32768 \
  --num-scheduler-steps 10 \
  --max-num-seqs 512

# (alternatif hemat: satu server saja + Qwen2.5-VL menangani teks murni;
#  scale-up: Qwen2.5-VL-72B / Llama-3.1-70B dengan --tensor-parallel-size 4
#  atau --data-parallel-size 4 di VM 8x MI300X)

# ── 6. Smoke test ────────────────────────────────────────────
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"Qwen/Qwen2.5-VL-7B-Instruct","messages":[
        {"role":"user","content":[
          {"type":"image_url","image_url":{"url":"https://qianwen-res.oss-cn-beijing.aliyuncs.com/Qwen-VL/assets/demo.jpeg"}},
          {"type":"text","text":"Describe this image."}]}],
       "max_tokens":128}'

# ── 7. Benchmark cepat (opsional) ────────────────────────────
vllm bench serve --host 0.0.0.0 --port 8000 --backend openai-chat \
  --endpoint /v1/chat/completions --model Qwen/Qwen2.5-VL-7B-Instruct \
  --dataset-name hf --dataset-path lmarena-ai/VisionArena-Chat --num-prompts 128

# ── 8. Kebersihan kredit (PENTING) ───────────────────────────
# VM tetap ditagih walau dimatikan → DESTROY instance segera setelah selesai;
# snapshot VM jika ingin melanjutkan nanti (storage snapshot tidak ditanggung kredit).
```

Sumber langkah: [How to Get Started on AMD Developer Cloud](https://www.amd.com/en/developer/resources/technical-articles/2025/how-to-get-started-on-the-amd-developer-cloud-.html), [ROCm AI Ecosystem — vLLM](https://rocm.docs.amd.com/projects/ai-ecosystem/en/latest/inference/vllm.html), [vLLM Recipes — Qwen2.5-VL](https://docs.vllm.ai/projects/recipes/en/latest/Qwen/Qwen2.5-VL.html), [vLLM blog — MI300X best practices](https://vllm.ai/blog/2024-10-23-vllm-serving-amd), [FAQ kredit](https://www.amd.com/en/developer/resources/cloud-access.html).

---

## Ringkasan jawaban per pertanyaan

1. **Akses ADC**: login GitHub/akun di devcloud.amd.com → pilih droplet 1×/8× MI300X + image (Bare OS / Vanilla ROCm / Quick Start vLLM dkk.) + SSH key; SSH `root@<ip>`; `docker exec -it rocm bash` untuk paket vLLM. Kredit: 25 jam (~$50, 10 hari) jalur langsung; **$100 ADP, 30 hari** via Member Perks. VM ditagih sampai di-destroy.
2. **vLLM+ROCm**: first-class; wheel resmi (Python 3.12, `wheels.vllm.ai/rocm`) dan Docker `rocm/vllm`. Model terbukti: **Qwen2.5-VL 3B/7B/72B** (resep resmi MI300X), Qwen2/Llama 3.1/Mixtral (blog & MAD AMD). Mistral/Mixtral terbatas ctx ≤4096 di ROCm. Llama-3.2-Vision dihapus sejak vLLM 0.10.2.
3. **Benchmark VLM MI300X**: Qwen2.5-VL-7B DP=4 → 13.1 req/s, TTFT ~4.4 s, TPOT 58 ms; Qwen2.5-VL-72B TP=4 → 3.8 req/s, TTFT ~13.7 s (vLLM Recipes).
4. **Alternatif ringan**: Qwen2.5-VL-3B / Qwen2-VL-2B + **FP8 via AMD Quark** (AWQ/GPTQ/bitsandbytes ❌ di vLLM+ROCm; FP8 & GGUF ✅).
5. **Kredit**: $100 ADP berlaku 30 hari setelah aktivasi (bukan "rapid trial" 10 hari — itu jalur 25-jam/$50 ADC); keduanya MI300X-only, kartu kredit wajib.
