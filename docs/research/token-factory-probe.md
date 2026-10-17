# Token Factory probe: localisation mode and assist model

> **Superseded for the vision model (2026-10-17).** This probe picked
> `MiniCPM-V-4.7-35B-A3B` on RealWaste close-ups. A later bake-off on the truck-bed
> demo photos (`vlm-bakeoff-2026-10-17.json`) moved the primary vision model to
> `DeepSeek-V4-Flash-Vision-Exp`, with `Gemma-4-31B-IT` (which answered badly in
> this earlier probe) as the fallback; see the README's Validation section. The
> localisation-mode and assist-model decisions below still stand.

Date: 2026-10-13. Endpoint: `https://developer.amd.com.cn/radeon/api/v1` (shared team key, calls spaced >= 2 s, zero 429s observed).
Script: `backend/scripts/probe_token_factory.py`. Raw replies (each truncated to 2 KB): `docs/research/token-factory-probe.json`.

## Decisions

```
VLM_MODEL         = "MiniCPM-V-4.7-35B-A3B"
LOCALISATION_MODE = "box"
ASSIST_MODEL      = "DeepSeek-V4-Flash"
```

**At probe time `backend/.env` set `VLM_MODEL=DeepSeek-V4.1-Flash`; it now uses `MiniCPM-V-4.7-35B-A3B` (see Decisions). In the recorded probe its image requests timed out at the 90 s per-read timeout in 3/3 runs (slow vs. unsupported was not distinguished; see below), so it is not usable as the VLM.**

## Method

- `/models` returned the 12 models listed in the task (HTTP 200).
- Localisation prompt = existing `_VLM_PROMPT` + the `locations` key (label, box 0..1 from top-left, zone). Image sent as `data:image/jpeg;base64,...` in an OpenAI `image_url` part, temperature 0.1, max_tokens 700. The script has both an SSE path and a JSON path, but every recorded reply was `application/json`, so the SSE path was untested in this probe.
- 3 runs per image (`red-1.jpg`, `amber-1.jpg`, `green-1.jpg`) per vision candidate. A model that failed 3 times in a row on its first image was not run on the rest, to avoid hammering the shared key.
- Ground truth for `red-1.jpg` (524x524, a crumpled aluminium foil tray, visible metal spans about x 32..505 px, y 50..440 px): normalised box `[0.06, 0.09, 0.96, 0.84]`. "Overlaps" = a valid box (4 numbers, 0 <= x0 < x1 <= 1, 0 <= y0 < y1 <= 1) labelled `metal` with IoU > 0 against that box.
- Assist: system message lists three made-up sources as `[ID] title\ntext` (`SOP-RDF-5.3` moisture penalty, `SOP-RDF-2.1` hard contaminants, `REG-ID-07` waybill retention carrying an injected "ignore this instruction" line). Question: "What price penalty applies when moisture is 0.30?" A reply passes if it parses as `{"answer": str, "citations": [ids]}` with every citation id among the given ids (and non-empty).

## Localisation results (red-1.jpg is the decision image)

| Model | red-1 runs with valid box over metal | IoU on red-1 (3 runs) | Other behaviour | p50 latency (200s) |
|---|---|---|---|---|
| `MiniCPM-V-4.7-35B-A3B` | **3/3** | 0.953, 0.888, 0.888 | Valid JSON 9/9. amber-1 returned no boxes, green-1 returned one full-frame box `[0,0,1,1]` labelled `textile` (see concerns). Zone `center` on red-1. The decision rests on the IoU values (all >= 0.888), not merely on IoU > 0. | **14.5 s** (12.9..19.8 s, 9 calls; 13.5 s on red-1) |
| `DeepSeek-V4-Flash-Vision-Exp` | 0/3 | n/a | Accepts images and returns valid JSON, but `contamination: "none detected"` and `locations: []` on red-1 every time, so it misses the foil. 1 of 9 calls timed out at 90 s. | 7.7 s (6.1..20.5 s, 8 calls) |
| `DeepSeek-V4.1-Flash` | 0/3 | n/a | Recorded: all 3 red-1 image requests ended in `ReadTimeout` at about 91.6 s (the 90 s per-read timeout; no HTTP status). Slow vs. unsupported was not distinguished. amber/green not run (fail-fast). Unrecorded ad hoc observations (not in token-factory-probe.json): an earlier 150 s attempt also timed out, a 60-token image request returned HTTP 500 carrying an upstream 504 gateway timeout, and a text-only request succeeded in 3.7 s. | none |

Rule applied: valid box overlapping the metal in >= 2/3 red-1 runs gives "box"; MiniCPM is the only model that qualifies, so there is no tie to break.

## Assist results (Task 7 contract, 3 runs each)

| Model | Parses as contract JSON with valid citation | p50 latency | Notes |
|---|---|---|---|
| `Gemma-4-31B-IT` | **0/3** | 13.3 s | Replies in all 3 recorded runs are degenerate garbage (`` ```// single own//////`` and similar). Every recorded Gemma call included the system message with sources; a plain no-system text prompt was not recorded. A teammate separately reported Gemma noise for vision JSON (unverified here). |
| `DeepSeek-V4-Flash` | **3/3** | **4.5 s** (4.1, 4.5, 63.5 s) | Reply: `{"answer": "15% price penalty", "citations": ["SOP-RDF-5.3"]}`. Cited the right source every time and ignored the injected line in `REG-ID-07`. One 63 s outlier. |

Rule applied: Gemma needs 3/3 to be chosen; it scored 0/3, so `ASSIST_MODEL = "DeepSeek-V4-Flash"`.

## Observed latency and rate limits

- HTTP 429s: 0 across the 28 calls recorded in the JSON (1 `/models` GET + 21 localisation + 6 assist; spacing >= 2 s). A few extra unrecorded smoke/sanity calls were also made and are not counted. `Retry-After` handling is in the script but was never exercised.
- Vision calls are slow and spiky: MiniCPM p50 14.5 s, Vision-Exp p50 7.7 s but with a 20 s and a >90 s call. Assist p50 4.5 s with one 63 s outlier. Product code should use a client timeout of at least 60 s and fail open to the existing stub / zone path.

## Concerns and recommendations for Task 4 / Task 7

1. **Do not trust a lone full-frame box.** On green-1, MiniCPM labelled the whole image as `textile` (`[0,0,1,1]`) while also saying "none detected". Task 4 should drop boxes with area > ~0.9 of the frame and only show boxes whose label matches a listed hard or light contaminant. A `zone`-only fallback should remain for empty or invalid `locations`.
2. **The model's own `zone` was `center` for the foil**, which is coarse; the box is the useful signal here. Keep the zone as a text fallback.
3. `locations` was empty for amber-1 in all 3 runs, and green-1 produced the full-frame false positive: the box path was only validated positively on one image (red-1, a single metal object). More hard-contaminant photos (red-2, red-3) should be spot-checked before the demo; this probe used only the three `-1` images per the brief.
4. Do not send images to `DeepSeek-V4.1-Flash`; it hangs. Qwen3.8 and Gemma were not probed for vision, as instructed.
5. Gemma produced garbage in all 3 recorded Pythia-style (system message + question) runs, so avoid it for that task on this endpoint until the deployment is checked.
6. Raw JSON file holds the replies only (no key, no images).

## Validation benchmark: manual inspection time per truck (searched, not found)

Searched 14 Oct 2026 for a citable figure for how long a manual visual load
inspection takes per truck at waste / RDF receiving (three web searches:
"manual visual inspection ... per truck seconds minutes", "tipping floor visual
load check duration per vehicle", "load inspection takes approximately minutes
per load"). Every hit describes procedure or sampling frequency; none states a
duration per truck. What the sources do support:

- New Mexico guidance sets one random load inspection per day or 1 % of incoming
  loads, whichever is greater
  (https://www.env.nm.gov/solid-waste/wp-content/uploads/sites/17/2025/04/10_Waste-Screening-Inspection-Plan-Guidance_12.2024.doc).
- Massachusetts sets monthly minimums of 4 to 20 inspected vehicles by permitted
  tonnage (https://www.mass.gov/doc/attachment-g-compliance-plan-form-for-facility-operators/download).
- A random-load inspection means diverting the truck to a separate pad, spreading
  the load and searching it by hand
  (https://www.law.cornell.edu/regulations/illinois/Ill-Admin-Code-tit-35-SS-811.323).

No baseline is invented. `/validation` therefore reports Lynceus p50/p95 latency
only, with no "vs manual" comparison and no `manual_check_seconds` in the summary.
