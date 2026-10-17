# Demo video script (target 3:45, limit 5:00)

lablab limits: MP4 or MOV, under 5 minutes, under 300 MB. Record the screen at
1920×1080 with the voice-over live or dubbed. Before recording, run one throwaway
inspection so the shared endpoint is warm (a cold first call can take 40–60 s);
cut the waiting time in the edit and say so on screen ("verdict in 12–30 s live,
shortened here").

Every number below is from `backend/benchmark/results/` or `docs/BUSINESS.md`;
do not add others.

| Time | Screen | Voice-over |
|---|---|---|
| 0:00–0:20 | Deck slide **cover** | "This is Lynceus, an AI gate inspector for cement plants and RDF producers. It checks every truck of refuse-derived fuel at the weighbridge and decides before the load is tipped. All of its AI runs on AMD Token Factory." |
| 0:20–0:55 | Slides **problem**, **today** | "Cement kilns burn shredded waste instead of coal, and a single piece of metal in a truck can wreck a shredder, about 350 million rupiah, or stop a kiln, which a US benchmark puts near 28 thousand dollars an hour. Today's checks act after tipping: magnets on the conveyor, people on the floor. Nobody decides at the weighbridge." |
| 0:55–1:15 | Slide **solution** | "Lynceus does. The operator registers the truck. A vision model says what it sees and where, a language model checks the declared waybill against the weighed load, a small CPU detector gives a second opinion, and then a rule engine with cited thresholds decides: accept, escalate or reject." |
| 1:15–2:25 | **Live site**: lynceus.web.id → sign in (admin / admin123) → Inspection → press **Metal** preset → **Sample** waybill → **Inspect Load** → REJECT appears; scroll to the boxes and next steps; click the record id to open the audit record | "Here it is live. I pick a load photo, the register fills in, I attach the waybill photo as evidence and press Inspect. DeepSeek V4 Flash Vision, running on AMD Token Factory, finds the rusted pipe and marks it. The rule engine rejects the load. The operator sees why, the six gates, and three next steps, each citing the gate SOP: don't tip, send it to the sorting bay, notify the supplier with this record. The record itself is sealed with SHA-256, so a disputed refusal has evidence behind it." |
| 2:25–2:45 | Live site: **Clean** preset → Inspect → ACCEPT | "A clean load goes straight through: accepted, recommended for RDF processing." |
| 2:45–3:15 | Live site: **/validation** page (Shipped gate panel) | "We measured it. Eighty public waste photos, posted live on AMD; all eighty answered, median twelve seconds. The vision model alone missed twelve of twenty metal items on these close-ups, but the CPU detector held every one of them for a person. The shipped gate let zero of twenty metal photos through, passed 37 of 40 clean loads and held every glass and organic load. These are single-item public photos, not truck loads, and every raw row is in the repo." |
| 3:15–3:30 | Slide **amd** | "Every AI call runs on AMD Token Factory: DeepSeek V4 Flash Vision as the eye, Gemma 4 as the fallback, DeepSeek V4 Flash for the waybill and the assistant, picked by a ten-model bake-off. If the endpoint goes down, the CPU detector still holds every truck for a person." |
| 3:30–3:45 | Slides **market**, **model**, **roadmap** | "We start with Indonesia's cement plants and RDF producers, then Italy and the EU, at about six million rupiah or five hundred euros per gate per month, under one percent of the fuel it protects. Next: operator interviews and a pilot gate. Try it at lynceus.web.id. Thank you." |

Checklist before upload:

- [ ] Duration under 5:00, file under 300 MB, MP4 or MOV.
- [ ] The REJECT and ACCEPT runs are real live calls (no stub label on screen).
- [ ] The cut of waiting time is stated on screen.
- [ ] The video link is pasted into the lablab form and the README.
