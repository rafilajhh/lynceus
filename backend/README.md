# Lynceus — backend

FastAPI service exposing anomaly prediction, defect detection, and LLM explanation endpoints.

```
backend/
├── app/
│   ├── main.py          # FastAPI entrypoint (coming soon)
│   ├── api/             # Route handlers
│   ├── core/            # Config, logging
│   └── services/        # Inference, RAG, alerting
├── models/              # Training & model definitions (PyTorch ROCm)
└── tests/
```

Run locally (dev):

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```
