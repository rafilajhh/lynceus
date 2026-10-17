"use client";

/**
 * GateHeader: the first thing a visitor reads at /app. One sentence says
 * what this gate does; the amber button plays one truck end to end; the
 * presets load a truck without running it.
 */

import { Button } from "@/components/ui/button";
import { PRESETS, type PresetKey } from "@/lib/demo-cases";
import { cn } from "@/lib/utils";
import { IconPlay } from "./gate-icons";

export function GateHeader({
  busyLabel,
  activePreset,
  disabled,
  onRunDemo,
  onPreset,
  onClear,
}: {
  /** What the one-click run is doing now; null when idle. */
  busyLabel: string | null;
  activePreset: PresetKey | null;
  /** An inspection or a preset load is in flight. */
  disabled: boolean;
  onRunDemo: () => void;
  onPreset: (key: PresetKey) => void;
  onClear: () => void;
}) {
  return (
    <section
      aria-labelledby="gate-title"
      className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between lg:gap-8"
    >
      <div className="flex max-w-[68ch] flex-col gap-1.5">
        <h1 id="gate-title" className="m-0 text-[22px] leading-tight font-semibold tracking-[-0.01em] text-ink">
          RDF reception gate · Weighbridge A
        </h1>
        <p className="m-0 text-[14.5px] leading-relaxed text-muted">
          Lynceus reads the supplier&rsquo;s waybill, inspects the load photo and checks the
          weighbridge, then tells the operator to accept, hold or reject the truck before it
          tips, with the SOP steps to follow. Every decision is sealed as a tamper-evident record.
        </p>
      </div>

      <div className="flex shrink-0 flex-col gap-2.5 lg:items-end">
        <Button
          type="button"
          variant="primary"
          size="lg"
          onClick={onRunDemo}
          disabled={disabled}
          aria-describedby="run-demo-caption"
          className="min-w-[230px] justify-center"
        >
          <IconPlay size={15} />
          {busyLabel ?? "Run the demo truck"}
        </Button>
        <p id="run-demo-caption" className="m-0 text-[12px] text-faint lg:text-right">
          One click: waybill read, weighing, AI inspection, verdict.
        </p>
        <div
          role="group"
          aria-label="Load a preset truck without running it"
          className="flex flex-wrap items-center gap-1.5"
        >
          <span className="mr-1 text-[12px] font-semibold text-muted">Or load a truck:</span>
          {PRESETS.map((p) => (
            <Button
              key={p.key}
              type="button"
              size="sm"
              onClick={() => onPreset(p.key)}
              disabled={disabled}
              aria-pressed={activePreset === p.key}
              title={p.hint}
              className={cn(
                "text-[12.5px]",
                activePreset === p.key && "border-amber bg-amber-soft",
              )}
            >
              {p.label}
            </Button>
          ))}
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={onClear}
            disabled={disabled}
            className="text-[12.5px]"
          >
            Clear gate
          </Button>
        </div>
      </div>
    </section>
  );
}
