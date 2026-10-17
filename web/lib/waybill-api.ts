/**
 * Gate intake clients: the AI waybill reader (POST /waybill/read), the
 * weighbridge indicator feed (GET /weighbridge/reading) and the model
 * warm-up (POST /warmup). Contract: .omc/plans/product-win.md §1, §2, §6.
 *
 * Responses are untrusted JSON, parsed once here with zod; a malformed field
 * degrades to null instead of throwing. An endpoint the backend does not
 * have (404/405, an older build) surfaces as `kind: "unavailable"` so the
 * console falls back to typed fields and a manual weight.
 */

import { z } from "zod";

// ---- Waybill fields ----------------------------------------------------

/** Every field the reader extracts, in the order the operator checks them. */
export const WAYBILL_FIELDS = [
  { key: "plate", label: "Plate", kind: "text" },
  { key: "carrier", label: "Carrier (supplier)", kind: "text" },
  { key: "load_type", label: "Load type", kind: "text" },
  { key: "moisture_pct", label: "Moisture %", kind: "number" },
  { key: "gross_kg", label: "Gross kg", kind: "number" },
  { key: "tare_kg", label: "Tare kg", kind: "number" },
  { key: "net_kg", label: "Net kg", kind: "number" },
  { key: "document_no", label: "Waybill no.", kind: "text" },
  { key: "date", label: "Date", kind: "text" },
  { key: "reference_no", label: "DO / ref.", kind: "text" },
  { key: "origin", label: "Origin", kind: "text" },
  { key: "destination", label: "Destination", kind: "text" },
  { key: "shipper", label: "Shipper", kind: "text" },
  { key: "driver", label: "Driver", kind: "text" },
  { key: "remarks", label: "Remarks", kind: "text" },
] as const;

export type WaybillFieldKey = (typeof WAYBILL_FIELDS)[number]["key"];
export type WaybillValues = Record<WaybillFieldKey, string>;

export const EMPTY_WAYBILL: WaybillValues = Object.fromEntries(
  WAYBILL_FIELDS.map((f) => [f.key, ""]),
) as WaybillValues;

/** A field below this read confidence is shown amber: the operator checks it. */
export const LOW_CONFIDENCE = 0.6;

const fieldSchema = z
  .object({
    value: z.union([z.string(), z.number()]).nullish().catch(null),
    confidence: z.number().min(0).max(1).catch(0),
  })
  .catch({ value: null, confidence: 0 });

const waybillReadSchema = z.object({
  fields: z.record(z.string(), fieldSchema).catch({}),
  derived: z
    .object({
      waste_stream: z.string().nullish().catch(null),
      declares_processed_rdf: z.boolean().nullish().catch(null),
      arithmetic: z
        .object({
          gross_minus_tare_kg: z.number().nullish().catch(null),
          net_kg: z.number().nullish().catch(null),
          consistent: z.boolean().nullish().catch(null),
        })
        .nullish()
        .catch(null),
    })
    .nullish()
    .catch(null),
  confidence: z.number().nullish().catch(null),
  transcript: z.string().nullish().catch(null),
  model: z.string().nullish().catch(null),
  provider: z.string().nullish().catch(null),
  latency_ms: z.number().nullish().catch(null),
  provenance: z.string().nullish().catch(null),
  warnings: z.array(z.string()).catch([]),
  /** Server-signed proof of this read, bound to the image's sha256: sent
      back as waybill_read.read_token with the SAME image bytes. Without it
      the fields are sealed as operator-typed. */
  read_token: z.string().nullish().catch(null),
});

export type WaybillRead = z.infer<typeof waybillReadSchema>;

/** Read values as editable strings plus their per-field confidence. */
export function readToValues(read: WaybillRead): {
  values: WaybillValues;
  confidence: Record<WaybillFieldKey, number>;
} {
  const values = { ...EMPTY_WAYBILL };
  const confidence = {} as Record<WaybillFieldKey, number>;
  for (const { key } of WAYBILL_FIELDS) {
    const f = read.fields[key];
    const v = f?.value;
    values[key] = v === null || v === undefined ? "" : String(v);
    confidence[key] = values[key] ? (f?.confidence ?? 0) : 0;
  }
  return { values, confidence };
}

/**
 * A plain decimal: "28,5" / "28.5" / "0.125" / "31.5 %" → the number as
 * written (a comma is a decimal point). For percentages and lab values,
 * where "0.125" must stay 0.125. Null when empty or not a number.
 */
export function parseDecimal(raw: string): number | null {
  const s = raw.replace(/\s|%/g, "").replace(",", ".");
  if (!s || !/^-?\d*\.?\d+$/.test(s)) return null;
  const n = Number(s);
  return Number.isFinite(n) ? n : null;
}

/** Waybill fields in kilograms: thousands grouping is read as grouping. */
const KG_FIELD = /_kg$/;

/**
 * A weight in kg: "32.580" / "32,580" / "16340 kg" → 32580; "28,5" → 28.5.
 * The thousands heuristic is for kilograms only: use parseDecimal for
 * percentages and lab values. Null when empty.
 */
export function parseFieldNumber(raw: string): number | null {
  let s = raw.replace(/[^\d.,-]/g, "");
  if (!s) return null;
  // Indonesian thousands dots ("32.580") and decimal commas ("28,5").
  if (/^\d{1,3}([.,]\d{3})+$/.test(s)) s = s.replace(/[.,]/g, "");
  else s = s.replace(",", ".");
  const n = Number(s);
  return Number.isFinite(n) ? n : null;
}

/** Waybill values as the plain dict /inspect takes (`waybill_fields`). */
export function toWaybillFields(values: WaybillValues): Record<string, string | number | null> {
  const out: Record<string, string | number | null> = {};
  for (const { key, kind } of WAYBILL_FIELDS) {
    const v = values[key].trim();
    out[key] = !v
      ? null
      : kind === "number"
        ? KG_FIELD.test(key)
          ? parseFieldNumber(v)
          : parseDecimal(v)
        : v;
  }
  return out;
}

/** Load type / remarks → engine waste stream (same mapping as the backend). */
export function streamFromDeclaration(values: WaybillValues): string {
  const text = `${values.load_type} ${values.remarks}`.toLowerCase();
  if (/\b(rdf|srf)\b|fluff|pemilahan|hasil proses/.test(text)) return "rdf-feedstock";
  if (/\bmsw\b|sampah campuran|mixed/.test(text)) return "mixed-msw";
  if (/organi/.test(text)) return "organic-rich";
  return "rdf-feedstock";
}

/** Deterministic waybill text from the confirmed fields (what the record
    stores as the manifest). Empty fields are left out, never invented. */
export function transcriptOf(values: WaybillValues): string {
  return WAYBILL_FIELDS.filter((f) => values[f.key].trim())
    .map((f) => `${f.label}: ${values[f.key].trim()}`)
    .join(" | ");
}

// ---- Transport ---------------------------------------------------------

export type IntakeErrorKind = "unavailable" | "offline" | "network" | "http";

export class IntakeError extends Error {
  kind: IntakeErrorKind;
  status: number | null;

  constructor(kind: IntakeErrorKind, message: string, status: number | null) {
    super(message);
    this.name = "IntakeError";
    this.kind = kind;
    this.status = status;
  }
}

async function call(path: string, init?: RequestInit): Promise<unknown> {
  let res: Response;
  try {
    res = await fetch(path, { cache: "no-store", ...init });
  } catch {
    throw new IntakeError("network", "The backend could not be reached.", null);
  }
  if (res.status === 404 || res.status === 405) {
    throw new IntakeError("unavailable", "This backend has no such endpoint.", res.status);
  }
  if (!res.ok) {
    let message = `HTTP ${res.status}`;
    let error = "";
    try {
      const body = (await res.json()) as { detail?: unknown };
      const d = body?.detail;
      if (typeof d === "string") message = d;
      else if (d && typeof d === "object") {
        const m = (d as { message?: unknown }).message;
        const e = (d as { error?: unknown }).error;
        if (typeof m === "string" && m) message = m;
        if (typeof e === "string") error = e;
      }
    } catch {
      // Non-JSON error body: keep the status line.
    }
    // "busy" is also a 503, but it means "try again", not "type the fields".
    const offline = error.endsWith("_offline");
    throw new IntakeError(offline ? "offline" : "http", message, res.status);
  }
  return res.json();
}

/** Read a waybill photo with the vision model. Bytes go unchanged: the
    offline reader recognises the bundled sample by its sha256. */
export async function readWaybill(
  imageBase64: string,
  filename: string | null,
  signal?: AbortSignal,
): Promise<WaybillRead> {
  const raw = await call("/waybill/read", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({ image_base64: imageBase64, filename }),
    signal,
  });
  return waybillReadSchema.parse(raw);
}

// ---- Weighbridge -----------------------------------------------------------

const scaleSchema = z.object({
  scale: z.string().catch("Weighbridge"),
  plate: z.string().catch(""),
  gross_kg: z.number().nullish().catch(null),
  tare_kg: z.number().nullish().catch(null),
  net_kg: z.number(),
  stable: z.boolean().catch(true),
  source: z.string().catch("simulated"),
  read_at_utc: z.string().nullish().catch(null),
  note: z.string().nullish().catch(null),
});

export type ScaleReading = z.infer<typeof scaleSchema>;

/** Capture the indicator reading for a plate (simulated feed in the demo). */
export async function readWeighbridge(
  plate: string,
  declaredNetKg: number | null,
  signal?: AbortSignal,
): Promise<ScaleReading> {
  const q = new URLSearchParams({ plate });
  if (declaredNetKg !== null && declaredNetKg > 0) q.set("declared_net_kg", String(declaredNetKg));
  const raw = await call(`/weighbridge/reading?${q}`, {
    headers: { Accept: "application/json" },
    signal,
  });
  return scaleSchema.parse(raw);
}

/** Ask the backend to warm the vision model; never fails the caller. */
export async function warmUp(): Promise<void> {
  try {
    await fetch("/warmup", { method: "POST", cache: "no-store" });
  } catch {
    // Warm-up is a courtesy: the first inspection is just slower without it.
  }
}
