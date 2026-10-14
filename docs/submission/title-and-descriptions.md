# Submission text (lablab.ai form)

Limits from the lablab submission guide: title max 50 characters, short
description max 255 characters, long description min 100 words. The counts
below were measured on the text exactly as written here.

Every figure comes from `backend/benchmark/results/` (2026-10-13 live run and
its replay under the current rules), `backend/src/lynceus/impact.py`
(`value_model`) or `docs/BUSINESS.md`. Re-check them if the benchmark is re-run.

## Title (46 characters)

Lynceus: AI Gate Inspector for RDF Fuel Trucks

## Short description (250 characters)

Lynceus inspects each refuse-derived-fuel truck at the weighbridge before it tips. An open vision model on AMD Token Factory reads the load photo; a rule engine decides accept, escalate or reject, cites the gate SOP and seals a tamper-evident record.

## Long description (307 words)

Cement plants burn refuse-derived fuel (RDF) to replace coal, but every truck of
shredded waste can hide metal, rock, concrete or tyres. One piece that reaches the
shredder or the kiln can destroy a machine and stop the line. Magnets catch
ferrous metal only after the load is tipped; manual checks at the gate are slow
and leave no record.

Lynceus is the gate inspector, and it decides before the load is tipped. At the
weighbridge the operator uploads a photo of the load and types the waybill. An
open vision model (MiniCPM-V-4.7) running on AMD Token Factory names what it sees
and marks where; DeepSeek-V4-Flash reads the waybill and checks it against the
weighed mass. The AI only observes: a rule-based engine compares the waybill with
what the vision model saw and decides ACCEPT, ESCALATE or REJECT, so the verdict
is explainable and repeatable. Each verdict comes with next steps that cite the
gate SOP, a cited assistant (Pythia) that answers only from plant documents, and
a SHA-256 tamper-evident audit record. The shift report shows what the gate
caught, which suppliers repeat, and the value per 1,000 trucks with and without
Lynceus.

We tested the vision gate live on AMD on 80 public waste photos: it rejected 19 of
20 metal-waste photos. Replaying the recorded model outputs through the current
rules, it passed 35 of 40 paper, cardboard, plastic and textile photos and sent
26% of the 80 to an operator, where today the gate officer checks every truck by
eye. The rules were tuned on these same photos, so the replay is not a held-out
result, and photos of single items are not truck loads; the method, the raw rows
and every assumption are in the repository.

Lynceus is built for RDF and SRF receiving gates in Indonesia and Italy, priced
as a per-gate subscription.

## Technology tags

AMD Token Factory, MiniCPM-V, DeepSeek, Vision-Language
Model, Computer Vision, FastAPI, Python, Next.js, TypeScript, BM25 retrieval,
Industrial AI, Waste-to-Energy

## Category

Track 1: Intelligent Industry
