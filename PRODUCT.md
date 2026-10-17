# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

Next.js 15 (App Router, React 19, Tailwind v4) in `web/` built to a static export (`npm run build` → `web/out/`) served by FastAPI static mount + JSON API backend (`backend/src/lynceus/`). Existing codebase answers this.

## Users

1. **Judges of AMD Developer Hackathon ACT III** (lablab.ai, international) — open the demo URL, evaluate in minutes against the Intelligent Industry brief: real problem, working product, operator-understandable results, measurable improvement. *(inferred from hackathon context)*
2. **Weighbridge operators at RDF co-processing cement plants in Indonesia** (e.g. Semen Gresik, SBI Cilacap lines) — inspect incoming waste trucks in under 30 seconds before tipping into the shredder line. *(confirmed via research: docs/research/realcase-indonesia.md)*

## Product Purpose

Lynceus is an AI gate inspector for alternative-fuel (RDF) facilities. It fuses a load photo (VLM), waybill text (LLM), weighbridge mass, and gate gas telemetry (physics digital twin) into one verdict — ACCEPT / ESCALATE / REJECT — with reasons, confidence, and a tamper-evident SHA-256 audit record per truck. Success: stops contaminants (metal, rock) before they destroy shredders (≈Rp 350jt) or halt kilns (≈US$28k/hour).

## Positioning

AI vision + regulation-grounded decision engine (Eq. HH-1, EN 15359-style route scoring) + tamper-evident audit trail — not a chatbot, not a dashboard. The decision engine (`lynceus_engine`) is the team's own earlier MIT engine, vendored in on 13 Oct 2026; the AMD AI layer, the CPU detector, the fusion pipeline, the audit trail and the web app were built during the hackathon.

## Operating Context

- Trucks stop at the weighbridge 15–30 s; operator uploads/submits photo + surat jalan + weight; verdict ticket must be readable in seconds (traffic-light + reasons).
- Demo runs live at a public URL; AI served via AMD Token Factory (AMD's shared OpenAI-compatible endpoint catalogue on AMD GPUs; env-var switch to any OpenAI-compatible server, zero code change).
- Demo cases grounded in real Indonesian data: arm-roll trucks ~5.2 t/trip, MSW moisture 40–60%, PUPR surat jalan format; the demo truck-bed photos and the waybill are AI-generated, fictitious illustrations; the benchmark uses RealWaste photos (licence terms disagree, CC BY-NC-SA 4.0 treated as binding).
- English UI for international judges.

## Capabilities and Constraints

- `POST /inspect`: full pipeline (photo base64 → VLM stub/live → LLM cross-check → Lynceus engine → fusion verdict → audit record + impact estimate with per-figure source URLs).
- `POST /assess`: direct Lynceus engine assessment.
- Audit records: tamper-evident, atomic-write, strict-decode; 57 invariant checks; record_id never reused.
- Gas digital twin: Eq. HH-1 generation → virtual NDIR/PID/EC sensors, deterministic per truck/record; gas supports (never overrides) the visual verdict.
- Impact estimates: prevented-loss in IDR/USD with cited basis rows (REJECT: shredder + kiln downtime; ACCEPT: RDF value band).
- Backend test suite green (`pytest`); stub AI is deterministic and honestly labeled (`provenance: stub` vs `live`).
- Constraint: eligibility requires AMD to power the working product at demo time.

## Brand Commitments

- Name: **Lynceus** (the sharp-sighted watchman of Greek myth); agent name **Pythia**.
- Visual direction: **industrial** — enterprise-grade, dark, technical, credible — with minimalism and typographic discipline.

## Evidence on Hand

- `docs/research/realcase-indonesia.md` — sourced figures (SIPSN, ITATS, SBI Cilacap, RDI reports) for demo data and impact numbers.
- `docs/research/token-factory-probe.md` — measured Token Factory model comparison and selection.
- `web/public/demo/` — AI-generated truck-bed photos (metal / clean / ambiguous scenarios) and an AI-generated sample waybill; see `web/public/demo/README.md`.
- `docs/BUSINESS.md`, `docs/submission/` — business case and the lablab submission text.
- Absences that must not be fabricated: no real customer logos, no real deployment, no measured accuracy on production data (label demo numbers as sourced estimates).

## Product Principles

1. **Show the real case, not the tech** — every number on screen must answer "from where?" with a citation.
2. **Operator-first comprehension** — verdict in seconds, reasons in plain English, uncertainty stated honestly (screening vs validated).
3. **Evidence is the product** — the audit record is a first-class citizen, not a hidden JSON blob.
4. **Flawless beats featureful** — one pipeline that works end-to-end wins over three half-built features.

## Accessibility & Inclusion

Not yet established; apply WCAG-conscious defaults (contrast, focus states, keyboard operability) as craft floor.
