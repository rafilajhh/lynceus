/**
 * VerdictBanner: the decision word the operator acts on, then the one
 * sentence that says why. The banner stays graphite until the checks
 * interlock has lit (DESIGN.md signature move).
 */

import type { InspectResponse } from "@/lib/inspect-api";
import { cn } from "@/lib/utils";
import { formatSecs } from "./units";

export type VerdictTone = "accept" | "escalate" | "reject" | "refuse" | "unknown";

export function verdictTone(decision: string | undefined): VerdictTone {
  const d = String(decision || "").toLowerCase();
  if (d.startsWith("accept")) return "accept";
  if (d.startsWith("reject")) return "reject";
  if (d.startsWith("escalate")) return "escalate";
  if (d.startsWith("refuse")) return "refuse";
  return "unknown";
}

const STYLE: Record<VerdictTone, { label: string; cls: string }> = {
  accept: { label: "ACCEPT", cls: "bg-green-dim border-verdict-green text-verdict-green" },
  escalate: { label: "HOLD FOR REVIEW", cls: "bg-amber-dim border-amber text-amber" },
  reject: { label: "REJECT · DO NOT TIP", cls: "bg-red-dim border-verdict-red text-verdict-red" },
  refuse: { label: "REFUSED · INPUT MISSING", cls: "bg-amber-dim border-amber text-amber" },
  unknown: { label: "NO VERDICT", cls: "bg-raised border-seam-strong text-muted" },
};

/** When the backend sent no `why`: the old directive headline. */
function fallbackWhy(tone: VerdictTone, data: InspectResponse): string {
  if (tone === "reject") return "Rejected: do not tip this load into the RDF line.";
  if (tone === "escalate") return "Held: a supervisor checks this load before it tips.";
  if (tone === "refuse") return "A mandatory input is missing, so no verdict was issued.";
  return data.engine_outputs?.recommendation?.headline || data.headline || "Inspection completed.";
}

export function VerdictBanner({
  tone,
  data,
  lit,
  recordId,
  elapsedMs,
}: {
  tone: VerdictTone;
  data: InspectResponse;
  lit: boolean;
  recordId: string | null;
  elapsedMs: number | null;
}) {
  const style = STYLE[tone];
  const why = data.why ?? fallbackWhy(tone, data);
  return (
    <div className="flex flex-col gap-3">
      <div
        className={cn(
          "flex flex-wrap items-center justify-between gap-x-4 gap-y-1 rounded-[10px] border px-4 py-3 transition-[background-color,border-color,color] duration-200",
          lit ? style.cls : "border-seam bg-raised text-faint",
        )}
      >
        <span className="text-[20px] leading-tight font-bold tracking-[3px] sm:tracking-[4px]">
          {lit ? style.label : "— — —"}
        </span>
        <span className="figure text-[12px] text-muted">
          {[recordId, elapsedMs !== null ? `decided in ${formatSecs(elapsedMs / 1000)}` : null]
            .filter(Boolean)
            .join(" · ")}
        </span>
      </div>
      <p
        className={cn(
          "m-0 max-w-[72ch] text-[19px] leading-snug font-semibold text-balance text-ink transition-opacity duration-200 sm:text-[21px]",
          lit ? "opacity-100" : "opacity-0",
        )}
      >
        {why}
      </p>
      {/* One announcement once lit: the word and the reason together. */}
      <p className="sr-only" role="status" aria-live="polite">
        {lit ? `Verdict: ${style.label}. ${why}` : ""}
      </p>
    </div>
  );
}
