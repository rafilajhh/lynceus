/**
 * Streaming inspection: POST /inspect/stream returns NDJSON, one event per
 * line, flushed as each pipeline stage happens (contract §6):
 *
 *   {"event":"stage","stage":"detector","status":"done","t":1.1,"data":{...}}
 *   {"event":"result","data":{ ...exact /inspect response... }}
 *   {"event":"error","status":503,"error":"busy","message":"..."}
 *
 * A backend without the endpoint (404/405) falls back to POST /inspect;
 * the caller learns which path ran through `onMode`. The fallback only
 * fires before the backend accepted the request, so a truck is never
 * inspected (and sealed) twice.
 */

import {
  InspectError,
  inspectLoad,
  normaliseInspectResponse,
  type InspectPayload,
  type InspectResponse,
} from "./inspect-api";

export interface StageEvent {
  stage: string;
  status: "running" | "done" | string;
  /** Seconds since the backend accepted the request. */
  t: number;
  data: Record<string, unknown>;
}

export type InspectMode = "stream" | "single";

function asStage(raw: Record<string, unknown>): StageEvent | null {
  if (typeof raw.stage !== "string") return null;
  return {
    stage: raw.stage,
    status: typeof raw.status === "string" ? raw.status : "done",
    t: typeof raw.t === "number" && Number.isFinite(raw.t) ? raw.t : 0,
    data:
      raw.data && typeof raw.data === "object" ? (raw.data as Record<string, unknown>) : {},
  };
}

async function errorFrom(resp: Response): Promise<InspectError> {
  let message = "";
  try {
    const body = (await resp.json()) as { detail?: unknown };
    const d = body?.detail;
    if (typeof d === "string") message = d;
    else if (d && typeof d === "object") {
      const m = (d as { message?: unknown }).message;
      if (typeof m === "string") message = m;
    }
  } catch {
    // Non-JSON body: the status line says enough.
  }
  return new InspectError("http", message || `HTTP ${resp.status}`, resp.status);
}

export async function inspectStreaming(
  payload: InspectPayload,
  onStage: (e: StageEvent) => void,
  onMode: (mode: InspectMode) => void,
): Promise<InspectResponse> {
  let resp: Response;
  try {
    resp = await fetch("/inspect/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/x-ndjson" },
      body: JSON.stringify(payload),
    });
  } catch {
    throw new InspectError("network", "The request never reached the backend.", null);
  }
  if (resp.status === 404 || resp.status === 405) {
    onMode("single");
    return inspectLoad(payload);
  }
  if (!resp.ok) throw await errorFrom(resp);
  onMode("stream");
  if (!resp.body) {
    // No readable body (very old browser): the whole stream arrives at once.
    return parseLines(await resp.text(), onStage);
  }

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let result: InspectResponse | null = null;
  try {
    for (;;) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      let nl = buffer.indexOf("\n");
      while (nl >= 0) {
        result = handleLine(buffer.slice(0, nl), onStage) ?? result;
        buffer = buffer.slice(nl + 1);
        nl = buffer.indexOf("\n");
      }
      if (done) break;
    }
  } catch (err) {
    if (err instanceof InspectError) throw err;
    throw new InspectError("network", "The connection dropped before the verdict arrived.", null);
  }
  result = handleLine(buffer, onStage) ?? result;
  if (!result) {
    throw new InspectError("http", "The stream ended without a verdict.", resp.status);
  }
  return result;
}

function parseLines(text: string, onStage: (e: StageEvent) => void): InspectResponse {
  let result: InspectResponse | null = null;
  for (const line of text.split("\n")) result = handleLine(line, onStage) ?? result;
  if (!result) throw new InspectError("http", "The stream ended without a verdict.", null);
  return result;
}

/** One NDJSON line → a stage callback, the final result, or a thrown error. */
function handleLine(line: string, onStage: (e: StageEvent) => void): InspectResponse | null {
  const trimmed = line.trim();
  if (!trimmed) return null;
  let raw: Record<string, unknown>;
  try {
    raw = JSON.parse(trimmed) as Record<string, unknown>;
  } catch {
    return null; // a torn or non-JSON line carries no state
  }
  if (raw.event === "stage") {
    const stage = asStage(raw);
    if (stage) onStage(stage);
    return null;
  }
  if (raw.event === "result" && raw.data && typeof raw.data === "object") {
    return normaliseInspectResponse(raw.data as Record<string, unknown>);
  }
  if (raw.event === "error") {
    const status = typeof raw.status === "number" ? raw.status : null;
    const message =
      typeof raw.message === "string" && raw.message
        ? raw.message
        : typeof raw.error === "string"
          ? raw.error
          : "The inspection failed.";
    throw new InspectError("http", message, status);
  }
  return null;
}
