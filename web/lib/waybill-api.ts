/**
 * Waybill OCR client: POST /waybill/extract. The vision model on AMD Token
 * Factory reads the paper waybill photo; the register is auto-filled from
 * the fields it could read. Every field is nullable: an unreadable field
 * stays empty for the operator, it is never guessed.
 */

import { z } from "zod";

const text = z.string().trim().min(1).nullish().catch(null);
const num = z.coerce.number().finite().positive().nullish().catch(null);

const STREAMS = [
  "mixed-msw",
  "co-disposal",
  "organic-rich",
  "green-waste",
  "rdf-feedstock",
  "dry-recyclables",
] as const;

const waybillExtractSchema = z.object({
  fields: z.object({
    truck_id: text,
    supplier: text,
    weight_kg: num,
    stream: z.enum(STREAMS).nullish().catch(null),
    moisture_pct: z.coerce.number().min(0).max(100).nullish().catch(null),
    waybill_no: text,
    date: text,
    origin: text,
    destination: text,
    driver: text,
    reference: text,
  }),
  stream_raw: text,
  confidence: z.coerce.number().min(0).max(1).catch(0),
  model: z.string().nullish().catch(null),
  provider: z.string().nullish().catch(null),
  latency_ms: z.coerce.number().nullish().catch(null),
  provenance: z.string().catch("live"),
});

export type WaybillExtract = z.infer<typeof waybillExtractSchema>;
export type WaybillFields = WaybillExtract["fields"];

export class WaybillError extends Error {
  constructor(
    readonly kind: "unavailable" | "http" | "network",
    message: string,
  ) {
    super(message);
    this.name = "WaybillError";
  }
}

/** Read a waybill photo (raw base64, no data: prefix). */
export async function extractWaybill(
  imageBase64: string,
  filename: string | null,
  signal?: AbortSignal,
): Promise<WaybillExtract> {
  let resp: Response;
  try {
    resp = await fetch("/waybill/extract", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ image_base64: imageBase64, filename }),
      credentials: "same-origin",
      signal,
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    throw new WaybillError("network", "The waybill reader is unreachable.");
  }
  if (!resp.ok) {
    let message = "";
    try {
      const body = (await resp.json()) as { detail?: { message?: unknown } | string };
      const detail = body?.detail;
      if (typeof detail === "string") message = detail;
      else if (detail && typeof detail.message === "string") message = detail.message;
    } catch {
      // non-JSON body: use the status below
    }
    throw new WaybillError(
      resp.status === 503 ? "unavailable" : "http",
      message || `Couldn't read the waybill (HTTP ${resp.status}).`,
    );
  }
  const parsed = waybillExtractSchema.safeParse(await resp.json().catch(() => null));
  if (!parsed.success) {
    throw new WaybillError("http", "The waybill reader returned an unreadable answer.");
  }
  return parsed.data;
}
