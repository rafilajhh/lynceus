# Lynceus Design Language — DESIGN.md

Single source of documentation for the Lynceus visual language. All tokens below
are read from actual code: `web/app/globals.css` (`@theme` block), the component
primitives in `web/components/ui/`, and the direction contract in
`.impeccable/surface-briefs/web-app.md`. Machine-readable tokens live in
`.impeccable/design.json`.

---

## 1. World Identity

**Lynceus — AI Gate Inspector.**

An enterprise-grade, graphite-dark industrial control room where one truck
inspection is the whole stage: hairline panel seams instead of shadows, one
amber accent reserved for state, IBM Plex Sans/Mono figures, and a verdict that
assembles itself gate-by-gate like a machine startup interlock. The category
default (dashboard with KPI cards + accent) is refused.

Register keywords: industrial control-room, graphite-dark, weighbridge,
enterprise-grade, hairline seams, mono figures, honest degradation.

**Dial: ENERGY 1 / RHYTHM 2 / MOTION 1**
- ENERGY 1: Calm, authoritative, no flashy hero. The problem speaks, not the product name.
- RHYTHM 2: Consistent panel structure with deliberate breaks (unequal proof columns, gate strip interlock).
- MOTION 1: Hover states only + one scroll-reveal (count-up). No parallax, no bounce, no floating.

---

## 2. Palette

All color tokens from the `@theme` block in `web/app/globals.css`. Tailwind v4
exposes each as a utility (`bg-ground`, `text-ink`, `border-seam`, …). Default
border color for every element is `--color-seam` (set via `* { border-color }`).

### Ground — ordered graphite scale (deepest → most raised)

| Token | Value | Role |
|---|---|---|
| `--color-ground` | `#0a0c10` | Page background, deepest tier. Also the `<pre>` surface inside the audit modal. |
| `--color-panel` | `#0e1116` | Panels / cards / sticky top bar (`bg-panel`). |
| `--color-raised` | `#161b23` | Raised surface inside a panel: panel-head band, inputs, gate cells, table header rows. |
| `--color-seam` | `#1c2128` | 1px hairline borders, row separators, dividers. |
| `--color-seam-strong` | `#2a323d` | Hovered seams, control borders (inputs, default buttons), scrollbar thumb. |

### Ink — text

| Token | Value | Role |
|---|---|---|
| `--color-ink` | `#e8eaed` | Primary text. |
| `--color-muted` | `#9aa3ad` | Secondary text, labels, panel-head titles. |
| `--color-faint` | `#7d8899` | Tertiary text, source lines, placeholder verdict (`— — —`), `dot-idle`. Documented as ≥4.5:1 on panel/raised. |

### Accent — the ONE brand accent (amber)

| Token | Value | Role |
|---|---|---|
| `--color-amber` | `#f5a623` | State + signature only: focus ring, caret, active filter chip border, selected-row marker, verdict ESCALATE/REFUSED banner, top-bar glyph. |
| `--color-amber-soft` | `rgba(245, 166, 35, 0.16)` | Tint backgrounds: `::selection`, active filter chip bg, gate strip evaluating state. |
| `--color-amber-line` | `rgba(245, 166, 35, 0.45)` | Outer ring / dimmed amber border (default button hover border). |

### Verdict states — meaning-only colors

| Token | Value | Role |
|---|---|---|
| `--color-verdict-green` | `#2ecc71` | ACCEPT verdict, passed gate text, prevented-loss figure. |
| `--color-verdict-amber` | `#f5a623` | ESCALATE verdict (shares the accent). |
| `--color-verdict-red` | `#e74c3c` | REJECT verdict, failed gate, error states. |
| `--color-green-dim` | `rgba(46, 204, 113, 0.14)` | Green tint bg (verdict banner, badge, passed gate cell). |
| `--color-amber-dim` | `rgba(245, 166, 35, 0.14)` | Amber tint bg (verdict banner, badge, REFUSED explainer, demo amber button hover). |
| `--color-red-dim` | `rgba(231, 76, 60, 0.14)` | Red tint bg (verdict banner, badge, failed gate cell, error panel). |

### Status dots

| Token | Value | Role |
|---|---|---|
| `--color-dot-ok` | `#2ecc71` | Service up / gate passed dot. |
| `--color-dot-warn` | `#f5a623` | Probe pending / stub dot. |
| `--color-dot-down` | `#e74c3c` | Service down dot. |
| `--color-dot-idle` | `#7d8899` | Un-lit gate light (strip before resolve). |

Verdict-tinted borders use inline rgba values in components, e.g. badge borders
`border-[rgba(46,204,113,0.45)]` / `border-[rgba(245,166,35,0.45)]` /
`border-[rgba(231,76,60,0.45)]`, status-chip outline `border-[rgba(231,76,60,0.4)]` /
`border-[rgba(46,204,113,0.4)]`.

---

## 3. Typography

Loaded via `next/font/google` in `web/app/layout.tsx`:

- **IBM Plex Sans** — UI typeface. Weights `400, 500, 600, 700`, variable
  `--font-plex-sans`, `display: "swap"`. Maps to `font-sans` (body default).
- **IBM Plex Mono** — data/figures. Weights `400, 500, 600`, variable
  `--font-plex-mono`. Maps to `font-mono`, wrapped by the `figure` utility.

Font stacks (`@theme`):
- `--font-sans: var(--font-plex-sans), "Segoe UI", system-ui, sans-serif`
- `--font-mono: var(--font-plex-mono), ui-monospace, Consolas, monospace`

Body base (globals.css `body`): `font-size: 15px`, `line-height: 1.55`,
antialiased, `font-synthesis: none`.

### Scale in use (from components)

| Usage | Spec |
|---|---|
| Hero headline (`/`) | `text-[clamp(28px,4.4vw,46px)]` `leading-[1.08]` `font-bold` `tracking-[-0.015em]` |
| Landing proof figures | `text-[clamp(34px,4.5vw,56px)]` `font-semibold` `tracking-[-0.01em]`, `.figure` (mono) |
| Impact counter | `.figure text-[26px] leading-tight` |
| Verdict banner label | `text-[20px] font-bold tracking-[4px]` (uppercase) |
| Verdict headline / landing sub | `text-[15px]` (landing hero sub `sm:text-[17px]`) |
| Section title (`h3`) | `text-[17px] font-semibold` |
| Body / table cells | `text-[13px]` – `text-[13.5px]` (table base `13.5px`) |
| Small labels, chips, captions | `text-[12px]` – `text-[12.5px]`, often `.figure` |
| Source lines / footnotes | `text-[11px]` |

Weights used: `400` (body), `500`, `600` (semibold — labels, buttons, figures),
`700` (bold — smallcaps heads, wordmark, banner label).

### Smallcaps pattern (panel heads & section eyebrows)

Two implementations, both real:

- `@utility smallcaps` (globals.css): `font-size: 12px; font-weight: 700;
  letter-spacing: 1.4px; text-transform: uppercase; color: var(--color-muted)`.
- `@utility panel-head`: the band itself — `flex` between title and meta,
  `padding: 12px 16px`, `bg-raised`, `border-bottom: 1px seam`, plus the same
  12px / 700 / 1.4px / uppercase / muted type. Meta slot reuses `.figure
  text-muted` with `letterSpacing: 0`.

Related uppercase micro-bands: table head `text-[12px] font-bold
tracking-[1.2px] uppercase text-muted`; top-bar subtitle `text-[12px]
font-semibold tracking-[1px] uppercase`.

### Mono rule

`.figure` utility: `font-family: var(--font-mono); font-variant-numeric:
tabular-nums`. Mono is used **only for data/measurement**: gate labels, impact
figures, record IDs, truck IDs, timestamps, source lines, photo captions, audit
JSON. Prose stays Plex Sans.

---

## 4. Material & Depth

- **Hairline seams, no shadows.** Depth is communicated exclusively by the
  graphite scale (ground → panel → raised) and 1px `seam` / `seam-strong`
  borders. There is no `box-shadow` on any card or panel.
- **One-step elevation.** A panel sits on `bg-panel`; the only thing raised
  above it is `bg-raised` (head band, inputs, gate cells). Nothing floats
  higher than that single step.
- **Radius.** `--radius-card: 14px` (default card/panel), `--radius-card-lg:
  16px` (photo hero), `--radius-control: 6px` (buttons, inputs — crisp
  machine feel). Component-level exceptions: verdict banner and gate strip use
  `rounded-[10px]`; badges, chips, dots use `rounded-full`; scrollbar thumb
  `999px`. The `@theme` comment states the intent: "Cards 12–16px; controls 6px
  for a crisper machine feel."
- **No-shadow exceptions (state, not elevation):** the only `shadow-*` in the
  codebase are functional glows on live status dots
  (`shadow-[0_0_6px_rgba(46,204,113,0.6)]`) and the selected ledger row's amber
  inset marker `shadow-[inset_3px_0_0_0_var(--color-amber)]` — a seam-thin
  3px inset bar, not card depth.

---

## 5. Components

All class patterns below are copied from the actual source.

### Panel / PanelHead — `web/components/ui/panel.tsx` + `@utility panel`
```
<section class="panel">            → bg-panel, 1px solid seam, radius-card(14px), overflow-hidden
  <div class="panel-head">         → flex between, px-4 py-3(12px 16px), bg-raised,
                                    border-b seam, 12px/700/1.4px uppercase muted
    <span>Title</span>
    <span class="figure text-muted" style="letter-spacing:0">record: 000123</span>
  </div>
  …body…
</section>
```

### Button — `web/components/ui/button.tsx` (cva)
Base: `inline-flex items-center justify-center gap-2 rounded-[6px] px-4 py-2
text-[13px] font-semibold tracking-[0.2px] transition-colors duration-100
cursor-pointer select-none disabled:pointer-events-none disabled:opacity-50
active:translate-y-px`

| Variant | Classes |
|---|---|
| `default` | `bg-raised border border-seam-strong text-ink hover:bg-seam hover:border-amber-line` |
| `primary` | `bg-amber border border-amber text-ground hover:bg-[#ffb53a] hover:border-[#ffb53a]` |
| `ghost` | `bg-transparent border border-transparent text-muted hover:text-ink hover:bg-seam` |

Sizes: `default` `px-4 py-2`; `sm` `px-3 py-1.5 text-xs`; `lg` `px-6 py-2.5 text-sm`.
Rule from source: "Other agents compose these variants; do not invent new ad-hoc buttons."

Demo-case buttons (intake form) are `default` buttons with verdict-tinted
overrides: e.g. red = `border-verdict-red/70 text-verdict-red hover:bg-red-dim`.

### Badge (verdict variants) — `web/components/ui/badge.tsx` (cva)
Base: `inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1
text-[12px] font-bold tracking-[0.4px] whitespace-nowrap uppercase`

| Variant | Classes |
|---|---|
| `default` | `border-seam-strong bg-raised text-muted` |
| `accept` | `border-[rgba(46,204,113,0.45)] bg-green-dim text-verdict-green` |
| `escalate` | `border-[rgba(245,166,35,0.45)] bg-amber-dim text-verdict-amber` |
| `reject` | `border-[rgba(231,76,60,0.45)] bg-red-dim text-verdict-red` |
| `refuse` | `border-seam-strong bg-raised text-muted` |

Ledger rows render a verdict dot inside the badge: `<span class="h-1.5 w-1.5
rounded-full bg-current" aria-hidden="true" />`.

### Gate strip (signature) — `web/components/workspace/gate-strip.tsx`
Strip: `flex items-stretch gap-0 overflow-hidden rounded-[10px] border
border-seam`, `role="group" aria-label="Interlock gate strip"`.
Each gate cell:
```
class="flex flex-1 flex-col items-center gap-1.5 border-r border-seam bg-raised
       px-2.5 py-3 last:border-r-0 transition-colors duration-150"
  evaluating → "animate-[gate-pulse_1.1s_ease-in-out_infinite]" + "bg-amber-soft"
  lit failed  → "bg-red-dim"    lit passed → "bg-green-dim"
  dot:  h-3 w-3 rounded-full transition-all duration-150
        unlit → bg-dot-idle; passed → bg-dot-ok; failed → bg-dot-down
  label: figure text-[12px] font-semibold tracking-[0.8px]
  state: text-[12px] font-semibold tracking-wide   ("—" until lit)
  <span class="sr-only">gate VLM: pending/passed/…</span>
```
Status line under the strip: `.figure text-[12px] tracking-[0.5px]` —
"Evaluating interlock…" (`text-amber`) → "Interlock resolved — verdict issued."
(`text-muted`), in an `aria-live="polite"` container.

### Status chip (top bar, single-dot) — `web/components/shell/status-chip.tsx`
```
<span role="status" aria-live="polite" aria-atomic="true"
  class="inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border
         bg-raised px-3 py-1.5 text-[12px] font-bold tracking-[0.8px] uppercase
         {tone}">
  <span class="h-2 w-2 shrink-0 rounded-full {engineDot}"/> ENGINE ONLINE
</span>
```
Tone: `text-verdict-red border-[rgba(231,76,60,0.4)]` when down;
`text-verdict-green border-[rgba(46,204,113,0.4)]` when ok; `text-muted` while
checking. Honest degradation — never a fake green (labels: ENGINE ONLINE /
ENGINE DOWN / BACKEND DOWN).

### Table ledger — `web/components/ui/table.tsx` + `ledger-view.tsx`
- `Table`: wrapper `w-full overflow-x-auto`, table `w-full caption-bottom
  text-[13.5px]`.
- `TableRow`: `border-b border-seam transition-colors duration-100
  hover:bg-raised` — hairline separators, no zebra, no shadow.
- `TableHead`: `bg-raised px-4 py-2.5 text-left align-middle text-[12px]
  font-bold tracking-[1.2px] whitespace-nowrap text-muted uppercase`
  (small-caps header band on the raised surface).
- `TableCell`: `px-4 py-2.5 align-middle`; IDs/timestamps add `.figure
  text-[12.5px]`.
- Selected row: `bg-raised shadow-[inset_3px_0_0_0_var(--color-amber)]` with
  `role="button" tabIndex={0}` keyboard activation.
- Summary hairline above filters: `border-b border-seam px-4 py-2.5
  text-[13px] text-muted`, figures in `.figure` with verdict coloring.
- Sort buttons: `cursor-pointer uppercase transition-colors duration-100
  hover:text-ink`, active indicator chip `rounded-[4px] px-1 py-0.5
  text-[12px] text-amber`.

### Filter chips — `ledger-view.tsx`
```
<button class="cursor-pointer rounded-full border px-3 py-1 text-[12.5px]
        font-semibold transition-colors duration-100"
  active   → "border-amber bg-amber-soft text-ink"
  inactive → "border-seam text-muted hover:border-seam-strong hover:text-ink">
  {label}<span class="figure ml-1.5 text-[12px] text-muted">{count}</span>
</button>
```
Group wrapper: `role="group" aria-label="Filter inspections by verdict"`, each
button `aria-pressed`.

### Modal (audit) — `web/components/workspace/audit-modal.tsx`
Hand-rolled accessible dialog: overlay `fixed inset-0 z-[100] flex
items-center justify-center bg-[rgba(10,12,16,0.78)] p-4 backdrop-blur-sm`;
dialog `panel flex max-h-[82vh] w-full max-w-[820px] flex-col focus:outline-none`
with `role="dialog" aria-modal="true"`, focus moves in on open, Escape closes,
focus returns to trigger, backdrop click closes. Header is a `panel-head`
("Audit record · 000123" + ghost ✕ Close). Body: `<pre class="figure m-0
flex-1 overflow-auto bg-ground px-4 py-3 text-[13px] leading-relaxed
text-muted">{JSON …}</pre>` — raw JSON on the deepest tier, mono.

### Input — `@utility input` (globals.css)
`width:100%; background: var(--color-raised); border:1px solid
var(--color-seam-strong); border-radius: var(--radius-control);
padding: 8px 10px; color: var(--color-ink); font-size: 13.5px;` with amber
focus from `:focus-visible`.

### Top bar — `web/components/shell/top-bar.tsx`
`sticky top-0 z-50 flex flex-wrap items-center gap-x-5 gap-y-2 border-b
border-seam bg-panel px-6 py-3 backdrop-blur` — sticky with a hairline seam,
no shadow. Wordmark: `text-[22px] font-bold tracking-[3px] text-ink` with
amber `◉` glyph; nav links `rounded-[6px] px-3 py-2 text-[13px] font-semibold
tracking-[0.6px] uppercase text-muted hover:bg-seam hover:text-ink`.

### Verdict banner — `verdict-panel.tsx`
`flex items-center justify-between gap-3 rounded-[10px] border px-4 py-3
transition-opacity duration-200` inside `role="status" aria-live="polite"`.
Lit styles by tone (from `VERDICT_STYLE`): accept `bg-green-dim
border-verdict-green text-verdict-green`; escalate/refuse `bg-amber-dim
border-amber text-amber`; reject `bg-red-dim border-verdict-red
text-verdict-red`; unknown `bg-raised border-seam-strong text-muted`. Unlit:
`border-seam bg-raised text-faint opacity-70` showing `— — —`. Label span:
`text-[20px] font-bold tracking-[4px]`; record id: `.figure text-[11px]
tracking-[0.5px] text-muted`.

---

## 6. Signature Move

Two motion moments, both driven by the verdict arriving (not by scroll, except
the landing figure):

### a) The interlock gate strip
Five gates (VLM confidence, OCR, manifest crosscheck, gas plausibility, weight
plausibility — labels VLM / OCR / XCHECK / GAS / WEIGHT) render as a horizontal
strip of industrial indicator lights. On `phase === "evaluating"` the strip
breathes amber: each cell gets `bg-amber-soft` +
`animate-[gate-pulse_1.1s_ease-in-out_infinite]` with
`animationDelay: i * 120ms` (`gate-pulse` keyframes: 0%/100% opacity 0.55 → 50%
opacity 1). When the verdict resolves, cells snap to their state color one by
one — `setTimeout(litCount = i+1, i * staggerMs)` with `staggerMs = 120`
(`--stagger: 120ms` in `@theme`, the `staggerMs` prop defaults to it) —
green-dim/green dot + label for passed, red-dim/red dot for failed, graphite for
not_run. **The verdict banner may only light after all five gates resolve**: the
strip fires `onAllResolved` at `gates.length * staggerMs`, and only then does
the parent flip `bannerLit`, transitioning the banner from the graphite
`— — —` state to the verdict tone (`transition-opacity duration-200`).

### b) The impact counter count-up
The prevented-loss figure ("Rp 798.000.000", `Intl.NumberFormat("id-ID")`)
counts up over **1400ms** with **easeOutExpo** (`1 - 2^-10t`) via
`requestAnimationFrame` (`web/lib/use-count-up.ts`), triggered by `bannerLit` +
`impactRunKey`. Landing proof figures use the same easeOutExpo count-up
(`CountUpFigure`) fired by `IntersectionObserver` at threshold 0.4. Honesty
contract: the end value is always the real backend/sourced figure — the
animation only delays the reveal, never changes it.

### Reduced-motion fallback
- `useCountUp` / `CountUpFigure` check
  `window.matchMedia("(prefers-reduced-motion: reduce)")` and **snap to the
  final value immediately** (no animation).
- globals.css hard-stops all CSS animation/transition:
  `@media (prefers-reduced-motion: reduce) { *, *::before, *::after {
  animation-duration: 0.01ms !important; animation-iteration-count: 1
  !important; transition-duration: 0.01ms !important; } }`

Other motion tokens: `--ease-smooth: cubic-bezier(0.2, 0.6, 0.2, 1)`;
interactive transitions are short (`transition-colors duration-100`–`150`,
banner `duration-200`); loader spinner `h-6 w-6 animate-spin rounded-full
border-2 border-seam border-t-amber`.

---

## 7. Browser Surfaces

From `web/app/globals.css` (all themed, none browser-default):

| Surface | Treatment |
|---|---|
| `::selection` | `background: var(--color-amber-soft); color: var(--color-ink);` — highlighted text reads as "flagged". |
| Scrollbar (webkit) | width/height `10px`; track `bg-ground`; thumb `bg-seam-strong`, `border-radius: 999px`, `2px solid var(--color-ground)` inset; thumb hover `bg-muted`. |
| Scrollbar (Firefox) | `scrollbar-width: thin; scrollbar-color: var(--color-seam-strong) var(--color-ground);` |
| `:focus-visible` | `outline: 2px solid var(--color-amber); outline-offset: 2px; border-radius: var(--radius-control);` — amber ring, keyboard only. |
| Caret | `input, textarea, [contenteditable] { caret-color: var(--color-amber); }` |
| Base border | `* { border-color: var(--color-seam); }` — every default border is a hairline. |
| `html` | `-webkit-text-size-adjust: 100%; scroll-behavior: smooth;` |
| Theme color | `#0a0c10` (`viewport.themeColor` in `layout.tsx`, `colorScheme: "dark"`). |

---

## 8. Do & Don't (craft floor)

**Do**
- Use the graphite scale for depth: ground → panel → raised, hairline 1px seams.
- Use `.figure` (IBM Plex Mono, tabular-nums) for every measurement, ID,
  timestamp, money figure, and source line.
- Use smallcaps (12px / 700 / tracking 1.4px / uppercase / muted) for panel
  heads and section eyebrows.
- Keep amber as the single brand accent, reserved for state + signature
  (focus, selection, active filter, selected row, gate pulse, primary CTA).
- Give verdict colors meaning only: they appear exclusively on verdict banners,
  badges, gate states, status dots, and error panels.
- Give destructive/reject actions deliberate isolation with empty space
  (direction contract).
- Use inline SVG or plain glyphs for icons; every number carries its source.
- Compose Button/Badge variants; keep modals focus-protected.

**Don't**
- No gradient text.
- No glass (the audit overlay's `backdrop-blur-sm` scrim and the top bar's
  `backdrop-blur` are surface scrims — never glass cards/frosted panels).
- No `border-left` accent bars thicker than the 3px inset seam marker used on
  the selected ledger row (`shadow-[inset_3px_0_0_0_var(--color-amber)]` is the
  ceiling; do not grow it).
- No shadows on cards/panels — depth comes from the graphite scale and seams
  only (dot glow on live status is a state signal, not elevation).
- No hero-metric / KPI-card grid template — landing proof figures are an
  unequal-column composition split by hairline seams, not a card grid.
- No emoji icons — use SVG glyphs (or documented text glyphs like ◉ / ✕ / ≡).
- No mono for prose — Plex Mono is for data/measurement only.
- No invented buttons/badges outside the cva variants; no fake green status.

---

## 9. Surfaces

Two shells: the landing group (`web/app/(landing)/layout.tsx`) keeps the sticky
`TopBar` (wordmark ◉ LYNCEUS · AI GATE INSPECTOR, one nav link, single-dot
StatusChip); the console group (`web/app/(console)/layout.tsx`) replaces it
with the `SideNavbar` (brand ◉ → `/`, items **Inspection** `/app` and **Audit
Trail** `/inspections` — one noun per route, enforced everywhere) plus a
status-only TopBar (no wordmark/nav, StatusChip right-aligned).

### `/` — landing (Persuade) — `web/app/page.tsx`
Problem-first, no kicker/eyebrow, no hero-metric grid:
1. **Hero** (`lg:grid-cols-[1.15fr_0.85fr]`): headline "One hidden metal chunk
   can stop a cement kiln." (`max-w-[16ch]`), one paragraph, CTAs **Open
   Inspection Console** (`primary lg`) → `/app` and **View Audit Trail**
   (`default lg`) → `/inspections`; right: proof photo `figure.panel` with
   labeled mono captions (real REJECT-case waste photo, RealWaste CC BY 4.0
   credit).
2. **Proof strip** — "What one missed truck costs" (`smallcaps` head):
   three unequal columns (`lg:w-[1.25fr]` etc.) split by `lg:border-l
   border-seam`, each a `CountUpFigure` + label + source line under a
   `border-t border-seam` hairline. Figures: Rp 350 jt shredder, US$ 28k/hr
   kiln (sourced to docs/research-realcase-indonesia.md).
3. **How it works** — "How a truck is cleared, gate by gate": three steps,
   mono step numerals in `text-faint`, each with a gate chip (`.figure …
   rounded-[6px] border border-seam bg-raised px-3 py-1.5` + green dot).
4. **Provenance footer** — honest note "Demo numbers
   are sourced estimates, not validated measurements".

### `/app` — inspection workspace (Operate) — `app/app/page.tsx` → `WorkspaceClient`
Grid `grid-cols-1 gap-5 lg:grid-cols-[5fr_7fr]` (5/7 split, single column below
lg):
- **LEFT — "Incoming Load"** (`Panel` + `PanelHead title="Incoming load"
  meta="weighbridge gate A"`): photo hero (`border-b border-seam px-4 py-4`,
  rounded 16px, mono caption), three demo-case buttons
  (Green/Amber/Red, verdict-tinted borders), intake form
  (truck_id, waybill textarea, weight, stream select, moisture, age) using the
  `.input` token, Inspect Load button (`primary`). First viewport is never
  empty: the green case's photo + values preload.
- **RIGHT — "Inspection Verdict"** (`VerdictPanel` + `PanelHead
  meta="record: …"`; idle meta `"gate A · live"` — the meta slot carries
  gate context or a record id, never a URL path): verdict banner (lights only
  after gates), directive headline (17px), GateStrip (five-gate interlock),
  ImpactCounter (count-up Rp figure + ≈ US$ line, **below** the gates and
  hidden while idle — the money must not outrank the evidence), reasons
  (amber-dot list), caveats, impact note + provenance, REFUSED explainer when
  applicable, inline red error panel with recovery, "View audit record" →
  AuditModal, and a **Clear for next truck →** reset (gate flow is
  truck-by-truck). Idle guidance: the headline reads "Pick a demo case on the
  left, then press Inspect Load." — one directive line, no duplicated
  placeholder.

### `/inspections` — audit ledger (Read/Operate) — `app/inspections/page.tsx` → `LedgerView`
- `Panel` + `PanelHead title="Audit trail" meta="immutable ledger"`.
- State views: loading (amber-top spinner), empty (≡ glyph + link to the
  Inspection console), error (red ✕ + Retry button).
- **Summary hairline**: total / rejected / prevented figures in mono with
  verdict colors.
- **Filter chips**: ALL / ACCEPT / ESCALATE / REJECT / REFUSED with live
  counts; active chip amber.
- **Ledger table** (desktop): sortable Record/When columns, verdict Badge with
  dot, prevented-loss right-aligned mono (green when > 0), row click/Enter
  opens detail, selected row gets raised bg + 3px amber inset seam.
- **Stacked cards** (mobile, `md:hidden`).
- **Inline detail** — `InspectionDetailPanel` (not a modal) with the full
  immutable audit record.

---

## 10. Machine-Readable Tokens

`.impeccable/design.json` mirrors the `@theme` block of
`web/app/globals.css` (colors, fonts, radii, spacing scale, motion) for
tooling/agents. Tokens there and here must stay in sync with the CSS source of
truth.
