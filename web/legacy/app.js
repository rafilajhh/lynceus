/* ============================================================
   Lynceus — AI Gate Inspector · app.js
   Vanilla JS, no dependencies. Talks to the FastAPI backend:
     POST {BASE_URL}/assess        (engine assessment)
     POST {BASE_URL}/inspect       (full AI inspection — later)
   BASE_URL is derived from window.location; when index.html is
   served by FastAPI, calls go to the same origin.
   ============================================================ */
"use strict";

// Backend base URL: same origin as the page. When opened via
// file:// this will be "null"-ish, so fetch fails cleanly and we
// show an inline error (see handleFetchError).
const BASE_URL = window.location.origin.startsWith("http")
  ? window.location.origin
  : "";

// ------------------------------------------------------------
// Demo cases (hardcoded, English)
// ------------------------------------------------------------
const DEMO_CASES = {
  green: {
    // Arm-roll truck on the Bantargebang RDF corridor. B = DKI/Jakarta
    // plate area (Bantargebang); offtakers are the cement co-processing
    // lines (SBI Narogong is one of the three RDF plants: Narogong,
    // Cilacap, Tuban). Numbers: arm roll 14 m³ × 372.71 kg/m³ ≈ 5.2 t/trip
    // (ITATS Surabaya, TPA Benowo weighbridge); RDF gate price
    // Rp 300,000/t (SWITCH-Asia §5d). Plate 'B' = DKI per TNKB codes.
    truck_id: "B 9174 KT",
    photo: "demo/green-1.jpg",
    photo_caption: "Arm-roll B 9174 KT · RDF feedstock, dry & baled — Bantargebang to SBI Narogong line",
    manifest_text:
      "WAYBILL / WEIGHBRIDGE TICKET (RDF-MSW) — No. SJ: SJ/RDF/2026/10/0001\n" +
      "Plate No.  : B 9174 KT        Date: 2026-10-13   Entry time: 01:20\n" +
      "Driver     : Sukarno          Origin: TPST Bantargebang RDF plant (waste source: TPS district 4)\n" +
      "Destination: SBI Narogong cement plant (RDF co-processing line)\n" +
      "Gross (kg) : 10,000           Tare (kg): 4,800\n" +
      "Netto (kg) : 5,200            Weighbridge operator: Gate A\n" +
      "Load type  : RDF fluff, pre-sorted, baled\n" +
      "Declared weight: 5,200 kg\n" +
      "Moisture declared: 10% (dry, stored under cover)\n" +
      "Checks     : non-hazardous, non-medical, moisture/calorific value (RDF)",
    weight_kg: 5200,
    stream: "rdf-feedstock",
    moisture_pct: 9.5,
    age_h: 5
  },
  amber: {
    // Wet organics rejected at RDF intake: Indonesian MSW runs 55-60%
    // moisture (SBI Cilacap study) and ~40.77% food waste nationally
    // (SIPSN 2025) — exactly why MBT pre-processing is mandatory before
    // kiln feeding. Plate "B" = Bantargebang/Jakarta corridor.
    truck_id: "B 9282 AP",
    photo: "demo/amber-1.jpg",
    photo_caption: "Compactor B 9282 AP · wet organics from TPST — 57% moisture measured",
    manifest_text:
      "WAYBILL / WEIGHBRIDGE TICKET (RDF-MSW) — No. SJ: SJ/RDF/2026/10/0002\n" +
      "Plate No.  : B 9282 AP        Date: 2026-10-13   Entry time: 04:05\n" +
      "Driver     : Rustam           Origin: TPST Bantargebang (waste source: TPS district 4)\n" +
      "Destination: RDF processing plant -> cement plant co-processing\n" +
      "Gross (kg) : 12,250           Tare (kg): 4,850\n" +
      "Netto (kg) : 7,400            Weighbridge operator: Gate A\n" +
      "Load type  : organic-rich, source-separated biowaste\n" +
      "Declared weight: 7,400 kg\n" +
      "Moisture declared: 30%\n" +
      "Checks     : non-hazardous, non-medical, moisture/calorific value (RDF)",
    weight_kg: 7400,
    stream: "organic-rich",
    moisture_pct: 57.0,
    age_h: 76
  },
  red: {
    // Scrap metal smuggled in under a 'clean RDF' claim with a weight
    // mismatch — the kiln-killer scenario: metal in the feed damages the
    // kiln/refractory; unplanned downtime ≈ Rp 450 million/hour
    // (oxmaint US benchmark @ Rp 16,000/USD, §5a). Metal is also 3.11% of
    // national MSW composition (SIPSN 2025) — the exact fraction screening
    // must catch at the gate. Plate "F" = Bogor (SBI Narogong corridor).
    truck_id: "F 7702 TS",
    photo: "demo/red-1.jpg",
    photo_caption: "Compactor F 7702 TS · scrap metal found under the bales — weight mismatch",
    manifest_text:
      "WAYBILL / WEIGHBRIDGE TICKET (RDF-MSW) — No. SJ: SJ/RDF/2026/10/0003\n" +
      "Plate No.  : F 7702 TS        Date: 2026-10-13   Entry time: 00:45\n" +
      "Driver     : Hendra           Origin: RDF supplier CV, Bogor (waste source: industrial park skip)\n" +
      "Destination: cement plant co-processing line\n" +
      "Gross (kg) : 24,800           Tare (kg): 9,300\n" +
      "Netto (kg) : 15,500           Weighbridge operator: Gate A\n" +
      "Load type  : clean RDF fluff, dry, no contamination\n" +
      "Declared weight: 15,500 kg\n" +
      "Moisture declared: 12%\n" +
      "NOTE (driver): drum of scrap metal and concrete rubble loaded on " +
      "top of the bales at the last minute.\n" +
      "Checks     : non-hazardous, non-medical, moisture/calorific value (RDF)",
    weight_kg: 19300, // weighbridge far above declared 15,500 kg
    stream: "mixed-msw",
    moisture_pct: 14.0,
    age_h: 8
  }
};

// ------------------------------------------------------------
// DOM helpers
// ------------------------------------------------------------
const $ = (id) => document.getElementById(id);

const form = $("inspect-form");
const formError = $("form-error");
const resultError = $("result-error");
const resultPlaceholder = $("result-placeholder");
const resultTicket = $("result-ticket");
const inspectBtn = $("inspect-btn");

function showFormError(msg) {
  formError.textContent = msg;
  formError.hidden = false;
}

function clearFormError() {
  formError.textContent = "";
  formError.hidden = true;
}

function showResultError(msg) {
  resultError.textContent = msg;
  resultError.hidden = false;
}

function clearResultError() {
  resultError.textContent = "";
  resultError.hidden = true;
}

// Demo-photo state: the current demo case's photo (path + fetched base64)
// lives outside photoFile, which stays reserved for user uploads.
let demoCase = null;
let demoPhotoPath = null;
let demoPhotoBase64 = null;
let demoPhotoCaption = "";

// ------------------------------------------------------------
// Demo case loading
// ------------------------------------------------------------
function loadDemo(caseKey) {
  const c = DEMO_CASES[caseKey];
  if (!c) return;
  clearFormError();
  clearResultError();
  $("truck_id").value = c.truck_id;
  $("manifest_text").value = c.manifest_text;
  $("weight_kg").value = c.weight_kg;
  $("stream").value = c.stream;
  $("moisture_pct").value = c.moisture_pct;
  $("age_h").value = c.age_h;
  demoCase = caseKey;
  demoPhotoBase64 = null;
  demoPhotoPath = c.photo || null;
  demoPhotoCaption = c.photo_caption || "";
  showDemoPhoto();
}

// Show the current demo photo in both previews (form + hero panel) and
// fetch its bytes as base64 so submit can send real image data.
function showDemoPhoto() {
  const heroPanel = $("load-photo-panel");
  if (!demoPhotoPath) {
    heroPanel.hidden = true;
    photoPreview.hidden = true;
    photoPreviewImg.removeAttribute("src");
    return;
  }
  photoPreviewImg.src = demoPhotoPath;
  photoPreview.hidden = false;
  $("load-photo-img").src = demoPhotoPath;
  $("load-photo-caption").textContent = demoPhotoCaption;
  heroPanel.hidden = false;
  const pathUsed = demoPhotoPath;
  fetch(pathUsed)
    .then((r) => {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.blob();
    })
    .then(blobToBase64)
    .then((b64) => {
      // Keep base64 in sync with the preview: if the user switched to
      // another demo case while this fetch was in flight, drop stale bytes.
      if (demoPhotoPath === pathUsed) demoPhotoBase64 = b64;
    })
    .catch(() => {
      // file:// or offline: the <img> preview still renders, but the
      // payload falls back to the filename-only stub path.
      if (demoPhotoPath === pathUsed) demoPhotoBase64 = null;
    });
}

// Blob → raw base64 (no data: URI prefix).
function blobToBase64(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",")[1] || "");
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(blob);
  });
}

$("demo-green").addEventListener("click", () => loadDemo("green"));
$("demo-amber").addEventListener("click", () => loadDemo("amber"));
$("demo-red").addEventListener("click", () => loadDemo("red"));

// ------------------------------------------------------------
// Photo preview
// ------------------------------------------------------------
const photoInput = $("photo");
const photoPreview = $("photo-preview");
const photoPreviewImg = $("photo-preview-img");
let photoFile = null;
let photoUploadBase64 = null;  // raw base64 of the user's uploaded file

photoInput.addEventListener("change", () => {
  photoFile = photoInput.files && photoInput.files[0] ? photoInput.files[0] : null;
  photoUploadBase64 = null;
  if (photoFile) {
    // A user upload takes precedence over the demo photo: drop the demo
    // state so the payload sends the uploaded bytes.
    demoPhotoBase64 = null;
    demoPhotoPath = null;
    const reader = new FileReader();
    reader.onload = (e) => {
      const dataUri = String(e.target.result);
      photoUploadBase64 = dataUri.split(",")[1] || "";
      photoPreviewImg.src = dataUri;
      photoPreview.hidden = false;
      $("load-photo-img").src = dataUri;
      $("load-photo-caption").textContent = photoFile ? photoFile.name : "";
      $("load-photo-panel").hidden = false;
    };
    reader.readAsDataURL(photoFile);
  } else {
    photoPreview.hidden = true;
    photoPreviewImg.removeAttribute("src");
  }
});

$("photo-clear").addEventListener("click", () => {
  photoInput.value = "";
  photoFile = null;
  photoUploadBase64 = null;
  demoPhotoBase64 = null;
  demoPhotoPath = null;
  photoPreview.hidden = true;
  photoPreviewImg.removeAttribute("src");
  $("load-photo-panel").hidden = true;
});

// Base64 of the user's uploaded photo, or null when no upload is active.
function photoBase64FromUpload() {
  return photoFile && photoUploadBase64 ? photoUploadBase64 : null;
}

// ------------------------------------------------------------
// Result rendering
// ------------------------------------------------------------

// Map backend decision strings (accept | reject | refuse_insufficient_input |
// escalate_human, per audit schema) to UI verdict classes/labels.
function verdictFromDecision(decision) {
  const d = String(decision || "").toLowerCase();
  if (d.startsWith("accept")) return { label: "ACCEPT", cls: "verdict-accept" };
  if (d.startsWith("reject")) return { label: "REJECT", cls: "verdict-reject" };
  if (d.startsWith("escalate")) return { label: "ESCALATE", cls: "verdict-escalate" };
  if (d.startsWith("refuse")) return { label: "REFUSED", cls: "verdict-escalate" };
  return { label: String(decision || "UNKNOWN").toUpperCase(), cls: "verdict-unknown" };
}

function firstNumber(...vals) {
  for (const v of vals) {
    if (typeof v === "number" && isFinite(v)) return v;
  }
  return null;
}

function gateClass(state) {
  const s = String(state || "").toLowerCase();
  if (s === "passed") return "gate-passed";
  if (s === "failed") return "gate-failed";
  if (s === "warning") return "gate-warning";
  return "";
}

function collectReasoning(data) {
  const reasons = [];
  const ai = data.ai_outputs || {};
  if (ai.llm && typeof ai.llm.reasoning === "string" && ai.llm.reasoning) {
    reasons.push(ai.llm.reasoning);
  }
  const rec = (data.engine_outputs && data.engine_outputs.recommendation) || {};
  if (Array.isArray(rec.reasons)) reasons.push(...rec.reasons);
  if (Array.isArray(data.reasoning)) reasons.push(...data.reasoning);
  if (Array.isArray(data.reasons)) reasons.push(...data.reasons);
  return reasons;
}

function collectCaveats(data) {
  const rec = (data.engine_outputs && data.engine_outputs.recommendation) || {};
  const out = Array.isArray(rec.caveats) ? rec.caveats.slice() : [];
  if (Array.isArray(data.caveats)) out.push(...data.caveats);
  if (data.verdict && typeof data.verdict.uncertainty === "string") {
    out.push(data.verdict.uncertainty);
  }
  return out;
}

function renderResult(data) {
  clearResultError();
  resultPlaceholder.hidden = true;
  resultTicket.hidden = false;

  // Verdict banner
  const decision =
    (data.verdict && data.verdict.decision) ||
    data.decision ||
    data.action ||
    "";
  const v = verdictFromDecision(decision);
  const banner = $("verdict-banner");
  banner.className = "verdict-banner " + v.cls;
  $("verdict-label").textContent = v.label;
  $("verdict-record-id").textContent = data.record_id
    ? "audit record: " + data.record_id
    : "";

  // Headline: the engine's routing headline is only appropriate when the
  // fusion verdict agrees; on reject/escalate/refuse it would contradict
  // the banner (e.g. "Recommended for RDF processing" under a REJECT).
  const engineHeadline =
    ((data.engine_outputs && data.engine_outputs.recommendation) || {}).headline;
  const headline =
    decision === "reject" || String(decision).startsWith("reject")
      ? "Load rejected — do not admit to RDF processing."
      : decision === "escalate_human" || String(decision).startsWith("escalate")
        ? "Human review required before unloading."
        : String(decision).startsWith("refuse")
          ? "Insufficient input — inspection cannot proceed."
          : engineHeadline || data.headline || "Inspection completed.";
  $("headline").textContent = headline;

  // Confidence (0..1 or 0..100 — both accepted)
  let conf = firstNumber(
    data.confidence,
    data.verdict && data.verdict.confidence,
    (data.engine_outputs && data.engine_outputs.recommendation || {}).confidence,
    (data.ai_outputs && data.ai_outputs.vlm || {}).confidence
  );
  if (conf !== null) {
    if (conf > 1) conf = conf / 100; // treat as percent
    conf = Math.max(0, Math.min(1, conf));
    $("confidence-fill").style.width = Math.round(conf * 100) + "%";
    $("confidence-text").textContent = Math.round(conf * 100) + "% confidence";
  } else {
    $("confidence-fill").style.width = "0%";
    $("confidence-text").textContent = "confidence: not reported";
  }

  // Reasoning list
  const reasons = collectReasoning(data);
  const reasoningEl = $("reasoning");
  reasoningEl.innerHTML = "";
  if (reasons.length === 0) {
    const li = document.createElement("li");
    li.textContent = "No reasoning returned by the backend.";
    li.className = "muted";
    reasoningEl.appendChild(li);
  } else {
    for (const r of reasons) {
      const li = document.createElement("li");
      li.textContent = String(r);
      reasoningEl.appendChild(li);
    }
  }

  // Caveats
  const caveats = collectCaveats(data);
  const caveatsEl = $("caveats");
  caveatsEl.innerHTML = "";
  $("no-caveats").hidden = caveats.length > 0;
  for (const c of caveats) {
    const li = document.createElement("li");
    li.textContent = String(c);
    caveatsEl.appendChild(li);
  }

  // Gates chips
  const gatesEl = $("gates");
  gatesEl.innerHTML = "";
  const gates = data.gates || {};
  const gateKeys = Object.keys(gates);
  if (gateKeys.length === 0) {
    const chip = document.createElement("span");
    chip.className = "gate-chip";
    chip.textContent = "no gate data reported";
    gatesEl.appendChild(chip);
  } else {
    for (const key of gateKeys) {
      const g = gates[key];
      const state = typeof g === "object" ? g.state : g;
      const chip = document.createElement("span");
      chip.className = "gate-chip " + gateClass(state);
      chip.textContent = key + ": ";
      const st = document.createElement("span");
      st.className = "gate-state";
      st.textContent = String(state || "not_evaluated");
      chip.appendChild(st);
      gatesEl.appendChild(chip);
    }
  }

  // Audit record JSON (collapsible)
  $("audit-json").textContent = JSON.stringify(data, null, 2);
}

function renderAwaiting() {
  resultTicket.hidden = true;
  resultPlaceholder.hidden = false;
}

// ------------------------------------------------------------
// Fetch / backend calls
// ------------------------------------------------------------
function handleFetchError(err) {
  const openedFile = !window.location.origin.startsWith("http");
  const msg =
    "Cannot reach the Lynceus backend. " +
    (openedFile
      ? "This page was opened directly as a file — serve it via the FastAPI backend (it serves web/ as static files), then retry. "
      : "Is the backend running at " + (BASE_URL || "this origin") + "? ") +
    "Start the FastAPI server, then press Inspect Load again. " +
    "(" + (err && err.message ? err.message : err) + ")";
  renderAwaiting();
  showResultError(msg);
}

async function postJSON(url, payload) {
  let resp;
  try {
    resp = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
  } catch (err) {
    // network-level failure (backend down / file:// page)
    throw err;
  }
  if (!resp.ok) {
    let detail = "";
    try {
      const body = await resp.json();
      detail = body.detail || body.message || JSON.stringify(body);
    } catch (_) {
      detail = await resp.text().catch(() => "");
    }
    throw new Error("Backend returned HTTP " + resp.status + " " + resp.statusText +
      (detail ? " — " + detail : ""));
  }
  return resp.json();
}

// ------------------------------------------------------------
// Form submission
// ------------------------------------------------------------
form.addEventListener("submit", async (e) => {
  e.preventDefault();
  clearFormError();
  clearResultError();

  // client-side validation
  if (!$("truck_id").value.trim()) {
    showFormError("Truck ID is required.");
    return;
  }
  const weight = parseFloat($("weight_kg").value);
  if (!isFinite(weight) || weight <= 0) {
    showFormError("Weight must be a positive number (kg).");
    return;
  }
  const moisture = parseFloat($("moisture_pct").value);
  if (!isFinite(moisture) || moisture < 0 || moisture > 100) {
    showFormError("Moisture must be between 0 and 100 (%).");
    return;
  }
  const age = parseFloat($("age_h").value);
  if (!isFinite(age) || age < 0) {
    showFormError("Age must be zero or more hours.");
    return;
  }

  const payload = {
    truck_id: $("truck_id").value.trim(),
    // photo_base64: demo-case photo bytes (fetched from demo/*.jpg) or the
    // user's upload; photo_filename covers the offline/file:// fallback.
    photo_base64: demoPhotoBase64 || photoBase64FromUpload(),
    photo_filename: photoFile ? photoFile.name : demoPhotoPath,
    demo_case: demoCase,
    manifest_text: $("manifest_text").value.trim() || null,
    weight_kg: weight,
    stream: $("stream").value,
    moisture_pct: moisture,
    age_h: age
  };

  inspectBtn.disabled = true;
  inspectBtn.textContent = "Inspecting…";

  try {
    // POST /assess — engine assessment (available now).
    // POST /inspect — full AI pipeline (backend endpoint, later);
    // falls back to /assess if /inspect is not implemented yet.
    let data;
    try {
      data = await postJSON(BASE_URL + "/inspect", payload);
    } catch (err) {
      if (err && /HTTP 404/.test(err.message)) {
        data = await postJSON(BASE_URL + "/assess", payload);
      } else {
        throw err;
      }
    }
    renderResult(data);
  } catch (err) {
    handleFetchError(err);
  } finally {
    inspectBtn.disabled = false;
    inspectBtn.textContent = "Inspect Load";
  }
});
