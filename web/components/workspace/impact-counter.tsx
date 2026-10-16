"use client";

/**
 * ImpactCounter: impact figure that counts up when a verdict
 * arrives (triggered by runKey, not viewport: the workspace is the
 * stage). USD is the headline figure; the small line keeps the rupiah.
 * Honesty contract: the end value is the backend's real estimate;
 * animation only delays the reveal.
 */

import { useCountUp } from "@/lib/use-count-up";
import { cn } from "@/lib/utils";
import { formatUsd, USD_IDR_RATE } from "@/lib/format";

export function ImpactCounter({
  preventedLossIdr,
  runKey,
  label = "Worst-case loss exposure",
  className,
}: {
  preventedLossIdr: number;
  /** Increment on each new verdict; 0 = no result yet. */
  runKey: number;
  /** What the figure is: the worst-case loss exposure for reject/escalate
      (damage booked as certain), but an accepted load's figure is its
      market value, never an avoided loss. */
  label?: string;
  className?: string;
}) {
  const [display, animating] = useCountUp(preventedLossIdr / USD_IDR_RATE, runKey);

  const usd = new Intl.NumberFormat("en-US", {
    maximumFractionDigits: 0,
  }).format(Math.round(display));

  const idr = new Intl.NumberFormat("id-ID", {
    maximumFractionDigits: 0,
  }).format(preventedLossIdr);

  return (
    <div className={cn("flex flex-col gap-1", className)}>
      <span className="smallcaps">{label}</span>
      {/* a11y (critique, Sam): the rAF count-up would be announced dozens
          of times by aria-live. Hide intermediates from AT; announce the
          final value once via the sr-only live region below. */}
      <span
        aria-hidden={animating || undefined}
        className="figure text-[26px] leading-tight text-ink"
      >
        US$ {usd}
      </span>
      <span aria-live="polite" className="sr-only">
        {animating ? "" : `US$ ${usd}`}
      </span>
      <span className="figure text-[12px] text-muted">≈ Rp {idr}</span>
    </div>
  );
}
