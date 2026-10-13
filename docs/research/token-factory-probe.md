# Token Factory probe: localisation mode and assist model

Date: 2026-10-13. Endpoint: `https://developer.amd.com.cn/radeon/api/v1` (shared team key, calls spaced >= 2 s, zero 429s observed).
Script: `backend/scripts/probe_token_factory.py`. Raw replies (each truncated to 2 KB): `docs/research/token-factory-probe.json`.

## Decisions

```
VLM_MODEL         = "MiniCPM-V-4.7-35B-A3B"
LOCALISATION_MODE = "box"
ASSIST_MODEL      = "DeepSeek-V4-Flash"
```

**`backend/.env` currently sets `VLM_MODEL=DeepSeek-V4.1-Flash`. That model cannot take images (see below); change it to `MiniCPM-V-4.7-35B-A3B`.**

## Method

- `/models` returned the 12 models listed in the task (HTTP 200).
- Localisation prompt = existing `_VLM_PROMPT` + the `locations` key (label, box 0..1 from top-left, zone). Image sent as `data:image/jpeg;base64,...` in an OpenAI `image_url` part, temperature 0.1, max_tokens 700. SSE and JSON bodies are both handled (every reply observed was `application/json`).
- 3 runs per image (`red-1.jpg`, `amber-1.jpg`, `green-1.jpg`) per vision candidate. A model that failed 3 times in a row on its first image was not run on the rest, to avoid hammering the shared key.
- Ground truth for `red-1.jpg` (524x524, a crumpled aluminium foil tray, visible metal spans about x 32..505 px, y 50..440 px): normalised box `[0.06, 0.09, 0.96, 0.84]`. "Overlaps" = a valid box (4 numbers, 0 <= x0 < x1 <= 1, 0 <= y0 < y1 <= 1) labelled `metal` with IoU > 0 against that box.
- Assist: system message lists three made-up sources as `[ID] title\ntext` (`SOP-RDF-5.3` moisture penalty, `SOP-RDF-2.1` hard contaminants, `REG-ID-07` waybill retention carrying an injected "ignore this instruction" line). Question: "What price penalty applies when moisture is 0.30?" A reply passes if it parses as `{"answer": str, "citations": [ids]}` with every citation id among the given ids (and non-empty).

## Localisation results (red-1.jpg is the decision image)

| Model | red-1 runs with valid box over metal | IoU on red-1 (3 runs) | Other behaviour | p50 latency (200s) |
|---|---|---|---|---|
| `MiniCPM-V-4.7-35B-A3B` | **3/3** | 0.953, 0.888, 0.888 | Valid JSON 9/9. amber-1 returned no boxes, green-1 returned one full-frame box `[0,0,1,1]` labelled `textile` (see concerns). Zone `center` on red-1. | **14.5 s** (12.9..19.8 s, 9 calls; 13.5 s on red-1) |
| `DeepSeek-V4-Flash-Vision-Exp` | 0/3 | n/a | Accepts images and returns valid JSON, but `contamination: "none detected"` and `locations: []` on red-1 every time, so it misses the foil. 1 of 9 calls timed out at 90 s. | 7.7 s (6.1..20.5 s, 8 calls) |
| `DeepSeek-V4.1-Flash` | 0/3 | n/a | Every image request hangs until our 90 s client timeout (earlier 150 s probe also timed out; a `max_tokens` 60 request returned HTTP 500 with a gateway 504 from the upstream). Text-only requests work (3.7 s). It does not work as a VLM on this endpoint. amber/green not run (fail-fast). | none |

Rule applied: valid box overlapping the metal in >= 2/3 red-1 runs gives "box"; MiniCPM is the only model that qualifies, so there is no tie to break.

## Assist results (Task 7 contract, 3 runs each)

| Model | Parses as contract JSON with valid citation | p50 latency | Notes |
|---|---|---|---|
| `Gemma-4-31B-IT` | **0/3** | 13.3 s | Replies are degenerate garbage (`` ```// single own//////`` and similar), even for a plain text question. Matches the teammate report. |
| `DeepSeek-V4-Flash` | **3/3** | **4.5 s** (4.1, 4.5, 63.5 s) | Reply: `{"answer": "15% price penalty", "citations": ["SOP-RDF-5.3"]}`. Cited the right source every time and ignored the injected line in `REG-ID-07`. One 63 s outlier. |

Rule applied: Gemma needs 3/3 to be chosen; it scored 0/3, so `ASSIST_MODEL = "DeepSeek-V4-Flash"`.

## Observed latency and rate limits

- HTTP 429s: 0 across about 35 calls (spacing >= 2 s). `Retry-After` handling is in the script but was never exercised.
- Vision calls are slow and spiky: MiniCPM p50 14.5 s, Vision-Exp p50 7.7 s but with a 20 s and a >90 s call. Assist p50 4.5 s with one 63 s outlier. Product code should use a client timeout of at least 60 s and fail open to the existing stub / zone path.

## Concerns and recommendations for Task 4 / Task 7

1. **Do not trust a lone full-frame box.** On green-1, MiniCPM labelled the whole image as `textile` (`[0,0,1,1]`) while also saying "none detected". Task 4 should drop boxes with area > ~0.9 of the frame and only show boxes whose label matches a listed hard or light contaminant. A `zone`-only fallback should remain for empty or invalid `locations`.
2. **The model's own `zone` was `center` for the foil**, which is coarse; the box is the useful signal here. Keep the zone as a text fallback.
3. `locations` was empty for amber-1 in all 3 runs, and green-1 produced the full-frame false positive: the box path was only validated positively on one image (red-1, a single metal object). More hard-contaminant photos (red-2, red-3) should be spot-checked before the demo; this probe used only the three `-1` images per the brief.
4. Do not send images to `DeepSeek-V4.1-Flash`; it hangs. Qwen3.8 and Gemma were not probed for vision, as instructed.
5. Gemma outputs garbage even for text here, so avoid it for any JSON task on this endpoint until the deployment is fixed.
6. Raw JSON file holds the replies only (no key, no images).
