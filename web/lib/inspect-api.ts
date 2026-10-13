/**
 * Inspect API client: POST /inspect with POST /assess fallback.
 * Ported from legacy web/app.js (same-origin base, legacy error
 * contract). The ledger client (GET /inspections) lives in api.ts.
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
 * POST JSON with the legacy error contract:
 * - network failure → rethrows TypeError (caller renders "backend unreachable")
 * - !ok → Error("Backend returned HTTP <status> <statusText>: <detail>")
 */
async function postJSON<T>(url: string, payload: unknown): Promise<T> {
  const resp = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!resp.ok) {
    let detail = "";
    try {
      const body: unknown = await resp.json();
      if (body && typeof body === "object") {
        const obj = body as { detail?: unknown; message?: unknown };
        detail = String(obj.detail ?? obj.message ?? JSON.stringify(body));
      } else {
        detail = JSON.stringify(body);
      }
    } catch {
      detail = await resp.text().catch(() => "");
    }
    throw new Error(
      `Backend returned HTTP ${resp.status} ${resp.statusText}` +
        (detail ? `: ${detail}` : ""),
    );
  }
  return (await resp.json()) as T;
}

/**
 * Inspect a truck: POST /inspect; on a 404 (endpoint missing on an
 * older backend) falls back to POST /assess: legacy app.js contract.
 */
export async function inspectLoad(
  payload: InspectPayload,
): Promise<InspectResponse> {
  let raw: Record<string, unknown>;
  try {
    raw = await postJSON<Record<string, unknown>>("/inspect", payload);
  } catch (err) {
    if (err instanceof Error && /HTTP 404/.test(err.message)) {
      raw = await postJSON<Record<string, unknown>>("/assess", payload);
    } else {
      throw err;
    }
  }
  return normaliseInspectResponse(raw);
}

/**
 * Parse the evidence/provenance fields at the boundary (untrusted JSON):
 * missing or malformed values degrade to null / [] instead of throwing,
 * so an older backend (or /assess) still renders a verdict.
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
