"use client";

import { useEffect, useState } from "react";

/**
 * Status chip: honest engine availability (review finding 5).
 *
 * Polls GET /health for the engine state ("ENGINE ONLINE" / "ENGINE
 * DOWN" / "BACKEND DOWN"). Never a fake green when the service is down.
 */
type HealthState =
  | { kind: "checking" }
  | { kind: "ok"; engineAvailable: boolean }
  | { kind: "down"; message: string };

export function StatusChip({ intervalMs = 15000 }: { intervalMs?: number }) {
  const [state, setState] = useState<HealthState>({ kind: "checking" });

  // ---- /health poll: engine availability -----------------------------
  useEffect(() => {
    let cancelled = false;

    async function check() {
      try {
        const res = await fetch("/health", {
          headers: { Accept: "application/json" },
          cache: "no-store",
        });
        if (cancelled) return;
        if (!res.ok) {
          setState({ kind: "down", message: `HTTP ${res.status}` });
          return;
        }
        const data = (await res.json()) as {
          status?: string;
          engine_available?: boolean;
        };
        if (cancelled) return;
        if (data?.status === "ok") {
          setState({
            kind: "ok",
            engineAvailable: Boolean(data.engine_available),
          });
        } else {
          setState({ kind: "down", message: "UNEXPECTED RESPONSE" });
        }
      } catch (err) {
        if (cancelled) return;
        const message =
          err instanceof TypeError
            ? "BACKEND UNREACHABLE"
            : (err as Error)?.message?.toUpperCase().slice(0, 40) || "ERROR";
        setState({ kind: "down", message });
      }
    }

    check();
    const timer = setInterval(check, intervalMs);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [intervalMs]);

  const engineLabel =
    state.kind === "checking"
      ? "ENGINE …"
      : state.kind === "ok"
        ? state.engineAvailable
          ? "ENGINE ONLINE"
          : "ENGINE DOWN"
        : "BACKEND DOWN";

  const backendDown = state.kind === "down";
  const engineOk = state.kind === "ok" && state.engineAvailable;

  const tone = backendDown
    ? "text-verdict-red border-[rgba(231,76,60,0.4)]"
    : state.kind === "checking"
      ? "text-muted"
      : "text-verdict-green border-[rgba(46,204,113,0.4)]";

  const engineDot = backendDown
    ? "bg-dot-down"
    : state.kind === "checking"
      ? "bg-dot-warn"
      : engineOk
        ? "bg-dot-ok shadow-[0_0_6px_rgba(46,204,113,0.6)]"
        : "bg-dot-down";

  return (
    <span
      role="status"
      aria-live="polite"
      aria-atomic="true"
      className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border bg-raised px-3 py-1.5 text-[12px] font-bold tracking-[0.8px] uppercase ${tone}`}
    >
      <span
        aria-hidden="true"
        className={`h-2 w-2 shrink-0 rounded-full ${engineDot}`}
      />
      <span>{engineLabel}</span>
    </span>
  );
}
