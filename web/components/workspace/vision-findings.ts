/**
 * What the verdict's checks and table read from the vision answer, and the
 * checks themselves on an older backend: derived from its gates, with the
 * two corrections the gates cannot make on their own (a hard item the
 * camera saw fails the photo check; a detector that missed it is "info").
 */

import type { InspectResponse, VisionVote } from "@/lib/inspect-api";
import type { Check, CheckStatus } from "@/lib/ops-api";

const GATE_CHECKS: { gate: string; key: string; label: string }[] = [
  { gate: "vlm_confidence", key: "vision", label: "Load photo" },
  { gate: "detector_second_opinion", key: "second_look", label: "Second look" },
  { gate: "ocr_confidence", key: "waybill_read", label: "Waybill read" },
  { gate: "manifest_crosscheck", key: "declaration", label: "Waybill vs load" },
  { gate: "weight_plausibility", key: "weight", label: "Weighbridge" },
];

function detectedList(data: InspectResponse | null, key: string): string[] {
  const detected = data?.ai_outputs.vlm?.detected as Record<string, unknown> | null | undefined;
  const list = detected?.[key];
  return Array.isArray(list) ? list.filter((h): h is string => typeof h === "string") : [];
}

/** Hard contaminants the vision model reported (merged frames). */
export function visionHard(data: InspectResponse | null): string[] {
  return detectedList(data, "hard_contaminants");
}

export function visionLight(data: InspectResponse | null): string[] {
  return detectedList(data, "light_contaminants");
}

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1).replace(/_/g, " ");

/** Checks from the response, or derived from its gates on an older backend. */
export function checksOf(data: InspectResponse): Check[] {
  if (data.checks.length > 0) return data.checks;
  const gates = (data.gates ?? {}) as Record<string, unknown>;
  const hard = visionHard(data);
  const conf = data.ai_outputs.vlm?.confidence;
  const out: Check[] = [];
  for (const g of GATE_CHECKS) {
    const raw = gates[g.gate];
    if (raw === undefined || raw === null) continue;
    const state = typeof raw === "object" ? String((raw as { state?: unknown }).state ?? "") : String(raw);
    const reason = typeof raw === "object" ? String((raw as { reason?: unknown }).reason ?? "") : "";
    let status: CheckStatus =
      state === "passed" ? "pass" : state === "failed" ? "fail" : state === "not_run" ? "skipped" : "info";
    let finding = status === "pass" ? "Passed" : status === "fail" ? "Failed" : status === "skipped" ? "Not run" : "Not evaluated";
    if (g.key === "vision" && hard.length > 0) {
      status = "fail";
      finding = `${hard.map(cap).join(", ")}${typeof conf === "number" ? ` · ${conf.toFixed(2)}` : ""}`;
    } else if (g.key === "vision" && status === "pass") {
      finding = "Nothing hard seen";
    }
    if (g.key === "second_look" && hard.length > 0 && (data.ai_outputs.detector?.hard_contaminants.length ?? 0) === 0) {
      status = "info";
      finding = "Did not see it";
    }
    out.push({ key: g.key, label: g.label, status, finding: finding.slice(0, 28), detail: reason, gate: g.gate });
  }
  return out;
}

export interface VoteAgreement {
  /** Reads whose answer matched the majority (hard items seen or not). */
  agree: number;
  total: number;
  /** "Reads 3/3 agree" / "Reads split 1/3: metal". */
  label: string;
  split: boolean;
  /** Early majority: how many reads decided, and what happened to the last one. */
  early: { votesUsed: number; thirdRead: string | null } | null;
}

/** How the vision reads voted; null when the backend sent no votes. */
export function voteAgreement(data: InspectResponse): VoteAgreement | null {
  const votes: VisionVote[] = data.votes;
  if (votes.length === 0) return null;
  const sawHard = votes.filter((v) => v.hard.length > 0);
  const total = votes.length;
  const minority = Math.min(sawHard.length, total - sawHard.length);
  const split = minority > 0;
  // "split 1/3: metal" reads as "1 of 3 reads saw metal".
  const items = [...new Set(sawHard.flatMap((v) => v.hard))];
  const label =
    total === 1
      ? "One read (no vote)"
      : split
        ? `Reads split ${sawHard.length}/${total}${items.length ? `: ${items.map((s) => s.replace(/_/g, " ")).join(", ")}` : ""}`
        : `Reads ${total}/${total} agree`;
  return { agree: total - minority, total, label, split, early: earlyMajority(data) };
}

function earlyMajority(data: InspectResponse): VoteAgreement["early"] {
  const vlm = (data.ai_outputs.vlm ?? {}) as Record<string, unknown>;
  const raw = (vlm.early_majority ?? vlm) as Record<string, unknown>;
  const used = raw?.votes_used;
  if (typeof used !== "number") return null;
  return { votesUsed: used, thirdRead: typeof raw.third_read === "string" ? raw.third_read : null };
}
