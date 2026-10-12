"use client";

/**
 * ImpactCounter — prevented-loss figure that counts up when a verdict
 * arrives (triggered by runKey, not viewport: the workspace is the
 * stage). "Rp 798.000.000" Indonesian grouping + small USD figure.
 * Honesty contract: the end value is the backend's real estimate;
 * animation only delays the reveal.
 */

import { useCountUp } from "@/lib/use-count-up";
import { cn } from "@/lib/utils";

export function ImpactCounter({
  preventedLossIdr,
  preventedLossUsd,
  runKey,
  className,
}: {
  preventedLossIdr: number;
  preventedLossUsd: number;
  /** Increment on each new verdict; 0 = no result yet. */
  runKey: number;
  className?: string;
}) {
  const [display] = useCountUp(preventedLossIdr, runKey);

  if (runKey === 0) {
    return (
      <div className={cn("flex flex-col gap-1", className)}>
        <span className="smallcaps">Prevented loss</span>
        <span className="figure text-[26px] leading-tight text-faint">
          Rp —
        </span>
        <span className="text-[13px] text-muted">
          Awaiting first verdict
        </span>
      </div>
    );
  }

  const idr = new Intl.NumberFormat("id-ID", {
    maximumFractionDigits: 0,
  }).format(Math.round(display));

  return (
    <div className={cn("flex flex-col gap-1", className)}>
      <span className="smallcaps">Prevented loss</span>
      <span className="figure text-[26px] leading-tight text-ink" aria-live="polite">
        Rp {idr}
      </span>
      <span className="figure text-[12px] text-muted">
        ≈ US$ {new Intl.NumberFormat("en-US", {
          maximumFractionDigits: 0,
        }).format(preventedLossUsd)}
      </span>
    </div>
  );
}
