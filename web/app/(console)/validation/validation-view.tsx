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
  type ReplaySummary,
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
  const framing = summary.framing.charAt(0).toUpperCase() + summary.framing.slice(1);
  return (
    <div className="flex flex-col gap-4">
      <Panel aria-labelledby="validation-title">
        <PanelHead title="Validation" meta={summary.date ?? undefined} />
        <h1 id="validation-title" className="sr-only">
          Validation benchmark
        </h1>
        <HeadlineRun summary={summary} />
        <p className="m-0 max-w-[78ch] border-t border-seam px-4 pt-3 text-[13px] leading-relaxed text-muted">
          {framing}. Each image was posted live through the gate&apos;s API code to the vision
          model on AMD Token Factory, with the same neutral waybill and a consistent weight, so
          the weight and cross-check gates pass and the photo decides. Scripted demo cases were
          not used.
        </p>
        <Incomplete summary={summary} />
      </Panel>

      {summary.replay ? <ReplayPanel summary={summary} replay={summary.replay} /> : null}

      <Panel>
        <PanelHead title="Confusion matrix" meta="live run · rows: expected · columns: gate verdict" />
        <p className="m-0 border-b border-seam px-4 py-2.5 text-[13px] text-muted">
          <strong className="font-semibold text-ink">Escalate is policy, not vision error:</strong>{" "}
          in this live run, light contaminants (plastic film, glass, textile) were escalated by
          rule; only metal, rock, concrete, tyre and e-waste are rejected.
        </p>
        <ConfusionTable confusion={summary.confusion} />
        <details className="group border-t border-seam px-4 py-3">
          <summary className="cursor-pointer select-none text-[13px] font-semibold text-ink transition-colors hover:text-amber">
            Why accept and escalate disagree
          </summary>
          <p className="m-0 mt-2 max-w-[78ch] text-[12.5px] leading-relaxed text-muted">
            The headline above is the hard-contaminant gate only, with metal as the positive
            class. Where the matrix shows accept and escalate disagreeing, part of that reflects
            policy (textile trash and plastic expected to accept were escalated for plastic film
            or textile, which the current rules treat as RDF feedstock), not vision error. In
            this run, one of the three false rejects (a plastic image) came from the vision
            model&apos;s free-text description mentioning a &quot;concrete floor&quot;, which the
            gate then matched as a hard-contaminant word; the current rules read hard
            contaminants from the structured list only. The Error column counts refusals and
            failed requests; they are never counted as correct.
          </p>
        </details>
      </Panel>

      <Panel>
        <PanelHead title="By category" meta="verdict per RealWaste class" />
        <CategoryTable summary={summary} />
      </Panel>

      <Panel>
        <PanelHead title="Latency and models" />
        <LatencyAndModels summary={summary} />
      </Panel>

      <p className="figure m-0 px-1 text-[13px] text-muted">
        <span className="text-ink">{ratio(summary.reject.recall)}</span> recall ·{" "}
        <span className="text-ink">{ratio(summary.reject.precision)}</span> precision ·{" "}
        n = <span className="text-ink">{summary.n}</span> · one run · raw data linked above
      </p>
    </div>
  );
}

/** Headline: the verdict on the gate, in numbers and in words. */
function HeadlineRun({ summary }: { summary: BenchmarkSummary }) {
  const r = summary.reject;
  const caught = `${r.tp} of ${r.tp + r.fn}`;
  const parts = [
    {
      key: "recall",
      value: ratio(r.recall),
      label: "recall",
      sub: `${caught} metal images rejected (95% interval ${wilson(r.tp, r.tp + r.fn)})`,
    },
    {
      key: "precision",
      value: ratio(r.precision),
      label: "precision",
      sub: `${r.tp} of ${r.tp + r.fp} rejects were metal (95% interval ${wilson(r.tp, r.tp + r.fp)})`,
    },
    { key: "f1", value: ratio(r.f1), label: "F1", sub: null as string | null },
  ];
  return (
    <div className="px-4 pt-4 pb-4">
      <p className="smallcaps m-0 mb-3">Metal gate</p>
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
        Out of every {r.tp + r.fn} loads carrying metal, the gate rejected {r.tp}.
      </p>
      <p className="figure m-0 mt-2 text-[12px] text-faint">
        n = {summary.n} images · {summary.errors} errors or refusals in the final results (an error on a
        metal image counts as a miss) · one run, small sample: the intervals are wide
      </p>
    </div>
  );
}

/** Failed-then-retried requests are disclosed; latency figures cover completed ones. */
function Retries({ summary }: { summary: BenchmarkSummary }) {
  const a = summary.attempt_stats;
  if (!a || a.retried === 0) return null;
  return (
    <p className="m-0 border-t border-seam px-4 py-3 text-[13px] text-muted">
      <span className="figure text-ink">{a.retried}</span> of{" "}
      <span className="figure text-ink">{a.attempts}</span> requests timed out on the shared
      endpoint and were retried; latency covers completed requests (all-attempt p95{" "}
      <span className="figure text-ink">{seconds(a.total_ms.p95)}</span>, longest{" "}
      <span className="figure text-ink">{seconds(a.total_ms.max)}</span>).
    </p>
  );
}

function Incomplete({ summary }: { summary: BenchmarkSummary }) {
  if (summary.complete) return null;
  return (
    <p role="note" className="m-0 border-t border-seam px-4 py-3 text-[13px] text-muted">
      <strong className="font-semibold text-ink">Partial run:</strong>{" "}
      <span className="figure">{summary.n}</span> of{" "}
      <span className="figure">{summary.manifest_n}</span> manifest images were completed.
    </p>
  );
}

/** Clean loads passed and loads sent to a person, counted from a confusion matrix
 * (same definitions as backend/benchmark/metrics.py). */
function operatorCounts(confusion: Confusion) {
  const clean = confusion.accept;
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
  };
}

function share(k: number, n: number): string {
  return n > 0 ? ratio(k / n) : "—";
}

/** The same recorded model outputs, scored by the rules the gate runs today. */
function ReplayPanel({ summary, replay }: { summary: BenchmarkSummary; replay: ReplaySummary }) {
  const live = operatorCounts(summary.confusion);
  const now = operatorCounts(replay.confusion);
  const lr = summary.reject;
  const rr = replay.reject;
  const rows = [
    {
      key: "recall",
      label: "Metal recall",
      live: ratio(lr.recall),
      liveSub: `${lr.tp} of ${lr.tp + lr.fn}`,
      now: ratio(rr.recall),
      nowSub: `${rr.tp} of ${rr.tp + rr.fn}`,
    },
    {
      key: "precision",
      label: "Metal precision",
      live: ratio(lr.precision),
      liveSub: `${lr.tp} of ${lr.tp + lr.fp}`,
      now: ratio(rr.precision),
      nowSub: `${rr.tp} of ${rr.tp + rr.fp}`,
    },
    {
      key: "clean",
      label: "Clean loads passed",
      live: share(live.cleanPassed, live.cleanN),
      liveSub: `${live.cleanPassed} of ${live.cleanN}`,
      now: share(now.cleanPassed, now.cleanN),
      nowSub: `${now.cleanPassed} of ${now.cleanN}`,
    },
    {
      key: "review",
      label: "Sent to operator review",
      live: share(live.escalated, live.graded),
      liveSub: `${live.escalated} of ${live.graded}`,
      now: share(now.escalated, now.graded),
      nowSub: `${now.escalated} of ${now.graded}`,
    },
  ];
  const changed = replay.changed ?? [];
  return (
    <Panel aria-labelledby="replay-title">
      <PanelHead title="Current rules" meta="replay of this run" />
      <p id="replay-title" className="m-0 border-b border-seam px-4 py-2.5 text-[13px] text-muted">
        <strong className="font-semibold text-ink">Replay:</strong> {replay.framing}
      </p>
      <Table>
        <TableHeader>
          <TableRow className="hover:bg-raised">
            <TableHead className="px-2 sm:px-4">Measure</TableHead>
            <TableHead className="px-1.5 text-right sm:px-4">Live run</TableHead>
            <TableHead className="px-1.5 text-right sm:px-4">Current rules</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => (
            <TableRow key={row.key} className="hover:bg-transparent">
              <TableCell className="px-2 font-semibold text-ink sm:px-4">{row.label}</TableCell>
              <TableCell className="figure px-1.5 text-right text-[13px] text-muted sm:px-4">
                {row.live}
                <span className="block text-[11.5px]">{row.liveSub}</span>
              </TableCell>
              <TableCell className="figure px-1.5 text-right text-[13px] font-semibold text-ink sm:px-4">
                {row.now}
                <span className="block text-[11.5px] font-normal text-muted">{row.nowSub}</span>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <details className="group border-t border-seam px-4 py-3">
        <summary className="cursor-pointer select-none text-[13px] font-semibold text-ink transition-colors hover:text-amber">
          What changed, and why this is not a new measurement
        </summary>
        <p className="m-0 mt-2 max-w-[78ch] text-[12.5px] leading-relaxed text-muted">
          The current rules treat plastic film and textile as RDF feedstock, not as light
          contaminants, and read hard contaminants from the vision model&apos;s structured list
          only. Glass, organic residue and wet mix still go to a person.{" "}
          {replay.disclosure ?? null}
        </p>
        {replay.llm_note ? (
          <p className="m-0 mt-2 max-w-[78ch] text-[12.5px] leading-relaxed text-muted">
            {replay.llm_note}
          </p>
        ) : null}
        {changed.length ? (
          <p className="m-0 mt-2 max-w-[78ch] text-[12.5px] leading-relaxed text-muted">
            <span className="figure text-ink">{changed.length}</span> of{" "}
            <span className="figure text-ink">{replay.n}</span> verdicts changed:{" "}
            {changed
              .map((c) => `${c.image} (expected ${c.expected}: ${c.recorded} → ${c.replay})`)
              .join("; ")}
            .
          </p>
        ) : null}
        <div className="mt-3">
          <ConfusionTable confusion={replay.confusion} />
        </div>
      </details>
    </Panel>
  );
}

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

function CategoryTable({ summary }: { summary: BenchmarkSummary }) {
  const rows = Object.entries(summary.per_category).sort(
    ([a], [b]) =>
      LABELS.indexOf(expectedFor(a)) - LABELS.indexOf(expectedFor(b)) || a.localeCompare(b),
  );
  if (rows.length === 0) {
    return (
      <p className="m-0 px-4 py-4 text-[13px] text-muted">
        No per-category counts in this summary.
      </p>
    );
  }
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
            <TableCell className="px-2 font-semibold text-ink sm:px-4">
              {category}
              <span className="block text-[11.5px] font-normal text-muted sm:hidden">
                expect {COLUMN_LABEL[expectedFor(category)].toLowerCase()}
              </span>
            </TableCell>
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

function LatencyAndModels({ summary }: { summary: BenchmarkSummary }) {
  const rows: [string, React.ReactNode][] = [
    [
      "Request, end to end",
      <span key="t" className="figure text-ink">
        p50 {seconds(summary.total_ms.p50)} · p95 {seconds(summary.total_ms.p95)}
      </span>,
    ],
    [
      "Vision model call",
      <span key="v" className="figure text-ink">
        p50 {seconds(summary.latency_ms.p50)} · p95 {seconds(summary.latency_ms.p95)}
      </span>,
    ],
    ["Vision model", <span key="vm" className="figure text-ink">{summary.vlm_model ?? "—"}</span>],
    ["Language model", <span key="lm" className="figure text-ink">{summary.llm_model ?? "—"}</span>],
    [
      "Provider",
      <span key="p" className="text-ink">
        {summary.provider ? providerName(summary.provider) : "—"}
        {summary.provenance.length ? (
          <span className="figure text-muted"> · provenance {summary.provenance.join(", ")}</span>
        ) : null}
      </span>,
    ],
    ["Run date", <span key="d" className="figure text-ink">{summary.date ?? "—"} (UTC)</span>],
    ["Images", <span key="n" className="figure text-ink">{summary.n}</span>],
  ];
  if (summary.manual_check_seconds && summary.source_url) {
    rows.splice(2, 0, [
      "Manual check",
      <span key="m" className="figure text-ink">
        {summary.manual_check_seconds} s per truck (
        <a href={summary.source_url} className="text-amber underline underline-offset-2">
          source
        </a>
        )
      </span>,
    ]);
  }
  return (
    <>
      <dl className="m-0 grid grid-cols-1 text-[13px] sm:grid-cols-[13rem_1fr]">
        {rows.map(([term, value]) => (
          <div key={term} className="contents">
            <dt className="border-b border-seam px-4 pt-2.5 text-muted sm:py-2.5">{term}</dt>
            <dd className="m-0 border-b border-seam px-4 pb-2.5 sm:py-2.5">{value}</dd>
          </div>
        ))}
      </dl>
      <Retries summary={summary} />
      <details className="group px-4 py-3">
        <summary className="cursor-pointer select-none text-[13px] font-semibold text-ink transition-colors hover:text-amber">
          Method, data &amp; licence
        </summary>
        <p className="m-0 mt-2 max-w-[78ch] text-[12.5px] leading-relaxed text-muted">
          Latency is measured through the live endpoint and includes provider queueing; it is
          not a hardware benchmark. No manual-inspection time is compared: no citable per-truck
          figure was found (see docs/research/token-factory-probe.md).
        </p>
        <p className="m-0 mt-2 max-w-[78ch] text-[12.5px] leading-relaxed text-muted">
          Images: RealWaste (Single, Iranmanesh, Raad),{" "}
          <a href={DATASET_URL} className="text-amber underline underline-offset-2">
            UCI ML Repository
          </a>
          . UCI lists the licence as CC BY 4.0; the README inside the dataset says CC BY-NC-SA
          4.0, so the stricter terms are assumed. 6 of the 80 files were re-encoded to fit 200
          KB; none were resized. The image list and expected verdicts are in the{" "}
          <a href="/benchmark/manifest.csv" className="text-amber underline underline-offset-2">
            manifest
          </a>
          .
        </p>
      </details>
    </>
  );
}
