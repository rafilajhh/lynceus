"use client";

import { useCallback, useEffect, useState } from "react";
import { BookOpen, FlaskConical } from "lucide-react";
import { providerName } from "@/lib/format";
import {
  COLUMNS,
  LABELS,
  ValidationError,
  fetchBenchmark,
  type BenchmarkSummary,
  type Confusion,
  type ReplaySummary,
} from "@/lib/validation-api";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { PageBody, PageHeader } from "@/components/shell/page-header";
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
type Column = (typeof COLUMNS)[number];

const DATASET_URL = "https://archive.ics.uci.edu/dataset/908/realwaste";
const COLUMN_LABEL: Record<Column, string> = {
  reject: "Reject",
  escalate: "Escalate",
  accept: "Accept",
  error: "Error",
};

/** Outcome-bar colour per returned verdict (error = no verdict). */
const COLUMN_FILL: Record<Column, string> = {
  reject: "bg-danger",
  escalate: "bg-warning",
  accept: "bg-success",
  error: "bg-fg-faint",
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

function rowTotal(row: Record<Column, number>): number {
  return COLUMNS.reduce((sum, c) => sum + row[c], 0);
}

/** Loading / error states share the page frame and one centred card. */
function StateFrame({ children }: { children: React.ReactNode }) {
  return (
    <>
      <PageHeader crumb="Console / Model quality" title="Validation" />
      <PageBody>
        <section className="card">{children}</section>
      </PageBody>
    </>
  );
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
      <StateFrame>
        <div role="status" className="flex flex-col items-center gap-3 px-4 py-12 text-center">
          <span
            aria-hidden="true"
            className="h-6 w-6 animate-spin rounded-full border-2 border-line-strong border-t-brand"
          />
          <p className="text-[13px] text-fg-muted">Loading the benchmark summary.</p>
        </div>
      </StateFrame>
    );
  }

  if (state.kind === "error") {
    return (
      <StateFrame>
        <div role="alert" className="flex flex-col items-center gap-3 px-4 py-12 text-center">
          <p className="max-w-[52ch] text-[13.5px] text-fg-muted">
            {state.missing ? state.message : `The benchmark could not be loaded. ${state.message}`}
          </p>
          {state.missing ? null : (
            <Button variant="default" size="sm" onClick={() => void load()}>
              Retry
            </Button>
          )}
        </div>
      </StateFrame>
    );
  }

  const { summary } = state;
  return (
    <>
      <PageHeader
        crumb={`Console / Model quality · Live on AMD Token Factory, ${summary.date?.match(/^\d{4}-\d{2}-\d{2}/)?.[0] ?? summary.date ?? "—"}`}
        title="Validation"
      >
        {summary.complete ? (
          <Badge variant="accept" className="px-2.5 py-[5px]">
            Complete · {summary.n} images
          </Badge>
        ) : summary.n >= summary.manifest_n && summary.errors > 0 ? (
          // Every image ran, but some model calls errored: say so, not "partial".
          <Badge variant="escalate" className="px-2.5 py-[5px]">
            {summary.n} / {summary.manifest_n} images · {summary.errors} model{" "}
            {summary.errors === 1 ? "error" : "errors"}
          </Badge>
        ) : (
          <Badge variant="escalate" className="px-2.5 py-[5px]">
            Partial · {summary.n} / {summary.manifest_n} images
          </Badge>
        )}
        <a href="#method" className={buttonVariants({ variant: "default" })}>
          <BookOpen aria-hidden="true" className="h-3.5 w-3.5" />
          Method &amp; data
        </a>
      </PageHeader>
      <PageBody className="flex flex-col gap-6">
        <div className="flex items-center gap-2.5 rounded-[10px] border border-[#03A2FE33] bg-[#03A2FE10] px-4 py-3">
          <FlaskConical aria-hidden="true" className="h-4 w-4 shrink-0 text-[#0284C7]" />
          <p className="m-0 flex-1 text-[13px] text-fg">
            {summary.framing}.
            {summary.vlm_model ? ` Vision model: ${summary.vlm_model}.` : null}
          </p>
        </div>
        <Headline summary={summary} />
        <MetricRings summary={summary} />
        <div className="flex flex-col gap-4 xl:flex-row xl:items-stretch">
          <ConfusionCard confusion={summary.confusion} />
          <div className="flex w-full shrink-0 flex-col gap-4 xl:w-[420px]">
            {summary.replay ? <ReplayCard summary={summary} replay={summary.replay} /> : null}
            <RunDetails summary={summary} />
          </div>
        </div>
        <CategoryCard summary={summary} />
        <p id="method" className="m-0 scroll-mt-24 text-[12px] leading-[18px] text-fg-subtle">
          Images: RealWaste (Single, Iranmanesh, Raad),{" "}
          <a href={DATASET_URL} className="text-brand underline underline-offset-2">
            UCI ML Repository
          </a>
          . Licence: UCI lists CC BY 4.0; the dataset README says CC BY-NC-SA 4.0 — the stricter
          terms are assumed.{" "}
          <a href="/benchmark/manifest.csv" className="text-brand underline underline-offset-2">
            Manifest
          </a>
          .
        </p>
      </PageBody>
    </>
  );
}

/** Rejection metrics from the current-rules replay when available (shipped rules). */
function headlineMetrics(summary: BenchmarkSummary) {
  return summary.replay ? summary.replay.reject : summary.reject;
}

/** Headline: the verdict on the gate, in words. */
function Headline({ summary }: { summary: BenchmarkSummary }) {
  const r = headlineMetrics(summary);
  // Clean-load pass rate comes from the confusion's accept row, not from
  // reject precision (tp / (tp + fp)), which only looks similar.
  const clean = summary.replay ? operatorCounts(summary.replay.confusion) : null;
  return (
    <div className="flex flex-col gap-1.5 pt-2">
      <h2 className="m-0 max-w-[860px] font-display text-[clamp(22px,2.4vw,28px)] leading-[1.2] font-medium tracking-[-0.4px] text-fg">
        {summary.replay
          ? `Under current rules, the gate rejects ${r.tp} of ${r.tp + r.fn} metal loads and passes ${clean?.cleanPassed ?? 0} of ${clean?.cleanN ?? 0} clean loads.`
          : `Out of every ${r.tp + r.fn} loads carrying metal, the gate rejected ${r.tp}.`}
      </h2>
      <p className="figure m-0 text-[12px] text-fg-muted">
        n = {summary.n} · one run · 95% interval {wilson(r.tp, r.tp + r.fn)}
      </p>
    </div>
  );
}

/** 76px donut: track + clockwise arc from 12 o'clock, flat ends. */
function Ring({ value, stroke }: { value: number | null | undefined; stroke: string }) {
  const size = 76;
  const width = 7.6;
  const radius = (size - width) / 2;
  const circumference = 2 * Math.PI * radius;
  const v = typeof value === "number" && Number.isFinite(value) ? Math.min(1, Math.max(0, value)) : 0;
  return (
    <svg
      aria-hidden="true"
      width={size}
      height={size}
      viewBox={`0 0 ${size} ${size}`}
      className="shrink-0 -rotate-90"
    >
      <circle
        cx={size / 2}
        cy={size / 2}
        r={radius}
        fill="none"
        strokeWidth={width}
        className="stroke-surface-muted"
      />
      {v > 0 ? (
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          strokeWidth={width}
          strokeDasharray={`${v * circumference} ${circumference}`}
          className={stroke}
        />
      ) : null}
    </svg>
  );
}

function MetricRings({ summary }: { summary: BenchmarkSummary }) {
  const r = headlineMetrics(summary);
  const tone = (v: number | null | undefined) =>
    typeof v === "number" && v >= 0.8 ? "stroke-success" : "stroke-warning";
  const metrics = [
    {
      key: "recall",
      label: "Metal recall",
      value: r.recall,
      stroke: tone(r.recall),
      sub: `${r.tp} of ${r.tp + r.fn} metal images rejected`,
    },
    {
      key: "precision",
      label: "Metal precision",
      value: r.precision,
      stroke: tone(r.precision),
      sub: `${r.tp} of ${r.tp + r.fp} rejects were metal`,
    },
    {
      key: "f1",
      label: "F1 score",
      value: r.f1,
      stroke: "stroke-brand",
      sub: "Harmonic mean of recall and precision",
    },
  ];
  return (
    <dl className="m-0 grid grid-cols-1 gap-4 md:grid-cols-3">
      {metrics.map((m) => (
        <div key={m.key} className="card flex items-center gap-5 p-6">
          <Ring value={m.value} stroke={m.stroke} />
          <div className="flex min-w-0 flex-1 flex-col gap-1">
            <dt className="text-[13px] text-fg-muted">{m.label}</dt>
            <dd className="figure m-0 text-[clamp(28px,2.6vw,36px)] leading-tight font-light tracking-[-0.6px] text-fg">
              {ratio(m.value)}
            </dd>
            <p className="m-0 text-[12px] text-fg-muted">{m.sub}</p>
          </div>
        </div>
      ))}
    </dl>
  );
}

function CardHead({ title, sub }: { title: string; sub?: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5 border-b border-line px-5 py-4">
      <h2 className="m-0 font-display text-[17px] font-medium text-fg">{title}</h2>
      {sub ? <p className="m-0 text-[12px] text-fg-muted">{sub}</p> : null}
    </div>
  );
}

/** Confusion matrix as a heat grid: blue = correct, grey = wrong, red = model error. */
function ConfusionCard({ confusion }: { confusion: Confusion }) {
  const max = Math.max(1, ...LABELS.flatMap((row) => COLUMNS.map((c) => confusion[row][c])));
  const cellStyle = (expected: Label, c: Column, v: number) => {
    if (v === 0) return { className: "bg-surface-subtle text-fg-faint", style: undefined };
    const t = v / max;
    if (c === expected) {
      const alpha = 0.22 + 0.72 * t;
      return {
        className: alpha > 0.6 ? "text-white" : "text-fg",
        style: { backgroundColor: `rgb(37 99 235 / ${alpha.toFixed(2)})` },
      };
    }
    if (c === "error") {
      return { className: "text-fg", style: { backgroundColor: `rgb(234 38 48 / ${(0.18 + 0.3 * t).toFixed(2)})` } };
    }
    return { className: "text-fg", style: { backgroundColor: `rgb(24 25 27 / ${(0.22 + 0.4 * t).toFixed(2)})` } };
  };

  return (
    <section className="card flex min-w-0 flex-1 flex-col" aria-labelledby="confusion-title">
      <div className="flex flex-col gap-0.5 border-b border-line px-5 py-4">
        <h2 id="confusion-title" className="m-0 font-display text-[17px] font-medium text-fg">
          Confusion matrix
        </h2>
        <p className="m-0 text-[12px] text-fg-muted">
          Rows: expected verdict · Columns: what the gate returned
        </p>
      </div>
      <div className="flex flex-1 flex-col justify-center p-4 sm:p-5">
        <table className="w-full border-separate border-spacing-1.5">
          <thead>
            <tr>
              <th scope="col" className="w-[64px] sm:w-[96px]">
                <span className="sr-only">Expected</span>
              </th>
              {COLUMNS.map((c) => (
                <th
                  key={c}
                  scope="col"
                  className="pb-1 text-center font-mono text-[11px] font-normal tracking-[0.4px] text-fg-muted"
                >
                  {COLUMN_LABEL[c]}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {LABELS.map((expected) => (
              <tr key={expected}>
                <th scope="row" className="text-left text-[13px] font-medium text-fg">
                  {COLUMN_LABEL[expected]}
                </th>
                {COLUMNS.map((c) => {
                  const v = confusion[expected][c];
                  const s = cellStyle(expected, c, v);
                  return (
                    <td
                      key={c}
                      style={s.style}
                      className={cn(
                        "figure h-16 rounded-[8px] text-center text-[18px] sm:h-[104px] sm:text-[20px]",
                        s.className,
                      )}
                    >
                      {v}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
        <ul className="m-0 flex list-none flex-wrap gap-x-4 gap-y-1 p-0 pt-2.5 sm:pl-[102px]" aria-hidden="true">
          <li className="flex items-center gap-1.5 text-[12px] text-fg-muted">
            <span className="h-2.5 w-2.5 rounded-[2px] bg-brand" /> Correct verdict
          </li>
          <li className="flex items-center gap-1.5 text-[12px] text-fg-muted">
            <span className="h-2.5 w-2.5 rounded-[2px] bg-fg/40" /> Wrong verdict
          </li>
          <li className="flex items-center gap-1.5 text-[12px] text-fg-muted">
            <span className="h-2.5 w-2.5 rounded-[2px] bg-danger/50" /> Model error
          </li>
        </ul>
      </div>
    </section>
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

/** Live vs current rules. */
function ReplayCard({ summary, replay }: { summary: BenchmarkSummary; replay: ReplaySummary }) {
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
    <section className="card" aria-label="Live run vs. current rules">
      <CardHead
        title="Live run vs. current rules"
        sub="Replay: recorded outputs scored by today's rules — not a new measurement"
      />
      <Table>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead className="pl-5">Metric</TableHead>
            <TableHead className="w-[90px] text-right">Live run</TableHead>
            <TableHead className="w-[100px] pr-5 text-right">Current rules</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => (
            <TableRow key={row.key} className="hover:bg-transparent">
              <TableCell className="h-auto py-3 pl-5 text-[13px] text-fg">{row.label}</TableCell>
              <TableCell className="figure h-auto py-3 text-right text-[13px] text-fg-muted">{row.live}</TableCell>
              <TableCell className="figure h-auto py-3 pr-5 text-right text-[13px] font-medium text-fg">{row.now}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </section>
  );
}

/** Latency, models, provider, images. */
function RunDetails({ summary }: { summary: BenchmarkSummary }) {
  const items: { key: string; label: string; value: string; mono?: boolean }[] = [
    { key: "total", label: "End to end", value: `p50 ${seconds(summary.total_ms.p50)} · p95 ${seconds(summary.total_ms.p95)}` },
    { key: "vlm-call", label: "Vision model call", value: `p50 ${seconds(summary.latency_ms.p50)} · p95 ${seconds(summary.latency_ms.p95)}` },
    { key: "vlm", label: "Vision model", value: summary.vlm_model ?? "—" },
    { key: "llm", label: "Language model", value: summary.llm_model ?? "—" },
    { key: "provider", label: "Provider", value: summary.provider ? providerName(summary.provider) : "—" },
    { key: "images", label: "Images", value: String(summary.n) },
  ];
  return (
    <section className="card flex-1" aria-label="Run details">
      <CardHead title="Run details" />
      <dl className="m-0 flex flex-col px-5 pt-1.5 pb-2.5">
        {items.map((item) => (
          <div key={item.key} className="flex items-center justify-between gap-4 py-[9px]">
            <dt className="shrink-0 text-[13px] text-fg-muted">{item.label}</dt>
            <dd className="figure m-0 min-w-0 truncate text-right text-[12px] text-fg" title={item.value}>
              {item.value}
            </dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

/** "10 images per waste class · 20 metal" when the non-metal classes are even. */
function categorySub(rows: [string, Record<Column, number>][]): string {
  const totals = rows.map(([name, cell]) => [name, rowTotal(cell)] as const);
  const metal = totals.find(([name]) => name === "Metal")?.[1];
  const others = totals.filter(([name]) => name !== "Metal").map(([, n]) => n);
  if (others.length > 0 && others.every((n) => n === others[0])) {
    return `${others[0]} images per waste class${metal !== undefined ? ` · ${metal} metal` : ""}`;
  }
  const n = totals.reduce((sum, [, t]) => sum + t, 0);
  return `${n} images across ${rows.length} classes`;
}

/** Per-category outcome table with a stacked bar of what the gate returned. */
function CategoryCard({ summary }: { summary: BenchmarkSummary }) {
  const rows = Object.entries(summary.per_category).sort(
    ([a], [b]) =>
      LABELS.indexOf(expectedFor(a)) - LABELS.indexOf(expectedFor(b)) || a.localeCompare(b),
  );
  if (rows.length === 0) return null;
  return (
    <section className="card" aria-label="By category">
      <CardHead title="By category" sub={categorySub(rows)} />
      <Table>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead className="pl-5">Category</TableHead>
            <TableHead className="hidden w-[160px] sm:table-cell">Expected</TableHead>
            <TableHead className="hidden w-[320px] lg:table-cell">Outcome</TableHead>
            {COLUMNS.map((c, i) => (
              <TableHead
                key={c}
                className={cn("w-[64px] px-2 text-right sm:w-[80px] sm:px-4", i === COLUMNS.length - 1 && "pr-5 sm:pr-5")}
              >
                {COLUMN_LABEL[c]}
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map(([category, cell]) => {
            const expected = expectedFor(category);
            const total = rowTotal(cell);
            return (
              <TableRow key={category} className="hover:bg-transparent">
                <TableCell className="h-12 pl-5 text-[14px] font-medium text-fg">{category}</TableCell>
                <TableCell className="hidden h-12 sm:table-cell">
                  <Badge variant={expected}>{COLUMN_LABEL[expected]}</Badge>
                </TableCell>
                <TableCell className="hidden h-12 pr-10 lg:table-cell">
                  <div
                    role="img"
                    aria-label={COLUMNS.map((c) => `${COLUMN_LABEL[c]} ${cell[c]}`).join(", ")}
                    className="flex h-2 w-full max-w-[280px] gap-0.5"
                  >
                    {total > 0
                      ? COLUMNS.filter((c) => cell[c] > 0).map((c) => (
                          <div
                            key={c}
                            className={cn("h-full rounded-[2px]", COLUMN_FILL[c])}
                            style={{ flexGrow: cell[c], flexBasis: 0 }}
                          />
                        ))
                      : null}
                  </div>
                </TableCell>
                {COLUMNS.map((c, i) => {
                  const v = cell[c];
                  return (
                    <TableCell
                      key={c}
                      className={cn(
                        "figure h-12 px-2 text-right text-[13px] sm:px-4",
                        i === COLUMNS.length - 1 && "pr-5 sm:pr-5",
                        v === 0
                          ? "text-fg-faint"
                          : c === "error"
                            ? "text-danger"
                            : c === expected
                              ? "font-medium text-fg"
                              : "text-fg-muted",
                      )}
                    >
                      {v}
                    </TableCell>
                  );
                })}
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </section>
  );
}
