"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { formatUsd, formatUsdCompact, USD_IDR_RATE } from "@/lib/format";
import {
  FLAG_MIN_RISK,
  FLAG_MIN_TRUCKS,
  ShiftError,
  fetchShiftReport,
  type ShiftReport,
  type SupplierRow,
  type ValueModel,
} from "@/lib/shift-api";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
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
  | { kind: "error"; message: string }
  | { kind: "ready"; report: ShiftReport };

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** Money in US dollars: compact by default, full for tooltips/rates. */
type Money = (idr: number, opts?: { full?: boolean }) => string;

/** IDR figures convert at the backend's stated rate (impact.py USD_IDR_RATE). */
const money: Money = (idr, opts) =>
  !Number.isFinite(idr) ? "—" : opts?.full ? formatUsd(idr) : formatUsdCompact(idr);

/** "1.000" / "0,6": the console's id-ID number register (as formatWeight). */
function formatCount(n: number, digits = 1): string {
  return new Intl.NumberFormat("id-ID", { maximumFractionDigits: digits }).format(n);
}

/** "2026-10-13T09:53:07Z" → { day: "13 Oct", time: "09:53" } (UTC, no locale drift). */
function utcParts(iso: string | null | undefined): { day: string; time: string } | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(iso ?? "");
  if (!m) return null;
  return { day: `${Number(m[3])} ${MONTHS[Number(m[2]) - 1] ?? m[2]}`, time: `${m[4]}:${m[5]}` };
}

/** "13 Oct 09:53–17:40 UTC" from the first and last truck of the window. */
function windowLabel(report: ShiftReport): string {
  const first = utcParts(report.window.first_truck_utc);
  const last = utcParts(report.window.last_truck_utc);
  if (!first || !last) return "no trucks";
  return first.day === last.day
    ? `${first.day} ${first.time}–${last.time} UTC`
    : `${first.day} ${first.time} – ${last.day} ${last.time} UTC`;
}

/** Drill-through: the flag is an accusation; make its evidence one click away. */
function SupplierLink({ name, className }: { name: string; className?: string }) {
  return (
    <Link
      href={`/inspections?supplier=${encodeURIComponent(name)}`}
      title={`View ${name} trucks in the audit trail`}
      className={cn(
        "underline-offset-2 transition-colors duration-100 hover:text-amber hover:underline",
        className,
      )}
    >
      {name}
    </Link>
  );
}

export function ShiftView() {
  const [state, setState] = useState<LoadState>({ kind: "loading" });

  const load = useCallback(async (signal?: AbortSignal) => {
    setState({ kind: "loading" });
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

  if (state.kind === "loading") {
    return (
      <Panel>
        <PanelHead title="Shift report" />
        <div role="status" className="flex flex-col items-center gap-3 px-4 py-12 text-center">
          <span
            aria-hidden="true"
            className="h-6 w-6 animate-spin rounded-full border-2 border-seam border-t-amber"
          />
          <p className="text-[13px] text-muted">
            Loading the shift report. Flagged suppliers may take a few seconds while the
            assist model writes their explanation.
          </p>
        </div>
      </Panel>
    );
  }

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
        <p className="mx-auto max-w-[46ch] px-4 py-12 text-center text-[13.5px] text-muted">
          No completed inspections yet: run one in the{" "}
          <Link href="/app" className="text-amber underline underline-offset-2">
            Inspection console
          </Link>
          .
        </p>
      </Panel>
    );
  }

  const model = report.value_model ?? null;
  const scriptedMeta =
    report.sample_records > 0
      ? `${windowLabel(report)} · ${report.sample_records}/${report.trucks} scripted`
      : windowLabel(report);

  return (
    <div className="flex flex-col gap-4">
      <Panel aria-labelledby="shift-headline">
        <PanelHead title="Shift report" meta={scriptedMeta} />
        <h1 id="shift-headline" className="sr-only">
          Shift report
        </h1>
        <HeadlineRun report={report} money={money} />
        <HandoverLine report={report} />
      </Panel>
      {model ? <ValuePanel model={model} money={money} /> : null}
      <SupplierPanel report={report} />
    </div>
  );
}

/** "50 h" from minutes. */
function hours(minutes: number): string {
  return `${formatCount(minutes / 60)} h`;
}

/** One parameter value in its unit: share → %, money → display currency. */
function paramValue(unit: string, value: number, money: Money): string {
  switch (unit) {
    case "share":
      return `${formatCount(value * 100)}%`;
    case "IDR":
      return money(value);
    case "IDR/t":
      return `${money(value, { full: true })}/t`;
    case "IDR/min":
      return `${money(value, { full: true })}/min`;
    default:
      return `${formatCount(value)} ${unit}`;
  }
}

function sourceHost(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

/**
 * Expected value per 1,000 trucks, with vs without Lynceus (impact.value_model).
 * With/without lead; every assumption sits one click away, never hidden.
 */
function ValuePanel({ model, money }: { model: ValueModel; money: Money }) {
  const { low, base, high } = model.scenarios;
  const fee = base.subscription_cost_idr ?? null;
  const net = base.net_after_subscription_idr ?? base.net_value_idr;
  const lowNet = low.net_after_subscription_idr ?? low.net_value_idr;
  const highNet = high.net_after_subscription_idr ?? high.net_value_idr;
  const rows: { key: string; label: string; without: string; with: string }[] = [
    {
      key: "damage",
      label: "Expected damage from escaped hard items",
      without: money(base.without.expected_damage_idr),
      with: money(base.with.expected_damage_idr),
    },
    {
      key: "escaped",
      label: "Hard-contaminant loads that get through",
      without: formatCount(base.without.escaped_hard_loads),
      with: formatCount(base.with.escaped_hard_loads),
    },
    {
      key: "false",
      label: "Clean loads wrongly rejected",
      without: formatCount(base.without.false_rejects, 0),
      with: `${formatCount(base.with.false_rejects, 0)} · ${money(base.with.false_reject_cost_idr)}`,
    },
  ];

  return (
    <Panel aria-labelledby="value-head">
      <PanelHead title={`Value per ${formatCount(model.trucks, 0)} trucks`} meta="expected value · base case" />
      <h2 id="value-head" className="sr-only">
        Value per {model.trucks} trucks
      </h2>
      <Table>
        <TableHeader>
          <TableRow className="hover:bg-raised">
            <TableHead />
            <TableHead className="text-right">Without Lynceus</TableHead>
            <TableHead className="text-right">With Lynceus</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => (
            <TableRow key={row.key} className="hover:bg-transparent">
              <TableCell className="text-[12.5px] text-muted">{row.label}</TableCell>
              <TableCell className="figure whitespace-nowrap text-right text-[12.5px] text-ink">
                {row.without}
              </TableCell>
              <TableCell className="figure whitespace-nowrap text-right text-[12.5px] text-ink">
                {row.with}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>

      <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1 border-t border-seam px-4 py-3">
        <p className="m-0 text-[13.5px] text-ink">
          Net expected value{fee !== null ? " after subscription" : ""}{" "}
          <strong
            title={money(net, { full: true })}
            className={cn(
              "figure font-semibold",
              net > 0 ? "text-verdict-green" : net < 0 ? "text-verdict-red" : undefined,
            )}
          >
            {money(net)}
          </strong>{" "}
          per {formatCount(model.trucks, 0)} trucks
        </p>
        <p className="figure m-0 text-[12px] text-muted">
          range {money(lowNet)} – {money(highNet)}
        </p>
      </div>

      <details className="group border-t border-seam px-4 py-3" open={false}>
        <summary className="cursor-pointer select-none text-[13px] font-semibold text-ink transition-colors hover:text-amber">
          Assumptions and sources
        </summary>
        <p className="m-0 mt-2 max-w-[78ch] text-[12.5px] leading-relaxed text-muted">
          The shift&apos;s worst-case exposure books {money(model.worst_case_per_incident_idr)} for
          every rejected hard contaminant, as if each would certainly have destroyed a shredder
          and stopped the kiln for an hour. This model weights that damage by its probability
          and compares a manual check of every truck (without) with Lynceus screening every
          truck and sending only flagged ones to that check (with). Range: low sets every
          adjustable value to the end least favourable to Lynceus, high to the most favourable.
          {model.note ? ` ${model.note}` : ""}
        </p>
        <ul className="m-0 mt-3 flex list-none flex-col gap-2.5 p-0">
          {model.parameters.map((param) => (
            <li key={param.key} className="text-[12.5px] leading-relaxed">
              <span className="text-ink">{param.label}</span>{" "}
              <span className="figure text-ink">
                {paramValue(param.unit, param.base, money)}
              </span>
              {param.low !== param.base || param.high !== param.base ? (
                <span className="figure text-muted">
                  {" "}
                  (low {paramValue(param.unit, param.low, money)}, high{" "}
                  {paramValue(param.unit, param.high, money)})
                </span>
              ) : null}
              {param.assumption ? (
                <Badge variant="escalate" className="ml-2 align-middle">
                  Assumption
                </Badge>
              ) : null}
              <span className="block text-muted">
                {param.rationale}
                {param.sources.map((url) => (
                  <span key={url}>
                    {" "}
                    <a href={url} className="text-amber underline underline-offset-2">
                      {sourceHost(url)}
                    </a>
                  </span>
                ))}
              </span>
            </li>
          ))}
        </ul>
        <p className="m-0 mt-3 text-[12px] text-muted">
          Benchmark rates from {model.benchmark_file}. US$ figures convert at
          the backend&apos;s fixed rate (US$1 = Rp {formatCount(USD_IDR_RATE, 0)}).
        </p>
      </details>
    </Panel>
  );
}

/** The headline figures: trucks, rejected, worst-case loss exposure avoided. */
function HeadlineRun({ report, money }: { report: ShiftReport; money: Money }) {
  const rejected = report.by_verdict.reject ?? 0;
  const prevented = report.loss_exposure_idr ?? report.prevented_loss_idr;
  const parts: { key: string; value: string; label: string; tone?: string; title?: string }[] = [
    { key: "trucks", value: String(report.trucks), label: report.trucks === 1 ? "truck" : "trucks" },
    { key: "rejected", value: String(rejected), label: "rejected", tone: rejected > 0 ? "text-verdict-red" : undefined },
    {
      key: "prevented",
      value: money(prevented),
      title:
        prevented > 0
          ? `${money(prevented, { full: true })}: each reject booked as certain shredder damage plus 1 h of kiln downtime.${report.value_model ? " The probability-weighted value is below." : ""}`
          : undefined,
      label: "worst-case exposure",
      tone: prevented > 0 ? "text-verdict-green" : undefined,
    },
  ];
  return (
    <dl className="m-0 grid grid-cols-3 gap-x-6 px-4 pt-5 pb-4">
      {parts.map((part) => (
        <div key={part.key} className="flex flex-col gap-1">
          <dd
            title={part.title}
            className={cn(
              "figure m-0 whitespace-nowrap text-[clamp(20px,2.4vw,28px)] leading-tight font-semibold text-ink",
              part.tone,
            )}
          >
            {part.value}
          </dd>
          <dt className="smallcaps">{part.label}</dt>
        </div>
      ))}
    </dl>
  );
}

function buildSummaryText(report: ShiftReport): string {
  const rejected = report.by_verdict.reject ?? 0;
  const escalated = report.by_verdict.escalate_human ?? 0;
  const accepted = report.by_verdict.accept ?? 0;
  const open = rejected + escalated;
  const parts = [
    `Shift ${windowLabel(report)}`,
    `${report.trucks} trucks`,
    `${accepted} accepted`,
    `${escalated} escalated`,
    `${rejected} rejected`,
    `worst-case loss exposure avoided ${formatUsd(report.loss_exposure_idr ?? report.prevented_loss_idr)}`,
    open > 0 ? `${open} need resolution before handover` : "all resolved",
  ];
  return parts.join(" · ");
}

function HandoverLine({ report }: { report: ShiftReport }) {
  const [copied, setCopied] = useState(false);
  const rejected = report.by_verdict.reject ?? 0;
  const escalated = report.by_verdict.escalate_human ?? 0;
  const open = rejected + escalated;

  const copySummary = useCallback(async () => {
    const text = buildSummaryText(report);
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
  }, [report]);

  return (
    <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2 border-t border-seam px-4 py-3">
      {open > 0 ? (
        <Link
          href="/inspections"
          className="flex min-w-0 flex-1 items-center gap-2.5 text-[13px] text-ink transition-colors duration-100 hover:text-amber"
        >
          <span aria-hidden="true" className="h-1.5 w-1.5 shrink-0 rounded-full bg-amber" />
          <span>
            <span className="figure font-semibold">{open}</span>{" "}
            {open === 1 ? "truck needs" : "trucks need"} resolution
          </span>
        </Link>
      ) : (
        <p className="m-0 flex min-w-0 flex-1 items-center gap-2.5 text-[13px] text-muted">
          <span aria-hidden="true" className="h-1.5 w-1.5 shrink-0 rounded-full bg-dot-ok" />
          All trucks resolved
        </p>
      )}
      <Button
        variant="ghost"
        size="sm"
        className="shrink-0"
        onClick={() => void copySummary()}
      >
        {copied ? "Copied" : "Copy summary"}
      </Button>
    </div>
  );
}

function SupplierPanel({ report }: { report: ShiftReport }) {
  const flaggedCount = report.suppliers.filter((s) => s.flagged).length;
  return (
    <Panel>
      <PanelHead
        title="Supplier risk"
        meta={`${report.suppliers.length} suppliers · ${flaggedCount} flagged`}
      />
      <p className="sr-only">
        Risk = (rejected + 0.5 × escalated) ÷ trucks. Flagged at ≥{" "}
        {FLAG_MIN_TRUCKS} trucks and risk ≥ {FLAG_MIN_RISK.toFixed(2)}.
      </p>

      {/* Desktop table */}
      <Table className="hidden md:table">
        <TableHeader>
          <TableRow className="hover:bg-raised">
            <TableHead>Supplier</TableHead>
            <TableHead className="text-right">Trucks</TableHead>
            <TableHead className="text-right">Rejected</TableHead>
            <TableHead className="text-right">Escalated</TableHead>
            <TableHead>Risk</TableHead>
            <TableHead>Status</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {report.suppliers.map((row) => (
            <SupplierTableRows key={row.supplier} row={row} />
          ))}
        </TableBody>
      </Table>

      {/* Mobile stacked rows */}
      <ul className="m-0 flex list-none flex-col gap-2 p-3 md:hidden">
        {report.suppliers.map((row) => (
          <li key={row.supplier} className="rounded-[10px] border border-seam bg-raised p-3">
            <div className="flex items-start justify-between gap-3">
              <SupplierLink
                name={row.supplier}
                className="text-[13.5px] font-semibold text-ink"
              />
              <StatusMark row={row} />
            </div>
            <p className="m-0 mt-1.5 text-[12.5px] text-muted">
              <span className="figure text-ink">{row.trucks}</span> trucks ·{" "}
              <span className="figure text-ink">{row.reject}</span> rejected ·{" "}
              <span className="figure text-ink">{row.escalate}</span> escalated
            </p>
            <div className="mt-2">
              <RiskBar row={row} wide />
            </div>
            {row.flagged ? (
              <div className="mt-2">
                <Badge variant="escalate" className="text-[11px]">
                  Review before next delivery
                </Badge>
              </div>
            ) : null}
          </li>
        ))}
      </ul>

    </Panel>
  );
}

function SupplierTableRows({ row }: { row: SupplierRow }) {
  return (
    <TableRow className="hover:bg-transparent">
      <TableCell className="whitespace-nowrap font-semibold text-ink">
        <SupplierLink name={row.supplier} />
      </TableCell>
      <TableCell className="figure text-right text-[12.5px] text-ink">{row.trucks}</TableCell>
      <TableCell className="figure text-right text-[12.5px] text-ink">{row.reject}</TableCell>
      <TableCell className="figure text-right text-[12.5px] text-ink">{row.escalate}</TableCell>
      <TableCell>
        <RiskBar row={row} />
      </TableCell>
      <TableCell className="whitespace-nowrap">
        <StatusMark row={row} />
      </TableCell>
    </TableRow>
  );
}

/** Risk 0..1 as a hairline bar; amber fill only when flagged (state). */
function RiskBar({ row, wide = false }: { row: SupplierRow; wide?: boolean }) {
  const pct = Math.round(Math.min(1, Math.max(0, row.risk_score)) * 100);
  return (
    <div className="flex items-center gap-2.5">
      <div
        aria-hidden="true"
        className={cn("relative h-1.5 overflow-hidden rounded-full bg-seam", wide ? "flex-1" : "w-28")}
      >
        <div
          className={cn("h-full rounded-full", row.flagged ? "bg-amber" : "bg-faint")}
          style={{ width: `${pct}%` }}
        />
        <div
          className="absolute top-[-1px] h-[calc(100%+2px)] w-px bg-ink"
          style={{ left: `${FLAG_MIN_RISK * 100}%` }}
        />
      </div>
      <span className="figure text-[12.5px] text-ink">
        <span className="sr-only">risk score </span>
        {row.risk_score.toFixed(2)}
      </span>
    </div>
  );
}

function StatusMark({ row }: { row: SupplierRow }) {
  if (row.flagged) return <Badge variant="escalate">Flagged</Badge>;
  return (
    <Badge variant="default">
      {row.trucks < FLAG_MIN_TRUCKS ? "Few trucks" : "Within limit"}
    </Badge>
  );
}

/** The actionable sentence for a flagged supplier — kept quiet and short. */
function Explanation({ row }: { row: SupplierRow }) {
  return (
    <p className="m-0 text-[12.5px] leading-snug text-muted">
      {row.explanation}
    </p>
  );
}
