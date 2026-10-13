# Lynceus

**AI gate inspector for alternative-fuel (RDF) facilities — built for the AMD Developer Hackathon: ACT III (Intelligent Industry track).**

Lynceus inspects a waste truck's load at the weighbridge in seconds, before it is
tipped into the plant: a photo of the load, the waybill, the weighed mass, and
gate gas telemetry are fused by a **vision-language model (Qwen2.5-VL-7B)** and
an **LLM (Qwen2.5-7B)** served with **vLLM on AMD Instinct MI300X (ROCm)**,
then scored by a **regulation-grounded decision engine**. The operator gets a
verdict — **ACCEPT / ESCALATE / REJECT** — with reasons, confidence, and an
tamper-evident, SHA-256-audited record for every inspection.

> One hour of kiln downtime costs ≈ US$28,000. One escaped metal chunk can do
> exactly that. Lynceus stops it at the gate.

## Architecture

```
photo + waybill + weight + gas   (inputs frozen + SHA-256 digested)
        │
        ▼
VLM (Qwen2.5-VL, vLLM @ AMD MI300X) ──► contaminants, wet/dry, confidence
LLM (Qwen2.5-7B,  vLLM @ AMD MI300X) ─► waybill fields, claim-vs-observation crosscheck
        │
        ▼
Lynceus decision engine (rule-based, cited: Eq. HH-1 40 CFR 98, EN 15359-style route scores)
        │
        ▼
Verdict ACCEPT / ESCALATE / REJECT  +  gates  +  audit record (atomic, tamper-evident)
```

## Provenance

The decision engine, the AMD-hosted AI layer (Qwen2.5-VL + Qwen2.5-7B +
vLLM + ROCm), the multi-modal fusion pipeline, and the web operator UI
were all built for this project.

## Repository layout

```
backend/            FastAPI app: engine adapter, AI pipeline (vLLM client), audit records
  src/lynceus/        the service package (api, pipeline, decision, audit, impact)
  src/lynceus_engine/ the vendored decision engine (pure Python, MIT)
  tests/              35 backend tests (one audit-invariant test with ~57 sub-checks) + opt-in live smoke module (LYNCEUS_LIVE_TESTS=1)
  scripts/            demo seeding utility
web/                Operator dashboard — Next.js 15 (App Router) static export
  app/                routes: / (landing), /app (workspace), /inspections (ledger)
  components/         ui/ primitives, shell/ chrome, workspace/ inspection flow
  lib/                API clients (zod contracts), demo cases, formatting
  public/demo/        RealWaste demo photos (CC BY 4.0)
  scripts/            dev utilities (mock API server)
docs/               Plan, hackathon checklist, design review
  research/           sourced research notes (AMD stack, Indonesia case, audit, datasets)
```

## Quickstart

Requirements: Python 3.12+, Node.js 20+, FastAPI deps. The decision engine
(`lynceus_engine`) is vendored in `backend/src/lynceus_engine/` — no
separate install needed.

```bash
# 1. Build the web dashboard (Next.js static export → web/out/)
cd web
npm install
npm run build
cd ..

# 2. Run the backend (serves API + the built web UI)
pip install fastapi "uvicorn[standard]" pydantic httpx pytest
cd backend
pip install -e .
python -m lynceus.main          # serves API + web UI at http://localhost:8020
```

Then open <http://localhost:8020> — the dashboard loads with three demo cases
(green / amber / red).

> The frontend is a Next.js app built to a **fully static export** (`web/out/`)
> that FastAPI serves — no Node runtime needed in production, but producing
> the bundle does require `npm run build`.

### Configuration (environment variables)

| Variable | Default | Meaning |
|---|---|---|
| `VLLM_VLM_URL` | `http://localhost:8000/v1` | vLLM OpenAI-compatible endpoint for the VLM |
| `VLLM_LLM_URL` | `http://localhost:8001/v1` | vLLM endpoint for the text LLM |
| `VLM_MODEL` | `Qwen/Qwen2.5-VL-7B-Instruct` | Vision-language model id |
| `LLM_MODEL` | `Qwen/Qwen2.5-7B-Instruct` | Text model id |
| `ASSIST_URL` | value of `VLLM_LLM_URL` | Endpoint for the assistant role |
| `ASSIST_MODEL` | value of `LLM_MODEL` | Assistant model id |
| `LOCALISATION_MODE` | `box` | Hazard localisation: `box` or `zone` |
| `VLLM_API_KEY` | *(empty)* | Optional bearer key for the vLLM endpoints; no auth header sent when empty |
| `LYNCEUS_STORAGE_DIR` | `./runs` | Where inspection audit records live |
| `AUDIT_FORMAT_VERSION` | `1` | Audit record schema version |

No API keys are committed; anything secret belongs in environment variables.

> **Honest-contract note:** `POST /inspect` also accepts `waybill_image_base64`
> (a photo of the paper waybill) for forward compatibility, but it is **not
> processed today** — the verdict uses the load photo plus the waybill *text*
> the operator types in (`manifest_text`), and no OCR is performed. The gas
> readings are simulated by a physics digital twin, not measured by hardware.

### Serving the models on AMD (ADC MI300X)

```bash
vllm serve Qwen/Qwen2.5-VL-7B-Instruct --host 0.0.0.0 --port 8000
vllm serve Qwen/Qwen2.5-7B-Instruct    --host 0.0.0.0 --port 8001
```

Full deployment notes (AMD Developer Cloud, credits, tuning flags):
see `docs/research/amd-gpu-stack.md`.

### Running live on AMD Token Factory (no self-host needed)

Token Factory is AMD's free shared endpoint catalog (OpenAI-compatible,
runs on AMD GPUs). It needs no instance — just a team API key from
`notebooks.amd.com/tokenfactory`. Point both model roles at the same base
URL in `backend/.env` (never commit the key):

```bash
VLLM_VLM_URL=https://developer.amd.com.cn/radeon/api/v1
VLLM_LLM_URL=https://developer.amd.com.cn/radeon/api/v1
VLM_MODEL=MiniCPM-V-4.7-35B-A3B # vision + box localisation (p50 14.5 s in the probe)
LLM_MODEL=DeepSeek-V4-Flash     # text waybill cross-check
ASSIST_URL=https://developer.amd.com.cn/radeon/api/v1
ASSIST_MODEL=DeepSeek-V4-Flash  # assistant role (p50 4.5 s in the probe)
LOCALISATION_MODE=box
VLLM_API_KEY=rc-your-team-key
```

Then `python -m lynceus.main` and submit an inspection **without** a
`demo_case` — the response carries `provenance: "live"`. The verdict panel
labels it `Live AMD`; scripted demo cases are labelled `Scripted sample`.

Model choice is empirical, not arbitrary (probe results and method in
`docs/research/token-factory-probe.md`): `MiniCPM-V-4.7-35B-A3B` was the only
vision model whose boxes overlapped the metal on the test photo in 3/3 runs
(p50 14.5 s); `DeepSeek-V4.1-Flash` timed out on image requests in 3/3 runs;
`Gemma-4-31B-IT` failed the assistant JSON contract in 3/3 runs, while
`DeepSeek-V4-Flash` passed it 3/3 (p50 4.5 s). The client honours
`Retry-After` on HTTP 429 (the team key is rate-limited per key, shared
across teammates).

## Tests

```bash
cd backend
python -m pytest tests/ -q        # 35 passed, 1 skipped by default; enable live smoke with LYNCEUS_LIVE_TESTS=1
```

## License

MIT (see `LICENSE`).

## Run with Docker

One container ships the API and the pre-built static UI. `Dockerfile` builds the
Next.js export in a `node:20-alpine` stage and copies it into a `python:3.12-slim`
runtime, so no Node toolchain is needed on the target host.

```bash
# Build the image
docker build -t lynceus .

# Run it, persisting audit records to a host directory
docker run --rm -p 8020:8020 \
  -v "$PWD/runs:/data" \
  lynceus
```

Then open <http://localhost:8020>. The `-v "$PWD/runs:/data"` flag mounts a host
directory onto `/data`, which is the image's `LYNCEUS_STORAGE_DIR` — inspection
audit records survive container restarts. Point the vLLM variables at your model
hosts with `-e VLLM_VLM_URL=... -e VLLM_LLM_URL=...` (see the configuration table
above); the container defaults to the built-in `http://localhost:...` endpoints,
which are not reachable from inside the container unless the models run alongside it.

> `docker build` not yet validated on this dev machine (no Docker installed);
> validate on a Docker-capable machine before deployment.
