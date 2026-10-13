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
  prevented_loss_idr: z.number().nonnegative().catch(0),
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
