"use client";

/**
 * ChecksStrip: what the gate checked, in operator words (backend
 * checks.py): Load photo, Second look, Waybill read, Waybill vs load,
 * Weighbridge, Supplier record. A failed or doubtful check carries a tinted
 * cell so the eye lands on the problem; passes stay quiet; "info" is
 * neutral, "skipped" grey.
 *
 * The signature interlock: cells light one by one (120 ms apart) when the
 * verdict arrives, and the banner lights only after the last one.
 *
 * An older backend sends no checks: they are derived from its gates, with
 * the two corrections the gates cannot make on their own (a hard item the
 * camera saw fails the photo check; a detector that missed it is "info").
 */

import { useEffect, useState } from "react";
import type { InspectResponse } from "@/lib/inspect-api";
import type { Check, CheckStatus } from "@/lib/ops-api";
import { cn } from "@/lib/utils";
import { IconCheck, IconCross, IconDash, IconInfo, IconWarn } from "./gate-icons";
import { prefersReducedMotion } from "./use-intake";

const STAGGER_MS = 120;

const GATE_CHECKS: { gate: string; key: string; label: string }[] = [
  { gate: "vlm_confidence", key: "vision", label: "Load photo" },
  { gate: "detector_second_opinion", key: "second_look", label: "Second look" },
  { gate: "ocr_confidence", key: "waybill_read", label: "Waybill read" },
  { gate: "manifest_crosscheck", key: "declaration", label: "Waybill vs load" },
  { gate: "weight_plausibility", key: "weight", label: "Weighbridge" },
];

/** Hard contaminants the vision model reported (merged frames). */
export function visionHard(data: InspectResponse | null): string[] {
  const detected = data?.ai_outputs.vlm?.detected as Record<string, unknown> | null | undefined;
  const hard = detected?.hard_contaminants;
  return Array.isArray(hard) ? hard.filter((h): h is string => typeof h === "string") : [];
}

export function visionLight(data: InspectResponse | null): string[] {
  const detected = data?.ai_outputs.vlm?.detected as Record<string, unknown> | null | undefined;
  const light = detected?.light_contaminants;
  return Array.isArray(light) ? light.filter((h): h is string => typeof h === "string") : [];
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

const TONE: Record<CheckStatus, { cell: string; icon: string; Icon: typeof IconCheck; word: string }> = {
  fail: { cell: "bg-red-dim", icon: "text-verdict-red", Icon: IconCross, word: "failed" },
  warn: { cell: "bg-amber-dim", icon: "text-amber", Icon: IconWarn, word: "needs a look" },
  pass: { cell: "bg-panel", icon: "text-verdict-green", Icon: IconCheck, word: "passed" },
  info: { cell: "bg-panel", icon: "text-muted", Icon: IconInfo, word: "for information" },
  skipped: { cell: "bg-panel", icon: "text-faint", Icon: IconDash, word: "not run" },
};

export function ChecksStrip({
  checks,
  runKey,
  onAllLit,
}: {
  checks: Check[];
  /** Changes per verdict: replays the interlock. */
  runKey: string | number;
  onAllLit: () => void;
}) {
  const [lit, setLit] = useState(0);
  const count = checks.length;

  useEffect(() => {
    if (prefersReducedMotion()) {
      setLit(count);
      onAllLit();
      return;
    }
    setLit(0);
    const timers = Array.from({ length: count }, (_, i) =>
      setTimeout(() => setLit(i + 1), (i + 1) * STAGGER_MS),
    );
    const done = setTimeout(onAllLit, (count + 1) * STAGGER_MS);
    return () => {
      timers.forEach(clearTimeout);
      clearTimeout(done);
    };
    // Keyed on the verdict, not the array identity: a re-render must not replay it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runKey, count]);

  if (count === 0) {
    return (
      <p className="m-0 rounded-[10px] border border-dashed border-seam-strong px-4 py-3 text-[13px] text-muted">
        This backend returned no checks for the verdict.
      </p>
    );
  }

  return (
    <ul
      aria-label="Gate checks"
      className={cn(
        "m-0 grid list-none grid-cols-2 gap-px overflow-hidden rounded-[10px] border border-seam bg-seam p-0 sm:grid-cols-3",
        count >= 6 ? "xl:grid-cols-6" : count === 5 ? "xl:grid-cols-5" : "xl:grid-cols-4",
      )}
    >
      {checks.map((c, i) => {
        const on = i < lit;
        const tone = TONE[c.status];
        return (
          <li
            key={c.key}
            className={cn(
              "flex min-w-0 flex-col gap-1 px-3 py-2.5 transition-colors duration-150",
              on ? tone.cell : "bg-raised",
            )}
          >
            <span className="flex items-start justify-between gap-2" aria-hidden="true">
              <span className="min-w-0 text-[11px] leading-tight font-bold tracking-[1px] break-words text-muted uppercase">
                {c.label}
              </span>
              <span className={cn("shrink-0 transition-opacity duration-150", on ? tone.icon : "text-faint")} aria-hidden="true">
                {on ? <tone.Icon size={15} /> : <IconDash size={15} />}
              </span>
            </span>
            <span aria-hidden="true" className={cn("text-[14px] leading-snug font-semibold", on ? "text-ink" : "text-faint")}>
              {on ? c.finding || "—" : "—"}
            </span>
            {c.detail ? (
              <span
                aria-hidden="true"
                title={c.detail}
                className={cn(
                  "line-clamp-3 text-[12px] leading-snug text-muted transition-opacity duration-150",
                  on ? "opacity-100" : "opacity-0",
                )}
              >
                {c.detail}
              </span>
            ) : null}
            <span className="sr-only">{`${c.label}: ${tone.word}. ${c.finding}. ${c.detail}`}</span>
          </li>
        );
      })}
    </ul>
  );
}
