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
Scentinel decision engine (rule-based, cited: Eq. HH-1 40 CFR 98, EN 15359-style route scores)
        │
        ▼
Verdict ACCEPT / ESCALATE / REJECT  +  gates  +  audit record (atomic, immutable)
```

## Provenance

The decision engine is built on **[Scentinel](https://github.com/alertxsto/scentinel)**,
an open-source (MIT) waste-assessment project by our own team that predates this
hackathon. What is new here, built during the hackathon: the AMD-hosted AI layer
(Qwen2.5-VL + Qwen2.5-7B + vLLM + ROCm), the multi-modal fusion pipeline, and the
web operator UI.

## Repository layout

```
backend/   FastAPI app: engine adapter, AI pipeline (vLLM client), audit records
web/       Operator dashboard (static, no build step)
docs/      Plan, hackathon checklist, and research notes
```

## Quickstart

Requirements: Python 3.12+, the Scentinel engine installed
(`pip install -e ../scentinel` or from its repo), FastAPI deps.

```bash
pip install fastapi "uvicorn[standard]" pydantic httpx pytest
cd backend
python -m lynceus.main          # serves API + web UI at http://localhost:8020
```

Then open <http://localhost:8020> — the dashboard loads with three demo cases
(green / amber / red).

### Configuration (environment variables)

| Variable | Default | Meaning |
|---|---|---|
| `VLLM_VLM_URL` | `http://localhost:8000/v1` | vLLM OpenAI-compatible endpoint for the VLM |
| `VLLM_LLM_URL` | `http://localhost:8001/v1` | vLLM endpoint for the text LLM |
| `VLM_MODEL` | `Qwen/Qwen2.5-VL-7B-Instruct` | Vision-language model id |
| `LLM_MODEL` | `Qwen/Qwen2.5-7B-Instruct` | Text model id |
| `LYNCEUS_STORAGE_DIR` | `./runs` | Where inspection audit records live |
| `AUDIT_FORMAT_VERSION` | `1` | Audit record schema version |

No API keys are committed; anything secret belongs in environment variables.

### Serving the models on AMD (ADC MI300X)

```bash
vllm serve Qwen/Qwen2.5-VL-7B-Instruct --host 0.0.0.0 --port 8000
vllm serve Qwen/Qwen2.5-7B-Instruct    --host 0.0.0.0 --port 8001
```

Full deployment notes (AMD Developer Cloud, credits, tuning flags):
see `docs/research-amd-gpu-stack.md`.

## Tests

```bash
cd backend
python -m pytest tests/ -q        # 57 audit-invariant checks + API tests
```

## License

MIT (see `LICENSE`).
