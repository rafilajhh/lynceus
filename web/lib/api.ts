/**
 * API client + contract types for the inspection ledger.
 *
 * Written against the backend contract (backend/src/lynceus/api.py):
 *
 *   GET /inspections →
 *     { inspections: [{ record_id, truck_id, decision, decided_at_utc,
 *                        prevented_loss_idr, admitted_value_idr,
 *                        gate_states }] }
 *   (prevented_loss_idr: reject/escalate only; admitted_value_idr: accept only)
 *
 *   GET /inspections/{record_id} → the full audit record (shape of
   *   backend/runs/inspection-<id>/audit.json): digest.record_sha256, gates,
 *   inputs, ai_outputs, engine_outputs, verdict, record_id.
 *
 * External JSON is untrusted: each response is parsed once at this boundary
 * with a zod schema; consumers receive a fully typed value. Missing fields
 * degrade to honest placeholders (catchall "passthrough" keeps unknown
 * backend extras available without crashing the UI).
 */

import { z } from "zod";

/** Final verdict values (audit.Decision closed enum). */
export type Decision =
  | "accept"
  | "reject"
  | "escalate_human"
  | "refuse_insufficient_input"
  | "unknown";

/** Per-gate states (audit.GateState closed enum). */
export type GateState = "passed" | "failed" | "not_run" | "not_evaluated";

const decisionSchema = z
  .enum(["accept", "reject", "escalate_human", "refuse_insufficient_input", "unknown"])
  .catch("unknown");

const gateStateSchema = z
  .enum(["passed", "failed", "not_run", "not_evaluated"])
  .catch("not_evaluated");

const inspectionSummarySchema = z.object({
  record_id: z.string(),
  truck_id: z.string().catch("—"),
  /** Supplier from the waybill; absent on v1 records and blanks. */
  supplier: z.string().nullish().catch(null),
  decision: decisionSchema,
  decided_at_utc: z.string().catch(""),
  /** Loss avoided by rejecting/escalating; 0 for accepted loads. */
  prevented_loss_idr: z.coerce.number().catch(0),
  /** Market value of an accepted load (NOT a prevented loss); 0 otherwise. */
  admitted_value_idr: z.coerce.number().catch(0),
  gate_states: z.record(z.string(), gateStateSchema).catch({}),
});

const inspectionsResponseSchema = z.object({
  inspections: z.array(inspectionSummarySchema).catch([]),
});

const gateResultSchema = z.object({
  state: gateStateSchema,
  value: z.number().nullable().catch(null),
  threshold: z.number().nullable().catch(null),
  reason: z.string().catch(""),
});

/**
 * Tolerant list: items that fail `item` are dropped, a non-array becomes
 * []. One malformed entry from the model must not blank the whole card.
 */
function tolerantList<T extends z.ZodType>(item: T) {
  return z
    .array(z.unknown())
    .catch([])
    .transform((items) =>
      items.flatMap((raw) => {
        const parsed = item.safeParse(raw);
        return parsed.success ? [parsed.data as z.infer<T>] : [];
      }),
    );
}

/** Normalised (0..1, top-left origin) contaminant region on the photo.
    Malformed or inverted boxes are dropped, never clamped (same rule as
    backend vision_boxes.py: a box in the wrong place is worse than none). */
const evidenceBoxSchema = z
  .object({
    label: z.string().catch("contaminant"),
    x0: z.number(),
    y0: z.number(),
    x1: z.number(),
    y1: z.number(),
  })
  .refine(
    (b) => 0 <= b.x0 && b.x0 < b.x1 && b.x1 <= 1 && 0 <= b.y0 && b.y0 < b.y1 && b.y1 <= 1,
  );

/** One SOP-cited operator step (backend actions.next_steps). */
const nextStepSchema = z.object({
  order: z.number().catch(0),
  text: z.string().min(1),
  sop_ref: z.string().catch(""),
});

export const nextStepsSchema = tolerantList(nextStepSchema);

/** AI model output provenance: v1 records lack provider/latency/boxes. */
const modelOutputShape = {
  model: z.string().nullish().catch(null),
  confidence: z.number().nullish().catch(null),
  provider: z.string().nullish().catch(null),
  latency_ms: z.number().nullish().catch(null),
};

export const vlmOutputSchema = z
  .object({
    ...modelOutputShape,
    detected: z.record(z.string(), z.unknown()).nullish().catch(null),
    boxes: tolerantList(evidenceBoxSchema),
    localisation: z.enum(["box", "zone"]).nullish().catch(null),
  })
  .catchall(z.unknown());

export const llmOutputSchema = z
  .object({
    ...modelOutputShape,
    reasoning: z.string().nullish().catch(null),
  })
  .catchall(z.unknown());

/** Top-level AI provenance of an /inspect response. */
export const provenanceSchema = z
  .enum(["live", "stub", "stub_fallback_live_error"])
  .nullish()
  .catch(null);

export type EvidenceBox = z.infer<typeof evidenceBoxSchema>;
export type NextStep = z.infer<typeof nextStepSchema>;
export type VlmOutput = z.infer<typeof vlmOutputSchema>;
export type LlmOutput = z.infer<typeof llmOutputSchema>;
export type InspectProvenance = z.infer<typeof provenanceSchema>;

const auditRecordSchema = z
  .object({
    record_id: z.string().optional(),
    digest: z
      .object({
        record_sha256: z.string().optional(),
        algorithm: z.string().optional(),
      })
      .optional(),
    gates: z.record(z.string(), gateResultSchema).optional(),
    inputs: z
      .object({
        truck_id: z.string().optional(),
        // Persisted from the intake form by a later backend task; absent
        // on older records.
        supplier: z.string().nullish().catch(null),
        photo: z
          .object({
            filename: z.string().catch("photo.jpg"),
            sha256: z.string().optional(),
            captured_at_utc: z.string().optional(),
            provenance: z.string().optional(),
            // TODO(backend): relative path to the stored photo, when exposed.
            path: z.string().optional(),
          })
          .optional(),
        weight: z
          .object({
            value_kg: z.number().optional(),
            source: z.string().optional(),
          })
          .optional(),
        gas: z
          .object({
            readings_ppm: z.record(z.string(), z.number()).optional(),
            source: z.string().optional(),
          })
          .optional(),
        manifest_text: z
          .object({
            source: z.string().optional(),
            ocr_confidence: z.number().optional(),
          })
          .optional(),
      })
      .optional(),
    ai_outputs: z
      .object({
        llm: llmOutputSchema.nullish().catch(null),
        vlm: vlmOutputSchema.nullish().catch(null),
        // null on records with no gas data (backend: GasOutput | None).
        gas: z
          .object({
            source: z.string().nullish(),
            model_basis: z.string().nullish(),
            instrument: z
              .object({
                model: z.string().nullish(),
                technology: z.string().nullish(),
                basis: z.string().nullish(),
              })
              .passthrough()
              .nullish(),
          })
          .nullish(),
      })
      .optional(),
    // v1 records carry no actions: the list degrades to [].
    engine_outputs: z
      .object({
        recommendation: z
          .object({ actions: nextStepsSchema })
          .catchall(z.unknown())
          .nullish()
          .catch(null),
      })
      .catchall(z.unknown())
      .nullish()
      .catch(null),
    verdict: z
      .object({
        decision: decisionSchema.optional(),
        decided_at_utc: z.string().optional(),
        classification: z.string().optional(),
        uncertainty: z.string().optional(),
      })
      .optional(),
    // Optional human-readable reasons list (as returned by POST /inspect).
    reasons: z.array(z.string()).optional(),
  })
  .catchall(z.unknown());

// The detail endpoint may wrap the record; accept {record|audit_record: …}
// as well as the bare record itself. Unwrap first, then parse strictly.
const unwrapRecordSchema = z.union([
  z.object({ record: z.unknown() }).transform((v) => v.record),
  z.object({ audit_record: z.unknown() }).transform((v) => v.audit_record),
  z.unknown().transform((v) => v),
]);

export type InspectionSummary = z.infer<typeof inspectionSummarySchema>;
export type InspectionDetail = z.infer<typeof auditRecordSchema>;
export type GateResult = z.infer<typeof gateResultSchema>;

/**
 * Impact estimate as returned by POST /inspect (backend
 * impact.estimate_prevented_loss): prevented-loss in IDR/USD with
 * per-figure provenance rows: every basis entry carries its source
 * URL, no invented figures.
 */
export interface ImpactBasisRow {
  label: string;
  value: string;
  source_url: string;
}

export interface ImpactEstimate {
  prevented_loss_idr?: number;
  prevented_loss_usd?: number;
  basis?: ImpactBasisRow[];
  note?: string;
  /** Research provenance string set by the backend (impact.py). */
  provenance?: string;
}
export type PhotoInput = NonNullable<
  NonNullable<InspectionDetail["inputs"]>["photo"]
>;

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function getJSON(path: string): Promise<unknown> {
  let res: Response;
  try {
    res = await fetch(path, {
      headers: { Accept: "application/json" },
      cache: "no-store",
    });
  } catch {
    throw new ApiError("Backend unreachable: is the Lynceus API running?", 0);
  }
  if (!res.ok) {
    throw new ApiError(`GET ${path} failed (HTTP ${res.status})`, res.status);
  }
  return res.json();
}

export async function fetchInspections(): Promise<InspectionSummary[]> {
  const data = inspectionsResponseSchema.parse(await getJSON("/inspections"));
  return data.inspections.filter((item) => item.record_id !== "");
}

export async function fetchInspectionDetail(
  recordId: string,
): Promise<InspectionDetail> {
  const record = auditRecordSchema.parse(
    unwrapRecordSchema.parse(
      await getJSON(`/inspections/${encodeURIComponent(recordId)}`),
    ),
  );
  // The path identifies the record; keep it even if the payload disagrees.
  return { ...record, record_id: recordId };
}
