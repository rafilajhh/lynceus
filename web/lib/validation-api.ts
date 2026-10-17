/**
 * Validation benchmark client: GET /benchmark/latest → the newest committed
 * summary of the live-on-AMD vision-gate benchmark plus its framing sentence,
 * (``replay``) that run re-scored offline under the current rules, and
 * (``hybrid``) that run fused offline with the CPU detector: the shipped gate.
 *
 * Untrusted JSON, parsed once here with zod. Malformed numbers degrade to
 * null (rendered as "—"), never to a made-up zero.
 */

import { z } from "zod";

const count = z.number().int().nonnegative().catch(0);
const metric = z.number().nullish().catch(null);

export const LABELS = ["reject", "escalate", "accept"] as const;
export const COLUMNS = [...LABELS, "error"] as const;

const confusionRow = z
  .object({
    reject: count,
    escalate: count,
    accept: count,
    error: count,
  })
  .catch({ reject: 0, escalate: 0, accept: 0, error: 0 });

const percentiles = z
  .object({ p50: metric, p95: metric })
  .catch({ p50: null, p95: null });

const confusion = z
  .object({ reject: confusionRow, escalate: confusionRow, accept: confusionRow })
  .catch({
    reject: { reject: 0, escalate: 0, accept: 0, error: 0 },
    escalate: { reject: 0, escalate: 0, accept: 0, error: 0 },
    accept: { reject: 0, escalate: 0, accept: 0, error: 0 },
  });

const rejectMetrics = z
  .object({
    precision: metric,
    recall: metric,
    f1: metric,
    tp: count,
    fp: count,
    fn: count,
  })
  .catch({ precision: null, recall: null, f1: null, tp: 0, fp: 0, fn: 0 });

/**
 * Offline re-score of the same run: its recorded model outputs replayed
 * through the current decision rules (no new model calls).
 */
const replaySchema = z.object({
  kind: z.literal("replay"),
  source_run: z.string().nullish().catch(null),
  framing: z.string().min(1),
  disclosure: z.string().nullish().catch(null),
  llm_note: z.string().nullish().catch(null),
  n: count,
  errors: count,
  confusion,
  reject: rejectMetrics,
  changed: z
    .array(
      z.object({
        image: z.string(),
        expected: z.string(),
        recorded: z.string(),
        replay: z.string(),
      }),
    )
    .nullish()
    .catch(null),
});

/**
 * The shipped gate (DETECTOR_ESCALATE_LIGHT=1): the same run's recorded VLM
 * outputs fused offline with the CPU detector through the current rules —
 * the `hybrid_light_escalation_on` variant of a `hybrid_replay` summary.
 * A what-if replay, not a new live measurement.
 */
const hybridRates = z.object({
  clean_accept_rate: metric,
  review_rate: metric,
  metal_reject_recall: metric,
  metal_reject_precision: metric,
  /** Metal photos the gate passed unchecked: the key safety number. */
  metal_accepted: z.number().int().nonnegative().nullish().catch(null),
  escalate_recall: metric,
  gate_accuracy: metric,
});

const hybridVariant = z.object({
  n: count,
  errors: count,
  graded: count,
  gate_correct: z.string().nullish().catch(null),
  confusion,
  metal_reject: z
    .object({ precision: metric, recall: metric, tp: count, fp: count, fn: count })
    .catch({ precision: null, recall: null, tp: 0, fp: 0, fn: 0 }),
});

const hybridSchema = z.object({
  kind: z.literal("hybrid_replay"),
  source_run: z.string().nullish().catch(null),
  framing: z.string().nullish().catch(null),
  /** One-line scope statement ("component validation on public … images"). */
  scope: z.string().nullish().catch(null),
  disclosure: z.string().nullish().catch(null),
  llm_note: z.string().nullish().catch(null),
  vlm_model: z.string().nullish().catch(null),
  detector: z
    .object({
      model: z.string().nullish().catch(null),
      runtime: z.string().nullish().catch(null),
      hard_conf_default: metric,
      light_conf: metric,
    })
    .nullish()
    .catch(null),
  table: z.object({ hybrid_light_escalation_on: hybridRates }),
  variants: z.object({ hybrid_light_escalation_on: hybridVariant }),
});

const summarySchema = z.object({
  framing: z.string().min(1),
  date: z.string().nullish().catch(null),
  n: count,
  manifest_n: count,
  complete: z.boolean().catch(false),
  errors: count,
  confusion,
  reject: rejectMetrics,
  latency_ms: percentiles,
  total_ms: percentiles,
  /** Every raw request attempt (failed ones included); absent in older summaries. */
  attempt_stats: z
    .object({
      attempts: count,
      retried: count,
      total_ms: z.object({ p95: metric, max: metric }).catch({ p95: null, max: null }),
    })
    .nullish()
    .catch(null),
  vlm_model: z.string().nullish().catch(null),
  llm_model: z.string().nullish().catch(null),
  provider: z.string().nullish().catch(null),
  provenance: z.array(z.string()).catch([]),
  per_category: z.record(z.string(), confusionRow).catch({}),
  manual_check_seconds: z.number().positive().nullish().catch(null),
  source_url: z.string().nullish().catch(null),
  /** Absent in older API responses; null when this run has no replay. */
  replay: replaySchema.nullish().catch(null),
  /** Absent in older API responses; null when this run has no hybrid re-score. */
  hybrid: hybridSchema.nullish().catch(null),
});

export type BenchmarkSummary = z.infer<typeof summarySchema>;
export type ReplaySummary = z.infer<typeof replaySchema>;
export type HybridSummary = z.infer<typeof hybridSchema>;
export type Confusion = BenchmarkSummary["confusion"];

export class ValidationError extends Error {
  /** True when no benchmark has been committed (a normal, honest state). */
  readonly missing: boolean;
  constructor(message: string, missing = false) {
    super(message);
    this.name = "ValidationError";
    this.missing = missing;
  }
}

export async function fetchBenchmark(signal?: AbortSignal): Promise<BenchmarkSummary> {
  let resp: Response;
  try {
    resp = await fetch("/benchmark/latest", {
      headers: { Accept: "application/json" },
      signal,
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    throw new ValidationError("Backend unreachable: is the Lynceus API running?");
  }
  if (resp.status === 404) {
    throw new ValidationError("No benchmark run has been committed yet.", true);
  }
  if (!resp.ok) {
    throw new ValidationError(`The benchmark summary is unavailable (HTTP ${resp.status}).`);
  }
  const parsed = summarySchema.safeParse(await resp.json().catch(() => null));
  if (!parsed.success) {
    throw new ValidationError("The backend returned an unreadable benchmark summary.");
  }
  return parsed.data;
}
