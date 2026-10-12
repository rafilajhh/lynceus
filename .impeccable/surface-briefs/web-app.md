# Surface Brief — Lynceus Web App (workspace + landing + audit log)

## Scope & Visitor Mode

Routes: `/` (landing, Persuade for judges), `/app` (inspection workspace, Operate), `/inspections` (audit log, Read/Operate). Multi-route single-page app (hash routing, no build step) served by FastAPI static mount.

## Audience, Job, Proof

Judges (first) and weighbridge operators (truth). Job: inspect a truck in <30s, get verdict + reasons + audit. Proof: real Indonesian demo data, Rp impact figures with source URLs, live AI, 9 real photos, immutable records. Constraints: vanilla HTML/CSS/JS, English, WCAG-conscious.

## Direction Contract

THESIS: an enterprise-grade dark working surface where the verdict is a *lived industrial moment*, not a form response — the category default (dashboard with KPI cards + accent) is refused by making one inspection the whole stage, with the audit ledger as living proof beneath it.

OWN-WORLD: graphite-dark ground (#0a0c10 family), hairline panel seams (1px #1c2128) instead of shadows, one-step elevation, IBM Plex Sans + IBM Plex Mono figures, small-caps panel headers, single amber accent (#f5a623 family) reserved for state and signature; verdict states green/amber/red on top of the palette only where they carry meaning.

STORY: visitor lands on a landing that states the real problem with real numbers (Rp 350jt shredder, US$28k/hr kiln), sees the product working in one screenshot, clicks "Open Live Demo" → workspace: left = incoming load photo + intake form, right = verdict ticket that assembles itself gate-by-gate (signature move: the five-gate strip that lights up sequentially like an industrial interlock), below = the inspection ledger with every audit record browsable; every number carries its source.

FIRST VIEWPORT: top bar "LYNCEUS — AI Gate Inspector" with live status chip (VLM/LLM/engine/gas green dots); main split 5/7: left column photo hero (real waste photo, mono caption) + compact intake form + demo-case buttons; right column verdict panel (traffic-light banner, headline, impact counter that counts up to Rp 798jt, gate strip, reasons, caveats, audit link). At 1440px; collapses to single column at 960px.

FORM: industrial control-room register via the dark-first developer-console grammar — panels tile and persist, hairline seams, syntax-derived accents for state only, destructive/reject actions given deliberate isolation with empty space, monospaced figures for all measurements.

Signature move (named): **the interlock gate strip** — five gates (VLM confidence, OCR, manifest crosscheck, gas plausibility, weight plausibility) as a horizontal strip of industrial indicator lights that evaluate sequentially when a verdict is computed, each snapping to green/red with a label, like a machine startup interlock; the verdict banner only lights after all five resolve.

Raises adopted from challengers (verdicts recorded): challenger #3 dark-first developer console = **wins** (assigned base fused with it); challenger #2 saville catalog — declined, donates "vast unprinted ground, one element owning the field" discipline; challenger #5 airport wayfinding — declined, donates "one message per band" copy discipline; challenger #1/#4/#6 — declined, no transfer.

## Memorable Moment

The gate strip interlock: five lights snap on, then the verdict banner fires — and the impact counter counts up to the prevented loss in rupiah.

## Unresolved Decisions

None blocking; landing hero photo = red-case RealWaste photo (labeled), logo = text wordmark LYNCEUS with eye-slit glyph (inline SVG, no asset needed).
