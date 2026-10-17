/**
 * Ops-loop client: the follow-ups sealed after a verdict (supervisor
 * resolution, lab result, supplier notice), the supplier scorecard and the
 * example supply contract. Shared by the gate (/app) and the ops surfaces
 * (/shift, /inspections). Contract: .omc/plans/product-win.md §5 and §8.
 */

import type { Decision } from "./api";

// ---- Operator checks (GET /inspections/{id}, POST /inspect) --------------

export type CheckStatus = "pass" | "warn" | "fail" | "info" | "skipped";

export interface Check {
  key: "vision" | "second_look" | "waybill_read" | "declaration" | "weight" | "supplier" | string;
  label: string;
  status: CheckStatus;
  /** Short finding, ≤ 28 chars, e.g. "Metal · 0.85". */
  finding: string;
  /** One plain sentence. */
  detail: string;
  /** The audit gate this check reads, when there is one. */
  gate: string | null;
}

const CHECK_STATUSES: readonly CheckStatus[] = ["pass", "warn", "fail", "info", "skipped"];

/** Untrusted JSON → checks; malformed entries are dropped, never thrown. */
export function parseChecks(raw: unknown): Check[] {
  if (!Array.isArray(raw)) return [];
  return raw.flatMap((item): Check[] => {
    if (!item || typeof item !== "object") return [];
    const c = item as Record<string, unknown>;
    if (typeof c.key !== "string" || typeof c.label !== "string") return [];
    const status = CHECK_STATUSES.includes(c.status as CheckStatus)
      ? (c.status as CheckStatus)
      : "skipped";
    return [
      {
        key: c.key,
        label: c.label,
        status,
        finding: typeof c.finding === "string" ? c.finding : "",
        detail: typeof c.detail === "string" ? c.detail : "",
        gate: typeof c.gate === "string" ? c.gate : null,
      },
    ];
  });
}

export interface Sampling {
  sample_this_truck: boolean;
  tier: SupplierTier;
  label: string;
  reason: string;
}

// ---- Follow-ups ----------------------------------------------------------

export type ResolutionDecision = "accept" | "sort_then_accept" | "reject" | "retake";

export interface ResolutionBody {
  decision: ResolutionDecision;
  note: string;
  ai_decision: Decision | string;
  /** null when the AI held the truck (the human made the call). */
  agrees_with_ai: boolean | null;
  hand_check_minutes: number | null;
}

export interface ContractBreach {
  param: string;
  value: number;
  limit: number;
  effect: string;
}

export interface ContractEval {
  spec: Record<string, number>;
  breaches: ContractBreach[];
  base_price_idr_per_t: number;
  adjusted_price_idr_per_t: number;
  adjustment_pct: number;
  net_t: number;
  payable_idr: number;
  deduction_idr: number;
}

export interface LabBody {
  sample_id: string;
  moisture_pct: number;
  ncv_mj_kg: number;
  chlorine_pct: number;
  ash_pct: number | null;
  lab: string;
  sampled_at_utc: string;
  contract_eval: ContractEval;
}

export interface NoticeBody {
  to: string;
  subject: string;
  text: string;
  facts: string[];
  model: string | null;
  provider: string | null;
  provenance: "live" | "template" | string;
  latency_ms: number | null;
}

interface FollowupBase {
  format: number;
  record_id: string;
  seq: number;
  created_at_utc: string;
  actor: string;
  parent_record_digest: string;
  previous_digest: string | null;
  digest: string;
}

export type Followup =
  | (FollowupBase & { kind: "resolution"; body: ResolutionBody })
  | (FollowupBase & { kind: "lab_result"; body: LabBody })
  | (FollowupBase & { kind: "notice"; body: NoticeBody });

export interface FollowupsResponse {
  record_id: string;
  followups: Followup[];
  chain: { ok: boolean; problems: string[] };
}

// ---- Suppliers and contract ---------------------------------------------

export type SupplierTier = "low" | "medium" | "high" | "new";

export interface SupplierProfile {
  supplier: string;
  trucks: number;
  accepted: number;
  escalated: number;
  rejected: number;
  hard_contaminant_loads: number;
  declaration_conflicts: number;
  reviews: number;
  overrides: number;
  lab_samples: number;
  avg_moisture_pct: number | null;
  avg_ncv_mj_kg: number | null;
  avg_chlorine_pct: number | null;
  spec_breaches: number;
  deductions_idr: number;
  breach_fees_idr: number;
  net_t: number;
  risk_score: number;
  tier: SupplierTier;
  sampling: { every_n: number; label: string };
  last_seen_utc: string | null;
}

export interface Contract {
  name: string;
  note?: string;
  base_price_idr_per_t: number;
  specs: Record<string, number>;
  [key: string]: unknown;
}

export interface SuppliersResponse {
  generated_at_utc: string;
  contract: Contract;
  suppliers: SupplierProfile[];
}

// ---- Transport -------------------------------------------------------------

export class OpsError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "OpsError";
    this.status = status;
  }
}

async function request<T>(method: "GET" | "POST", path: string, body?: unknown): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, {
      method,
      headers: {
        Accept: "application/json",
        ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
      cache: "no-store",
    });
  } catch {
    throw new OpsError("Backend unreachable: is the Lynceus API running?", 0);
  }
  if (!res.ok) {
    let message = `${method} ${path} failed (HTTP ${res.status})`;
    try {
      const data = (await res.json()) as { detail?: unknown };
      const detail = data?.detail;
      if (typeof detail === "string") message = detail;
      else if (detail && typeof detail === "object" && "message" in detail) {
        const m = (detail as { message?: unknown }).message;
        if (typeof m === "string" && m) message = m;
      }
    } catch {
      // Non-JSON error body: keep the status message.
    }
    throw new OpsError(message, res.status);
  }
  return (await res.json()) as T;
}

const recordPath = (recordId: string) => `/inspections/${encodeURIComponent(recordId)}`;

export function fetchFollowups(recordId: string): Promise<FollowupsResponse> {
  return request("GET", `${recordPath(recordId)}/followups`);
}

export function postResolution(
  recordId: string,
  body: { decision: ResolutionDecision; note?: string; hand_check_minutes?: number | null },
): Promise<Followup> {
  return request("POST", `${recordPath(recordId)}/resolution`, body);
}

export function postLabResult(
  recordId: string,
  body: {
    moisture_pct: number;
    ncv_mj_kg: number;
    chlorine_pct: number;
    ash_pct?: number | null;
    sample_id?: string;
    lab?: string;
  },
): Promise<Followup> {
  return request("POST", `${recordPath(recordId)}/lab`, body);
}

export function requestNotice(recordId: string): Promise<Followup> {
  return request("POST", `${recordPath(recordId)}/notice`, {});
}

export function fetchSuppliers(): Promise<SuppliersResponse> {
  return request("GET", "/suppliers");
}

export function fetchContract(): Promise<Contract> {
  return request("GET", "/contract");
}
