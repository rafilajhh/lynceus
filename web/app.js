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
    truck_id: "B-9174-KT",
    manifest_text:
      "DUTY OF CARE — WASTE TRANSFER NOTE\n" +
      "Producer: Eco RDF Processing Plant 2\n" +
      "Waste type: SRF / RDF fluff, pre-sorted, baled\n" +
      "Origin: MRF Bintara sorting line\n" +
      "Declared weight: 18,400 kg\n" +
      "Moisture declared: 10% (dry, stored under cover)\n" +
      "Collected: 2026-10-13 01:20 UTC",
    weight_kg: 18500,
    stream: "rdf-feedstock",
    moisture_pct: 9.5,
    age_h: 5
  },
  amber: {
    truck_id: "DK-4418-WR",
    manifest_text:
      "DUTY OF CARE — WASTE TRANSFER NOTE\n" +
      "Producer: TPA Suwung transfer station\n" +
      "Waste type: organic-rich source-separated biowaste\n" +
      "Origin: kerbside organics collection, district 4\n" +
      "Declared weight: 11,200 kg\n" +
      "Moisture declared: 30%\n" +
      "Collected: 2026-10-10 08:00 UTC",
    weight_kg: 11450,
    stream: "organic-rich",
    moisture_pct: 57.0,
    age_h: 76
  },
  red: {
    truck_id: "F-7702-TS",
    manifest_text:
      "DUTY OF CARE — WASTE TRANSFER NOTE\n" +
      "Producer: Metro Scrap Trading CV\n" +
      "Waste type: clean RDF fluff, dry, no contamination\n" +
      "Origin: industrial park skip hire\n" +
      "Declared weight: 15,500 kg\n" +
      "Moisture declared: 12%\n" +
      "NOTE (driver): drum of scrap metal and concrete rubble " +
      "loaded on top of the bales at the last minute.\n" +
      "Collected: 2026-10-13 00:45 UTC",
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

photoInput.addEventListener("change", () => {
  photoFile = photoInput.files && photoInput.files[0] ? photoInput.files[0] : null;
  if (photoFile) {
    const reader = new FileReader();
    reader.onload = (e) => {
      photoPreviewImg.src = e.target.result;
      photoPreview.hidden = false;
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
  photoPreview.hidden = true;
  photoPreviewImg.removeAttribute("src");
});

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

  // Headline
  const headline =
    ((data.engine_outputs && data.engine_outputs.recommendation) || {}).headline ||
    data.headline ||
    "Inspection completed.";
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
    photo_filename: photoFile ? photoFile.name : null,
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
