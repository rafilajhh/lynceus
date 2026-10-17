# Submission text (lablab.ai form)

Limits from the lablab submission guide: title max 50 characters, short
description max 255 characters, long description min 100 words. The counts
below were measured on the text exactly as written here.

Every figure comes from `backend/benchmark/results/` (the 2026-10-17
DeepSeek-Vision live run, complete 80/80, and its hybrid replay with the YOLO26m detector),
`backend/src/lynceus/impact.py` (`value_model`) or `docs/BUSINESS.md`.
Re-check them if the benchmark is re-run.

## Title (46 characters)

Lynceus: AI Gate Inspector for RDF Fuel Trucks

## Short description (244 characters)

Lynceus inspects each refuse-derived-fuel truck at the weighbridge before it tips. A vision model on AMD Token Factory reads the load photo; a rule engine decides accept, escalate or reject, cites the gate SOP and seals a tamper-evident record.

## Long description

Cement plants burn refuse-derived fuel (RDF) to replace coal, but every truck of
shredded waste can hide metal, rock, concrete or tyres. One piece that reaches the
shredder or the kiln can destroy a machine and stop the line. Magnets catch
ferrous metal only after the load is tipped; manual checks at the gate are slow
and leave no record.

Lynceus is the gate inspector, and it decides before the load is tipped. At the
weighbridge the operator uploads a photo of the load, registers the truck and
its weighed mass, and can attach the waybill photo as evidence. A
vision model (DeepSeek-V4-Flash-Vision-Exp) running on AMD Token Factory
names what it sees and marks where; DeepSeek-V4-Flash checks the declared
waybill text against the weighed mass; a CPU YOLO26m detector gives an independent
second opinion. The AI only observes: a rule-based engine compares the waybill
with what the vision model saw and decides ACCEPT, ESCALATE or REJECT, so the
verdict is explainable and repeatable. Each verdict comes with next steps that
cite the gate SOP, a cited assistant (Pythia) that answers only from plant
documents, and a SHA-256 tamper-evident audit record. The shift report shows what
the gate caught, which suppliers repeat, and the value per 1,000 trucks with and
without Lynceus.

We ran the vision model live on AMD on 80 public waste photos (all 80
answered) and replayed its answers with the CPU detector fused in, exactly as
the gate combines them. No metal-waste photo was let through: the vision model
rejected 8 of 20 outright and the detector held the other 12 for an operator.
Every glass and organic load was held for review, 37 of 40 paper, cardboard,
plastic and textile photos passed straight through, and 35 of the 80 trucks went
to an operator, where today the gate officer checks every truck by eye. The
rules were tuned on earlier runs of these photos, so this is not a held-out
result, and photos of single items are not truck loads; the method, the raw rows
and every assumption are in the repository.

Live demo: https://lynceus.web.id (sign in: admin / admin123).
Source: https://github.com/rafilajhh/lynceus

Lynceus is built for RDF and SRF receiving gates in Indonesia and Italy, priced
as a per-gate subscription.

## Technology tags

AMD Token Factory, AMD, DeepSeek, Gemma, Vision-Language Model, YOLO26,
ONNX Runtime, Computer Vision, FastAPI, Python, Next.js, TypeScript,
BM25 retrieval, Industrial AI, Waste-to-Energy

(Gemma-4-31B-IT on AMD Token Factory is the vision fallback model; it is in
the shipped configuration, `deploy/lynceus.env.example`.)

## Links for the form

- Demo platform: Web (Docker on a cloud VM, AI on AMD Token Factory)
- Demo URL: https://lynceus.web.id (sign in: admin / admin123)
- GitHub: https://github.com/rafilajhh/lynceus

## Category

Track 1: Intelligent Industry
