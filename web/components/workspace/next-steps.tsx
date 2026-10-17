/**
 * NextSteps: what the gate operator does now, in order. Every step cites
 * the clause of the reference gate SOP it comes from (deterministic rule
 * table in backend actions.py: no AI writes these).
 *
 * variant "plain" (default): eyebrow heading + list, for embedding.
 * variant "card": the redesign's emphasised card (dark 1.5px border,
 * title + sub head), with optional footer children.
 */

import { useId, type ReactNode } from "react";
import type { NextStep } from "@/lib/api";
import { cn } from "@/lib/utils";

function StepList({ steps, emptyText }: { steps: NextStep[]; emptyText: string }) {
  if (steps.length === 0) {
    return (
      <p className="m-0 rounded-[10px] border border-dashed border-line-strong px-3.5 py-3 text-[13px] text-fg-muted">
        {emptyText}
      </p>
    );
  }
  return (
    <ol className="m-0 flex list-none flex-col divide-y divide-line p-0">
      {steps.map((step, i) => (
        <li key={`${step.sop_ref}-${i}`} className="flex items-start gap-3 py-3">
          <span
            aria-hidden="true"
            className={cn(
              "flex h-6 w-6 shrink-0 items-center justify-center rounded-full font-mono text-[12px]",
              i === 0 ? "bg-fg text-white" : "bg-surface-muted text-fg",
            )}
          >
            {step.order || i + 1}
          </span>
          <span className="flex min-w-0 flex-1 flex-col items-start gap-1.5">
            <span className="text-[14px] leading-5 text-fg">{step.text}</span>
            {step.sop_ref ? (
              <span
                className="rounded-full border border-line-strong px-2 py-px font-mono text-[11px] font-medium text-fg-muted"
                title={`Reference gate SOP clause ${step.sop_ref}`}
              >
                {step.sop_ref}
              </span>
            ) : null}
          </span>
        </li>
      ))}
    </ol>
  );
}

export function NextSteps({
  steps,
  emptyText = "No next steps recorded for this inspection.",
  variant = "plain",
  children,
  className,
}: {
  steps: NextStep[];
  /** Shown when the list is empty (older records carry no steps). */
  emptyText?: string;
  variant?: "plain" | "card";
  /** Card variant only: footer under the list (actions). */
  children?: ReactNode;
  className?: string;
}) {
  const headingId = useId();

  if (variant === "card") {
    return (
      <section
        aria-labelledby={headingId}
        className={cn(
          "overflow-hidden rounded-[14px] border-[1.5px] border-fg bg-surface shadow-card",
          className,
        )}
      >
        <div className="flex flex-col gap-0.5 border-b border-line px-5 py-4">
          <h2 id={headingId} className="m-0 font-display text-[17px] font-medium text-fg">
            Next steps
          </h2>
          <p className="m-0 text-[12px] text-fg-muted">Follow the gate SOP before releasing the truck</p>
        </div>
        <div className="px-5 pt-2 pb-4">
          <StepList steps={steps} emptyText={emptyText} />
        </div>
        {children ? <div className="flex gap-2 px-5 pb-5">{children}</div> : null}
      </section>
    );
  }

  return (
    <section aria-labelledby={headingId} className={cn("flex flex-col gap-2", className)}>
      <h3 id={headingId} className="eyebrow m-0">
        Next steps
      </h3>
      {steps.length === 0 ? (
        <StepList steps={steps} emptyText={emptyText} />
      ) : (
        <div className="rounded-[10px] border border-line-strong px-3.5 py-1">
          <StepList steps={steps} emptyText={emptyText} />
        </div>
      )}
    </section>
  );
}
