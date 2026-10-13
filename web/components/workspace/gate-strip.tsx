"use client";

/**
 * GateStrip: the signature move: five industrial indicator lights
 * (VLM, OCR, XCHECK, GAS, WEIGHT) on a horizontal strip that light
 * up sequentially with a 120ms stagger when a verdict arrives, like
 * a machine startup interlock. Green = passed, red = failed,
 * graphite = not_run/not_evaluated.
 *
 * The verdict banner may only light after all five gates resolve:
 * the parent reads `allResolved`.
 */

import { useEffect, useState } from "react";
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
    display.state =
      state === "passed" || state === "failed" ? state : "not_run";
    display.reason =
      typeof raw === "object" && raw !== null
        ? ((raw as GateResult).reason ?? null)
        : null;
  }
  return [...map.values()];
}

type InspectGates = Record<string, GateResult | GateResult["state"]>;

const DOT_TONE: Record<GateDisplay["state"], string> = {
  passed: "bg-dot-ok shadow-[0_0_8px_rgba(46,204,113,0.7)]",
  failed: "bg-dot-down shadow-[0_0_8px_rgba(231,76,60,0.7)]",
  not_run: "bg-dot-idle",
  not_evaluated: "bg-dot-idle",
};

const STATE_LABEL: Record<GateDisplay["state"], string> = {
  passed: "passed",
  failed: "FAILED",
  not_run: "not_run",
  not_evaluated: "n/a",
};

export function GateStrip({
  gates,
  phase,
  onAllResolved,
  staggerMs = 120,
}: {
  gates: GateDisplay[];
  /** idle = pre-submit graphite; evaluating = amber pulsing; resolved = run */
  phase: GatePhase;
  onAllResolved?: () => void;
  staggerMs?: number;
}) {
  const [litCount, setLitCount] = useState(0);
  const allResolved = phase === "resolved" && litCount >= gates.length;

  useEffect(() => {
    if (phase !== "resolved") {
      setLitCount(0);
      return;
    }
    // Snap the lights on one by one, 120ms apart: the interlock.
    const timers: ReturnType<typeof setTimeout>[] = [];
    gates.forEach((_, i) => {
      timers.push(setTimeout(() => setLitCount(i + 1), i * staggerMs));
    });
    const done = setTimeout(() => onAllResolved?.(), gates.length * staggerMs);
    return () => {
      timers.forEach(clearTimeout);
      clearTimeout(done);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase, gates, staggerMs]);

  const evaluating = phase === "evaluating";

  return (
    <div>
      <div
        className="flex items-stretch gap-0 overflow-hidden rounded-[10px] border border-seam"
        role="group"
        aria-label="Interlock gate strip"
      >
        {gates.map((gate, i) => {
          const lit = phase === "resolved" && i < litCount;
          const tone = lit ? DOT_TONE[gate.state] : "bg-dot-idle";
          const textTone = !lit
            ? "text-muted"
            : gate.state === "passed"
              ? "text-verdict-green"
              : gate.state === "failed"
                ? "text-verdict-red"
                : "text-muted";
          return (
            <div
              key={gate.key}
              className={cn(
                "flex flex-1 flex-col items-center gap-1.5 border-r border-seam bg-raised px-2.5 py-3 last:border-r-0 transition-colors duration-150",
                evaluating && "animate-[gate-pulse_1.1s_ease-in-out_infinite]",
                evaluating && "bg-amber-soft",
                lit && gate.state === "failed" && "bg-red-dim",
                lit && gate.state === "passed" && "bg-green-dim",
              )}
              style={
                evaluating
                  ? { animationDelay: `${i * staggerMs}ms` }
                  : undefined
              }
            >
              <span
                aria-hidden="true"
                className={cn(
                  "h-3 w-3 rounded-full transition-all duration-150",
                  tone,
                )}
              />
              <span
                className={cn(
                  "figure text-[12px] font-semibold tracking-[0.8px]",
                  textTone,
                )}
              >
                {gate.label}
              </span>
              <span
                className={cn("text-[12px] font-semibold tracking-wide", textTone)}
                aria-hidden="true"
              >
                {lit ? STATE_LABEL[gate.state] : "—"}
              </span>
              <span className="sr-only">
                {`gate ${gate.label}: ${
                  lit ? STATE_LABEL[gate.state] : "pending"
                }`}
              </span>
            </div>
          );
        })}
      </div>

      <div className="mt-2 text-center" aria-live="polite">
        {evaluating ? (
          <span className="figure text-[12px] tracking-[0.5px] text-amber">
            Evaluating interlock…
          </span>
        ) : allResolved ? (
          <span className="figure text-[12px] tracking-[0.5px] text-muted">
            Interlock resolved: verdict issued.
          </span>
        ) : (
          <span className="figure text-[12px] tracking-[0.5px] text-muted">
            Awaiting inspection.
          </span>
        )}
      </div>
    </div>
  );
}
