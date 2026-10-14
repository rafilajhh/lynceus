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

> One escaped metal chunk can wreck a shredder and stop a kiln. On 80 public waste
> photos run live on AMD Token Factory, the gate rejected 19 of 20 metal loads and,
> under the current rules, passed 35 of 40 clean RDF loads straight through
> ([Validation](#validation): component test on public images, not plant data).

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
- Shift report with a scripted sample shift (24 trucks, seeded offline, labelled "Sample shift — scripted data") and repeat-supplier flags.
- Ledger of stored inspections (`/inspections`).
- `/validation` page: the benchmark below, with its framing.
- Honest provenance: live results are labelled "Live AMD" (the verdict also shows model and latency on one quiet line); a stub answer after a live failure is labelled as a scripted fallback. With `LYNCEUS_ALLOW_STUB_FALLBACK=0` a live-AI failure returns HTTP 503 instead of an offline stub.

### Limits stated up front

- `POST /inspect` accepts `waybill_image_base64` for forward compatibility, but it is **not processed** — the verdict uses the load photo plus the waybill *text* the operator types in; no OCR is performed.
- Gas readings come from a physics digital twin unless `LYNCEUS_GAS_SENSOR_URL` points at a sensor gateway; the record says which (`digital_twin` or `sentinel_gate_sensor`).

## Validation

**Component validation on public RealWaste images — not field data from a plant.**

80 RealWaste images (Metal 20, plus 60 from seven other classes at fixed quotas;
see `backend/benchmark/images/ATTRIBUTION.md`), each posted live to
`POST /inspect` on Token Factory with a fixed neutral waybill, one run on
2026-10-13. The expected verdict per image is in `backend/benchmark/manifest.csv`.

| Metric | Live run (rules of 2026-10-13) | Current rules (replay) |
|---|---|---|
| Metal gate (REJECT) recall | 0.95 (19/20) | 0.95 (19/20) |
| Metal gate (REJECT) precision | 0.86 (19/22) | 0.90 (19/21) |
| Clean RDF loads passed (ACCEPT) | 0.30 (12/40) | 0.88 (35/40) |
| Trucks sent to an operator (ESCALATE) | 0.55 (44/80) | 0.26 (21/80) |
| n | 80, one run | same 80 recorded outputs |
| Completed-request latency (end to end) | p50 19.5 s, p95 34.4 s | no new model calls |
| Requests that needed a retry | 3 of 83 attempts | — |

The live run escalated plastic film and textile as "light contaminants", although
they are the calorific fraction RDF is made from. The current rules treat them as
feedstock. The **replay** feeds the recorded live model outputs of the same run
through the current decision rules, without new model calls; the rule change was
motivated by this same data, so the replay is not a held-out measurement.

Raw rows: `backend/benchmark/results/2026-10-13.jsonl`; summary:
`2026-10-13.summary.json`; replay: `2026-10-13.rescore.{jsonl,summary.json}`.
Re-run the live benchmark from `backend/` with
`PYTHONPATH=src python -m benchmark.run --min-interval 4` (needs the images,
which are not shipped in the Docker image, and a live key); re-score with
`PYTHONPATH=src python -m benchmark.rescore --source benchmark/results/2026-10-13.jsonl`
(offline). Both are served at `/benchmark/latest` and shown on `/validation`.

This measures the vision gate on one dataset in one run. It says nothing about
performance on a particular plant's trucks, lighting or waste mix.

**Value per 1,000 trucks.** The `/shift` page turns these rates into an expected
value with and without Lynceus (escaped hard loads, damage, operator time, cost
of wrongly rejected clean loads), with every parameter either sourced or marked
as an adjustable assumption and a low/base/high range — the low case is negative
and is shown as such. Model: `value_model` in `backend/src/lynceus/impact.py`.

## Business case

Users, buyers, market (Indonesia and Italy), competitors and the pricing
proposal: [`docs/BUSINESS.md`](docs/BUSINESS.md).

## Operator validation

A 15-minute interview kit to check the problem, its cost and willingness to pay
with an RDF gate operator or co-processing manager:
[`docs/operator-validation-kit.md`](docs/operator-validation-kit.md).

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

Open <http://localhost:8020>. The workspace takes an uploaded photo plus the waybill
text; inspections need the Token Factory settings below. Without a key the live call
fails: by default (`LYNCEUS_ALLOW_STUB_FALLBACK=1`) the backend answers with an
offline scripted stub labelled `stub_fallback_live_error` and the UI says so; with
`LYNCEUS_ALLOW_STUB_FALLBACK=0` it returns HTTP 503. The 24-truck sample shift is
seeded offline and needs no key. (`POST /inspect` still accepts a scripted
`demo_case` for the seeder and tests; the UI no longer offers it.)

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
development, with localhost vLLM URLs and models, whereas the template carries the
Token Factory endpoints and models and `LYNCEUS_ALLOW_STUB_FALLBACK=0`. It never sets
`LYNCEUS_STORAGE_DIR`, `LYNCEUS_WEB_DIR` or `LYNCEUS_BENCHMARK_DIR`, so the container's
`/data/runs` volume path stays in force (the entrypoint exits with an error if the
storage dir is not writable).

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
| `ASSIST_URL` | value of `VLLM_LLM_URL` | Endpoint for Pythia |
| `ASSIST_MODEL` | value of `LLM_MODEL` | Model id for Pythia |
| `EXPLAIN_URL` | value of `ASSIST_URL` | Endpoint for shift-report explanations (separate role) |
| `EXPLAIN_MODEL` | value of `ASSIST_MODEL` | Model id for shift-report explanations |
| `LOCALISATION_MODE` | `box` | Hazard localisation: `box` or `zone` |
| `VLLM_API_KEY` | *(empty)* | Bearer key sent to the endpoints (the Token Factory team key); no auth header when empty |
| `LYNCEUS_ALLOW_STUB_FALLBACK` | `1` | `0` / `false` / `no`: a live-AI failure returns HTTP 503 instead of the offline stub (use for hosted demos) |
| `LYNCEUS_GAS_SENSOR_URL` | *(empty)* | HTTP/JSON gate gas-sensor gateway; empty = physics digital twin |
| `LYNCEUS_STORAGE_DIR` | `./runs` (`/data/runs` in the image) | Where inspection audit records live |
| `LYNCEUS_WEB_DIR` | `<repo>/web/out` (`/app/web/out` in the image) | Static web export to serve |
| `LYNCEUS_BENCHMARK_DIR` | `<repo>/backend/benchmark` (`/app/backend/benchmark` in the image) | Benchmark manifest and results for `/benchmark/latest` |
| `PORT` | `8020` | Listening port of `python -m lynceus.main` |

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
PYTHONPATH=src python -m pytest tests/ -q   # 340 passed, 1 skipped
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
