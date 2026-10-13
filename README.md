# Lynceus

**AI gate inspector for alternative-fuel (RDF) facilities — built for the AMD Developer Hackathon: ACT III (Intelligent Industry track).**

Lynceus inspects a waste truck's load at the weighbridge in seconds, before it is
tipped into the plant: a photo of the load, the waybill, the weighed mass, and
gate gas telemetry are fused by a **vision-language model (Qwen2.5-VL-7B)** and
an **LLM (Qwen2.5-7B)** served with **vLLM on AMD Instinct MI300X (ROCm)**,
then scored by a **regulation-grounded decision engine**. The operator gets a
verdict — **ACCEPT / ESCALATE / REJECT** — with reasons, confidence, and an
immutable, SHA-256-audited record for every inspection.

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
Verdict ACCEPT / ESCALATE / REJECT  +  gates  +  audit record (atomic, immutable)
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
  tests/              pytest suite (57 audit-invariant checks + API tests)
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
| `VLLM_API_KEY` | *(empty)* | Optional bearer key for the vLLM endpoints; no auth header sent when empty |
| `LYNCEUS_AI_PROVIDER` | `vllm` | AI provider selector (`vllm` or `openai-compatible` — same client logic) |
| `LYNCEUS_STORAGE_DIR` | `./runs` | Where inspection audit records live |
| `AUDIT_FORMAT_VERSION` | `1` | Audit record schema version |

No API keys are committed; anything secret belongs in environment variables.

### Serving the models on AMD (ADC MI300X)

```bash
vllm serve Qwen/Qwen2.5-VL-7B-Instruct --host 0.0.0.0 --port 8000
vllm serve Qwen/Qwen2.5-7B-Instruct    --host 0.0.0.0 --port 8001
```

Full deployment notes (AMD Developer Cloud, credits, tuning flags):
see `docs/research/amd-gpu-stack.md`.

## Tests

```bash
cd backend
python -m pytest tests/ -q        # 57 audit-invariant checks + API tests
```

## License

MIT (see `LICENSE`).
