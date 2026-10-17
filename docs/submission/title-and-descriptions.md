# Submission text (lablab.ai form)

Limits from the lablab submission guide: title max 50 characters, short
description max 255 characters, long description min 100 words. The counts
below were measured on the text exactly as written here.

Every figure matches the README: the live benchmark in
`backend/benchmark/results/` (2026-10-13 run and its replay; the 2026-10-17
hybrid replay with the YOLO26m detector for "no metal let through"), the median
latency of the live run, and the base case of `value_model` in
`backend/src/lynceus/impact.py` (shown on the Shift report). Re-check them if
the benchmark is re-run.

## Title (46 characters)

Lynceus: AI Gate Inspector for RDF Fuel Trucks

## Short description (235 characters)

Lynceus checks every refuse-derived-fuel truck at the weighbridge before it tips. Vision AI on AMD Token Factory spots metal in the load and reads the waybill; a rule engine decides accept, escalate or reject and seals an audit record.

## Long description (304 words)

Cement plants burn refuse-derived fuel (RDF) to replace coal, but every truck of
shredded waste can hide metal, stone or tyres. One piece that reaches the
shredder or the kiln can destroy the machine and stop the line: up to Rp 798
million per incident. Today a gate officer checks loads by eye and keeps no
record.

Lynceus moves that check to the weighbridge, before the load is tipped. The
operator photographs the load and the paper waybill. A vision model on AMD
Token Factory (DeepSeek-V4-Flash-Vision-Exp, with Gemma-4-31B-IT as the
fallback) names the contaminants and boxes them on the photo, and reads the
waybill to fill the register automatically. DeepSeek-V4-Flash cross-checks the
waybill against what the camera saw and the weighed mass, and a YOLO26m
detector on the gate PC's CPU gives an independent second opinion. A rule-based
engine then decides ACCEPT, ESCALATE or REJECT, so every verdict is
explainable and repeatable.

Each verdict comes with next steps that cite the gate SOP, one-click supplier
notice and supervisor escalation, and Pythia, an assistant that answers only
from plant documents with citations. Every inspection is sealed as a SHA-256
tamper-evident audit record, and the shift report shows supervisors what the
gate caught and which suppliers repeat.

Run live on AMD Token Factory, Lynceus stopped 19 of 20 metal loads, passes 35
of 40 clean RDF loads straight through, and returns a verdict in about 20
seconds; with the detector second opinion, no metal load is let through. Per
1,000 trucks, the base case of its value model cuts hard loads reaching the
shredder from 6 to 1, trucks checked by hand from 1,000 to about 140 and
operator time by 69 percent.

Lynceus is built for RDF and SRF receiving gates in Indonesia and Italy, sold
as a per-gate subscription. It is live at https://lynceus.web.id.

## Technology tags

AMD Token Factory, DeepSeek, Gemma, Vision-Language Model, Computer Vision,
OCR, YOLO, ONNX Runtime, FastAPI, Python, Next.js, TypeScript, BM25 retrieval,
Industrial AI, Waste-to-Energy

## Category

Track 1: Intelligent Industry
