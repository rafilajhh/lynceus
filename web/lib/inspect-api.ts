/**
 * Inspect API client: POST /inspect (same-origin base). The ledger client
 * (GET /inspections) lives in api.ts.
 */

import {
  detectorOutputSchema,
  llmOutputSchema,
  nextStepsSchema,
  provenanceSchema,
  vlmOutputSchema,
  type Decision,
  type DetectorOutput,
  type GateResult,
  type ImpactEstimate,
  type InspectProvenance,
  type LlmOutput,
  type NextStep,
  type VlmOutput,
} from "./api";
import { parseChecks, type Check, type Sampling, type SupplierTier } from "./ops-api";

export interface InspectPayload {
  truck_id: string;
  /** Hauler named on the waybill; the backend accepts extra fields. */
  supplier: string | null;
  photo_base64: string | null;
  photo_filename: string | null;
  /** Extra camera angles (max 2), sent as their own frames. */
  extra_photos_base64?: string[];
  extra_photo_filenames?: string[];
  demo_case: string | null;
  /** The confirmed waybill fields as text; the backend rebuilds it from
      `waybill_fields` when those are sent. */
  manifest_text: string | null;
  /** Photo of the paper waybill, archived (and digested) as evidence. */
  waybill_image_base64?: string | null;
  waybill_photo_filename?: string | null;
  /** Confirmed field values, plain (not {value, confidence}). */
  waybill_fields?: Record<string, string | number | null>;
  /** How the fields were obtained; absent when the operator typed them. */
  waybill_read?: {
    confidence: number;
    model: string;
    provenance: string;
    latency_ms: number | null;
    edited_fields: string[];
    /** Per-field read confidence, so the "Waybill read" check counts unsure fields. */
    field_confidences?: Record<string, number>;
  };
  /** Weighbridge net (what the scale says). */
  weight_kg: number;
  /** Net printed on the waybill. */
  declared_weight_kg?: number | null;
  weight_source?: "weighbridge_simulated" | "weighbridge" | "manual_entry";
  stream: string;
  /** Declared moisture; the backend defaults it from the waybill. */
  moisture_pct?: number | null;
  age_h?: number | null;
}

export interface InspectResponse {
  /** Operator checks (backend checks.py); [] on an older backend. */
  checks: Check[];
  /** One deterministic sentence that starts with the cause; null when absent. */
  why: string | null;
  /** Risk-based lab sampling for this supplier; null when not computed. */
  sampling: Sampling | null;
  /** Decision receipt: every rule in priority order; [] on an older backend. */
  receipt: ReceiptRule[];
  /** Gate sensors this verdict answered to (audit inputs.observations); [] when absent. */
  observations: Observation[];
  /** One summary per vision read (ai_outputs.vlm.votes); [] when absent. */
  votes: VisionVote[];
  record_id?: string;
  /** Backend-provenanced; null when absent or unrecognised. */
  provenance: InspectProvenance;
  /** Detector-only degraded runs: which live call failed (vision or
      waybill model); null otherwise or when unrecognised. */
  failed_stage: "vlm" | "llm" | null;
  /** SOP-cited operator steps; [] when the backend sent none. */
  actions: NextStep[];
  verdict?: {
    decision?: Decision;
    decided_at_utc?: string;
    classification?: string;
    uncertainty?: string;
  };
  decision?: Decision;
  headline?: string;
  reasons?: string[];
  impact?: ImpactEstimate;
  gates?: Record<string, GateResult | GateResult["state"]>;
  ai_outputs: {
    vlm: VlmOutput | null;
    llm: LlmOutput | null;
    /** CPU detector second opinion; null when it did not run. */
    detector: DetectorOutput | null;
  };
  engine_outputs?: {
    recommendation?: {
      headline?: string;
      reasons?: string[];
      caveats?: string[];
      confidence?: number;
    };
  };
  caveats?: string[];
  [key: string]: unknown;
}

/**
 * Why an inspection request failed, split by what the operator can do:
 * - "network": the request never reached the backend (server down, offline);
 * - "http": the backend answered with a 4xx/5xx and said why (its own
 *   `detail.message`, e.g. "photo exceeds the 8 MB limit.").
 */
export class InspectError extends Error {
  kind: "network" | "http";
  status: number | null;

  constructor(kind: "network" | "http", message: string, status: number | null) {
    super(message);
    this.name = "InspectError";
    this.kind = kind;
    this.status = status;
  }
}

/** Human message from a FastAPI error body (object detail, string, or 422 list). */
function detailMessage(body: unknown): string {
  if (!body || typeof body !== "object") return "";
  const { detail } = body as { detail?: unknown };
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    // Pydantic validation errors: [{loc: [...], msg: "..."}]
    return detail
      .map((d) => {
        if (!d || typeof d !== "object") return "";
        const { loc, msg } = d as { loc?: unknown; msg?: unknown };
        const field = Array.isArray(loc) ? loc.slice(1).join(".") : "";
        return [field, typeof msg === "string" ? msg : ""]
          .filter(Boolean)
          .join(": ");
      })
      .filter(Boolean)
      .join("; ");
  }
  if (detail && typeof detail === "object") {
    const { message, error } = detail as { message?: unknown; error?: unknown };
    if (typeof message === "string" && message) return message;
    if (typeof error === "string") return error;
  }
  return "";
}

/** POST JSON; network failures and HTTP errors surface as InspectError. */
async function postJSON<T>(url: string, payload: unknown): Promise<T> {
  let resp: Response;
  try {
    resp = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  } catch {
    throw new InspectError(
      "network",
      "The request never reached the backend.",
      null,
    );
  }
  if (!resp.ok) {
    let message = "";
    try {
      message = detailMessage(await resp.json());
    } catch {
      // Non-JSON error body (e.g. a proxy page): fall through to the status.
    }
    throw new InspectError(
      "http",
      message || `HTTP ${resp.status} ${resp.statusText}`.trim(),
      resp.status,
    );
  }
  return (await resp.json()) as T;
}

/** Inspect a truck: POST /inspect. */
export async function inspectLoad(
  payload: InspectPayload,
): Promise<InspectResponse> {
  return normaliseInspectResponse(
    await postJSON<Record<string, unknown>>("/inspect", payload),
  );
}

/**
 * Parse the evidence/provenance fields at the boundary (untrusted JSON):
 * missing or malformed values degrade to null / [] instead of throwing,
 * so an older backend still renders a verdict.
 */
export function normaliseInspectResponse(raw: Record<string, unknown>): InspectResponse {
  const ai =
    raw.ai_outputs && typeof raw.ai_outputs === "object"
      ? (raw.ai_outputs as Record<string, unknown>)
      : {};
  const record =
    raw.audit_record && typeof raw.audit_record === "object"
      ? (raw.audit_record as Record<string, unknown>)
      : {};
  const recordInputs =
    record.inputs && typeof record.inputs === "object" ? (record.inputs as Record<string, unknown>) : {};
  const vlmRaw = ai.vlm && typeof ai.vlm === "object" ? (ai.vlm as Record<string, unknown>) : {};
  return {
    ...raw,
    checks: parseChecks(raw.checks),
    why: typeof raw.why === "string" && raw.why.trim() ? raw.why.trim() : null,
    sampling: parseSampling(raw.sampling),
    receipt: parseReceipt(raw.receipt),
    observations: parseObservations(raw.observations ?? recordInputs.observations),
    votes: parseVotes(vlmRaw.votes),
    provenance: provenanceSchema.parse(raw.provenance),
    failed_stage:
      raw.failed_stage === "vlm" || raw.failed_stage === "llm" ? raw.failed_stage : null,
    actions: nextStepsSchema.parse(raw.actions),
    ai_outputs: {
      ...ai, // keeps gas and any other blocks for the raw audit view
      vlm: vlmOutputSchema.nullish().catch(null).parse(ai.vlm) ?? null,
      llm: llmOutputSchema.nullish().catch(null).parse(ai.llm) ?? null,
      detector:
        detectorOutputSchema.nullish().catch(null).parse(ai.detector) ?? null,
    },
  };
}

export type RuleEffect = "reject" | "hold" | "accept" | "none";

/** One row of the decision receipt (decision.rule_trace). */
export interface ReceiptRule {
  id: string;
  rule: string;
  fired: boolean;
  evidence: string;
  effect: RuleEffect;
}

export type ObservationStatus = "ok" | "poor" | "mismatch" | "not_installed" | "unavailable";

/** One gate sensor reading (lynceus.observations record). */
export interface Observation {
  source: string;
  kind: string;
  value: unknown;
  unit: string | null;
  uncertainty: number | null;
  status: ObservationStatus;
  measured_at_utc: string | null;
  sha256: string | null;
  simulated: boolean;
  note: string | null;
  frame: number | null;
}

/** One vision read's summary. */
export interface VisionVote {
  hard: string[];
  light: string[];
  confidence: number | null;
  frame: number | null;
}

const str = (v: unknown): string | null => (typeof v === "string" ? v : null);
const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
const strList = (v: unknown): string[] => (Array.isArray(v) ? v.filter((s): s is string => typeof s === "string") : []);
const objects = (v: unknown): Record<string, unknown>[] =>
  Array.isArray(v) ? v.filter((o): o is Record<string, unknown> => Boolean(o) && typeof o === "object") : [];

const EFFECTS: readonly RuleEffect[] = ["reject", "hold", "accept", "none"];
const OBS_STATUSES: readonly ObservationStatus[] = ["ok", "poor", "mismatch", "not_installed", "unavailable"];

export function parseReceipt(raw: unknown): ReceiptRule[] {
  return objects(raw)
    .filter((r) => typeof r.rule === "string" || typeof r.id === "string")
    .map((r, i) => ({
      id: str(r.id) ?? `rule-${i + 1}`,
      rule: str(r.rule) ?? str(r.id) ?? "",
      fired: r.fired === true,
      evidence: str(r.evidence) ?? "",
      effect: EFFECTS.includes(r.effect as RuleEffect) ? (r.effect as RuleEffect) : "none",
    }));
}

export function parseObservations(raw: unknown): Observation[] {
  return objects(raw)
    .filter((o) => typeof o.kind === "string")
    .map((o) => ({
      source: str(o.source) ?? "",
      kind: o.kind as string,
      value: o.value ?? null,
      unit: str(o.unit),
      uncertainty: num(o.uncertainty),
      status: OBS_STATUSES.includes(o.status as ObservationStatus) ? (o.status as ObservationStatus) : "unavailable",
      measured_at_utc: str(o.measured_at_utc),
      sha256: str(o.sha256),
      simulated: o.simulated === true,
      note: str(o.note),
      frame: num(o.frame),
    }));
}

export function parseVotes(raw: unknown): VisionVote[] {
  return objects(raw).map((v) => ({
    hard: strList(v.hard),
    light: strList(v.light),
    confidence: num(v.confidence),
    frame: num(v.frame),
  }));
}

/** One gate sensor plug-in (GET /sensors). */
export interface SensorPlugin {
  kind: string;
  name: string;
  status: "installed" | "simulated" | "not_installed";
  source: string | null;
  unit: string | null;
  note: string;
}

export interface SensorsResponse {
  sensors: SensorPlugin[];
  integration_note: string | null;
}

const PLUGIN_STATUSES: readonly SensorPlugin["status"][] = ["installed", "simulated", "not_installed"];

/** The gate's sensor plug-ins; null when this backend has no /sensors. */
export async function fetchSensors(): Promise<SensorsResponse | null> {
  try {
    const resp = await fetch("/sensors", { headers: { Accept: "application/json" }, cache: "no-store" });
    if (!resp.ok) return null;
    const raw = (await resp.json()) as Record<string, unknown>;
    return {
      sensors: objects(raw.sensors)
        .filter((p) => typeof p.kind === "string")
        .map((p) => ({
          kind: p.kind as string,
          name: str(p.name) ?? (p.kind as string),
          status: PLUGIN_STATUSES.includes(p.status as SensorPlugin["status"])
            ? (p.status as SensorPlugin["status"])
            : "not_installed",
          source: str(p.source),
          unit: str(p.unit),
          note: str(p.note) ?? "",
        })),
      integration_note: str(raw.integration_note),
    };
  } catch {
    return null;
  }
}

/** Same-origin link to a sealed record's dispute evidence (zip download). */
export function evidencePackUrl(recordId: string): string {
  return `/inspections/${encodeURIComponent(recordId)}/evidence-pack?format=zip`;
}

const TIERS: readonly SupplierTier[] = ["low", "medium", "high", "new"];

function parseSampling(raw: unknown): Sampling | null {
  if (!raw || typeof raw !== "object") return null;
  const s = raw as Record<string, unknown>;
  if (typeof s.sample_this_truck !== "boolean") return null;
  return {
    sample_this_truck: s.sample_this_truck,
    tier: TIERS.includes(s.tier as SupplierTier) ? (s.tier as SupplierTier) : "new",
    label: typeof s.label === "string" ? s.label : "",
    reason: typeof s.reason === "string" ? s.reason : "",
  };
}

/** Blob → raw base64 (no data: URI prefix): legacy blobToBase64. */
export function blobToBase64(blob: Blob): Promise<string> {
  const { promise, resolve, reject } = Promise.withResolvers<string>();
  const reader = new FileReader();
  reader.onload = () => resolve(String(reader.result).split(",")[1] || "");
  reader.onerror = () => reject(reader.error);
  reader.readAsDataURL(blob);
  return promise;
}

/** Fetch a demo photo's bytes as raw base64; null on failure (stub path). */
export async function fetchPhotoBase64(path: string): Promise<string | null> {
  try {
    const resp = await fetch(path);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    return await blobToBase64(await resp.blob());
  } catch {
    // file:// or offline: the <img> preview still renders, but the
    // payload falls back to the filename-only stub path.
    return null;
  }
}
