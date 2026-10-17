# Lynceus

<p align="center">
  <img src="docs/assets/lynceus-cover-light.jpg" alt="Lynceus AI gate inspector — an RDF truck on the weighbridge; the vision model boxes a metal contaminant and the gate card says REJECT" width="840">
</p>

**AI gate inspector for alternative-fuel (RDF) facilities — built for the AMD
Developer Hackathon: ACT III (Intelligent Industry track).**

Lynceus inspects a waste truck's load at the weighbridge, before it is tipped
into the plant. The load photo, the waybill, the weighed mass and the gate gas
readings are fused into one verdict — **ACCEPT / ESCALATE / REJECT** — by a
rule-based, regulation-grounded decision engine. The AI models only *observe*
(what is in the photo, what the waybill says); the engine decides, and every
inspection is sealed as a tamper-evident, SHA-256-digested audit record.

> One escaped metal chunk can wreck a shredder and stop a kiln. On 80 public
> waste photos run live on AMD Token Factory, the gate rejected 19 of 20
> metal-waste photos; replayed through the current rules, it passed 35 of 40
> paper, cardboard, plastic and textile photos straight through
> ([Validation](#validation): single-item public photos, not plant data; the
> replay is not a held-out result).

**Contents:** [The console](#the-console) ·
[AI on AMD Token Factory](#ai-on-amd-token-factory) ·
[Architecture](#architecture) · [Limits](#limits-stated-up-front) ·
[Validation](#validation) · [Quickstart](#quickstart) ·
[Configuration](#environment-variables) · [API](#api) · [Tests](#tests) ·
[Licences](#licences)

## The console

A Next.js 15 static export served by the backend. Sign-in is required when
`LYNCEUS_ADMIN_USERNAME` and a password are set; otherwise the console is open.

| Page | What the operator does there |
|---|---|
| **Inspection** (`/app`) | Upload the load photo and the waybill photo. The waybill is read by the vision model (OCR) and **auto-fills the register** (plate, supplier, net weight, stream, moisture); auto-filled fields are marked and stay editable, an unreadable field stays empty, and a failed read offers **Retry**. Inspect → verdict with the six gate checks, hazard boxes on the photo, the next-step card and Pythia. On the verdict: **Notify supplier** and **Escalate** (to a supervisor, with an optional note). |
| **Audit trail** (`/inspections`) | Ledger of sealed records with verdict tabs, a filter popover (supplier, period, failed check), search and CSV export. A record opens the full detail: verdict, evidence photo with boxes, the gate checklist, inputs, SOP next steps, the follow-up log, Pythia, and the raw record as a JSON download. |
| **Shift report** (`/shift`) | Trucks inspected and rejected, worst-case exposure, the verdict mix, the open review queue and supplier risk with repeat-offender flags. On first start it is seeded with a scripted 24-truck sample shift, labelled as such. |

**Next-step card.** After every verdict a deterministic rule table lists what to
do at the gate; each step cites a clause of the reference gate SOP.

**Pythia.** A gate assistant that answers only from the plant knowledge base
(`backend/src/lynceus/knowledge/*.md`) and the open record, with citations;
an ungrounded answer is replaced by "cannot answer".

**Follow-up actions.** Notifying the supplier or escalating never touches the
sealed record. Each action is appended to a separate, hash-chained log next to
it (`actions.jsonl`); the chain is re-verified on every read. A supplier notice
is built deterministically from the record (plate, verdict, contaminants seen,
SOP next steps, record id and digest) and is POSTed to
`SUPPLIER_NOTIFY_WEBHOOK` when set, otherwise only logged.

## AI on AMD Token Factory

The live AI runs on **AMD Token Factory** (AMD's free, shared, OpenAI-compatible
model endpoints, running on AMD GPUs), reached with one team API key. It is not
a self-hosted GPU stack: the app calls the Token Factory API and needs no GPU of
its own.

| Role | Model | Why |
|---|---|---|
| Vision: contaminants, wet/dry, hazard boxes, waybill OCR | `DeepSeek-V4-Flash-Vision-Exp` (fallback `Gemma-4-31B-IT`) | Won the 2026-10-17 truck-photo bake-off: metal detected 3/3 and the clean load kept clean 3/3, p50 18–32 s. Gemma matches detection and cleanliness but is slower (p50 28–35 s), so it ships as the fallback. See [the bake-off](#vision-model-bake-off-2026-10-17). |
| Waybill cross-check, Pythia, shift explanations | `DeepSeek-V4-Flash` | Passed the assistant citation contract 3/3 and the waybill JSON contract 3/3 on a contradictory waybill (`Gemma-4-31B-IT` failed citations 0/3; `Qwen3.8-Flash-Next` broke JSON 2/3; `GLM-5.3-Flash` timed out / 429). |
| Detector second opinion: metal, glass, organic boxes | YOLO26m fine-tuned on RealWaste + TACO, bundled ONNX (`backend/models/`) | Runs on the gate PC's CPU (ONNX Runtime), so it keeps working when the shared endpoint is down. Out of domain (TACO litter scenes) it finds 14/29 metal photos where the first model found 2/29 (`backend/models/README.md`). |

Probe and bake-off data: `docs/research/token-factory-probe.md`,
`docs/research/vlm-bakeoff-2026-10-17.json`,
`docs/research/llm-contract-2026-10-17.json`.

## Architecture

```
load photo + waybill + weight + gas   (inputs frozen + SHA-256 digested)
        │
        ▼
VLM  (DeepSeek-V4-Flash-Vision-Exp)  ──► contaminants, wet/dry, confidence, hazard boxes
LLM  (DeepSeek-V4-Flash)             ──► waybill fields, claim-vs-observation cross-check
YOLO26m detector (ONNX, CPU)         ──► metal / glass / organic boxes (can only hold a truck)
gas  (digital twin, or a sensor gateway when LYNCEUS_GAS_SENSOR_URL is set)
        │
        ▼
Fusion + rule-based decision engine  (cited: Eq. HH-1 40 CFR 98, EN 15359-style route scores)
        │
        ▼
Verdict ACCEPT / ESCALATE / REJECT + gates + audit record (atomic, tamper-evident)
        │
        ├──► Next-step card    (deterministic rule table, each step cites a gate-SOP clause)
        ├──► Pythia            (BM25 over the plant knowledge base + the current record)
        ├──► Follow-up log     (append-only, hash-chained: supplier notice, escalation)
        └──► Shift report      (aggregation over stored records; supplier flags)

Waybill OCR (before the inspection): waybill photo ──► VLM ──► register fields
```

How the gate stays safe when a model is wrong or down:

- **Detector second opinion.** A metal box the vision model did not confirm
  holds the truck for a human (escalate); so does an unconfirmed glass/organic
  box while `DETECTOR_ESCALATE_LIGHT=1`. The detector never accepts or rejects
  on its own. Its dashed boxes, model, runtime and latency are shown; the audit
  record also stores the weights' SHA-256 and the thresholds used.
- **Votes and fallback.** The vision model votes over `VLM_VOTES` reads
  (default 3, in parallel) and can fall back to other models
  (`VLM_FALLBACK_MODELS`) inside one time budget; a fallback outside
  `VLM_BENCHMARKED_MODELS` can never accept or reject.
- **Strict boxes.** The VLM's hazard boxes are validated; malformed boxes are
  dropped, never repaired.
- **Honest provenance.** Live results are labelled "Live AMD" with model and
  latency. A stub answer after a live failure is labelled as a scripted
  fallback. With `LYNCEUS_ALLOW_STUB_FALLBACK=0` and the vision model down, a
  readable photo gets a detector-only verdict that always holds the truck for a
  human (`detector_only_degraded`); without the detector it returns HTTP 503.
- **OCR never guesses.** An unreadable waybill field is returned as `null`; if
  the reader is down, `POST /waybill/extract` returns 503 and the operator types
  the register by hand. Large photos are re-encoded (long side ≤ 2000 px) before
  the call so a slow endpoint still answers in time.

### Limits stated up front

- The waybill photo is OCR'd only to **pre-fill the register**. The verdict
  uses what is in the register when the operator presses Inspect (they can
  correct any field); `POST /inspect` archives the waybill photo as evidence
  but does not read it again.
- Gas readings come from a physics digital twin unless `LYNCEUS_GAS_SENSOR_URL`
  points at a sensor gateway; the record says which (`digital_twin` or
  `sentinel_gate_sensor`).
- The sample load and waybill photos in `web/public/demo/` are generated images
  made for this project, not photos from a plant.

## Validation

**Component validation on public RealWaste images — not field data from a plant.**

80 RealWaste images (Metal 20, plus 60 from seven other classes at fixed quotas;
see `backend/benchmark/images/ATTRIBUTION.md`), each posted live to
`POST /inspect` on Token Factory with a fixed neutral waybill, one run on
2026-10-13 with the vision model of that day, `MiniCPM-V-4.7-35B-A3B`. The
expected verdict per image is in `backend/benchmark/manifest.csv`.

| Metric | Live run (rules of 2026-10-13) | Current rules (replay) |
|---|---|---|
| Metal gate (REJECT) recall | 0.95 (19/20) | 0.95 (19/20) |
| Metal gate (REJECT) precision | 0.86 (19/22) | 0.90 (19/21) |
| Clean RDF loads passed (ACCEPT) | 0.30 (12/40) | 0.88 (35/40) |
| Trucks sent to an operator (ESCALATE) | 0.55 (44/80) | 0.26 (21/80) |
| Escalate-expected loads escalated (ESCALATE recall) | 0.90 (18/20) | 0.85 (17/20) |
| n | 80, one run | same 80 recorded outputs |
| Completed-request latency (end to end) | p50 19.5 s, p95 34.4 s | no new model calls |
| Requests that needed a retry | 3 of 83 attempts | — |

The **replay** feeds the recorded live model outputs of the same run through
the current decision rules, without new model calls, so it scores every rule
change made after the run, not one. Two changes landed since:

1. Hard contaminants are read only from the model's structured fields, not its
   prose. The live run rejected one plastic load (`plastic_277.jpg`) because the
   word "concrete" appeared in the description; this change alone moves metal
   precision from 0.86 to 0.90.
2. Plastic film and textile, which the live run escalated as "light
   contaminants", are the calorific fraction RDF is made from and are now
   treated as feedstock. This moves clean loads passed from 0.30 to 0.88. The
   cost is one escalate-expected load (`glass_121.jpg`, whose only flag was
   plastic film) now passing: ESCALATE recall falls from 0.90 to 0.85.

Both changes were motivated by this same data, so the replay is not a held-out
measurement. It measures the vision gate on one dataset in one run and says
nothing about a particular plant's trucks, lighting or waste mix.

Files: raw rows `backend/benchmark/results/2026-10-13.jsonl`, summary
`2026-10-13.summary.json`, replay `2026-10-13.rescore.{jsonl,summary.json}`;
the newest summary and replay are served at `GET /benchmark/latest`. From
`backend/`, re-run live with
`PYTHONPATH=src python -m benchmark.run --min-interval 4` (needs the images,
which are not in the Docker image, and a live key), or re-score offline with
`PYTHONPATH=src python -m benchmark.rescore --source benchmark/results/2026-10-13.jsonl`.

### Vision-model bake-off (2026-10-17)

The shipped vision model was re-picked on 2026-10-17 with a 10-model bake-off
on the truck-bed sample photos (production prompt, 3 runs per photo):
`DeepSeek-V4-Flash-Vision-Exp` and `Gemma-4-31B-IT` both detected the metal 3/3
and stayed clean 3/3; DeepSeek wins the latency tie-break (p50 18–32 s vs
28–35 s) and ships as the primary, Gemma as the fallback.
`MiniCPM-V-4.7-35B-A3B`, the 2026-10-13 pick, is not reliable here: one read
times out on the metal photo, its JSON parses on only 1 of 3 clean-load reads
and 1 of 3 ambiguous reads, and its latency reaches 84 s. The rest failed in
different ways: timeouts (`DeepSeek-V4.1-Flash`, `GLM-5.3-Flash`), unparseable
or empty JSON (`Qwen3.8-Flash-Next`, `MiMo-V2.6-Flash`), HTTP errors
(`MiniCPM5-2B`), not vision-capable (`DeepSeek-V4-Flash`), or hallucinated hard
contaminants on the clean load (`MiniCPM-V-4.7-1B`).

The same 80-image RealWaste benchmark was then run live with the new model
(`2026-10-17.deepseek-vision-exp.jsonl`; 8 timeout rows, 72/80 graded). On these
close-up single-item photos it is clearly weaker: metal recall 0.40 (8/20),
gate accuracy 0.625 VLM-only. What matters for the gate is the hybrid: replayed
with the YOLO26m second opinion
(`2026-10-17.deepseek-vision-exp.hybrid-rescore.summary.json`), **no metal is
accepted — the 8 confirmed rejects stand and the 10 metal misses become 10
operator holds** (2 metal images errored out; gate accuracy 0.75, clean accept
rate 0.85, review rate 0.42). The MiniCPM hybrid replay on the same rules also
accepts no metal, at higher accuracy (0.90), but MiniCPM cannot read the truck
photos reliably. The truck photo is the demo; RealWaste close-ups are the
benchmark. Both results are kept and stated.

Bake-off limits: the probe runs the production prompt at temperature 0.0
(production votes at 0.1) with 512-token reads, and it recorded box counts only.
The counts varied across runs (e.g. 6/4/4 on the metal photo for the winner),
so spatial box consistency was not validated. The pick rests on detection
correctness, cleanliness and latency, plus the live `/inspect` run and the
committed benchmark artifacts.

### Value per 1,000 trucks

`GET /shift-report` returns a `value_model` that turns these rates into an
expected value with and without Lynceus (escaped hard loads, damage, operator
time, the cost of wrongly rejected clean loads). Every parameter is either
sourced or marked as an adjustable assumption, with a low/base/high range; the
low case is negative and is reported as such. Model: `value_model` in
`backend/src/lynceus/impact.py`.

## Business case and operator validation

- Users, buyers, market (Indonesia and Italy), competitors and pricing:
  [`docs/BUSINESS.md`](docs/BUSINESS.md).
- A 15-minute interview kit to check the problem, its cost and willingness to
  pay with an RDF gate operator or co-processing manager:
  [`docs/operator-validation-kit.md`](docs/operator-validation-kit.md).

## Repository layout

```
backend/                FastAPI app: AI pipeline, decision, audit records
  src/lynceus/            service package (api, pipeline, decision, actions, followup,
                          assist, shift, audit, impact, detector, auth)
  src/lynceus/knowledge/  plant knowledge base used by Pythia (markdown, package data)
  src/lynceus_engine/     the vendored decision engine (pure Python, MIT)
  models/                 bundled YOLO26m ONNX detector + NOTICE
  benchmark/              validation benchmark: manifest, runner, committed results
  scripts/                seed_demo.py (sample-shift seeding), probe_token_factory.py
  tests/                  backend tests + opt-in live smoke module
web/                    operator console — Next.js 15 (App Router) static export
ml/                     detector training, evaluation and ONNX export
deploy/                 container entrypoint, env template, deployment guide
docs/                   business case, research notes, hackathon checklist, assets
Dockerfile              single-container image (API + built UI)
```

## Quickstart

### Local development

Requirements: Python 3.12+, Node.js 20+.

```bash
# 1. Build the web UI (static export -> web/out/)
cd web && npm ci && npm run build && cd ..

# 2. Run the backend (serves the API and the built UI)
cd backend
pip install -e ".[dev]"
cp ../.env.example .env        # then paste the Token Factory key; see below
python -m lynceus.main         # http://localhost:8020
```

If `npm run build` fails with `Cannot find module '../lightningcss.<platform>.node'`,
npm skipped an optional native package during `npm ci` (seen once on Windows;
the lockfile does list it). Delete `web/node_modules` and run `npm ci` again.

Open <http://localhost:8020>. Inspections and waybill OCR need the Token Factory
key. Without it the live call fails: by default
(`LYNCEUS_ALLOW_STUB_FALLBACK=1`) an inspection answers with an offline
scripted stub labelled `stub_fallback_live_error` and the UI says so; with
`LYNCEUS_ALLOW_STUB_FALLBACK=0` it returns HTTP 503. Waybill OCR never uses a
stub. The 24-truck sample shift is seeded offline and needs no key.

### Docker

```bash
docker build -t lynceus .
cp deploy/lynceus.env.example deploy/lynceus.env   # git-ignored; paste the key, set a password
docker run -d --name lynceus -p 8020:8020 \
  --env-file deploy/lynceus.env \
  -v lynceus-runs:/data/runs \
  lynceus
```

Use the Docker template, not `.env.example`: the template carries the console
login (set `LYNCEUS_ADMIN_PASSWORD` to turn sign-in on) and
`LYNCEUS_ALLOW_STUB_FALLBACK=0` (fail closed), and it never
sets `LYNCEUS_STORAGE_DIR`, `LYNCEUS_WEB_DIR` or `LYNCEUS_BENCHMARK_DIR`, so the
container's `/data/runs` volume path stays in force (the entrypoint exits with
an error if the storage dir is not writable).

On first start (empty storage) the container seeds the 24-truck sample shift,
then serves on `${PORT:-8020}`. Records persist in the `lynceus-runs` volume.
The API key is read from `--env-file` at run time and is never copied into the
image. Full server guide (HTTPS, updates, backups, judging-day checklist):
[`deploy/README.md`](deploy/README.md).

### Environment variables

Token Factory settings (local: `backend/.env`; Docker: `deploy/lynceus.env`;
never commit the key; get the team key at `notebooks.amd.com/tokenfactory`):

```bash
VLLM_VLM_URL=https://developer.amd.com.cn/radeon/api/v1
VLLM_LLM_URL=https://developer.amd.com.cn/radeon/api/v1
VLLM_API_KEY=rc-your-team-key
VLM_MODEL=DeepSeek-V4-Flash-Vision-Exp
VLM_FALLBACK_MODELS=Gemma-4-31B-IT
LLM_MODEL=DeepSeek-V4-Flash
LYNCEUS_ALLOW_STUB_FALLBACK=0
```

An inspection submitted without a `demo_case` carries `provenance: "live"`. The
key is rate-limited and shared across the team; the client honours
`Retry-After` on HTTP 429.

Full reference (defaults are the code defaults, used when a variable is unset):

| Variable | Default | Meaning |
|---|---|---|
| `VLLM_VLM_URL` | `http://localhost:8000/v1` | OpenAI-compatible endpoint for the vision model (also used for waybill OCR) |
| `VLLM_LLM_URL` | `http://localhost:8001/v1` | OpenAI-compatible endpoint for the text model |
| `VLLM_API_KEY` | *(empty)* | Bearer key sent to the endpoints (the Token Factory team key); no auth header when empty |
| `VLM_MODEL` | `Qwen/Qwen2.5-VL-7B-Instruct` | Vision-language model id |
| `LLM_MODEL` | `Qwen/Qwen2.5-7B-Instruct` | Text model id |
| `VLM_FALLBACK_MODELS` | *(empty)* | Comma-separated vision fallback chain, tried in order inside one time budget |
| `VLM_BENCHMARKED_MODELS` | `MiniCPM-V-4.7-35B-A3B` | Fallback models allowed to accept or reject (those with an 80-image benchmark run behind them); the primary VLM is exempt, any other fallback can only escalate |
| `VLM_VOTES` | `3` | Vision reads per photo, merged by majority vote (1..3, run in parallel) |
| `ASSIST_URL` / `ASSIST_MODEL` | `VLLM_LLM_URL` / `LLM_MODEL` | Endpoint and model for Pythia |
| `EXPLAIN_URL` / `EXPLAIN_MODEL` | `ASSIST_URL` / `ASSIST_MODEL` | Endpoint and model for shift-report supplier explanations |
| `LOCALISATION_MODE` | `box` | Hazard localisation: `box` or `zone` |
| `LYNCEUS_ALLOW_STUB_FALLBACK` | `1` | `0` / `false` / `no`: a live-AI failure returns HTTP 503 instead of the offline stub (use for hosted demos) |
| `LYNCEUS_ADMIN_USERNAME` | *(empty)* | Console login user; login is on only when this and a password are set |
| `LYNCEUS_ADMIN_PASSWORD` / `LYNCEUS_ADMIN_PASSWORD_SHA256` | *(empty)* | Login password, or its hex SHA-256 (takes precedence, so the raw password need not be stored) |
| `SUPPLIER_NOTIFY_WEBHOOK` | *(empty)* | https URL that receives a POSTed supplier notice (5 s timeout); empty, non-https or a failed POST = the notice is only logged in the follow-up log |
| `LYNCEUS_GAS_SENSOR_URL` | *(empty)* | HTTP/JSON gate gas-sensor gateway; empty = physics digital twin |
| `DETECTOR_MODEL_PATH` | bundled `backend/models/lynceus-yolo26m-realwaste-taco.onnx` | Detector weights; empty = detector off |
| `DETECTOR_HARD_CONF` / `DETECTOR_LIGHT_CONF` | `0.35` / `0.05` | Detector thresholds for metal / glass+organic, picked on a val split (`backend/models/README.md`) |
| `DETECTOR_ESCALATE_LIGHT` | `1` | An unconfirmed glass/organic box holds the truck too |
| `DETECTOR_THREADS` / `DETECTOR_PROVIDERS` | `2` / `CPUExecutionProvider` | ONNX Runtime threads and execution providers |
| `LYNCEUS_STORAGE_DIR` | `./runs` (`/data/runs` in the image) | Where audit records and follow-up logs live |
| `LYNCEUS_WEB_DIR` | `<repo>/web/out` (`/app/web/out` in the image) | Static web export to serve |
| `LYNCEUS_BENCHMARK_DIR` | `<repo>/backend/benchmark` (`/app/backend/benchmark` in the image) | Benchmark manifest and results for `/benchmark/latest` |
| `PORT` | `8020` | Listening port of `python -m lynceus.main` |

## API

All routes except `/health`, the login routes and the static pages require a
session when login is on (401 JSON otherwise).

| Route | Purpose |
|---|---|
| `GET /health` | Liveness, version, engine availability |
| `POST /auth/login` · `POST /auth/logout` · `GET /auth/session` | Console session |
| `POST /inspect` | Full gate inspection: VLM + LLM + detector + engine → sealed verdict |
| `POST /waybill/extract` | Read a waybill photo into register fields (503 `ocr_unavailable` when the reader is down) |
| `POST /assist` | Pythia: cited answers over the plant documents and a record |
| `GET /inspections` | Ledger rows (verdict, reason, digest, follow-up counts) |
| `GET /inspections/{id}` | One audit record, digest re-verified on read |
| `GET /inspections/{id}/evidence/{slot}` | The archived load or waybill photo |
| `GET` · `POST /inspections/{id}/actions` | Follow-up log: list (with `chain_ok`) or append `notify_supplier` / `escalate` |
| `GET /shift-report` | Shift aggregation, supplier risk and explanations, `value_model` |
| `GET /benchmark/latest` · `GET /benchmark/replay` · `GET /benchmark/manifest.csv` | Committed validation results |
| `POST /assess` | One batch assessment through the decision engine alone |

`POST /inspect` also accepts a scripted `demo_case` for the seeder and tests;
the console does not offer it.

## Tests

```bash
cd backend
PYTHONPATH=src python -m pytest tests/ -q   # 603 passed, 1 skipped
```

The skipped test is the live smoke module; enable it with `LYNCEUS_LIVE_TESTS=1`
(needs a live endpoint and key). The web console type-checks and builds with
`npx tsc --noEmit` and `npm run build` in `web/`.

## Licences

- Lynceus code: MIT (see `LICENSE`).
- **RealWaste images** (the benchmark images in `backend/benchmark/images/`)
  are from the RealWaste dataset (Single, Iranmanesh, Raad, University of
  Wollongong; UCI ML Repository id 908) and remain under their own licence. The
  licence statements disagree: the UCI page says **CC BY 4.0**, the README
  inside the dataset zip says **CC BY-NC-SA 4.0**. Until the authors clarify,
  treat the more restrictive terms as binding (attribution, non-commercial,
  share-alike). Details: `backend/benchmark/images/ATTRIBUTION.md`. The
  benchmark images are excluded from the Docker image.
- **Third-party model weights.** The bundled CPU detector
  (`backend/models/lynceus-yolo26m-realwaste-taco.onnx`) is **not** covered by
  the MIT licence. The weights derive from Ultralytics YOLO26 (**AGPL-3.0**) and
  were fine-tuned on RealWaste (**CC BY-NC-SA 4.0** treated as binding, as
  above) and TACO (annotations **CC BY 4.0**). Their training and export source
  is in `ml/` (our offer of the corresponding source). Commercial use requires
  retraining on your own data and an Ultralytics Enterprise licence, or a
  permissively licensed detector (`DETECTOR_MODEL_PATH` points at it; empty
  turns the detector off). Details: `backend/models/NOTICE`.
