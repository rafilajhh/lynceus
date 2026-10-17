# Demo video: shot list and script

Target length **4:40** (lablab: MP4 or MOV, under 5 minutes, at most 300 MB;
under 3 minutes scores lower). Narration is about 600 words at a calm pace.
Every figure here matches the README, the submission text and
`docs/BUSINESS.md`.

## Before recording

- Record on **https://lynceus.web.id**, browser at 1440 × 900, zoom 100%.
- Sign in **before** recording, then go back to the landing page. Never show the
  password, an API key or a server address on screen.
- In Inspection, press **Reset** so the gate is empty.
- Cut the waiting time in editing: the waybill read takes ~10–30 s, an
  inspection ~15–35 s. Keep 1 s of the loading state, then cut to the result,
  and add a small caption "≈ 20 s on AMD Token Factory".
- Slides (scenes 3, 10, 11, 12) come from the PDF deck so video and slides match.
- Pythia (scene 6): click the suggested question **"Why was this truck
  rejected?"**. The answer comes from a live model and varies; if it declines,
  ask again and keep the take with citations.

## Sequence

| # | Time | Screen | What to do |
|---|---|---|---|
| 1 | 0:00–0:12 | Cover image | Title card: "Lynceus — AI gate inspector for RDF fuel trucks" |
| 2 | 0:12–0:40 | Landing page (hero) | Slow scroll from the headline to the cost figures |
| 3 | 0:40–1:00 | Slide: how it works | Photo + waybill → AMD Token Factory → rule engine → verdict + audit record |
| 4 | 1:00–1:30 | Inspection | Click **Use sample** on the waybill → register fills (cut the wait) → hover the OCR-marked fields |
| 5 | 1:30–2:10 | Inspection | Click **Metal** → **Inspect load** → (cut) **REJECT**: boxes on the photo, reasons, the six checks, the line *model · AMD Token Factory · latency* |
| 6 | 2:10–2:40 | Inspection, verdict | Scroll to the SOP next steps → click **Notify supplier** → ask Pythia one suggested question → show the cited answer |
| 7 | 2:40–2:55 | Inspection | **Next truck** → **Clean** → **Inspect load** → (cut) **ACCEPT** |
| 8 | 2:55–3:10 | Audit trail | Show the ledger, open the metal record, point at copy hash / **Download JSON** |
| 9 | 3:10–3:35 | Shift report | Show the "What Lynceus changes at the gate" card |
| 10 | 3:35–3:55 | Slide: technology + results | AMD Token Factory models, Gemma 4, Google Colab, 19/20 · 35/40 · ~20 s |
| 11 | 3:55–4:25 | Slide: market, pricing, competitors | Indonesia → Italy/EU, per-gate price, comparison table |
| 12 | 4:25–4:40 | Slide: roadmap + team + links | lynceus.web.id and the GitHub URL on screen |

## Script (narration)

**1 · Opening (0:00–0:12)**
> One hidden piece of metal can stop a cement kiln. This is Lynceus — an AI
> gate inspector for refuse-derived-fuel trucks.

**2 · Problem (0:12–0:40)**
> Cement plants burn refuse-derived fuel, RDF, to replace coal. But every
> truck of shredded waste can hide metal, stone or tyres. One piece that
> reaches the shredder or the kiln can destroy the machine and stop the line —
> up to 798 million rupiah per incident. Today, a gate officer checks each
> load by eye, and keeps no record.

**3 · Solution (0:40–1:00)**
> Lynceus moves that check to the weighbridge — while the truck is still on
> the scale, before the load is tipped. AI on AMD Token Factory observes; a
> rule engine decides: accept, escalate or reject. It is built for gate
> operators, shift supervisors and plant managers.

**4 · Waybill read (1:00–1:30)**
> The operator starts with the paper waybill. A vision model on AMD Token
> Factory reads it and fills the register — plate, supplier, net weight, load
> type and moisture. Every auto-filled field is marked, and the operator can
> still correct it.

**5 · Inspection (1:30–2:10)**
> Next, the photo of the load. The vision model finds the metal and draws a
> box around it, and a YOLO detector on the gate PC's CPU gives a second
> opinion. Then the rule engine — not the model — decides. This truck is
> rejected. The operator sees why: what the camera saw, which of the six gate
> checks failed, and which model answered on AMD Token Factory, and how fast.

**6 · Actions (2:10–2:40)**
> Every verdict comes with next steps that cite the gate SOP. One click sends
> the supplier a notice built from the record. And Pythia, our gate assistant,
> answers questions only from plant documents — with citations.

**7 · Clean load (2:40–2:55)**
> A clean load is not held up. The same check, the same rules — and this truck
> is accepted and can tip straight away.

**8 · Audit trail (2:55–3:10)**
> Every inspection is sealed as a tamper-evident SHA-256 audit record. The
> supervisor can filter the trail, copy the hash or download the full record —
> evidence a supplier cannot easily dispute.

**9 · Impact (3:10–3:35)**
> For the plant, the shift report shows what changes. Per 1,000 trucks, hard
> loads reaching the shredder drop from 6 to 1. Trucks checked by hand fall
> from 1,000 to about 140, and operator time drops by 69 percent.

**10 · Technology and results (3:35–3:55)**
> All live AI runs on AMD GPUs through AMD Token Factory. We also build on
> Google: Gemma 4 is our fallback vision model, and the YOLO detector was
> fine-tuned on Google Colab. Run live on AMD Token Factory, Lynceus stopped
> 19 of 20 metal loads and passed 35 of 40 clean loads, with a verdict in about
> 20 seconds.

**11 · Market and competitors (3:55–4:25)**
> We start in Indonesia — 23 integrated cement plants and 18 RDF plants — then
> Italy and the EU, with about 200 cement kilns. Lynceus is a per-gate
> subscription: 6 million rupiah or 500 euros a month, after a free 60-day
> pilot. Magnets and shredder trips act after tipping and only catch metal;
> sorting-line systems like Greyparrot and TOMRA work further down the line.
> None of them checks the load against the waybill while the truck is still on
> the scale, and keeps an audit record. Lynceus does.

**12 · Close (4:25–4:40)**
> Next: a pilot at an Indonesian RDF gate, then an Italian plant. Lynceus —
> built by Rafi Cahya Mahardika and Muhammad Muqorrobin Al Anshori. Try it at
> lynceus.web.id.

## On-screen captions (optional)

| Scene | Caption |
|---|---|
| 2 | "Up to Rp 798 M per incident" |
| 4 | "Waybill read by AI on AMD Token Factory" |
| 5 | "≈ 20 s on AMD Token Factory" |
| 9 | "Per 1,000 trucks · base case" |
| 10 | "AMD Token Factory · Gemma 4 · Google Colab" |
| 12 | "lynceus.web.id · github.com/rafilajhh/lynceus" |
