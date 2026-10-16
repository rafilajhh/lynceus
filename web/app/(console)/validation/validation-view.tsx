"use client";

import { useCallback, useEffect, useState } from "react";
import { providerName } from "@/lib/format";
import {
  COLUMNS,
  LABELS,
  ValidationError,
  fetchBenchmark,
  type BenchmarkSummary,
  type Confusion,
} from "@/lib/validation-api";
import { Button } from "@/components/ui/button";
import { Panel, PanelHead } from "@/components/ui/panel";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

type LoadState =
  | { kind: "loading" }
  | { kind: "error"; message: string; missing: boolean }
  | { kind: "ready"; summary: BenchmarkSummary };

type Label = (typeof LABELS)[number];

const DATASET_URL = "https://archive.ics.uci.edu/dataset/908/realwaste";
const COLUMN_LABEL: Record<(typeof COLUMNS)[number], string> = {
  reject: "Reject",
  escalate: "Escalate",
  accept: "Accept",
  error: "Error",
};

/** Expected verdict per RealWaste class (mirrors backend/benchmark/manifest.csv). */
const CATEGORY_EXPECTED: Record<string, Label> = {
  Metal: "reject",
  Glass: "escalate",
  "Food Organics": "escalate",
  Vegetation: "escalate",
  Paper: "accept",
  Cardboard: "accept",
  Plastic: "accept",
  "Textile Trash": "accept",
};

function expectedFor(category: string): Label {
  return CATEGORY_EXPECTED[category] ?? "accept";
}

function ratio(value: number | null | undefined): string {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(2) : "—";
}

/** 95% Wilson score interval for k of n, as "0.76 to 0.99"; "—" when n is 0. */
function wilson(k: number, n: number): string {
  if (n <= 0) return "—";
  const z = 1.96;
  const p = k / n;
  const denom = 1 + (z * z) / n;
  const centre = (p + (z * z) / (2 * n)) / denom;
  const half = (z * Math.sqrt((p * (1 - p)) / n + (z * z) / (4 * n * n))) / denom;
  return `${Math.max(0, centre - half).toFixed(2)} to ${Math.min(1, centre + half).toFixed(2)}`;
}

function seconds(ms: number | null | undefined): string {
  return typeof ms === "number" && Number.isFinite(ms) ? `${(ms / 1000).toFixed(1)} s` : "—";
}

export function ValidationView() {
  const [state, setState] = useState<LoadState>({ kind: "loading" });

  const load = useCallback(async (signal?: AbortSignal) => {
    setState({ kind: "loading" });
    try {
      setState({ kind: "ready", summary: await fetchBenchmark(signal) });
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") return;
      setState({
        kind: "error",
        missing: err instanceof ValidationError && err.missing,
        message: err instanceof Error ? err.message : "Unexpected error loading the benchmark.",
      });
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  if (state.kind === "loading") {
    return (
      <Panel>
        <PanelHead title="Validation" />
        <div role="status" className="flex flex-col items-center gap-3 px-4 py-12 text-center">
          <span
            aria-hidden="true"
            className="h-6 w-6 animate-spin rounded-full border-2 border-seam border-t-amber"
          />
          <p className="text-[13px] text-muted">Loading the benchmark summary.</p>
        </div>
      </Panel>
    );
  }

  if (state.kind === "error") {
    return (
      <Panel>
        <PanelHead title="Validation" />
        <div role="alert" className="flex flex-col items-center gap-3 px-4 py-12 text-center">
          <p className="max-w-[52ch] text-[13.5px] text-muted">
            {state.missing ? state.message : `The benchmark could not be loaded. ${state.message}`}
          </p>
          {state.missing ? null : (
            <Button variant="default" size="sm" onClick={() => void load()}>
              Retry
            </Button>
          )}
        </div>
      </Panel>
    );
  }

  const { summary } = state;
  return (
    <div className="flex flex-col gap-4">
      <Panel aria-labelledby="validation-title">
        <PanelHead
          title="Validation"
          meta={
            summary.complete
              ? summary.date ?? undefined
              : `partial · ${summary.n}/${summary.manifest_n}`
          }
        />
        <h1 id="validation-title" className="sr-only">
          Validation benchmark
        </h1>
        <HeadlineRun summary={summary} />
        <p className="m-0 border-t border-seam px-4 py-2.5 text-[13px] text-muted">
          {summary.framing}. Live on AMD Token Factory, {summary.date ?? "—"}.
        </p>
        {summary.replay ? <ReplayTable summary={summary} replay={summary.replay} /> : null}
        <details className="group border-t border-seam px-4 py-3">
          <summary className="cursor-pointer select-none text-[13px] font-semibold text-ink transition-colors hover:text-amber">
            Method, data &amp; per-category detail
          </summary>
          <MethodDetail summary={summary} />
        </details>
      </Panel>
    </div>
  );
}

/** Headline: the verdict on the gate, in numbers and in words. */
function HeadlineRun({ summary }: { summary: BenchmarkSummary }) {
  // Use current-rules replay when available; it reflects the shipped rules.
  const replay = summary.replay;
  const r = replay ? replay.reject : summary.reject;
  const caught = `${r.tp} of ${r.tp + r.fn}`;
  const precisionNote = replay
    ? `${r.tp} of ${r.tp + r.fp} rejects were metal (current rules)`
    : `${r.tp} of ${r.tp + r.fp} rejects were metal`;
  const parts = [
    {
      key: "recall",
      value: ratio(r.recall),
      label: "recall",
      sub: `${caught} metal images rejected`,
    },
    {
      key: "precision",
      value: ratio(r.precision),
      label: "precision",
      sub: precisionNote,
    },
    { key: "f1", value: ratio(r.f1), label: "F1", sub: null as string | null },
  ];
  return (
    <div className="px-4 pt-4 pb-3">
      <dl className="m-0 grid grid-cols-3 gap-x-6">
        {parts.map((part) => (
          <div key={part.key} className="flex flex-col gap-1">
            <dd className="figure m-0 whitespace-nowrap text-[clamp(24px,3vw,34px)] leading-tight font-semibold text-ink">
              {part.value}
            </dd>
            <dt className="text-[14px] font-semibold text-ink">{part.label}</dt>
            {part.sub ? (
              <p className="m-0 text-[12px] leading-snug text-muted">{part.sub}</p>
            ) : null}
          </div>
        ))}
      </dl>
      <p className="m-0 mt-3 text-[14px] font-medium text-ink">
        {replay
          ? `Under current rules, the gate rejects ${r.tp} of ${r.tp + r.fn} metal loads and passes ${r.tp} of ${r.tp + r.fp} clean loads.`
          : `Out of every ${r.tp + r.fn} loads carrying metal, the gate rejected ${r.tp}.`}
      </p>
      <p className="figure m-0 mt-2 text-[12px] text-faint">
        n = {summary.n} · one run · 95% interval {wilson(r.tp, r.tp + r.fn)}
      </p>
    </div>
  );
}

/** Live vs current rules, inline in the same panel. */
function ReplayTable({
  summary,
  replay,
}: {
  summary: BenchmarkSummary;
  replay: import("@/lib/validation-api").ReplaySummary;
}) {
  const live = operatorCounts(summary.confusion);
  const now = operatorCounts(replay.confusion);
  const lr = summary.reject;
  const rr = replay.reject;
  const rows = [
    { key: "recall", label: "Metal recall", live: ratio(lr.recall), now: ratio(rr.recall) },
    { key: "precision", label: "Metal precision", live: ratio(lr.precision), now: ratio(rr.precision) },
    { key: "clean", label: "Clean loads passed", live: share(live.cleanPassed, live.cleanN), now: share(now.cleanPassed, now.cleanN) },
    { key: "review", label: "Sent to operator", live: share(live.escalated, live.graded), now: share(now.escalated, now.graded) },
  ];
  return (
    <div className="border-t border-seam px-4 py-3">
      <Table>
        <TableHeader>
          <TableRow className="hover:bg-raised">
            <TableHead className="px-2 sm:px-4" />
            <TableHead className="px-1.5 text-right sm:px-4">Live run</TableHead>
            <TableHead className="px-1.5 text-right sm:px-4">Current rules</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => (
            <TableRow key={row.key} className="hover:bg-transparent">
              <TableCell className="px-2 font-semibold text-ink sm:px-4">{row.label}</TableCell>
              <TableCell className="figure px-1.5 text-right text-[13px] text-muted sm:px-4">{row.live}</TableCell>
              <TableCell className="figure px-1.5 text-right text-[13px] font-semibold text-ink sm:px-4">{row.now}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <p className="figure m-0 mt-2 text-[12px] text-faint">
        Replay: recorded model outputs scored by today&apos;s rules — not a new measurement.
      </p>
    </div>
  );
}

/** Clean loads passed, loads sent to a person and escalate-expected loads escalated. */
function operatorCounts(confusion: Confusion) {
  const clean = confusion.accept;
  const esc = confusion.escalate;
  const graded = LABELS.reduce(
    (sum, row) => sum + confusion[row].reject + confusion[row].escalate + confusion[row].accept,
    0,
  );
  const escalated = LABELS.reduce((sum, row) => sum + confusion[row].escalate, 0);
  return {
    cleanPassed: clean.accept,
    cleanN: clean.reject + clean.escalate + clean.accept + clean.error,
    escalated,
    graded,
    escalateCaught: esc.escalate,
    escalateN: esc.reject + esc.escalate + esc.accept + esc.error,
  };
}

function share(k: number, n: number): string {
  return n > 0 ? ratio(k / n) : "—";
}

/** Confusion matrix, used inside the method detail. */
function ConfusionTable({ confusion }: { confusion: Confusion }) {
  return (
    <Table>
      <TableHeader>
        <TableRow className="hover:bg-raised">
          <TableHead className="px-2 sm:px-4">Expected</TableHead>
          {COLUMNS.map((c) => (
            <TableHead key={c} className="px-1.5 text-right text-[11px] tracking-[0.4px] sm:px-4 sm:text-[12px] sm:tracking-[1.2px]">
              {COLUMN_LABEL[c]}
            </TableHead>
          ))}
        </TableRow>
      </TableHeader>
      <TableBody>
        {LABELS.map((expected) => (
          <TableRow key={expected} className="hover:bg-transparent">
            <TableCell className="px-2 font-semibold text-ink sm:px-4">{COLUMN_LABEL[expected]}</TableCell>
            {COLUMNS.map((c) => (
              <TableCell
                key={c}
                className={
                  c === expected
                    ? "figure px-1.5 text-right text-[13px] font-semibold text-ink sm:px-4"
                    : "figure px-1.5 text-right text-[13px] text-muted sm:px-4"
                }
              >
                {confusion[expected][c]}
              </TableCell>
            ))}
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

/** Per-category table, used inside the method detail. */
function CategoryTable({ summary }: { summary: BenchmarkSummary }) {
  const rows = Object.entries(summary.per_category).sort(
    ([a], [b]) =>
      LABELS.indexOf(expectedFor(a)) - LABELS.indexOf(expectedFor(b)) || a.localeCompare(b),
  );
  if (rows.length === 0) return null;
  return (
    <Table>
      <TableHeader>
        <TableRow className="hover:bg-raised">
          <TableHead className="px-2 sm:px-4">Category</TableHead>
          <TableHead className="hidden px-2 sm:table-cell sm:px-4">Expected</TableHead>
          {COLUMNS.map((c) => (
            <TableHead key={c} className="px-1.5 text-right text-[11px] tracking-[0.4px] sm:px-4 sm:text-[12px] sm:tracking-[1.2px]">
              {COLUMN_LABEL[c]}
            </TableHead>
          ))}
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map(([category, cell]) => (
          <TableRow key={category} className="hover:bg-transparent">
            <TableCell className="px-2 font-semibold text-ink sm:px-4">{category}</TableCell>
            <TableCell className="hidden px-2 text-[12.5px] text-muted sm:table-cell sm:px-4">
              {COLUMN_LABEL[expectedFor(category)]}
            </TableCell>
            {COLUMNS.map((c) => (
              <TableCell key={c} className="figure px-1.5 text-right text-[13px] text-ink sm:px-4">
                {cell[c]}
              </TableCell>
            ))}
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

/** Latency, models, method, data — all inside the detail. */
function MethodDetail({ summary }: { summary: BenchmarkSummary }) {
  return (
    <div className="flex flex-col gap-4 pt-3">
      <dl className="m-0 grid grid-cols-1 gap-x-6 text-[12.5px] sm:grid-cols-2">
        <div className="flex justify-between gap-4 border-b border-seam py-2">
          <dt className="text-muted">End to end</dt>
          <dd className="figure m-0 text-ink">
            p50 {seconds(summary.total_ms.p50)} · p95 {seconds(summary.total_ms.p95)}
          </dd>
        </div>
        <div className="flex justify-between gap-4 border-b border-seam py-2">
          <dt className="text-muted">Vision model call</dt>
          <dd className="figure m-0 text-ink">
            p50 {seconds(summary.latency_ms.p50)} · p95 {seconds(summary.latency_ms.p95)}
          </dd>
        </div>
        <div className="flex justify-between gap-4 border-b border-seam py-2">
          <dt className="text-muted">Vision model</dt>
          <dd className="figure m-0 text-ink">{summary.vlm_model ?? "—"}</dd>
        </div>
        <div className="flex justify-between gap-4 border-b border-seam py-2">
          <dt className="text-muted">Language model</dt>
          <dd className="figure m-0 text-ink">{summary.llm_model ?? "—"}</dd>
        </div>
        <div className="flex justify-between gap-4 border-b border-seam py-2">
          <dt className="text-muted">Provider</dt>
          <dd className="m-0 text-ink">
            {summary.provider ? providerName(summary.provider) : "—"}
          </dd>
        </div>
        <div className="flex justify-between gap-4 border-b border-seam py-2">
          <dt className="text-muted">Images</dt>
          <dd className="figure m-0 text-ink">{summary.n}</dd>
        </div>
      </dl>
      <div>
        <p className="smallcaps m-0 mb-2">Confusion matrix</p>
        <ConfusionTable confusion={summary.confusion} />
      </div>
      <div>
        <p className="smallcaps m-0 mb-2">By category</p>
        <CategoryTable summary={summary} />
      </div>
      <p className="m-0 text-[12px] leading-relaxed text-muted">
        Images: RealWaste (Single, Iranmanesh, Raad),{" "}
        <a href={DATASET_URL} className="text-amber underline underline-offset-2">
          UCI ML Repository
        </a>
        . Licence: UCI lists CC BY 4.0; the dataset README says CC BY-NC-SA 4.0 — the stricter
        terms are assumed.{" "}
        <a href="/benchmark/manifest.csv" className="text-amber underline underline-offset-2">
          Manifest
        </a>
        .
      </p>
    </div>
  );
}
