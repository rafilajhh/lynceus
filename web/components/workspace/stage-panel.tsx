"use client";

/**
 * StagePanel: the pipeline, live. Each stage the backend streams lights up
 * with its own timer: the waybill read and the weighing (done before the
 * run), the CPU second look, the vision reads on AMD Token Factory (1 of 3,
 * 2 of 3, 3 of 3), the waybill audit, the rules, the seal. Real clocks
 * only: nothing advances unless the backend said so.
 */

import { forwardRef, useEffect, useMemo, useState } from "react";
import { Panel, PanelHead } from "@/components/ui/panel";
import { LIVE_LATENCY_COPY, providerName } from "@/lib/format";
import type { StageEvent } from "@/lib/inspect-stream";
import { cn } from "@/lib/utils";
import { WAYBILL_FIELDS } from "@/lib/waybill-api";
import { IconCheck, IconDash } from "./gate-icons";
import type { RunState } from "./use-inspection";
import { formatKg, formatSecs } from "./units";

type RowStatus = "pending" | "running" | "done" | "skipped";

interface Row {
  key: string;
  label: string;
  detail: string;
  status: RowStatus;
  /** Final duration in seconds (done rows). */
  seconds: number | null;
  /** Backend t (s) the stage started at, for a live timer while running. */
  startT: number | null;
  /** Vision reads: done count of total. */
  reads?: { done: number; of: number; hard: boolean[] };
}

/** Stages the backend streams, in pipeline order (contract §6). */
const STREAM_STAGES: { key: string; label: string; detail: string }[] = [
  { key: "detector", label: "Second look", detail: "CPU detector (YOLO26m), trained on close-ups" },
  { key: "vision", label: "Vision read", detail: "Vision-language model" },
  { key: "waybill_audit", label: "Waybill audit", detail: "Language model notes for the record" },
  { key: "rules", label: "Decision rules", detail: "Hard contaminants, weight, declaration · SOP steps" },
  { key: "sealed", label: "Sealed record", detail: "SHA-256 digest over every input and output" },
];

function useNow(active: boolean): number {
  const [now, setNow] = useState(() => performance.now());
  useEffect(() => {
    if (!active) return;
    setNow(performance.now());
    const id = window.setInterval(() => setNow(performance.now()), 100);
    return () => window.clearInterval(id);
  }, [active]);
  return now;
}

function str(v: unknown): string | null {
  return typeof v === "string" && v ? v : null;
}

function num(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

function shortModel(model: string): string {
  return model.replace(/-\d+B(-A\d+B)?(-Instruct)?$/i, "");
}

function streamRows(events: StageEvent[], finished: boolean, single: boolean): Row[] {
  const byStage = new Map<string, StageEvent[]>();
  for (const e of events) {
    const list = byStage.get(e.stage) ?? [];
    list.push(e);
    byStage.set(e.stage, list);
  }
  const doneT = (stage: string) => byStage.get(stage)?.find((e) => e.status === "done")?.t ?? null;

  const known = new Set(STREAM_STAGES.map((s) => s.key).concat(["queued", "vision_read"]));
  const extra = [...byStage.keys()]
    .filter((k) => !known.has(k))
    .map((k) => ({ key: k, label: k.replace(/_/g, " "), detail: "" }));

  return [...STREAM_STAGES, ...extra].map((s) => {
    const list = byStage.get(s.key) ?? [];
    const running = list.find((e) => e.status === "running");
    const done = list.find((e) => e.status === "done");
    const ended = list.find((e) => e.status === "skipped" || e.status === "failed");
    const data = { ...(running?.data ?? {}), ...(done?.data ?? {}), ...(ended?.data ?? {}) };
    let detail = s.detail;
    let reads: Row["reads"];

    if (ended && !done) {
      const error = str(data.error);
      detail =
        ended.status === "failed"
          ? `Did not answer${error ? ` (${error})` : ""}`
          : s.key === "detector"
            ? "Did not run on this photo"
            : "Skipped";
    }
    if (s.key === "detector" && done) {
      const labels = Array.isArray(data.labels) ? data.labels.filter((l): l is string => typeof l === "string") : [];
      detail = labels.length > 0 ? `Flags ${labels.join(", ")}` : "Nothing flagged on this photo";
    }
    if (s.key === "vision") {
      const model = str(data.model);
      const provider = str(data.provider);
      if (model) detail = `${shortModel(model)}${provider ? ` on ${providerName(provider)}` : ""}`;
      const readEvents = (byStage.get("vision_read") ?? []).filter((e) => e.status === "done");
      const of = num(data.reads) ?? num(readEvents[0]?.data.of) ?? 0;
      if (of > 0) {
        reads = {
          done: readEvents.length,
          of,
          hard: readEvents.map((e) => Array.isArray(e.data.hard) && e.data.hard.length > 0),
        };
      }
      const frames = num(data.frames);
      if (frames && frames > 1) detail += ` · ${frames} angles`;
    }
    if (s.key === "sealed" && done) {
      const id = str(data.record_id);
      if (id) detail = `${id} · SHA-256 digest`;
    }

    // Duration: from the stage's own start, else from what it waits on.
    let start = running?.t ?? null;
    if (start === null && s.key === "rules") {
      const prior = ["detector", "vision", "waybill_audit"].map(doneT).filter((t): t is number => t !== null);
      start = prior.length ? Math.max(...prior) : 0;
    }
    if (start === null && s.key === "sealed") start = doneT("rules") ?? 0;
    const latency = s.key === "detector" ? num(data.latency_ms) : null;
    const seconds = done ? (latency !== null ? latency / 1000 : Math.max(0, done.t - (start ?? 0))) : null;

    let status: RowStatus = done ? "done" : ended ? "skipped" : running ? "running" : "pending";
    if (single) status = finished ? "done" : "running";
    else if (finished && status !== "done") status = "skipped";

    return { key: s.key, label: s.label, detail, status, seconds, startT: running?.t ?? (single ? 0 : null), reads };
  });
}

export const StagePanel = forwardRef<HTMLElement, { run: RunState }>(function StagePanel({ run }, ref) {
  const running = run.phase === "running";
  const finished = run.phase === "done" || run.phase === "error";
  const single = run.mode === "single";
  const now = useNow(running);
  const elapsedS =
    run.startedAt === null ? 0 : ((run.elapsedMs ?? now - run.startedAt) as number) / 1000;
  const snap = run.snapshot;

  const rows = useMemo<Row[]>(() => {
    const pre: Row[] = [];
    if (snap) {
      const w = snap.waybill;
      const read = w.status === "read" ? w.read : null;
      const fields = read ? WAYBILL_FIELDS.filter((f) => w.values[f.key]).length : 0;
      pre.push({
        key: "waybill",
        label: "Waybill read",
        detail: read
          ? read.provenance === "stub"
            ? `Offline reader · ${fields} fields of the bundled sample`
            : `${read.model ? shortModel(read.model) : "Vision model"}${read.provider ? ` on ${providerName(read.provider)}` : ""} · ${fields} fields${
                w.editedFields.length ? `, ${w.editedFields.length} edited` : ""
              }`
          : w.status === "empty"
            ? "No waybill: the record will say so"
            : "Typed by the operator",
        status: read ? "done" : "skipped",
        seconds: read?.latency_ms != null ? read.latency_ms / 1000 : null,
        startT: null,
      });
      pre.push({
        key: "weighbridge",
        label: "Weighbridge",
        detail:
          snap.scale.source === "manual_entry"
            ? `Typed by the operator · ${formatKg(snap.scale.netKg)}`
            : `${snap.scale.reading?.scale ?? "Indicator"}${
                snap.scale.source === "weighbridge_simulated" ? " · simulated feed" : ""
              } · ${formatKg(snap.scale.netKg)} net`,
        status: "done",
        seconds: null,
        startT: null,
      });
    }
    return [...pre, ...streamRows(run.events, finished, single)];
  }, [snap, run.events, finished, single]);

  const last = run.events.at(-1);
  const announce = last
    ? `${rows.find((r) => r.key === (last.stage === "vision_read" ? "vision" : last.stage))?.label ?? last.stage} ${
        last.status === "done" ? "done" : "started"
      }`
    : "";

  const plate = snap?.waybill.values.plate.trim();

  return (
    <Panel ref={ref} aria-labelledby="stage-title" className="scroll-mt-3">
      <PanelHead title={finished ? "Inspection trace" : "Inspecting"} meta={plate ? plate : undefined}>
        <span
          className={cn("figure text-[13px] font-semibold", running ? "text-amber" : "text-ink")}
          style={{ letterSpacing: 0 }}
          aria-hidden="true"
        >
          {formatSecs(elapsedS)}
        </span>
      </PanelHead>
      <h2 id="stage-title" className="sr-only">
        Inspection stages
      </h2>
      <p className="sr-only" aria-live="polite">
        {announce}
      </p>

      <ol className="m-0 list-none p-0">
        {rows.map((row) => (
          <StageRow key={row.key} row={row} now={now} startedAt={run.startedAt} />
        ))}
      </ol>

      <p className="m-0 border-t border-seam px-4 py-2.5 text-[12px] leading-relaxed text-faint">
        {single
          ? "This backend answers in one piece, so stages are not timed individually."
          : running
            ? `Live vision on the shared AMD endpoint takes ${LIVE_LATENCY_COPY}.`
            : run.phase === "done"
              ? `Decided ${formatSecs(elapsedS)} after Inspect, measured in this browser.`
              : "The run stopped before a verdict; nothing was decided."}
      </p>
    </Panel>
  );
});

function StageRow({ row, now, startedAt }: { row: Row; now: number; startedAt: number | null }) {
  const liveSeconds =
    row.status === "running" && startedAt !== null && row.startT !== null
      ? Math.max(0, (now - startedAt) / 1000 - row.startT)
      : null;
  return (
    <li
      className={cn(
        "grid grid-cols-[18px_minmax(0,1fr)_auto] items-start gap-x-3 border-b border-seam px-4 py-2.5 transition-colors duration-200 last:border-b-0",
        row.status === "running" && "bg-amber-soft/40",
      )}
    >
      <span className="mt-[3px] flex h-[14px] w-[18px] items-center justify-center" aria-hidden="true">
        {row.status === "done" ? (
          <span className="text-ink">
            <IconCheck size={15} />
          </span>
        ) : row.status === "running" ? (
          <span className="h-2 w-2 animate-[gate-pulse_1.1s_ease-in-out_infinite] rounded-full bg-amber" />
        ) : row.status === "skipped" ? (
          <span className="text-faint">
            <IconDash size={15} />
          </span>
        ) : (
          <span className="h-2 w-2 rounded-full border border-seam-strong" />
        )}
      </span>
      <span className="flex min-w-0 flex-col gap-0.5 sm:flex-row sm:items-baseline sm:gap-3">
        <span
          className={cn(
            "shrink-0 text-[13.5px] font-semibold sm:w-[128px]",
            row.status === "pending" || row.status === "skipped" ? "text-muted" : "text-ink",
          )}
        >
          {row.label}
          <span className="sr-only">{`: ${row.status}`}</span>
        </span>
        <span className="flex min-w-0 flex-wrap items-center gap-x-2.5 gap-y-1 text-[12.5px] leading-snug text-muted">
          <span className="min-w-0">{row.detail}</span>
          {row.reads ? <ReadPips reads={row.reads} /> : null}
        </span>
      </span>
      <span
        className={cn(
          "figure pt-px text-right text-[12.5px] tabular-nums",
          row.status === "running" ? "text-amber" : "text-muted",
        )}
      >
        {row.status === "done" && row.seconds !== null
          ? formatSecs(row.seconds)
          : liveSeconds !== null
            ? formatSecs(liveSeconds)
            : ""}
      </span>
    </li>
  );
}

/** Vision reads as pips: filled = answered (red ring when it saw a hard item). */
function ReadPips({ reads }: { reads: NonNullable<Row["reads"]> }) {
  return (
    <span className="figure inline-flex items-center gap-1.5 text-[11.5px] text-muted">
      <span className="inline-flex gap-1" aria-hidden="true">
        {Array.from({ length: reads.of }, (_, i) => (
          <span
            key={i}
            className={cn(
              "h-2 w-2 rounded-full border",
              i < reads.done ? "border-ink bg-ink" : "border-seam-strong",
              i < reads.done && reads.hard[i] && "border-verdict-red bg-verdict-red",
            )}
          />
        ))}
      </span>
      {`read ${reads.done} of ${reads.of}`}
    </span>
  );
}
