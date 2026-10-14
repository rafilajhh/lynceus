/**
 * NextSteps: what the gate operator does now, in order. Every step cites
 * the clause of the reference gate SOP it comes from (deterministic rule
 * table in backend actions.py: no AI writes these).
 */

import { useId } from "react";
import type { NextStep } from "@/lib/api";
import { cn } from "@/lib/utils";

export function NextSteps({
  steps,
  emptyText = "No next steps recorded for this inspection.",
  className,
}: {
  steps: NextStep[];
  /** Shown when the list is empty (older records carry no steps). */
  emptyText?: string;
  className?: string;
}) {
  const headingId = useId();

  return (
    <section aria-labelledby={headingId} className={cn("flex flex-col gap-2", className)}>
      <h3 id={headingId} className="smallcaps m-0">
        Next steps
      </h3>
      {steps.length === 0 ? (
        <p className="m-0 rounded-[10px] border border-dashed border-seam-strong px-3.5 py-3 text-[13px] text-muted">
          {emptyText}
        </p>
      ) : (
        <ol className="m-0 flex list-none flex-col divide-y divide-seam rounded-[10px] border border-seam p-0">
          {steps.map((step, i) => (
            <li key={`${step.sop_ref}-${i}`} className="flex items-start gap-3 px-3.5 py-3">
              <span
                aria-hidden="true"
                className="figure flex h-6 w-6 shrink-0 items-center justify-center rounded-[6px] border border-seam-strong bg-raised text-[12px] font-semibold text-ink"
              >
                {step.order || i + 1}
              </span>
              <span className="flex min-w-0 flex-1 flex-col gap-1 sm:flex-row sm:items-baseline sm:justify-between sm:gap-4">
                <span className="text-[14px] leading-snug text-ink">{step.text}</span>
                {step.sop_ref ? (
                  <span
                    className="figure shrink-0 text-[12px] text-muted"
                    title={`Reference gate SOP clause ${step.sop_ref}`}
                  >
                    {step.sop_ref}
                  </span>
                ) : null}
              </span>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
