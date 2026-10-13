/**
 * Inspect API client: POST /inspect with POST /assess fallback.
 * Ported from legacy web/app.js (same-origin base, legacy error
 * contract). The ledger client (GET /inspections) lives in api.ts.
 */

import type { Decision, GateResult, ImpactEstimate } from "./api";

export interface InspectPayload {
  truck_id: string;
  photo_base64: string | null;
  photo_filename: string | null;
  demo_case: string | null;
  manifest_text: string | null;
  weight_kg: number;
  stream: string;
  moisture_pct: number;
  age_h: number;
}

export interface InspectResponse {
  record_id?: string;
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
  ai_outputs?: {
    vlm?: { confidence?: number; detected?: Record<string, unknown> };
    llm?: { reasoning?: string; confidence?: number };
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
  try {
    return await postJSON<InspectResponse>("/inspect", payload);
  } catch (err) {
    if (err instanceof Error && /HTTP 404/.test(err.message)) {
      return await postJSON<InspectResponse>("/assess", payload);
    }
    throw err;
  }
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
