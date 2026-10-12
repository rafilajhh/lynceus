# Design Review — Lynceus Web App Redesign

**Date:** 2026-10-13 · **Reviewer pass:** live browser at 127.0.0.1:8020 (1440px + 390px), all 7 review screenshots, direction contract, PRODUCT.md.

## Verdict: **FIX**

The redesign is genuinely strong — contract-compliant, memorable, and error-free in the happy path. But two material credibility risks would be exposed by normal judge behavior (refreshing the page, reading the ledger), so ship only after the fixes below.

## What works (verified live)

- **First 10 seconds:** landing headline + real red-case photo (labeled) + "Open Live Demo" is immediate and persuasive; cost counters animate on scroll (Rp 350jt, US$28k/hr) and land correctly.
- **Signature move works:** gate strip snaps on sequentially (120ms stagger), verdict banner lights only after all five resolve, impact counter counts to Rp 798.000.000. Math checks: 350jt + 448jt = 798jt ≈ US$49,875 @ 16.000. All three verdict states (ACCEPT/ESCALATE/REJECT) render correctly.
- **Evidence is real:** audit modal shows SHA-256 digest, per-gate values/thresholds/reasons, gas readings, and every rupiah figure carries a source URL. Ledger filter + detail panel work. Zero console errors across all flows.
- **Craft floor:** token system matches the contract exactly (graphite #0a0c10, 1px #1c2128 seams, single amber, Plex Sans/Mono); global `:focus-visible` amber ring; hover/active/disabled states present; prefers-reduced-motion respected in counters; mobile single-column holds up.

## Material findings (fix before ship)

1. **HIGH — Hard reload / direct URL breaks the demo.** Refresh at `/app` → in-app 404 ("No such route"); direct open of `/inspections` → raw JSON API payload instead of the ledger page. FastAPI `StaticFiles(html=True)` never maps `/app` → `app.html`, and `GET /inspections` (API) shadows the page. **Fix:** explicit FastAPI routes serving `app.html`/`inspections.html` for HTML requests (or namespace the API under `/api/`). This is the single most likely demo-day failure.
2. **HIGH — Ledger seed data undermines "real Indonesian data."** Truck F 7702 TS is REJECTED 9× in 3 hours, each "preventing" Rp 798jt, summed to "Rp 9.593.474.788 prevented" — double-counting one shredder/kiln event. Raw IDs `demo-green/amber/red` are judge-visible. **Fix:** vary seeded trucks/figures, footnote the aggregate as "demo history," never let `demo-*` IDs render.
3. **MEDIUM — Indonesian impact notes inside an English UI.** Notes like "REJECT dengan kontaminan keras…" and basis labels "Downtime kiln (1 jam…)" appear in the verdict panel and audit modal. Contract says English for international judges. **Fix:** translate notes/labels; keep Indonesian only in cited source names.
4. **LOW — Stale state during re-inspection:** old REJECT impact note stays visible beneath pending gates while the new run evaluates.
5. **LOW — Unexplained terms:** "REFUSED" verdict has no tooltip/copy anywhere; status chip is one aggregate dot, not the per-service (VLM/LLM/engine/gas) dots the brief specifies.

## Standard check

Enterprise-grade à la Cloudflare/Vercel? **Visually yes** — typography discipline, hairline seams, honest degradation, mono figures. **Operationally not yet**: a 404 on refresh and inflated aggregate math are exactly the flaws that category never ships. Fix findings 1–3 and this is credibly in that tier.
