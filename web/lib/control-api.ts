/**
 * Control-room client: GET /control/summary (the whole room in one call),
 * GET /benchmark/amd (inference on AMD, measured) and GET /followups/summary
 * (the ledger's follow-up badges in one call).
 *
 * Untrusted JSON, parsed once here with zod. Every section of the summary
 * parses on its own: a malformed section degrades to null (the panel says it
 * is unavailable) instead of blanking the room. On a backend without
 * /control/summary the room is composed from the per-area routes; what they
 * cannot give (queue, held list, lab trend) stays null.
 */

import { z } from "zod";
import { improvementSchema, supplierProfileSchema } from "./shift-api";

const num = z.number().nullish().catch(null);
const text = z.string().nullish().catch(null);
const strings = z.array(z.string()).catch([]);

/** A list whose malformed items are dropped, never the whole list. */
function tolerant<T extends z.ZodType>(item: T) {
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

const windowSchema = z
  .object({ name: text, since: text, until: text })
  .catch({ name: null, since: null, until: null });

// ---- Kiln intake (GET /kiln/intake, summary.kiln) -------------------------

export const kilnSchema = z.object({
  window: windowSchema,
  trucks_accepted: num,
  accepted_t: num,
  dry_t: num,
  energy_gj: num,
  chlorine_kg: num,
  chlorine_budget_kg: num,
  chlorine_budget_pct: num,
  chlorine_status: z.enum(["ok", "warn", "over"]).nullish().catch(null),
  chlorine_budget_note: text,
  weighted: z
    .object({ moisture_pct: num, ncv_mj_kg: num, chlorine_pct: num })
    .nullish()
    .catch(null),
  spec: z.record(z.string(), z.number()).catch({}),
  vs_spec: z.record(z.string(), z.boolean().nullable()).catch({}),
  methods: z.record(z.string(), z.number()).catch({}),
  /** "Cl from lab on 13 loads, supplier average on 10, contract limit on 7". */
  method_mix: text,
  notes: strings,
});

export type KilnIntake = z.infer<typeof kilnSchema>;

// ---- Carbon (GET /carbon, summary.carbon) ---------------------------------

export const carbonSchema = z.object({
  window: windowSchema,
  af_energy_gj: num,
  biogenic_share: num,
  biogenic_share_note: text,
  coal_co2_displaced_t: num,
  af_fossil_co2_t: num,
  af_biogenic_co2_t: num,
  net_co2_avoided_t: num,
  gcca: z
    .object({
      gross_emissions_from_af_t: num,
      biogenic_memo_item_t: num,
      net_co2_avoided_t: num,
    })
    .nullish()
    .catch(null),
  tsr: z.object({ af_energy_gj: num, note: text }).nullish().catch(null),
  factors: z.record(z.string(), z.number()).catch({}),
  sources: z.record(z.string(), z.string()).catch({}),
  notes: strings,
});

export type Carbon = z.infer<typeof carbonSchema>;

// ---- Alerts (GET /alerts, summary.alerts) ---------------------------------

export type AlertSeverity = "critical" | "warning" | "info";

export const alertSchema = z.object({
  id: z.string(),
  severity: z.enum(["critical", "warning", "info"]).catch("info"),
  kind: z.string().catch("alert"),
  title: z.string(),
  detail: z.string().catch(""),
  at_utc: text,
  record_id: text,
  supplier: text,
});

export type Alert = z.infer<typeof alertSchema>;

// ---- Gate queue and held worklist (summary.queue / summary.held) ----------

export const gateCardSchema = z.object({
  record_id: z.string(),
  truck_id: text,
  supplier: z.string().catch("unknown"),
  decision: z.string().catch("unknown"),
  why: text,
  at_utc: text,
  decision_s: num,
  followups: z
    .object({
      reviewed: z.boolean().catch(false),
      lab: z.boolean().catch(false),
      notice: z.boolean().catch(false),
    })
    .catch({ reviewed: false, lab: false, notice: false }),
  /** The latest supervisor decision, when there is one. */
  resolution: text,
  /** Held cards only: minutes the load has waited for a supervisor. */
  age_min: num,
});

export type GateCard = z.infer<typeof gateCardSchema>;

// ---- Lab trend (summary.lab_trend) -----------------------------------------

export const labPointSchema = z.object({
  record_id: z.string(),
  supplier: z.string().catch("unknown"),
  at_utc: text,
  moisture_pct: num,
  ncv_mj_kg: num,
  chlorine_pct: num,
  in_spec: z.boolean().nullish().catch(null),
  tier: text,
});

export type LabPoint = z.infer<typeof labPointSchema>;

const labTrendSchema = z.object({
  spec: z.record(z.string(), z.number()).catch({}),
  points: tolerant(labPointSchema),
});

export type LabTrend = z.infer<typeof labTrendSchema>;

// ---- Inference on AMD (GET /benchmark/amd .measured, summary.amd) ---------

const latencySchema = z
  .object({ p50: num, p95: num, mean: num, n: num })
  .nullish()
  .catch(null);

const shareSchema = z.object({ count: num, share: num }).nullish().catch(null);

export const amdMeasuredSchema = z.object({
  run_date: text,
  started_at_utc: text,
  finished_at_utc: text,
  provider: text,
  /** "AMD Token Factory": the backend's display name for `provider`. */
  provider_label: text,
  model: text,
  headline: z
    .object({
      read_latency_ms: latencySchema,
      inspection_latency_ms: latencySchema,
      inspections_per_min_concurrent: num,
      tokens_per_inspection: latencySchema,
      parallel_speedup: num,
      read_agreement: z
        .object({ n: num, "3/3": shareSchema, "2/3": shareSchema, split: shareSchema })
        .nullish()
        .catch(null),
      errors: num,
      retries: num,
      calls: num,
    })
    .nullish()
    .catch(null),
  cost: z
    .object({
      token_factory: z.object({ basis: text, note: text }).nullish().catch(null),
    })
    .nullish()
    .catch(null),
  detector_cpu: z
    .object({
      model: text,
      runtime: text,
      cpu: text,
      threads: num,
      inference_ms: latencySchema,
      note: text,
    })
    .nullish()
    .catch(null),
  caveats: strings,
});

export type AmdMeasured = z.infer<typeof amdMeasuredSchema>;

const countOfSchema = z.object({ count: num, n: num }).nullish().catch(null);

export const evalSchema = z.object({
  vlm_model: text,
  detector: text,
  framing: text,
  disclosure: text,
  card: z
    .record(
      z.string(),
      z.object({ shipped: countOfSchema, vlm_only: countOfSchema }).catch({ shipped: null, vlm_only: null }),
    )
    .catch({}),
  definitions: z.record(z.string(), z.string()).catch({}),
  fusion_lift: tolerant(
    z.object({
      variant: z.string(),
      label: z.string().catch(""),
      note: text,
      metal_let_through: countOfSchema,
      metal_rejected: countOfSchema,
      clean_passed: countOfSchema,
      held_for_human: countOfSchema,
      held_by_class: z.record(z.string(), countOfSchema).catch({}),
    }),
  ),
});

export type EvalCard = z.infer<typeof evalSchema>;
export type FusionVariant = EvalCard["fusion_lift"][number];

const liveSchema = z.object({
  count: num,
  window: num,
  vlm_latency_ms: latencySchema,
  detector_latency_ms: latencySchema,
  note: text,
});

export type AmdLive = z.infer<typeof liveSchema>;

const benchmarkAmdSchema = z.object({
  measured: amdMeasuredSchema.nullish().catch(null),
  live: liveSchema.nullish().catch(null),
  eval: evalSchema.nullish().catch(null),
});

export type BenchmarkAmd = z.infer<typeof benchmarkAmdSchema>;

// ---- The summary -------------------------------------------------------------

const shiftSchema = improvementSchema.extend({ window: windowSchema });

export type ShiftNow = z.infer<typeof shiftSchema>;

const summarySchema = z.object({
  generated_at_utc: text,
  shift: shiftSchema.nullish().catch(null),
  kiln: kilnSchema.nullish().catch(null),
  carbon: carbonSchema.nullish().catch(null),
  alerts: tolerant(alertSchema).nullish().catch(null),
  queue: tolerant(gateCardSchema).nullish().catch(null),
  held: tolerant(gateCardSchema).nullish().catch(null),
  suppliers: tolerant(supplierProfileSchema).nullish().catch(null),
  lab_trend: labTrendSchema.nullish().catch(null),
  amd: amdMeasuredSchema.nullish().catch(null),
  contract_note: text,
});

export type ControlSummary = z.infer<typeof summarySchema> & {
  /** "summary": one call; "composed": per-area routes on an older backend. */
  source: "summary" | "composed";
};

export class ControlError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ControlError";
    this.status = status;
  }
}

async function getJSON(path: string, signal?: AbortSignal): Promise<unknown> {
  let res: Response;
  try {
    res = await fetch(path, { headers: { Accept: "application/json" }, cache: "no-store", signal });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    throw new ControlError("Backend unreachable: is the Lynceus API running?", 0);
  }
  if (!res.ok) throw new ControlError(`${path} is unavailable (HTTP ${res.status}).`, res.status);
  return res.json().catch(() => {
    throw new ControlError(`${path} returned unreadable JSON.`, res.status);
  });
}

/** A route that may not exist on this backend: null instead of an error. */
async function optional(path: string, signal?: AbortSignal): Promise<unknown> {
  try {
    return await getJSON(path, signal);
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    return null;
  }
}

/** Older backend: assemble what the per-area routes give. */
async function composeSummary(signal?: AbortSignal): Promise<ControlSummary> {
  const [report, kiln, carbon, alerts, suppliers, bench] = await Promise.all([
    optional("/shift-report", signal),
    optional("/kiln/intake?window=shift", signal),
    optional("/carbon?window=shift", signal),
    optional("/alerts", signal),
    optional("/suppliers", signal),
    optional("/benchmark/amd", signal),
  ]);
  if ([report, kiln, carbon, alerts, suppliers, bench].every((part) => part === null)) {
    throw new ControlError("Backend unreachable: is the Lynceus API running?", 0);
  }
  const pick = (raw: unknown, key: string) =>
    raw && typeof raw === "object" ? (raw as Record<string, unknown>)[key] : undefined;
  const improvement = pick(report, "improvement");
  const parsed = summarySchema.parse({
    generated_at_utc: pick(alerts, "generated_at_utc") ?? null,
    shift: improvement ? { ...(improvement as object), window: pick(report, "window") } : null,
    kiln,
    carbon,
    alerts: pick(alerts, "alerts") ?? null,
    queue: null,
    held: null,
    suppliers: pick(suppliers, "suppliers") ?? null,
    lab_trend: null,
    amd: pick(bench, "measured") ?? null,
    contract_note: pick(pick(suppliers, "contract"), "note") ?? null,
  });
  return { ...parsed, source: "composed" };
}

export async function fetchControlSummary(signal?: AbortSignal): Promise<ControlSummary> {
  let raw: unknown;
  try {
    raw = await getJSON("/control/summary", signal);
  } catch (err) {
    if (err instanceof ControlError && err.status === 404) return composeSummary(signal);
    throw err;
  }
  const parsed = summarySchema.safeParse(raw);
  if (!parsed.success) throw new ControlError("The backend returned an unreadable control summary.", 200);
  return { ...parsed.data, source: "summary" };
}

export async function fetchBenchmarkAmd(signal?: AbortSignal): Promise<BenchmarkAmd> {
  const parsed = benchmarkAmdSchema.safeParse(await getJSON("/benchmark/amd", signal));
  if (!parsed.success) throw new ControlError("The backend returned an unreadable AMD benchmark.", 200);
  return parsed.data;
}

// ---- Follow-up badges (GET /followups/summary) ----------------------------

const followupStateSchema = z.object({
  kinds: strings,
  count: z.number().int().nonnegative().catch(0),
  chain_ok: z.boolean().nullish().catch(null),
  latest_resolution: text,
});

export type FollowupState = z.infer<typeof followupStateSchema>;

/** Record id → its follow-ups at a glance. A malformed entry is dropped. */
export async function fetchFollowupSummary(signal?: AbortSignal): Promise<Map<string, FollowupState>> {
  const raw = await getJSON("/followups/summary", signal);
  const records =
    raw && typeof raw === "object" ? (raw as Record<string, unknown>).records : undefined;
  const out = new Map<string, FollowupState>();
  if (!records || typeof records !== "object") return out;
  for (const [id, value] of Object.entries(records as Record<string, unknown>)) {
    const parsed = followupStateSchema.safeParse(value);
    if (parsed.success) out.set(id, parsed.data);
  }
  return out;
}
