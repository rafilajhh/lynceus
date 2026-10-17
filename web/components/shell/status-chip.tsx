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

  const tone = backendDown || (state.kind === "ok" && !engineOk)
    ? "bg-danger-tint text-danger"
    : state.kind === "checking"
      ? "bg-surface-subtle text-fg-muted"
      : "bg-success-tint text-success";

  const engineDot = backendDown
    ? "bg-danger"
    : state.kind === "checking"
      ? "bg-warning"
      : engineOk
        ? "bg-success"
        : "bg-danger";

  return (
    <span
      role="status"
      aria-live="polite"
      aria-atomic="true"
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 font-mono text-[11px] font-medium tracking-[0.8px] whitespace-nowrap uppercase ${tone}`}
    >
      <span
        aria-hidden="true"
        className={`h-1.5 w-1.5 shrink-0 rounded-full ${engineDot}`}
      />
      <span>{engineLabel}</span>
    </span>
  );
}
