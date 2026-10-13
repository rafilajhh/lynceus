/**
 * Inspect API client: POST /inspect (same-origin base). The ledger client
 * (GET /inspections) lives in api.ts.
 */

import {
  llmOutputSchema,
  nextStepsSchema,
  provenanceSchema,
  vlmOutputSchema,
  type Decision,
  type GateResult,
  type ImpactEstimate,
  type InspectProvenance,
  type LlmOutput,
  type NextStep,
  type VlmOutput,
} from "./api";

export interface InspectPayload {
  truck_id: string;
  /** Hauler named on the waybill; the backend accepts extra fields. */
  supplier: string | null;
  photo_base64: string | null;
  photo_filename: string | null;
  demo_case: string | null;
  manifest_text: string | null;
  /** Optional photo of the paper waybill (extra evidence; backend's
      InspectRequest allows extra fields and digests all inputs). */
  waybill_image_base64?: string | null;
  weight_kg: number;
  stream: string;
  moisture_pct: number;
  age_h: number;
}

export interface InspectResponse {
  record_id?: string;
  /** Backend-provenanced; null when absent or unrecognised. */
  provenance: InspectProvenance;
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
function normaliseInspectResponse(raw: Record<string, unknown>): InspectResponse {
  const ai =
    raw.ai_outputs && typeof raw.ai_outputs === "object"
      ? (raw.ai_outputs as Record<string, unknown>)
      : {};
  return {
    ...raw,
    provenance: provenanceSchema.parse(raw.provenance),
    actions: nextStepsSchema.parse(raw.actions),
    ai_outputs: {
      ...ai, // keeps gas and any other blocks for the raw audit view
      vlm: vlmOutputSchema.nullish().catch(null).parse(ai.vlm) ?? null,
      llm: llmOutputSchema.nullish().catch(null).parse(ai.llm) ?? null,
    },
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
