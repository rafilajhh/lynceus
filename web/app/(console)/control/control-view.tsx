"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { ControlError, fetchControlSummary, type ControlSummary } from "@/lib/control-api";
import { fetchContract } from "@/lib/ops-api";
import { parseContract, type ContractTerms } from "@/lib/shift-api";
import { cn } from "@/lib/utils";
import { PythiaPanel } from "@/components/assist/pythia-panel";
import { ShiftBriefing } from "@/components/assist/shift-briefing";
import { AmdPanel } from "@/components/ops/amd-panel";
import { CarbonPanel } from "@/components/ops/carbon-panel";
import { LabTrendPanel } from "@/components/ops/lab-trend";
import { SupplierScorecard, type ScoreState } from "@/components/ops/supplier-scorecard";
import { num, plural, utcClock } from "@/components/ops/format";
import { Button } from "@/components/ui/button";
import { Panel, PanelHead } from "@/components/ui/panel";
import { AlarmBand } from "./alarm-band";
import { GateStrip } from "./gate-strip";
import { GateQueue, HeldWorklist } from "./gate-lists";

/** Refresh period; polling pauses while the tab is hidden. */
const POLL_MS = 20_000;
/** Decisions shown in the gate column; the audit trail has the rest. */
const QUEUE_SHOWN = 8;

type LoadState =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ready"; data: ControlSummary; failed: string | null };

/** The room's one sentence: volume, chlorine, and who is waiting. */
function headline(d: ControlSummary): string {
  const parts: string[] = [];
  if (d.shift?.trucks != null) parts.push(`${d.shift.trucks} ${plural(d.shift.trucks, "truck", "trucks")} this shift`);
  const pct = d.kiln?.chlorine_budget_pct;
  if (pct != null) {
    parts.push(
      d.kiln?.chlorine_status === "over"
        ? `chlorine over the shift budget at ${num(pct)} %`
        : `chlorine at ${num(pct)} % of the shift budget`,
    );
  }
  if (d.held) {
    parts.push(
      d.held.length === 0
        ? "no load waiting for a supervisor"
        : `${d.held.length} ${plural(d.held.length, "load", "loads")} waiting for a supervisor`,
    );
  }
  if (parts.length === 0) return "The gate at a glance.";
  const text = parts.join(", ");
  return `${text.charAt(0).toUpperCase()}${text.slice(1)}.`;
}

function windowMeta(d: ControlSummary): string | undefined {
  const w = d.shift?.window ?? d.kiln?.window;
  if (!w?.since || !w.until) return undefined;
  return `shift ${utcClock(w.since).replace(" UTC", "")}–${utcClock(w.until)}`;
}

function LiveState({ hidden, failed, at }: { hidden: boolean; failed: string | null; at: string | null }) {
  const tone = failed ? "bg-dot-down" : hidden ? "bg-dot-idle" : "bg-dot-ok";
  const word = failed
    ? `Update failed · showing ${utcClock(at)}`
    : hidden
      ? "Paused while hidden"
      : `Live · ${utcClock(at)}`;
  return (
    <span role="status" title={failed ?? undefined} className="flex items-center gap-2 text-[12px] font-semibold tracking-normal normal-case">
      <span
        aria-hidden="true"
        className={cn("size-2 rounded-full", tone, !failed && !hidden && "motion-safe:animate-pulse")}
      />
      <span className={failed ? "text-verdict-red" : "text-muted"}>{word}</span>
    </span>
  );
}

function ControlSkeleton() {
  const bar = "rounded-[6px] bg-raised motion-safe:animate-pulse";
  return (
    <div className="flex flex-col gap-4" role="status">
      <span className="sr-only">Loading the control room</span>
      <Panel aria-hidden="true">
        <PanelHead title="Control room" />
        <div className="px-5 py-5">
          <div className={cn(bar, "h-6 w-[70%]")} />
        </div>
        <div className="grid grid-cols-2 gap-px border-t border-seam bg-seam lg:grid-cols-5">
          {Array.from({ length: 5 }, (_, i) => (
            <div key={i} className={cn("bg-panel px-5 py-4", i === 0 && "col-span-2 lg:col-span-1")}>
              <div className={cn(bar, "h-14")} />
            </div>
          ))}
        </div>
      </Panel>
      <div className="grid gap-4 lg:grid-cols-[1.35fr_1fr]" aria-hidden="true">
        <div className={cn(bar, "h-72")} />
        <div className={cn(bar, "h-72")} />
      </div>
    </div>
  );
}

export function ControlView() {
  const [state, setState] = useState<LoadState>({ kind: "loading" });
  const [hidden, setHidden] = useState(false);
  const [contract, setContract] = useState<ContractTerms | null>(null);
  const [reload, setReload] = useState(0);

  // Poll the one-call summary; a failed refresh keeps the last good room on
  // screen and says so, it never blanks it.
  useEffect(() => {
    let alive = true;
    let inflight: AbortController | null = null;

    const tick = async () => {
      if (document.hidden) return;
      inflight?.abort();
      const controller = new AbortController();
      inflight = controller;
      try {
        const data = await fetchControlSummary(controller.signal);
        if (alive) setState({ kind: "ready", data, failed: null });
      } catch (err) {
        if (!alive || controller.signal.aborted) return;
        const message = err instanceof ControlError ? err.message : "The control room could not be loaded.";
        setState((prev) => (prev.kind === "ready" ? { ...prev, failed: message } : { kind: "error", message }));
      }
    };

    const onVisibility = () => {
      setHidden(document.hidden);
      if (!document.hidden) void tick();
    };

    setHidden(document.hidden);
    void tick();
    const timer = window.setInterval(() => void tick(), POLL_MS);
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      alive = false;
      inflight?.abort();
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [reload]);

  // The contract changes rarely: read once for the scorecard's spec limits
  // and sampling rules.
  useEffect(() => {
    let alive = true;
    fetchContract()
      .then((raw) => alive && setContract(parseContract(raw)))
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, []);

  const data = state.kind === "ready" ? state.data : null;
  const score = useMemo<ScoreState>(() => {
    if (!data) return { kind: "loading" };
    if (!data.suppliers) return { kind: "unavailable", reason: "absent" };
    return {
      kind: "ready",
      scorecard: { generated_at_utc: data.generated_at_utc ?? null, contract: contract, suppliers: data.suppliers },
      contract,
    };
  }, [data, contract]);

  if (state.kind === "loading") return <ControlSkeleton />;

  if (state.kind === "error") {
    return (
      <Panel>
        <PanelHead title="Control room" />
        <div role="alert" className="flex flex-col items-center gap-3 px-4 py-12 text-center">
          <p className="m-0 text-[14px] font-semibold text-ink">{state.message}</p>
          <Button variant="default" size="sm" onClick={() => setReload((n) => n + 1)}>
            Retry
          </Button>
        </div>
      </Panel>
    );
  }

  const d = state.data;
  return (
    <div className="flex flex-col gap-4">
      <Panel aria-labelledby="control-headline">
        <PanelHead title="Control room" meta={windowMeta(d)}>
          <LiveState hidden={hidden} failed={state.failed} at={d.generated_at_utc ?? null} />
        </PanelHead>
        <div className="px-5 py-5">
          <h1
            id="control-headline"
            className="m-0 max-w-[62ch] text-[19px] leading-[1.4] font-semibold text-balance text-ink sm:text-[21px]"
          >
            {headline(d)}
          </h1>
          {d.source === "composed" ? (
            <p className="m-0 mt-2 text-[12.5px] text-faint">
              This backend has no <span className="figure">/control/summary</span>: the room is assembled from
              the per-area routes, without the decision list, the held list or the lab trend.
            </p>
          ) : null}
        </div>
        <GateStrip shift={d.shift ?? null} kiln={d.kiln ?? null} />
      </Panel>

      <AlarmBand alerts={d.alerts ?? null} />

      <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)]">
        <GateQueue cards={d.queue ?? null} limit={QUEUE_SHOWN} />
        <div className="flex flex-col gap-4">
          <HeldWorklist cards={d.held ?? null} />
          <ShiftBriefing className="bg-panel" />
          <PythiaPanel context="shift" className="bg-panel" />
          <CarbonPanel carbon={d.carbon ?? null} />
        </div>
      </div>

      <SupplierScorecard score={score} limit={6} showContract={false} />

      <LabTrendPanel trend={d.lab_trend ?? null} />

      <AmdPanel measured={d.amd ?? null} />

      <p className="m-0 px-1 text-[12.5px] leading-relaxed text-faint">
        {d.contract_note ? `${d.contract_note} ` : ""}
        The full shift story and every supplier are on the{" "}
        <Link href="/shift" className="text-amber underline underline-offset-2">
          shift report
        </Link>
        ; how the gate was measured is on{" "}
        <Link href="/validation" className="text-amber underline underline-offset-2">
          validation
        </Link>
        .
      </p>
    </div>
  );
}
