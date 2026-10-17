/**
 * Shift report client: GET /shift-report → what the gate caught this shift,
 * what it saved, and which suppliers keep sending bad loads.
 *
 * Untrusted JSON, parsed once here with zod. Malformed fields degrade to
 * honest placeholders; a malformed supplier row is dropped rather than
 * blanking the table.
 */

import { z } from "zod";

const count = z.number().int().nonnegative().catch(0);

const supplierRowSchema = z.object({
  supplier: z.string().min(1),
  trucks: count,
  reject: count,
  escalate: count,
  risk_score: z.number().min(0).max(1).catch(0),
  flagged: z.boolean().catch(false),
  explanation: z.string().nullish().catch(null),
  /** "model" = assist model text that passed the number check; "rule" =
      the deterministic sentence. */
  explanation_source: z.enum(["model", "rule"]).nullish().catch(null),
});

/** Value-model figures carry no fallback: a malformed one fails the scenario,
    which drops the whole value model (below) rather than render as Rp 0. */
const money = z.number();

const sideSchema = z.object({
  escaped_hard_loads: z.number(),
  expected_damage_idr: money,
  trucks_checked_by_hand: z.number(),
  operator_minutes: z.number(),
  false_rejects: z.number(),
  false_reject_cost_idr: money,
});

const scenarioSchema = z.object({
  without: sideSchema,
  with: sideSchema,
  expected_loss_avoided_idr: money,
  false_reject_cost_idr: money,
  operator_minutes_saved: z.number(),
  operator_time_value_idr: money,
  net_value_idr: money,
  /** Lynceus's proposed per-gate fee over the days one gate takes to receive
      these trucks. Nullish for an older backend; no .catch, so a malformed
      value still drops the model. */
  days_per_1000_trucks: z.number().nullish(),
  subscription_cost_idr: money.nullish(),
  net_after_subscription_idr: money.nullish(),
});

const valueParameterSchema = z.object({
  key: z.string(),
  label: z.string(),
  unit: z.string(),
  low: z.number(),
  base: z.number(),
  high: z.number(),
  sources: z.array(z.string()).catch([]),
  assumption: z.boolean().catch(true),
  rationale: z.string().catch(""),
});

/** Expected value per 1,000 trucks, with vs without Lynceus (impact.value_model).
    Any malformed part drops the whole model: half a value model would mislead. */
const valueModelSchema = z.object({
  trucks: z.number().int().positive(),
  scenarios: z.object({ low: scenarioSchema, base: scenarioSchema, high: scenarioSchema }),
  parameters: z.array(valueParameterSchema),
  worst_case_per_incident_idr: z.number().nonnegative(),
  benchmark_file: z.string(),
  benchmark_reject_precision: z.number().nullish(),
  eur_idr_rate: z.number().positive(),
  eur_idr_rate_date: z.string(),
  eur_idr_source_url: z.string(),
  note: z.string().nullish(),
});

const optionalCount = z.number().nonnegative().nullish().catch(null);

/**
 * What the gate measurably changed this shift (shift.build_report
 * `improvement`): counted from the sealed ledger and its follow-ups. The one
 * assumption (minutes per manual hand check) is stated in its own field and
 * in `notes`. Every figure is nullable: an absent one is left out, never
 * shown as 0.
 */
export const improvementSchema = z.object({
  trucks: optionalCount,
  auto_cleared: optionalCount,
  held: optionalCount,
  rejected: optionalCount,
  refused: optionalCount,
  hand_checks_avoided: optionalCount,
  manual_check_minutes_assumed: optionalCount,
  staff_minutes_freed: optionalCount,
  median_decision_s: optionalCount,
  p95_decision_s: optionalCount,
  hazardous_loads_stopped: optionalCount,
  declaration_conflicts: optionalCount,
  supervisor_reviews: optionalCount,
  ai_confirmed: optionalCount,
  ai_overridden: optionalCount,
  lab_samples: optionalCount,
  spec_breaches: optionalCount,
  deductions_idr: optionalCount,
  breach_fees_idr: optionalCount,
  notices: optionalCount,
  exposure_if_tipped_idr: optionalCount,
  notes: z.array(z.string()).catch([]),
});

const shiftReportSchema = z.object({
  window: z
    .object({
      since: z.string().nullish().catch(null),
      until: z.string().nullish().catch(null),
      first_truck_utc: z.string().nullish().catch(null),
      last_truck_utc: z.string().nullish().catch(null),
    })
    .catch({ since: null, until: null, first_truck_utc: null, last_truck_utc: null }),
  trucks: count,
  by_verdict: z.record(z.string(), count).catch({}),
  contaminants: z.record(z.string(), count).catch({}),
  /** Sum of per-verdict estimates; each reject's assumes certain damage, so
      this is worst-case exposure (loss_exposure_idr is the same figure). */
  prevented_loss_idr: z.number().nonnegative().catch(0),
  loss_exposure_idr: z.number().nonnegative().nullish().catch(null),
  value_model: valueModelSchema.nullish().catch(null),
  /** Absent on an older backend: the page then falls back to verdict counts. */
  improvement: improvementSchema.nullish().catch(null),
  median_seconds_per_truck: z.number().nonnegative().nullish().catch(null),
  suppliers: z
    .array(z.unknown())
    .catch([])
    .transform((items) =>
      items.flatMap((raw) => {
        const parsed = supplierRowSchema.safeParse(raw);
        return parsed.success ? [parsed.data] : [];
      }),
    ),
  sample: z.boolean().catch(false),
  sample_records: count,
  explanation_model: z.string().nullish().catch(null),
  explanation_provider: z.string().nullish().catch(null),
});

export type ShiftReport = z.infer<typeof shiftReportSchema>;
export type SupplierRow = ShiftReport["suppliers"][number];
export type ValueModel = NonNullable<ShiftReport["value_model"]>;
export type ValueScenario = ValueModel["scenarios"]["base"];
export type Improvement = NonNullable<ShiftReport["improvement"]>;

/** Risk rule, mirrored from backend/src/lynceus/shift.py for the legend. */
export const FLAG_MIN_TRUCKS = 3;
export const FLAG_MIN_RISK = 0.34;

// ---- Supplier scorecard (GET /suppliers, GET /contract) -------------------

const nullableNumber = z.number().nullish().catch(null);

/** One supplier's scorecard row (backend suppliers.SupplierProfile). The
    transport and types live in ops-api.ts; this is the runtime guard. */
export const supplierProfileSchema = z.object({
  supplier: z.string().min(1),
  trucks: count,
  accepted: count,
  escalated: count,
  rejected: count,
  hard_contaminant_loads: count,
  declaration_conflicts: count,
  reviews: count,
  overrides: count,
  lab_samples: count,
  avg_moisture_pct: nullableNumber,
  avg_ncv_mj_kg: nullableNumber,
  avg_chlorine_pct: nullableNumber,
  spec_breaches: count,
  deductions_idr: z.number().nonnegative().catch(0),
  breach_fees_idr: z.number().nonnegative().catch(0),
  net_t: z.number().nonnegative().catch(0),
  risk_score: z.number().min(0).max(1).catch(0),
  tier: z.enum(["low", "medium", "high", "new"]).catch("new"),
  /** Why the supplier sits in this tier, one sentence. */
  tier_reason: z.string().nullish().catch(null),
  sampling: z
    .object({ every_n: z.number().int().positive().catch(1), label: z.string().catch("") })
    .nullish()
    .catch(null),
  last_seen_utc: z.string().nullish().catch(null),
});

const contractSchema = z
  .object({
    name: z.string().nullish().catch(null),
    note: z.string().nullish().catch(null),
    base_price_idr_per_t: nullableNumber,
    specs: z.record(z.string(), z.unknown()).catch({}),
  })
  .catchall(z.unknown());

const suppliersSchema = z.object({
  generated_at_utc: z.string().nullish().catch(null),
  contract: contractSchema.nullish().catch(null),
  suppliers: z
    .array(z.unknown())
    .catch([])
    .transform((items) =>
      items.flatMap((raw) => {
        const parsed = supplierProfileSchema.safeParse(raw);
        return parsed.success ? [parsed.data] : [];
      }),
    ),
});

export type SupplierScore = z.infer<typeof supplierProfileSchema>;
export type ContractTerms = z.infer<typeof contractSchema>;
export type Scorecard = z.infer<typeof suppliersSchema>;

/** Untrusted /suppliers JSON → scorecard; null when it is unreadable. */
export function parseScorecard(raw: unknown): Scorecard | null {
  const parsed = suppliersSchema.safeParse(raw);
  return parsed.success ? parsed.data : null;
}

/** Untrusted /contract JSON → terms; null when it is unreadable. */
export function parseContract(raw: unknown): ContractTerms | null {
  const parsed = contractSchema.safeParse(raw);
  return parsed.success ? parsed.data : null;
}

export class ShiftError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ShiftError";
  }
}

export async function fetchShiftReport(
  window?: { since?: string; until?: string },
  signal?: AbortSignal,
): Promise<ShiftReport> {
  const params = new URLSearchParams();
  if (window?.since) params.set("since", window.since);
  if (window?.until) params.set("until", window.until);
  const query = params.toString();

  let resp: Response;
  try {
    resp = await fetch(`/shift-report${query ? `?${query}` : ""}`, {
      headers: { Accept: "application/json" },
      signal,
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    throw new ShiftError("Backend unreachable: is the Lynceus API running?");
  }
  if (resp.status === 422) {
    throw new ShiftError("The shift window is not a valid UTC time range.");
  }
  if (!resp.ok) {
    throw new ShiftError(`The shift report is unavailable (HTTP ${resp.status}).`);
  }
  const parsed = shiftReportSchema.safeParse(await resp.json().catch(() => null));
  if (!parsed.success) {
    throw new ShiftError("The backend returned an unreadable shift report.");
  }
  return parsed.data;
}
