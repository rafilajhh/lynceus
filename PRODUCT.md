# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

Static web (`web/`: vanilla HTML/CSS/JS, no build step) served by FastAPI static mount + JSON API backend (`backend/lynceus/`). Existing codebase answers this.

## Users

1. **Judges of AMD Developer Hackathon ACT III** (lablab.ai, international) — open the demo URL, evaluate in minutes against the Intelligent Industry brief: real problem, working product, operator-understandable results, measurable improvement. *(inferred from hackathon context)*
2. **Weighbridge operators at RDF co-processing cement plants in Indonesia** (e.g. Semen Gresik, SBI Cilacap lines) — inspect incoming waste trucks in under 30 seconds before tipping into the shredder line. *(confirmed via research: docs/research-realcase-indonesia.md)*

## Product Purpose

Lynceus is an AI gate inspector for alternative-fuel (RDF) facilities. It fuses a load photo (VLM), waybill text (LLM), weighbridge mass, and gate gas telemetry (physics digital twin) into one verdict — ACCEPT / ESCALATE / REJECT — with reasons, confidence, and an immutable SHA-256 audit record per truck. Success: stops contaminants (metal, rock) before they destroy shredders (≈Rp 350jt) or halt kilns (≈US$28k/hour).

## Positioning

AI vision + regulation-grounded decision engine (Eq. HH-1, EN 15359-style route scoring) + immutable audit trail — not a chatbot, not a dashboard. The decision engine is built on Scentinel, the team's own pre-hackathon MIT open-source project; the AMD AI layer, fusion pipeline, and web app are new.

## Operating Context

- Trucks stop at the weighbridge 15–30 s; operator uploads/submits photo + surat jalan + weight; verdict ticket must be readable in seconds (traffic-light + reasons).
- Demo runs live at a public URL; AI served via vLLM on AMD Instinct MI300X (dev bridge: OpenAI-compatible endpoint; env-var switch, zero code change).
- Demo cases grounded in real Indonesian data: arm-roll trucks ~5.2 t/trip, MSW moisture 40–60%, PUPR surat jalan format, RealWaste photos (CC BY 4.0).
- English UI for international judges.

## Capabilities and Constraints

- `POST /inspect`: full pipeline (photo base64 → VLM stub/live → LLM cross-check → Scentinel engine → fusion verdict → audit record + impact estimate with per-figure source URLs).
- `POST /assess`: direct Scentinel engine assessment.
- Audit records: immutable, atomic-write, strict-decode; 57 invariant checks; record_id never reused.
- Gas digital twin: Eq. HH-1 generation → virtual NDIR/PID/EC sensors, deterministic per truck/record; gas supports (never overrides) the visual verdict.
- Impact estimates: prevented-loss in IDR/USD with cited basis rows (REJECT: shredder + kiln downtime; ACCEPT: RDF value band).
- 26 backend tests green; stub AI is deterministic and honestly labeled (`provenance: stub` vs `live`).
- Constraint: eligibility requires AMD to power the working product at demo time.

## Brand Commitments

- Name: **Lynceus** (the sharp-sighted watchman of Greek myth); agent name **Pythia**.
- User-pinned visual direction: **Cloudflare-style industrial** — enterprise-grade, dark, technical, credible — with Vercel-grade minimalism and typographic discipline. User's words: "cloudflare style, itu industrial paling mantep buat layak disebut, vercel style juga".

## Evidence on Hand

- `docs/research-realcase-indonesia.md` — sourced figures (SIPSN, ITATS, SBI Cilacap, RDI reports) for demo data and impact numbers.
- `docs/research-amd-gpu-stack.md` — AMD stack, benchmarks, deploy steps.
- `web/demo/` — 9 real RealWaste photos + ATTRIBUTION.md (CC BY 4.0).
- `docs/PLAN.md`, `docs/HACKATHON-CHECKLIST.md` — plan, judging criteria mapping, submission checklist.
- Absences that must not be fabricated: no real customer logos, no real deployment, no measured accuracy on production data (label demo numbers as sourced estimates).

## Product Principles

1. **Show the real case, not the tech** — every number on screen must answer "from where?" with a citation.
2. **Operator-first comprehension** — verdict in seconds, reasons in plain English, uncertainty stated honestly (screening vs validated).
3. **Evidence is the product** — the audit record is a first-class citizen, not a hidden JSON blob.
4. **Flawless beats featureful** — one pipeline that works end-to-end wins over three half-built features.

## Accessibility & Inclusion

Not yet established; apply WCAG-conscious defaults (contrast, focus states, keyboard operability) as craft floor.
