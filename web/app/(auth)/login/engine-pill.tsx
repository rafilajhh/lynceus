"use client";

import { useEffect, useState } from "react";

type Engine = "checking" | "online" | "down";

/**
 * Brand-panel status pill on the sign-in page: reads the public /health
 * once, so the panel never claims "Engine online" while it is down.
 */
export function EnginePill() {
  const [engine, setEngine] = useState<Engine>("checking");

  useEffect(() => {
    const controller = new AbortController();
    fetch("/health", { cache: "no-store", signal: controller.signal })
      .then((r) => (r.ok ? r.json() : null))
      .then((d: { status?: string; engine_available?: boolean } | null) =>
        setEngine(d?.status === "ok" && d.engine_available ? "online" : "down"),
      )
      .catch((err) => {
        if (err instanceof DOMException && err.name === "AbortError") return;
        setEngine("down");
      });
    return () => controller.abort();
  }, []);

  const dot =
    engine === "online" ? "bg-success" : engine === "down" ? "bg-danger" : "bg-warning";
  const label =
    engine === "online" ? "Engine online" : engine === "down" ? "Engine offline" : "Checking engine";

  return (
    <span
      role="status"
      aria-live="polite"
      className="inline-flex w-fit items-center gap-2 rounded-full border border-white/[0.12] bg-white/[0.08] px-3 py-1.5 font-mono text-[12px] text-white"
    >
      <span aria-hidden="true" className={`h-[7px] w-[7px] rounded-full ${dot}`} />
      {label} · Weighbridge Gate A
    </span>
  );
}
