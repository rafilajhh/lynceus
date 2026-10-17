"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { formatUsd, formatUsdCompact } from "@/lib/format";
import {
  ShiftError,
  fetchShiftReport,
  type ShiftReport,
  type ValueModel,
} from "@/lib/shift-api";
import { cn } from "@/lib/utils";
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
import { PythiaPanel } from "@/components/assist/pythia-panel";
import { num, plainWords, plural, rp, rpFull, utcParts } from "@/components/ops/format";
import {
  SupplierScorecard,
  loadScorecard,
  type ScoreState,
} from "@/components/ops/supplier-scorecard";

type LoadState =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ready"; report: ShiftReport };

/** "13 Oct 09:53–17:40 UTC" from the first and last truck of the window. */
function windowLabel(report: ShiftReport): string {
  const first = utcParts(report.window.first_truck_utc);
  const last = utcParts(report.window.last_truck_utc);
  if (!first || !last) return "no trucks";
  return first.day === last.day
    ? `${first.day} ${first.time}–${last.time} UTC`
    : `${first.day} ${first.time} – ${last.day} ${last.time} UTC`;
}

/* ----------------------------------------------------------------- story */

/**
 * The shift's measured change, normalised from `improvement` (counted from
 * the sealed ledger and its follow-ups) or, on an older backend, from the
 * verdict counts alone. null = not measured: left out, never shown as 0.
 */
interface Story {
  trucks: number;
  cleared: number;
  held: number;
  rejected: number;
  minutesFreed: number | null;
  minutesAssumed: number | null;
  medianS: number | null;
  p95S: number | null;
  hazardous: number | null;
  conflicts: number | null;
  reviews: number | null;
  confirmed: number | null;
  overridden: number | null;
  labs: number | null;
  breaches: number | null;
  deductions: number | null;
  fees: number | null;
  exposure: number | null;
  notices: number | null;
  notes: string[];
  measured: boolean;
}

function buildStory(report: ShiftReport): Story {
  const imp = report.improvement;
  const accept = report.by_verdict.accept ?? 0;
  const escalate = report.by_verdict.escalate_human ?? 0;
  const reject = report.by_verdict.reject ?? 0;
  if (!imp) {
    return {
      trucks: report.trucks,
      cleared: accept,
      held: escalate,
      rejected: reject,
      minutesFreed: null,
      minutesAssumed: null,
      medianS: report.median_seconds_per_truck ?? null,
      p95S: null,
      hazardous: null,
      conflicts: null,
      reviews: null,
      confirmed: null,
      overridden: null,
      labs: null,
      breaches: null,
      deductions: null,
      fees: null,
      exposure: null,
      notices: null,
      notes: [],
      measured: false,
    };
  }
  return {
    trucks: imp.trucks ?? report.trucks,
    cleared: imp.auto_cleared ?? imp.hand_checks_avoided ?? accept,
    held: imp.held ?? escalate,
    rejected: imp.rejected ?? reject,
    minutesFreed: imp.staff_minutes_freed ?? null,
    minutesAssumed: imp.manual_check_minutes_assumed ?? null,
    medianS: imp.median_decision_s ?? report.median_seconds_per_truck ?? null,
    p95S: imp.p95_decision_s ?? null,
    hazardous: imp.hazardous_loads_stopped ?? null,
    conflicts: imp.declaration_conflicts ?? null,
    reviews: imp.supervisor_reviews ?? null,
    confirmed: imp.ai_confirmed ?? null,
    overridden: imp.ai_overridden ?? null,
    labs: imp.lab_samples ?? null,
    breaches: imp.spec_breaches ?? null,
    deductions: imp.deductions_idr ?? null,
    fees: imp.breach_fees_idr ?? null,
    exposure: imp.exposure_if_tipped_idr ?? null,
    notices: imp.notices ?? null,
    notes: imp.notes,
    measured: true,
  };
}

function recovered(story: Story): number {
  return (story.deductions ?? 0) + (story.fees ?? 0);
}

/** One plain sentence: what this gate did for the shift. */
function storySentence(story: Story): string {
  const parts = [
    `${story.cleared} of ${story.trucks} ${plural(story.trucks, "truck", "trucks")} cleared without a hand check`,
  ];
  if (story.minutesFreed !== null && story.minutesFreed > 0) {
    parts.push(`${num(story.minutesFreed, 0)} min of gate time freed`);
  }
  const stopped = story.hazardous ?? story.rejected;
  if (stopped > 0) {
    parts.push(`${stopped} hazardous ${plural(stopped, "load", "loads")} stopped before tipping`);
  }
  if (recovered(story) > 0) parts.push(`${rp(recovered(story))} recovered under the supply contract`);
  const last = parts.length > 1 ? parts.pop() : null;
  return `This shift: ${parts.join(", ")}${last ? ` and ${last}` : ""}.`;
}

/* ------------------------------------------------------------------ view */

export function ShiftView() {
  const [state, setState] = useState<LoadState>({ kind: "loading" });
  const [score, setScore] = useState<ScoreState>({ kind: "loading" });

  const load = useCallback(async (signal?: AbortSignal) => {
    setState({ kind: "loading" });
    setScore({ kind: "loading" });
    void loadScorecard(signal).then((next) => {
      if (!signal?.aborted) setScore(next);
    });
    try {
      const report = await fetchShiftReport(undefined, signal);
      setState({ kind: "ready", report });
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") return;
      setState({
        kind: "error",
        message:
          err instanceof ShiftError || err instanceof Error
            ? err.message
            : "Unexpected error loading the shift report.",
      });
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  if (state.kind === "loading") return <ShiftSkeleton />;

  if (state.kind === "error") {
    return (
      <Panel>
        <PanelHead title="Shift report" />
        <div role="alert" className="flex flex-col items-center gap-3 px-4 py-12 text-center">
          <p className="max-w-[52ch] text-[13.5px] text-muted">
            The shift report could not be loaded. {state.message}
          </p>
          <Button variant="default" size="sm" onClick={() => void load()}>
            Retry
          </Button>
        </div>
      </Panel>
    );
  }

  const { report } = state;
  if (report.trucks === 0) {
    return (
      <Panel>
        <PanelHead title="Shift report" meta="no trucks" />
        <h1 className="sr-only">Shift report</h1>
        <p className="mx-auto max-w-[52ch] px-4 py-12 text-center text-[13.5px] leading-relaxed text-muted">
          No sealed inspections in this shift yet. Run the demo truck in the{" "}
          <Link href="/app" className="text-amber underline underline-offset-2">
            Inspection console
          </Link>
          : this page then counts what the gate cleared, held and stopped, and what the lab
          and contract recovered.
        </p>
      </Panel>
    );
  }

  const story = buildStory(report);
  return (
    <div className="flex flex-col gap-4">
      <Panel aria-labelledby="shift-headline">
        <PanelHead title="Shift report" meta={windowLabel(report)} />
        <ImprovementBlock story={story} tag={<SampleTag report={report} />} />
        <HandoverLine report={report} story={story} />
      </Panel>
      <SupplierScorecard
        score={score}
        shiftSuppliers={report.suppliers}
        explanationModel={report.explanation_model ?? null}
      />
      <PythiaPanel context="shift" className="bg-panel" />
      {report.value_model ? <ValuePanel model={report.value_model} /> : null}
    </div>
  );
}

/** Seeded records are labelled as such, in words, never as a bare ratio. */
function SampleTag({ report }: { report: ShiftReport }) {
  if (report.sample_records <= 0) return null;
  const all = report.sample_records >= report.trucks;
  return (
    <span
      title={`${report.sample_records} of ${report.trucks} records are seeded sample data (scripts/seed_demo.py), not live gate traffic.`}
      className="inline-flex items-center gap-1.5 rounded-full border border-seam-strong bg-panel px-2.5 py-0.5 text-[11.5px] font-semibold tracking-[0.4px] text-muted normal-case"
    >
      <span aria-hidden="true" className="h-1.5 w-1.5 rounded-full bg-dot-idle" />
      {all ? "Sample shift: scripted data" : `Includes ${report.sample_records} scripted sample records`}
    </span>
  );
}

function ShiftSkeleton() {
  const bar = "rounded-[4px] bg-raised animate-[gate-pulse_1.1s_ease-in-out_infinite]";
  return (
    <div className="flex flex-col gap-4" role="status">
      <span className="sr-only">Loading the shift report</span>
      <Panel aria-hidden="true">
        <PanelHead title="Shift report" />
        <div className="flex flex-col gap-3 px-5 py-6">
          <div className={cn(bar, "h-6 w-[78%]")} />
          <div className={cn(bar, "h-6 w-[52%]")} />
        </div>
        <div className="grid gap-6 border-t border-seam px-5 py-6 lg:grid-cols-[1.35fr_1fr]">
          <div className={cn(bar, "h-24")} />
          <div className="flex flex-col gap-3">
            <div className={cn(bar, "h-5")} />
            <div className={cn(bar, "h-5")} />
            <div className={cn(bar, "h-5")} />
          </div>
        </div>
      </Panel>
      <Panel aria-hidden="true">
        <PanelHead title="Supplier scorecard" />
        <div className="flex flex-col gap-3 px-5 py-6">
          <div className={cn(bar, "h-10")} />
          <div className={cn(bar, "h-10")} />
        </div>
      </Panel>
    </div>
  );
}

/* ------------------------------------------------------- improvement */

/** Where a figure comes from: measured from the ledger, or an assumption. */
function Source({ kind, children }: { kind: "measured" | "assumption"; children: React.ReactNode }) {
  return (
    <p className="m-0 flex items-baseline gap-1.5 text-[12px] leading-snug text-muted">
      <span className={cn("shrink-0 font-semibold", kind === "assumption" ? "text-ink" : "text-muted")}>
        {kind === "measured" ? "Measured" : "Assumption"}
      </span>
      <span className="text-faint">·</span>
      <span>{children}</span>
    </p>
  );
}

function ImprovementBlock({ story, tag }: { story: Story; tag?: React.ReactNode }) {
  const records = `${story.trucks} sealed ${plural(story.trucks, "record", "records")}`;
  const stopped = story.hazardous ?? story.rejected;
  const money = recovered(story);

  /* Right-hand ledger: one row per measured outcome, left out when absent. */
  const rows: {
    key: string;
    label: string;
    value: string;
    title?: string;
    source: React.ReactNode;
    kind?: "measured" | "assumption";
  }[] = [];
  rows.push({
    key: "stopped",
    label: "Hazardous loads stopped before tipping",
    value: String(stopped),
    source:
      story.exposure && story.exposure > 0
        ? `REJECT verdicts · worst case if tipped ${rp(story.exposure)}`
        : `REJECT verdicts in ${records}`,
  });
  rows.push({
    key: "held",
    label: "Held for a supervisor",
    value: String(story.held),
    source:
      story.reviews !== null
        ? `${story.reviews} reviewed · AI confirmed ${story.confirmed ?? 0}, overridden ${story.overridden ?? 0}`
        : `HOLD verdicts in ${records}`,
  });
  if (story.conflicts !== null) {
    rows.push({
      key: "conflicts",
      label: "Waybill contradicted by the load",
      value: String(story.conflicts),
      source:
        story.notices !== null
          ? `Declared sorted RDF, camera saw otherwise · ${story.notices} supplier ${plural(story.notices, "notice", "notices")} sent`
          : "Declared sorted RDF, camera saw otherwise",
    });
  }
  if (story.labs !== null) {
    rows.push({
      key: "labs",
      label: "Lab samples taken",
      value: String(story.labs),
      source: `${story.breaches ?? 0} outside contract spec`,
    });
  }
  if (story.deductions !== null || story.fees !== null) {
    rows.push({
      key: "recovered",
      label: "Recovered under the supply contract",
      value: rp(money),
      title: money > 0 ? rpFull(money) : undefined,
      source: `Deductions ${rp(story.deductions ?? 0)} + breach fees ${rp(story.fees ?? 0)}`,
    });
  }

  return (
    <>
      <div className="px-5 pt-5 pb-5">
        <h1
          id="shift-headline"
          className="m-0 max-w-[60ch] text-[19px] leading-[1.4] font-semibold text-balance text-ink sm:text-[21px]"
        >
          {storySentence(story)}
        </h1>
        {tag ? <div className="mt-3">{tag}</div> : null}
      </div>

      <div className="grid border-t border-seam lg:grid-cols-[1.3fr_1fr]">
        {/* Lead figure: the gate's daily work, the hand checks it took over. */}
        <div className="flex flex-col gap-5 px-5 py-5 lg:border-r lg:border-seam">
          <div className="flex flex-col gap-2">
            <p className="m-0 flex items-baseline gap-2">
              <span className="figure text-[clamp(44px,6vw,64px)] leading-none font-semibold tracking-[-0.02em] text-ink">
                {story.cleared}
              </span>
              <span className="figure text-[20px] text-faint">/ {story.trucks}</span>
            </p>
            <p className="m-0 text-[15px] font-semibold text-ink">
              trucks cleared without a hand check
            </p>
            <Source kind="measured">ACCEPT verdicts in {records}</Source>
          </div>

          <dl className="m-0 grid grid-cols-1 gap-px overflow-hidden rounded-[10px] border border-seam bg-seam sm:grid-cols-2">
            <div className="flex flex-col gap-1.5 bg-panel px-4 py-3.5">
              <dt className="text-[13px] font-semibold text-ink">Gate time freed</dt>
              <dd className="figure m-0 text-[26px] leading-tight font-semibold text-ink">
                {story.minutesFreed !== null ? `${num(story.minutesFreed, 0)} min` : "—"}
              </dd>
              {story.minutesFreed !== null && story.minutesAssumed !== null ? (
                <Source kind="assumption">
                  {num(story.minutesAssumed)} min per manual check × {story.cleared}
                </Source>
              ) : (
                <p className="m-0 text-[12px] text-faint">Not measured by this backend</p>
              )}
            </div>
            <div className="flex flex-col gap-1.5 bg-panel px-4 py-3.5">
              <dt className="text-[13px] font-semibold text-ink">Time to a decision</dt>
              <dd className="figure m-0 text-[26px] leading-tight font-semibold text-ink">
                {story.medianS !== null ? `${num(story.medianS)} s` : "—"}
              </dd>
              {story.medianS !== null ? (
                <Source kind="measured">
                  median{story.p95S !== null ? ` · p95 ${num(story.p95S)} s` : ""}
                </Source>
              ) : (
                <p className="m-0 text-[12px] text-faint">Not measured by this backend</p>
              )}
            </div>
          </dl>
        </div>

        {/* Outcome ledger: ruled rows, figure right-aligned. */}
        <dl className="m-0 flex flex-col border-t border-seam lg:border-t-0">
          {rows.map((row) => (
            <div
              key={row.key}
              className="flex items-start justify-between gap-4 border-b border-seam px-5 py-3 last:border-b-0"
            >
              <div className="flex min-w-0 flex-col gap-0.5">
                <dt className="text-[13.5px] font-semibold text-ink">{row.label}</dt>
                <dd className="m-0">
                  <Source kind={row.kind ?? "measured"}>{row.source}</Source>
                </dd>
              </div>
              <dd
                title={row.title}
                className="figure m-0 shrink-0 text-[20px] leading-tight font-semibold text-ink"
              >
                {row.value}
              </dd>
            </div>
          ))}
        </dl>
      </div>

      {story.notes.length > 0 ? (
        <details className="group border-t border-seam px-5 py-2.5">
          <summary className="cursor-pointer text-[12.5px] font-semibold text-muted transition-colors duration-100 select-none hover:text-ink">
            How these figures are counted
          </summary>
          <ul className="m-0 mt-2 flex max-w-[90ch] list-disc flex-col gap-1 pl-5 text-[12.5px] leading-relaxed text-muted">
            {story.notes.map((note) => (
              <li key={note}>{plainWords(note)}</li>
            ))}
          </ul>
        </details>
      ) : null}
    </>
  );
}

function buildSummaryText(report: ShiftReport, story: Story): string {
  const open = story.rejected + story.held - (story.reviews ?? 0);
  return [
    `Shift ${windowLabel(report)}`,
    storySentence(story).replace(/^This shift: /, ""),
    `${story.held} held, ${story.rejected} rejected`,
    story.medianS !== null ? `median decision ${num(story.medianS)} s` : null,
    report.sample_records > 0 ? `${report.sample_records} scripted sample records` : null,
    open > 0 ? `${open} still need a supervisor` : "all resolved",
  ]
    .filter(Boolean)
    .join(" · ");
}

function HandoverLine({ report, story }: { report: ShiftReport; story: Story }) {
  const [copied, setCopied] = useState(false);
  const open = Math.max(0, story.rejected + story.held - (story.reviews ?? 0));

  const copySummary = useCallback(async () => {
    const text = buildSummaryText(report, story);
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      // Clipboard blocked (permissions / non-secure context): fall back so
      // the supervisor is never left without a way to take the summary.
      const ta = document.createElement("textarea");
      ta.value = text;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      document.body.removeChild(ta);
    }
    setCopied(true);
    window.setTimeout(() => setCopied(false), 2000);
  }, [report, story]);

  return (
    <div className="flex flex-col items-start gap-x-6 gap-y-2 border-t border-seam px-5 py-3 sm:flex-row sm:items-center sm:justify-between">
      {open > 0 ? (
        <Link
          href="/inspections"
          className="flex min-w-0 flex-1 items-center gap-2.5 text-[13px] text-ink transition-colors duration-100 hover:text-amber"
        >
          <span aria-hidden="true" className="h-1.5 w-1.5 shrink-0 rounded-full bg-amber" />
          <span>
            <span className="figure font-semibold">{open}</span>{" "}
            {plural(open, "truck still needs", "trucks still need")} a supervisor decision
          </span>
        </Link>
      ) : (
        <p className="m-0 flex min-w-0 flex-1 items-center gap-2.5 text-[13px] text-muted">
          <span aria-hidden="true" className="h-1.5 w-1.5 shrink-0 rounded-full bg-dot-ok" />
          Every held or rejected truck has a supervisor decision
        </p>
      )}
      <Button variant="ghost" size="sm" className="shrink-0" onClick={() => void copySummary()}>
        <span aria-live="polite">{copied ? "Copied" : "Copy handover summary"}</span>
      </Button>
    </div>
  );
}

/* --------------------------------------------------------- value model */

/**
 * Expected value per 1,000 trucks, with vs without Lynceus (impact.value_model).
 * Secondary to the measured shift: a model, so it says so and sits last.
 */
function ValuePanel({ model }: { model: ValueModel }) {
  const { low, base, high } = model.scenarios;
  const fee = base.subscription_cost_idr ?? null;
  const net = base.net_after_subscription_idr ?? base.net_value_idr;
  const lowNet = low.net_after_subscription_idr ?? low.net_value_idr;
  const highNet = high.net_after_subscription_idr ?? high.net_value_idr;
  const rows: { key: string; label: string; without: string; with: string }[] = [
    {
      key: "escaped",
      label: "Hard-contaminant loads that get through",
      without: num(base.without.escaped_hard_loads),
      with: num(base.with.escaped_hard_loads),
    },
    {
      key: "damage",
      label: "Expected damage from those loads",
      without: formatUsdCompact(base.without.expected_damage_idr),
      with: formatUsdCompact(base.with.expected_damage_idr),
    },
    {
      key: "minutes",
      label: "Operator minutes on hand checks",
      without: num(base.without.operator_minutes, 0),
      with: num(base.with.operator_minutes, 0),
    },
    {
      key: "false",
      label: "Clean loads wrongly rejected",
      without: num(base.without.false_rejects, 0),
      with: `${num(base.with.false_rejects, 0)} · ${formatUsdCompact(base.with.false_reject_cost_idr)}`,
    },
  ];

  return (
    <Panel aria-labelledby="value-head">
      <PanelHead title={`Value model per ${num(model.trucks, 0)} trucks`} meta="expected value · base case" />
      <h2 id="value-head" className="sr-only">
        Value model per {model.trucks} trucks
      </h2>
      <p className="m-0 border-b border-seam px-5 py-2.5 text-[13px] leading-relaxed text-muted">
        A model, not a measurement: sourced prices and assumed incident rates, scaled to{" "}
        {num(model.trucks, 0)} trucks. The figures above are the measured ones.
      </p>
      <Table>
        <TableHeader>
          <TableRow className="hover:bg-raised">
            <TableHead className="px-3 sm:px-4">
              <span className="sr-only">Measure</span>
            </TableHead>
            <TableHead className="px-2 text-right sm:px-4">
              Without<span className="hidden sm:inline"> Lynceus</span>
            </TableHead>
            <TableHead className="px-3 text-right sm:px-4">
              With<span className="hidden sm:inline"> Lynceus</span>
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => (
            <TableRow key={row.key} className="hover:bg-transparent">
              <TableCell className="px-3 text-[12.5px] text-muted sm:px-4">{row.label}</TableCell>
              <TableCell className="figure px-2 text-right text-[12.5px] whitespace-nowrap text-ink sm:px-4">
                {row.without}
              </TableCell>
              <TableCell className="figure px-3 text-right text-[12.5px] whitespace-nowrap text-ink sm:px-4">
                {row.with}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>

      <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1 border-t border-seam px-5 py-3">
        <p className="m-0 text-[13.5px] text-ink">
          Net expected value{fee !== null ? " after the gate subscription" : ""}{" "}
          <strong title={formatUsd(net)} className="figure font-semibold text-ink">
            {formatUsdCompact(net)}
          </strong>{" "}
          per {num(model.trucks, 0)} trucks
        </p>
        <p className="figure m-0 text-[12px] text-muted">
          range {formatUsdCompact(lowNet)} to {formatUsdCompact(highNet)}
        </p>
      </div>
      <details className="group border-t border-seam px-5 py-3">
        <summary className="cursor-pointer text-[13px] font-semibold text-ink transition-colors duration-100 select-none hover:text-amber">
          Parameters and sources
        </summary>
        <ul className="m-0 flex list-none flex-col gap-2 p-0 pt-3">
          {model.parameters.map((p) => (
            <li key={p.key} className="flex flex-col gap-0.5 border-b border-seam pb-2 last:border-b-0">
              <span className="flex flex-wrap items-baseline justify-between gap-x-4 text-[12.5px]">
                <span className="text-ink">{p.label}</span>
                <span className="figure text-muted">
                  {num(p.low, 3)} / <span className="text-ink">{num(p.base, 3)}</span> / {num(p.high, 3)} {p.unit}
                </span>
              </span>
              <span className="text-[11.5px] text-faint">
                {p.assumption ? "Assumption" : "Sourced"}
                {p.rationale ? ` · ${p.rationale}` : ""}
              </span>
            </li>
          ))}
        </ul>
        {model.note ? <p className="m-0 mt-2 text-[12px] text-muted">{model.note}</p> : null}
      </details>
    </Panel>
  );
}
