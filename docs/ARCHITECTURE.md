# Lynceus Architecture

## Overview

```
[Sensors/PLC]──┐                      ┌──► Anomaly Detector (PyTorch on ROCm)
[Camera feeds]─┼──► Ingestion ──► GPU ┼──► Vision Defect Model (ROCm)
[Manuals/Rpts]─┘      Pipeline         └──► LLM Agent (vLLM on AMD Instinct)
                                              │
                                              ▼
                                    Operator Dashboard (alerts,
                                    root-cause explanation,
                                    recommended maintenance actions)
```

## Pipeline

1. **Ingest** — sensor time-series & images arrive via API/webhook.
2. **Detect** — anomaly + defect models run on AMD GPUs (ROCm PyTorch).
3. **Explain** — flagged anomalies are contextualized by an open-weight LLM served with vLLM on AMD Developer Cloud, grounded in maintenance manuals (RAG).
4. **Act** — operators receive alerts with root-cause hypotheses and concrete maintenance recommendations.

## AMD Component (hackathon requirement)

- Anomaly/defect model inference: **ROCm PyTorch** on AMD Instinct
- LLM serving: **vLLM** on AMD Developer Cloud
- Benchmarking: note comparing ROCm vs CPU inference throughput (docs/)
