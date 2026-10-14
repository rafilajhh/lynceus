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

/** Risk rule, mirrored from backend/src/lynceus/shift.py for the legend. */
export const FLAG_MIN_TRUCKS = 3;
export const FLAG_MIN_RISK = 0.34;

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
