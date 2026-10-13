"use client";

import { useEffect, useRef, useState } from "react";

/**
 * Status chip: per-service honest degradation (review finding 5).
 *
 * Polls GET /health for the engine dot ("ENGINE ONLINE" / "ENGINE DOWN")
 * and probes the configured vLLM VLM endpoint once on mount for the AI
 * dot ("AI LIVE" / "AI STUB": a 2s GET /models probe; any failure is
 * silent and reads as the offline stub). Never a fake green when a
 * service is down.
 */
type HealthState =
  | { kind: "checking" }
  | { kind: "ok"; engineAvailable: boolean; vllmVlmUrl?: string }
  | { kind: "down"; message: string };

type AiState = "probing" | "live" | "stub";

export function StatusChip({ intervalMs = 15000 }: { intervalMs?: number }) {
  const [state, setState] = useState<HealthState>({ kind: "checking" });
  const [ai, setAi] = useState<AiState>("probing");

  // ---- /health poll: engine availability + the configured VLM URL ----
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
          vllm_vlm_url?: string;
        };
        if (cancelled) return;
        if (data?.status === "ok") {
          setState({
            kind: "ok",
            engineAvailable: Boolean(data.engine_available),
            vllmVlmUrl: data.vllm_vlm_url,
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

  // ---- AI dot: one-shot 2s probe of the vLLM VLM endpoint ------------
  // Mirrors the backend's own liveness probe (pipeline._vlm_reachable:
  // GET {VLLM_VLM_URL}/models, 2s timeout). Runs once on mount; any
  // failure is silent and the chip honestly reads "AI STUB".
  const probedRef = useRef(false);
  useEffect(() => {
    if (state.kind !== "ok" || probedRef.current) return;
    probedRef.current = true;
    const base = (state.vllmVlmUrl || window.location.origin).replace(
      /\/+$/,
      "",
    );
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 2000);
    fetch(`${base}/models`, { signal: controller.signal, cache: "no-store" })
      .then((res) => setAi(res.status < 500 ? "live" : "stub"))
      .catch(() => setAi("stub"))
      .finally(() => clearTimeout(timer));
  }, [state]);

  const engineLabel =
    state.kind === "checking"
      ? "ENGINE …"
      : state.kind === "ok"
        ? state.engineAvailable
          ? "ENGINE ONLINE"
          : "ENGINE DOWN"
        : "BACKEND DOWN";

  const aiLabel =
    ai === "probing" ? "AI …" : ai === "live" ? "AI LIVE" : "AI STUB";

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

  const aiDot =
    ai === "live"
      ? "bg-dot-ok shadow-[0_0_6px_rgba(46,204,113,0.6)]"
      : ai === "stub"
        ? "bg-dot-warn"
        : "bg-dot-warn animate-[gate-pulse_1.1s_ease-in-out_infinite]";

  return (
    <span
      role="status"
      aria-live="polite"
      aria-atomic="true"
      className={`inline-flex items-center gap-3 whitespace-nowrap rounded-full border bg-raised px-3 py-1.5 text-[12px] font-bold tracking-[0.8px] uppercase ${tone}`}
    >
      <span className="inline-flex items-center gap-1.5">
        <span
          aria-hidden="true"
          className={`h-2 w-2 shrink-0 rounded-full ${engineDot}`}
        />
        <span>{engineLabel}</span>
      </span>
      <span aria-hidden="true" className="text-seam-strong">
        |
      </span>
      <span className="inline-flex items-center gap-1.5">
        <span
          aria-hidden="true"
          className={`h-2 w-2 shrink-0 rounded-full ${aiDot}`}
        />
        <span>{aiLabel}</span>
      </span>
    </span>
  );
}
