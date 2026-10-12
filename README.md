# Lynceus 👁️

> **Predictive Maintenance & Production Anomaly Intelligence on AMD ROCm**
>
> Entry for [AMD Developer Hackathon: ACT III](https://lablab.ai/ai-hackathons/amd-developer-hackathon-act-iii) — Track 1: **Intelligent Industry**

## 🏭 Problem

Factories produce massive data from machines, cameras, sensors, maintenance reports, and technical manuals. The problem is rarely a lack of information — it's **knowing what matters and what to do next**. Unplanned downtime costs manufacturers hundreds of thousands of dollars per hour.

## 💡 Solution

Lynceus helps manufacturers **reduce downtime, improve quality, and increase safety** by:

- **Predicting equipment failures** from sensor time-series (anomaly detection models running on AMD Instinct GPUs via ROCm/PyTorch)
- **Detecting defects** from images/video with vision models accelerated on AMD hardware
- **Explaining production anomalies** in plain language — an LLM agent turns raw alerts into root-cause hypotheses and recommended maintenance actions
- **Answering technician questions** from manuals and maintenance records (RAG)

## 🛠️ Tech Stack

| Layer | Technology |
|---|---|
| GPU compute | AMD Developer Cloud · AMD Instinct · ROCm |
| ML framework | PyTorch (ROCm build) |
| Models | Time-series anomaly detection, vision defect detection, open-weight LLM (served via vLLM on AMD) |
| Backend | Python · FastAPI |
| Frontend | (TBD) |
| Infra | Docker · Docker Compose |

## 📁 Project Structure

```
lynceus/
├── backend/          # FastAPI service + inference pipeline
│   ├── app/
│   ├── models/       # Model definitions & training scripts
│   └── tests/
├── frontend/         # Operator dashboard (TBD)
├── data/             # Sample industrial datasets (not committed)
├── docs/             # Architecture, pitch, demo assets
├── docker-compose.yml
├── Dockerfile
└── README.md
```

## 🚀 Getting Started

```bash
# Clone
git clone https://github.com/rafilajhh/lynceus.git
cd lynceus

# Environment
cp .env.example .env

# Run (CPU dev mode)
docker compose up --build
```

> Full AMD Developer Cloud / ROCm setup instructions coming at kickoff.

## 🏆 Hackathon

- **Event:** AMD Developer Hackathon: ACT III (Online: 12–18 Oct 2026, On-site: Italy)
- **Track:** Intelligent Industry (Track 1)
- **Requirement:** Meaningful part of the workload runs on AMD infrastructure (ROCm / AMD Instinct / AMD Developer Cloud)
- **Team:** [@rafilajhh](https://github.com/rafilajhh)

## 📄 License

MIT
