# Lynceus

**AI gate inspector for alternative-fuel (RDF) facilities — built for the AMD Developer Hackathon: ACT III (Intelligent Industry track).**

Lynceus inspects a waste truck's load at the weighbridge before it is tipped
into the plant. A photo of the load, the waybill text, the weighed mass and gate
gas readings are fused into a verdict — **ACCEPT / ESCALATE / REJECT** — by a
rule-based, regulation-grounded decision engine. The AI models only *observe*
(what is in the photo, whether the waybill matches it); the verdict is decided by
the engine, and every inspection is stored as a tamper-evident, SHA-256-audited
record.

After the verdict the operator gets a **next-step card** (what to do at the gate,
each step citing a clause of the reference gate SOP), can ask **Pythia** (a
gate assistant that answers only from plant documents, with citations), and the
**shift report** shows what the gate caught, what it saved and which suppliers
repeat.

> One hour of kiln downtime costs about US$28,000. One escaped metal chunk can do
> exactly that. Lynceus stops it at the gate.

## What the demo actually runs

The live AI runs on **AMD Token Factory** (AMD's free shared, OpenAI-compatible
endpoint catalogue, running on AMD GPUs), reached with one team API key:

| Role | Model | Why (measured in `docs/research/token-factory-probe.md`) |
|---|---|---|
| Vision: contaminants, wet/dry, hazard boxes | `MiniCPM-V-4.7-35B-A3B` | the only vision model whose boxes overlapped the metal on the test photo in 3/3 runs (`DeepSeek-V4.1-Flash` image requests timed out in 3/3 runs at the 90 s per-read timeout; `DeepSeek-V4-Flash-Vision-Exp` returned no boxes, 0/3) |
| Waybill cross-check and Pythia | `DeepSeek-V4-Flash` | passed the assistant citation contract 3/3 (`Gemma-4-31B-IT` failed it 0/3) |

It is **not** a self-hosted vLLM on an Instinct MI300X. Self-hosting remains a
supported option (the endpoints are plain OpenAI-compatible URLs, see
[Self-hosting the models](#self-hosting-the-models-optional-not-what-the-demo-runs)),
but no result in this repository was produced that way.

## Architecture

```
photo + waybill text + weight + gas   (inputs frozen + SHA-256 digested)
        │
        ▼
VLM  (MiniCPM-V, Token Factory)  ──► contaminants, wet/dry, confidence, hazard boxes
LLM  (DeepSeek-V4-Flash)         ──► waybill fields, claim-vs-observation cross-check
gas  (digital twin, or a sensor gateway when LYNCEUS_GAS_SENSOR_URL is set)
        │
        ▼
Fusion + rule-based decision engine  (cited: Eq. HH-1 40 CFR 98, EN 15359-style route scores)
        │
        ▼
Verdict ACCEPT / ESCALATE / REJECT + gates + audit record (atomic, tamper-evident)
        │
        ├──► Next-step card   (deterministic rule table, each step cites a gate-SOP clause)
        ├──► Pythia           (BM25 over the plant knowledge base + the current record;
        │                      ungrounded answers are replaced by "cannot answer")
        └──► Shift report     (aggregation over stored records; supplier flags with a
                               model or rule explanation)
```

### Features

- Photo + waybill + weight + gas fusion with a cited, deterministic verdict.
- Hazard localisation: the VLM's boxes are strictly validated (malformed boxes are dropped, never repaired) and drawn on the photo.
- Next-step card with SOP-cited actions after every verdict.
- Pythia assistant grounded in `backend/src/lynceus/knowledge/*.md` and the open record, with citations.
- Shift report with a scripted sample shift (24 trucks, labelled "Sample shift — scripted data") and repeat-supplier flags.
- Ledger of stored inspections (`/inspections`).
- `/validation` page: the benchmark below, with its framing.
- Honest provenance: live results are labelled "Live AMD", scripted demo cases "Scripted sample". With `LYNCEUS_ALLOW_STUB_FALLBACK=0` a live-AI failure returns HTTP 503 instead of an offline stub.

### Limits stated up front

- `POST /inspect` accepts `waybill_image_base64` for forward compatibility, but it is **not processed** — the verdict uses the load photo plus the waybill *text* the operator types in; no OCR is performed.
- Gas readings come from a physics digital twin unless `LYNCEUS_GAS_SENSOR_URL` points at a sensor gateway; the record says which (`digital_twin` or `sentinel_gate_sensor`).

## Validation

**Component validation on public RealWaste images — not field data from a plant.**

80 RealWaste images (Metal 20, plus 60 from seven other classes at fixed quotas;
see `backend/benchmark/images/ATTRIBUTION.md`), each posted live to
`POST /inspect` on Token Factory with a fixed neutral waybill, one run on
2026-10-13. The expected verdict per image is in `backend/benchmark/manifest.csv`.

| Metric | Value |
|---|---|
| Metal gate (REJECT) recall | 0.95 (19/20) |
| Metal gate (REJECT) precision | 0.86 (19/22) |
| n | 80, one run |
| Completed-request latency (end to end) | p50 19.5 s, p95 34.4 s |
| Requests that needed a retry | 3 of 83 attempts |

Raw rows: `backend/benchmark/results/2026-10-13.jsonl`; summary:
`2026-10-13.summary.json`. Re-run from `backend/` with
`PYTHONPATH=src python -m benchmark.run --min-interval 4` (needs the images,
which are not shipped in the Docker image, and a live key). The same numbers are
served at `/benchmark/latest` and shown on `/validation`.

This measures the vision gate on one dataset in one run. It says nothing about
performance on a particular plant's trucks, lighting or waste mix.

## Repository layout

```
backend/            FastAPI app: engine adapter, AI pipeline, audit records
  src/lynceus/        the service package (api, pipeline, decision, actions, assist, shift, audit, impact)
  src/lynceus/knowledge/  plant knowledge base used by Pythia (markdown, package data)
  src/lynceus_engine/ the vendored decision engine (pure Python, MIT)
  tests/              backend tests + opt-in live smoke module (LYNCEUS_LIVE_TESTS=1)
  scripts/            seed_demo.py (demo / sample-shift seeding), probe_token_factory.py
  benchmark/          validation benchmark: manifest, runner, committed results, images
web/                Operator console — Next.js 15 (App Router) static export
deploy/             container entrypoint and the deployment guide
docs/               Plan, hackathon checklist, research notes
Dockerfile          single-container image (API + built UI)
```

## Quickstart

### Local development

Requirements: Python 3.12+, Node.js 20+.

```bash
# 1. Build the web UI (static export -> web/out/)
cd web && npm ci && npm run build && cd ..

# 2. Run the backend (serves the API and the built UI)
cd backend
pip install -e ".[dev]"
cp ../.env.example .env        # then edit; see the env table below
python -m lynceus.main         # http://localhost:8020
```

If `npm run build` fails with `Cannot find module '../lightningcss.<platform>.node'`,
npm skipped an optional native package during `npm ci` (seen once on Windows; the
lockfile does list it). Delete `web/node_modules` and run `npm ci` again.

Open <http://localhost:8020>. The three demo cases (green / amber / red) work
without any key (offline, deterministic). Live inspections need the Token Factory
settings below.

### Docker

```bash
docker build -t lynceus .
cp deploy/lynceus.env.example deploy/lynceus.env   # git-ignored; paste the Token Factory key
docker run -d --name lynceus -p 8020:8020 \
  --env-file deploy/lynceus.env \
  -v lynceus-runs:/data/runs \
  lynceus
```

Use the Docker template, not `.env.example` or `backend/.env`: those are for local
development and set `LYNCEUS_STORAGE_DIR`, which would override the container's
`/data/runs` volume path (the entrypoint exits with an error if the storage dir is
not writable). The template carries the Token Factory endpoints and models and never
sets `LYNCEUS_STORAGE_DIR`, `LYNCEUS_WEB_DIR` or `LYNCEUS_BENCHMARK_DIR`.

On first start (empty storage) the container seeds the 24-truck sample shift,
then serves on `${PORT:-8020}`. Records persist in the `lynceus-runs` volume. The
API key is read from `--env-file` at run time and is never copied into the image.
Full server guide (HTTPS, updates, backups, judging-day checklist):
[`deploy/README.md`](deploy/README.md).

### Environment variables

| Variable | Default | Meaning |
|---|---|---|
| `VLLM_VLM_URL` | `http://localhost:8000/v1` | OpenAI-compatible endpoint for the vision model |
| `VLLM_LLM_URL` | `http://localhost:8001/v1` | OpenAI-compatible endpoint for the text model |
| `VLM_MODEL` | `Qwen/Qwen2.5-VL-7B-Instruct` | Vision-language model id |
| `LLM_MODEL` | `Qwen/Qwen2.5-7B-Instruct` | Text model id |
| `ASSIST_URL` | value of `VLLM_LLM_URL` | Endpoint for Pythia and shift explanations |
| `ASSIST_MODEL` | value of `LLM_MODEL` | Model id for Pythia and shift explanations |
| `LOCALISATION_MODE` | `box` | Hazard localisation: `box` or `zone` |
| `VLLM_API_KEY` | *(empty)* | Bearer key sent to the endpoints (the Token Factory team key); no auth header when empty |
| `LYNCEUS_ALLOW_STUB_FALLBACK` | `1` | `0` / `false` / `no`: a live-AI failure returns HTTP 503 instead of the offline stub (use for hosted demos) |
| `LYNCEUS_GAS_SENSOR_URL` | *(empty)* | HTTP/JSON gate gas-sensor gateway; empty = physics digital twin |
| `LYNCEUS_STORAGE_DIR` | `./runs` (`/data/runs` in the image) | Where inspection audit records live |
| `LYNCEUS_WEB_DIR` | `<repo>/web/out` (`/app/web/out` in the image) | Static web export to serve |
| `LYNCEUS_BENCHMARK_DIR` | `<repo>/backend/benchmark` (`/app/backend/benchmark` in the image) | Benchmark manifest and results for `/benchmark/latest` |
| `PORT` | `8020` | Listening port of `python -m lynceus.main` |
| `AUDIT_FORMAT_VERSION` | `1` | Audit record schema version |

Token Factory settings (local dev: put them in `backend/.env`; Docker: `deploy/lynceus.env`; never commit the key; get the
team key at `notebooks.amd.com/tokenfactory`):

```bash
VLLM_VLM_URL=https://developer.amd.com.cn/radeon/api/v1
VLLM_LLM_URL=https://developer.amd.com.cn/radeon/api/v1
VLM_MODEL=MiniCPM-V-4.7-35B-A3B
LLM_MODEL=DeepSeek-V4-Flash
ASSIST_URL=https://developer.amd.com.cn/radeon/api/v1
ASSIST_MODEL=DeepSeek-V4-Flash
LOCALISATION_MODE=box
VLLM_API_KEY=rc-your-team-key
LYNCEUS_ALLOW_STUB_FALLBACK=0
```

Submit an inspection **without** a `demo_case` and the response carries
`provenance: "live"`. The Token Factory key is rate-limited per key and shared
across the team; the client honours `Retry-After` on HTTP 429.

### Self-hosting the models (optional, not what the demo runs)

Any OpenAI-compatible server works, e.g. vLLM on an AMD Instinct GPU:

```bash
vllm serve Qwen/Qwen2.5-VL-7B-Instruct --host 0.0.0.0 --port 8000
vllm serve Qwen/Qwen2.5-7B-Instruct    --host 0.0.0.0 --port 8001
```

Set `VLLM_VLM_URL` / `VLLM_LLM_URL` accordingly. Deployment notes (AMD Developer
Cloud, tuning flags): `docs/research/amd-gpu-stack.md`. Those notes are research;
the numbers above were not measured on a self-hosted stack.

## Tests

```bash
cd backend
PYTHONPATH=src python -m pytest tests/ -q   # 313 passed, 1 skipped
```

The skipped test is the live smoke module; enable it with `LYNCEUS_LIVE_TESTS=1`
(needs a live endpoint and key).

## Licences

- Lynceus code: MIT (see `LICENSE`).
- **RealWaste images** (the demo photos in `web/public/demo/` and the benchmark
  images in `backend/benchmark/images/`) are from the RealWaste dataset (Single,
  Iranmanesh, Raad, University of Wollongong; UCI ML Repository id 908) and
  remain under their own licence. The licence statements disagree: the UCI page
  says **CC BY 4.0**, the README inside the dataset zip says **CC BY-NC-SA 4.0**.
  Until the authors clarify, treat the more restrictive terms as binding
  (attribution, non-commercial, share-alike). Details:
  `backend/benchmark/images/ATTRIBUTION.md`. The benchmark images are excluded
  from the Docker image.
