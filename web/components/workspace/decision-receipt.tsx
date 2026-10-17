/**
 * DecisionReceipt: every decision rule in priority order (backend
 * decision.rule_trace), with the ones that fired highlighted and what each
 * did to the verdict. This is the proof that deterministic code decided:
 * the models only supplied the evidence column.
 */

import type { ReceiptRule, RuleEffect } from "@/lib/inspect-api";
import { cn } from "@/lib/utils";

const EFFECT: Record<RuleEffect, { word: string; cls: string }> = {
  reject: { word: "Reject", cls: "text-verdict-red" },
  hold: { word: "Hold", cls: "text-amber" },
  accept: { word: "Accept", cls: "text-verdict-green" },
  none: { word: "No effect", cls: "text-faint" },
};

export function DecisionReceipt({ receipt }: { receipt: ReceiptRule[] }) {
  if (receipt.length === 0) return null;
  const fired = receipt.filter((r) => r.fired).length;
  return (
    <section aria-labelledby="receipt-title" className="flex min-w-0 flex-col gap-2">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 id="receipt-title" className="smallcaps m-0">
          Decision receipt
        </h3>
        <span className="text-[12px] text-faint">
          {fired} of {receipt.length} rules fired · checked in priority order
        </span>
      </div>
      <ol className="m-0 flex list-none flex-col overflow-hidden rounded-[10px] border border-seam p-0">
        {receipt.map((r, i) => {
          const effect = EFFECT[r.effect];
          return (
            <li
              key={r.id}
              className={cn(
                "grid grid-cols-[2rem_minmax(0,1fr)_auto] items-baseline gap-x-2 border-t border-seam px-3 py-2 first:border-t-0",
                r.fired ? "bg-raised" : "bg-panel",
              )}
            >
              <span className="figure text-[12px] text-faint">{String(i + 1).padStart(2, "0")}</span>
              <span className="min-w-0">
                <span className={cn("block text-[13px] leading-snug", r.fired ? "font-semibold text-ink" : "text-muted")}>
                  {r.rule}
                </span>
                {r.evidence ? (
                  <span className={cn("block text-[12px] leading-snug", r.fired ? "text-muted" : "text-faint")}>
                    {r.evidence}
                  </span>
                ) : null}
              </span>
              <span className="text-right text-[12px] font-semibold whitespace-nowrap">
                {r.fired ? (
                  <span className={effect.cls}>Fired · {effect.word}</span>
                ) : (
                  <span className="text-faint">Not fired</span>
                )}
              </span>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
