"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { providerName } from "@/lib/format";
import { cn } from "@/lib/utils";
import {
  COLUMNS,
  LABELS,
  ValidationError,
  fetchBenchmark,
  type BenchmarkSummary,
  type Confusion,
  type HybridSummary,
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
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** Gate outcome names, as the gate operator sees them. */
const COLUMN_LABEL: Record<(typeof COLUMNS)[number], string> = {
  reject: "Reject",
  escalate: "Hold",
  accept: "Accept",
  error: "Error",
};

/** What each expected row holds, in the gate's words. */
const ROW_LABEL: Record<Label, string> = {
  reject: "Metal (should reject)",
  escalate: "Glass, food, vegetation (should hold)",
  accept: "Clean RDF (should accept)",
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

function pct(k: number, n: number): string {
  return n > 0 ? `${Math.round((k / n) * 100)} %` : "—";
}

/** 95% Wilson score interval for k of n, as "0.22 to 0.61"; "—" when n is 0. */
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

/** "2026-10-17.deepseek-vision-exp" → "17 Oct 2026"; a run id without a date stays as is. */
function runDate(run: string | null | undefined): string | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(run ?? "");
  if (!m) return run ?? null;
  return `${Number(m[3])} ${MONTHS[Number(m[2]) - 1] ?? m[2]} ${m[1]}`;
}

/** Backend sentences may start lower-case or end without a stop: tidy, never reword. */
function sentence(text: string): string {
  const t = text.trim();
  if (!t) return t;
  const head = t.charAt(0).toUpperCase() + t.slice(1);
  return /[.!?]$/.test(head) ? head : `${head}.`;
}

const rowTotal = (row: Confusion["reject"]) => row.reject + row.escalate + row.accept + row.error;

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
    const bar = "rounded-[4px] bg-raised animate-[gate-pulse_1.1s_ease-in-out_infinite]";
    return (
      <Panel role="status">
        <PanelHead title="Validation" />
        <span className="sr-only">Loading the benchmark summary</span>
        <div aria-hidden="true" className="flex flex-col gap-3 px-5 py-6">
          <div className={cn(bar, "h-4 w-[60%]")} />
          <div className={cn(bar, "h-14 w-[40%]")} />
          <div className={cn(bar, "h-5 w-[70%]")} />
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
            {state.missing
              ? `${state.message} Run the benchmark (backend/benchmark/README) and commit its summary to show it here.`
              : `The benchmark could not be loaded. ${state.message}`}
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
      {summary.hybrid ? (
        <ShippedGatePanel hybrid={summary.hybrid} summary={summary} />
      ) : (
        <h1 className="sr-only">Validation benchmark</h1>
      )}
      <VisionOnlyPanel summary={summary} demoted={summary.hybrid !== null && summary.hybrid !== undefined} />
    </div>
  );
}

/**
 * The shipped gate: the vision model's recorded live outputs fused with the
 * CPU detector (light detections hold the truck). Leads with the safety
 * outcome, metal let through, in counts an operator can check.
 */
function ShippedGatePanel({ hybrid, summary }: { hybrid: HybridSummary; summary: BenchmarkSummary }) {
  const v = hybrid.variants.hybrid_light_escalation_on;
  const t = hybrid.table.hybrid_light_escalation_on;
  const metal = v.confusion.reject;
  const holdRow = v.confusion.escalate;
  const clean = v.confusion.accept;
  const metalN = rowTotal(metal);
  const holdN = rowTotal(holdRow);
  const cleanN = rowTotal(clean);
  const letThrough = t.metal_accepted ?? metal.accept;
  const sentToPerson = LABELS.reduce((sum, row) => sum + v.confusion[row].escalate, 0);
  const allHeld = holdN > 0 && holdRow.escalate === holdN;
  const detector = hybrid.detector;
  const scope = hybrid.scope ?? summary.framing;

  const headline = [
    `${letThrough} of ${metalN} metal photos let through`,
    `${clean.accept} of ${cleanN} clean loads passed`,
    allHeld
      ? "every glass and organic load held"
      : `${holdRow.escalate} of ${holdN} glass and organic loads held`,
  ].join(" · ");

  return (
    <Panel aria-labelledby="shipped-gate-title">
      <PanelHead title="Validation · shipped gate" meta={runDate(hybrid.source_run) ?? "replay"} />
      <p className="m-0 flex items-start gap-2 border-b border-seam px-5 py-2.5 text-[13px] leading-snug text-muted">
        <span aria-hidden="true" className="mt-[7px] h-1.5 w-1.5 shrink-0 rounded-full bg-dot-idle" />
        <span>
          {sentence(scope)} {v.graded} photos with known contents, re-scored offline from a live
          AMD run.
        </span>
      </p>

      <div className="px-5 pt-5 pb-5">
        <h1 id="shipped-gate-title" className="m-0 max-w-[62ch] text-[19px] leading-[1.4] font-semibold text-balance text-ink sm:text-[21px]">
          {headline}
        </h1>
        <p className="m-0 mt-2 max-w-[70ch] text-[13.5px] leading-relaxed text-muted">
          The gate that ships pairs the vision model with a CPU detector: when either one sees a
          hard or doubtful item the truck is held for a person, so no metal photo was waved through.
        </p>
      </div>

      <div className="grid border-t border-seam lg:grid-cols-[1.25fr_1fr_1fr]">
        <Outcome
          lead
          value={String(letThrough)}
          of={metalN}
          label="metal photos let through"
          detail={`${metal.reject} rejected outright, ${metal.escalate} held for an operator`}
          tone={letThrough > 0 ? "text-verdict-red" : "text-ink"}
        />
        <Outcome
          value={String(clean.accept)}
          of={cleanN}
          label="clean loads passed"
          detail={`${clean.escalate} held for a look, ${clean.reject} rejected by mistake`}
        />
        <Outcome
          value={String(holdRow.escalate)}
          of={holdN}
          label="glass and organic loads held"
          detail={`${holdRow.accept} passed, ${holdRow.reject} rejected`}
        />
      </div>

      <p className="m-0 border-t border-seam px-5 py-3 text-[13px] leading-relaxed text-muted">
        The cost of that caution:{" "}
        <span className="figure font-semibold text-ink">
          {sentToPerson} of {v.graded}
        </span>{" "}
        photos ({pct(sentToPerson, v.graded)}) go to a person, and{" "}
        <span className="figure font-semibold text-ink">{v.gate_correct ?? ratio(t.gate_accuracy)}</span>{" "}
        get the expected outcome.
      </p>
      <p className="figure m-0 border-t border-seam px-5 py-2.5 text-[12px] break-words text-faint">
        Graded {v.graded} of {v.n} · {v.errors} {v.errors === 1 ? "error" : "errors"}
        {hybrid.vlm_model ? ` · ${hybrid.vlm_model}` : ""}
        {detector?.model ? ` + ${detector.model}` : ""}
        {detector?.runtime ? ` (${detector.runtime})` : ""}
      </p>

      <details className="group border-t border-seam px-5 py-3">
        <summary className="cursor-pointer text-[13px] font-semibold text-ink transition-colors duration-100 select-none hover:text-amber">
          What this replay is, and is not
        </summary>
        <div className="flex max-w-[80ch] flex-col gap-2 pt-2 text-[12.5px] leading-relaxed text-muted">
          {hybrid.framing ? <p className="m-0">{sentence(hybrid.framing)}</p> : null}
          {hybrid.disclosure ? <p className="m-0">{sentence(hybrid.disclosure)}</p> : null}
          {hybrid.llm_note ? <p className="m-0">{sentence(hybrid.llm_note)}</p> : null}
        </div>
      </details>
    </Panel>
  );
}

function Outcome({
  value,
  of,
  label,
  detail,
  tone = "text-ink",
  lead = false,
}: {
  value: string;
  of: number;
  label: string;
  detail: string;
  tone?: string;
  lead?: boolean;
}) {
  return (
    <div className="flex flex-col gap-1.5 border-b border-seam px-5 py-4 last:border-b-0 lg:border-b-0 lg:border-l lg:first:border-l-0">
      <p className="m-0 flex items-baseline gap-1.5 whitespace-nowrap">
        <span
          className={cn(
            "figure leading-none font-semibold tracking-[-0.02em]",
            lead ? "text-[clamp(40px,5vw,56px)]" : "text-[clamp(30px,3.4vw,38px)]",
            tone,
          )}
        >
          {value}
        </span>
        <span className="figure text-[15px] text-faint">/ {of}</span>
      </p>
      <p className="m-0 text-[14px] font-semibold text-ink">{label}</p>
      <p className="m-0 text-[12.5px] leading-snug text-muted">{detail}</p>
    </div>
  );
}

/** The vision model on its own, the live run: what the detector is there to fix. */
function VisionOnlyPanel({ summary, demoted }: { summary: BenchmarkSummary; demoted: boolean }) {
  const r = summary.reject;
  const metalN = r.tp + r.fn;
  const live = summary.confusion;
  const passed = live.reject.accept;
  const date = runDate(summary.date);
  return (
    <Panel aria-labelledby="vlm-only-title">
      <PanelHead
        title="Vision model alone · live run"
        meta={summary.complete ? (date ?? undefined) : `partial · ${summary.n} of ${summary.manifest_n}`}
      />
      <div className="px-5 pt-4 pb-4">
        {demoted ? (
          <h2 id="vlm-only-title" className="m-0 text-[15px] font-semibold text-ink">
            On its own, the vision model rejected {r.tp} of {metalN} metal photos and passed {passed}.
          </h2>
        ) : (
          <h1 id="vlm-only-title" className="m-0 text-[19px] font-semibold text-ink">
            On its own, the vision model rejected {r.tp} of {metalN} metal photos and passed {passed}.
          </h1>
        )}
        <p className="m-0 mt-1.5 max-w-[72ch] text-[13.5px] leading-relaxed text-muted">
          Every one of its {r.tp + r.fp} rejects was metal (no false alarm), but it missed the
          rest: the reason the shipped gate adds a second look. Live on{" "}
          {summary.provider ? providerName(summary.provider) : "the model provider"}
          {date ? `, ${date}` : ""}.
        </p>
        <dl className="m-0 mt-4 grid max-w-[560px] grid-cols-3 gap-px overflow-hidden rounded-[10px] border border-seam bg-seam">
          {[
            { key: "recall", label: "Metal recall", value: ratio(r.recall), sub: `${r.tp} of ${metalN}` },
            { key: "precision", label: "Precision", value: ratio(r.precision), sub: `${r.tp} of ${r.tp + r.fp}` },
            { key: "f1", label: "F1", value: ratio(r.f1), sub: `n = ${summary.n}` },
          ].map((m) => (
            <div key={m.key} className="flex flex-col gap-0.5 bg-panel px-3.5 py-3">
              <dt className="text-[12px] font-semibold text-muted">{m.label}</dt>
              <dd className="figure m-0 text-[22px] leading-tight font-semibold text-ink">{m.value}</dd>
              <span className="figure text-[11.5px] text-faint">{m.sub}</span>
            </div>
          ))}
        </dl>
        <p className="figure m-0 mt-2 text-[12px] text-faint">
          One run · 95 % interval for recall {wilson(r.tp, metalN)}
        </p>
      </div>
      {summary.replay ? <ReplayNote summary={summary} replay={summary.replay} /> : null}
      <details className="group border-t border-seam px-5 py-3">
        <summary className="cursor-pointer text-[13px] font-semibold text-ink transition-colors duration-100 select-none hover:text-amber">
          Method, data and per-category detail
        </summary>
        <MethodDetail summary={summary} />
      </details>
    </Panel>
  );
}

function sameConfusion(a: Confusion, b: Confusion): boolean {
  return LABELS.every((row) => COLUMNS.every((col) => a[row][col] === b[row][col]));
}

/**
 * Live run vs the same outputs re-scored under today's rules. Identical
 * columns say nothing twice: one sentence states the result instead.
 */
function ReplayNote({ summary, replay }: { summary: BenchmarkSummary; replay: ReplaySummary }) {
  if (sameConfusion(summary.confusion, replay.confusion)) {
    return (
      <p className="m-0 border-t border-seam px-5 py-2.5 text-[13px] leading-relaxed text-muted">
        Re-scored under today&apos;s decision rules: every verdict is unchanged.
      </p>
    );
  }
  const live = operatorCounts(summary.confusion);
  const now = operatorCounts(replay.confusion);
  const rows = [
    { key: "recall", label: "Metal rejected", live: share(summary.reject.tp, summary.reject.tp + summary.reject.fn), now: share(replay.reject.tp, replay.reject.tp + replay.reject.fn) },
    { key: "clean", label: "Clean loads passed", live: share(live.cleanPassed, live.cleanN), now: share(now.cleanPassed, now.cleanN) },
    { key: "review", label: "Sent to an operator", live: share(live.escalated, live.graded), now: share(now.escalated, now.graded) },
  ];
  return (
    <div className="border-t border-seam px-5 py-3">
      <Table>
        <TableHeader>
          <TableRow className="hover:bg-raised">
            <TableHead className="px-2 sm:px-4">
              <span className="sr-only">Measure</span>
            </TableHead>
            <TableHead className="px-1.5 text-right sm:px-4">Live run</TableHead>
            <TableHead className="px-1.5 text-right sm:px-4">Today&apos;s rules</TableHead>
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
      <p className="m-0 mt-2 text-[12px] text-faint">
        Replay: recorded model outputs scored by today&apos;s rules, not a new measurement.
      </p>
    </div>
  );
}

/** Clean loads passed and loads sent to a person. */
function operatorCounts(confusion: Confusion) {
  const graded = LABELS.reduce(
    (sum, row) => sum + confusion[row].reject + confusion[row].escalate + confusion[row].accept,
    0,
  );
  const escalated = LABELS.reduce((sum, row) => sum + confusion[row].escalate, 0);
  return {
    cleanPassed: confusion.accept.accept,
    cleanN: rowTotal(confusion.accept),
    escalated,
    graded,
  };
}

function share(k: number, n: number): string {
  return n > 0 ? `${k} of ${n}` : "—";
}

/** Columns that are zero in every row say nothing: they are left out. */
function liveColumns(rows: Confusion["reject"][]): (typeof COLUMNS)[number][] {
  return COLUMNS.filter((c) => c !== "error" || rows.some((r) => r.error > 0));
}

/** Confusion matrix, used inside the method detail. */
function ConfusionTable({ confusion }: { confusion: Confusion }) {
  const cols = liveColumns(LABELS.map((l) => confusion[l]));
  return (
    <Table>
      <TableHeader>
        <TableRow className="hover:bg-raised">
          <TableHead className="px-2 sm:px-4">Photo set</TableHead>
          {cols.map((c) => (
            <TableHead key={c} className="px-1.5 text-right sm:px-4">
              {COLUMN_LABEL[c]}
            </TableHead>
          ))}
        </TableRow>
      </TableHeader>
      <TableBody>
        {LABELS.map((expected) => (
          <TableRow key={expected} className="hover:bg-transparent">
            <TableCell className="px-2 text-[12.5px] font-semibold text-ink sm:px-4">{ROW_LABEL[expected]}</TableCell>
            {cols.map((c) => (
              <TableCell
                key={c}
                className={cn(
                  "figure px-1.5 text-right text-[13px] sm:px-4",
                  c === expected ? "font-semibold text-ink" : "text-muted",
                )}
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
  const cols = liveColumns(rows.map(([, cell]) => cell));
  return (
    <Table>
      <TableHeader>
        <TableRow className="hover:bg-raised">
          <TableHead className="px-2 sm:px-4">Category</TableHead>
          <TableHead className="hidden px-2 sm:table-cell sm:px-4">Should</TableHead>
          {cols.map((c) => (
            <TableHead key={c} className="px-1.5 text-right sm:px-4">
              {COLUMN_LABEL[c]}
            </TableHead>
          ))}
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map(([category, cell]) => {
          const expected = expectedFor(category);
          return (
            <TableRow key={category} className="hover:bg-transparent">
              <TableCell className="px-2 font-semibold text-ink sm:px-4">{category}</TableCell>
              <TableCell className="hidden px-2 text-[12.5px] text-muted sm:table-cell sm:px-4">
                {COLUMN_LABEL[expected]}
              </TableCell>
              {cols.map((c) => (
                <TableCell
                  key={c}
                  className={cn(
                    "figure px-1.5 text-right text-[13px] sm:px-4",
                    c === expected ? "font-semibold text-ink" : "text-muted",
                  )}
                >
                  {cell[c]}
                </TableCell>
              ))}
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}

/** Latency, models, method, data: all inside the detail. */
function MethodDetail({ summary }: { summary: BenchmarkSummary }) {
  const facts: { key: string; label: string; value: string; mono?: boolean }[] = [
    { key: "e2e", label: "Full inspection", value: `p50 ${seconds(summary.total_ms.p50)} · p95 ${seconds(summary.total_ms.p95)}`, mono: true },
    { key: "vlm", label: "Vision model call", value: `p50 ${seconds(summary.latency_ms.p50)} · p95 ${seconds(summary.latency_ms.p95)}`, mono: true },
    { key: "vm", label: "Vision model", value: summary.vlm_model ?? "—", mono: true },
    { key: "lm", label: "Language model", value: summary.llm_model ?? "—", mono: true },
    { key: "prov", label: "Provider", value: summary.provider ? providerName(summary.provider) : "—" },
    { key: "n", label: "Photos", value: String(summary.n), mono: true },
  ];
  return (
    <div className="flex flex-col gap-5 pt-3">
      <dl className="m-0 grid grid-cols-1 gap-x-8 text-[12.5px] sm:grid-cols-2">
        {facts.map((f) => (
          <div key={f.key} className="flex justify-between gap-4 border-b border-seam py-2">
            <dt className="text-muted">{f.label}</dt>
            <dd className={cn("m-0 text-right break-all text-ink", f.mono ? "figure" : null)}>{f.value}</dd>
          </div>
        ))}
      </dl>
      <div>
        <h3 className="smallcaps m-0 mb-2">Vision model alone: outcome by photo set</h3>
        <ConfusionTable confusion={summary.confusion} />
      </div>
      <div>
        <h3 className="smallcaps m-0 mb-2">By category</h3>
        <CategoryTable summary={summary} />
      </div>
      <p className="m-0 max-w-[80ch] text-[12px] leading-relaxed text-muted">
        Photos: RealWaste (Single, Iranmanesh, Raad),{" "}
        <a href={DATASET_URL} className="text-amber underline underline-offset-2">
          UCI ML Repository
        </a>
        . Licence: UCI lists CC BY 4.0; the dataset README says CC BY-NC-SA 4.0, so the stricter
        terms are assumed.{" "}
        <a href="/benchmark/manifest.csv" className="text-amber underline underline-offset-2">
          Manifest
        </a>
        . Try one truck yourself in the{" "}
        <Link href="/app" className="text-amber underline underline-offset-2">
          Inspection console
        </Link>
        .
      </p>
    </div>
  );
}
