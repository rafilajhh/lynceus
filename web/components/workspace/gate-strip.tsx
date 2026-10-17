"use client";

/**
 * GateStrip: the six interlock checks (VLM, Manifest, X-check, Gas,
 * Weight, YOLO) as the check row under the verdict banner. Each cell
 * names its gate and what it checks; the icons light one by one with a
 * 120ms stagger when a verdict arrives, like a machine startup
 * interlock. Green check = passed, red cross = failed, dash = not run /
 * N/A; dashed circles pulse while the inspection evaluates.
 *
 * The verdict banner may only light after every gate resolves: the
 * strip calls onAllResolved after the last stagger step.
 */

import { useEffect, useState } from "react";
import { CircleCheck, CircleDashed, CircleMinus, CircleX } from "lucide-react";
import { GATE_ORDER } from "@/lib/demo-cases";
import type { GateResult } from "@/lib/api";
import { cn } from "@/lib/utils";

export type GatePhase = "idle" | "evaluating" | "resolved";

export interface GateDisplay {
  key: string;
  label: string;
  state: "passed" | "failed" | "not_run" | "not_evaluated";
  reason: string | null;
}

/** Normalize the API's gates record (object or bare string states). */
export function normalizeGates(
  gates: InspectGates | undefined,
): GateDisplay[] {
  const map = new Map<string, GateDisplay>();
  for (const g of GATE_ORDER) {
    map.set(g.key, {
      key: g.key,
      label: g.label,
      state: "not_run",
      reason: null,
    });
  }
  if (!gates) return [...map.values()];
  for (const [key, raw] of Object.entries(gates)) {
    const display = map.get(key);
    if (!display) continue; // unknown gate key: ignore
    const state =
      typeof raw === "object" && raw !== null
        ? String((raw as GateResult).state ?? "not_evaluated")
        : String(raw ?? "not_run");
    // not_evaluated stays its own neutral N/A: a gate that ran but cannot
    // pass or fail (e.g. a detector-only run that flagged nothing) is
    // neither a green clearance nor "not run".
    display.state =
      state === "passed" || state === "failed" || state === "not_evaluated"
        ? state
        : "not_run";
    display.reason =
      typeof raw === "object" && raw !== null
        ? ((raw as GateResult).reason ?? null)
        : null;
  }
  return [...map.values()];
}

type InspectGates = Record<string, GateResult | GateResult["state"]>;


/** Operator names + one-line meaning of each gate (the redesign's check row
    replaces the old legend paragraph: every cell explains itself). */
const GATE_COPY: Record<string, { name: string; desc: string }> = {
  vlm_confidence: { name: "VLM", desc: "Visual contaminants" },
  ocr_confidence: { name: "Manifest", desc: "Manual waybill text" },
  manifest_crosscheck: { name: "X-check", desc: "Waybill vs observed load" },
  gas_plausibility: { name: "Gas", desc: "Gate sensors" },
  weight_plausibility: { name: "Weight", desc: "Weighbridge vs declared" },
  detector_second_opinion: { name: "YOLO", desc: "CPU detector, 2nd opinion" },
};

const STATE_LABEL: Record<GateDisplay["state"], string> = {
  passed: "PASSED",
  failed: "FAILED",
  not_run: "NOT RUN",
  not_evaluated: "N/A",
};

function GateIcon({
  state,
  lit,
  evaluating,
  delayMs,
}: {
  state: GateDisplay["state"];
  lit: boolean;
  evaluating: boolean;
  delayMs: number;
}) {
  const cls = "h-3.5 w-3.5 shrink-0 transition-colors duration-150";
  if (!lit) {
    return (
      <CircleDashed
        aria-hidden="true"
        className={cn(cls, evaluating ? "animate-[gate-pulse_1.1s_ease-in-out_infinite] text-brand" : "text-fg-subtle")}
        style={evaluating ? { animationDelay: `${delayMs}ms` } : undefined}
      />
    );
  }
  if (state === "passed") return <CircleCheck aria-hidden="true" className={cn(cls, "text-success")} />;
  if (state === "failed") return <CircleX aria-hidden="true" className={cn(cls, "text-danger")} />;
  return <CircleMinus aria-hidden="true" className={cn(cls, "text-fg-subtle")} />;
}

export function GateStrip({
  gates,
  phase,
  onAllResolved,
  staggerMs = 120,
  className,
}: {
  gates: GateDisplay[];
  /** idle = pre-submit; evaluating = pulsing; resolved = interlock run */
  phase: GatePhase;
  onAllResolved?: () => void;
  staggerMs?: number;
  className?: string;
}) {
  const [litCount, setLitCount] = useState(0);
  const gateCount = gates.length;

  useEffect(() => {
    if (phase !== "resolved") {
      setLitCount(0);
      return;
    }
    // Snap the lights on one by one, 120ms apart: the interlock.
    const timers: ReturnType<typeof setTimeout>[] = [];
    for (let i = 0; i < gateCount; i += 1) {
      timers.push(setTimeout(() => setLitCount(i + 1), i * staggerMs));
    }
    const done = setTimeout(() => onAllResolved?.(), gateCount * staggerMs);
    return () => {
      timers.forEach(clearTimeout);
      clearTimeout(done);
    };
    // Keyed on the gate COUNT, not the array: a re-render that hands in a
    // new array of the same gates must not replay the interlock.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase, gateCount, staggerMs]);

  const evaluating = phase === "evaluating";

  return (
    <div
      role="group"
      aria-label="Interlock gate strip"
      className={cn(
        "grid grid-cols-2 gap-px bg-line sm:grid-cols-3 xl:grid-cols-6",
        className,
      )}
    >
      {gates.map((gate, i) => {
        const lit = phase === "resolved" && i < litCount;
        const copy = GATE_COPY[gate.key] ?? { name: gate.label, desc: "" };
        return (
          <div
            key={gate.key}
            title={lit && gate.reason ? gate.reason : undefined}
            className={cn(
              "flex min-w-0 flex-col gap-1.5 bg-surface px-5 py-4 transition-colors duration-150",
              lit && gate.state === "failed" && "bg-[color-mix(in_srgb,var(--color-danger)_5%,white)]",
            )}
          >
            <span className="flex items-center gap-1.5">
              <GateIcon state={gate.state} lit={lit} evaluating={evaluating} delayMs={i * staggerMs} />
              <span
                className={cn(
                  "truncate text-[13px] font-medium",
                  lit && gate.state === "failed" ? "text-danger" : "text-fg",
                )}
                aria-hidden="true"
              >
                {copy.name}
              </span>
              <span className="sr-only">
                {`gate ${gate.label}: ${lit ? STATE_LABEL[gate.state] : "pending"}`}
              </span>
            </span>
            <span className="truncate text-[12px] text-fg-muted">
              {lit && gate.state !== "passed" ? `${STATE_LABEL[gate.state]} · ${copy.desc}` : copy.desc}
            </span>
          </div>
        );
      })}
    </div>
  );
}
