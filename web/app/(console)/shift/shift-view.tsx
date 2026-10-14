"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { formatRupiah, formatRupiahCompact } from "@/lib/format";
import {
  FLAG_MIN_RISK,
  FLAG_MIN_TRUCKS,
  ShiftError,
  fetchShiftReport,
  type ShiftReport,
  type SupplierRow,
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

  return (
    <div className="flex flex-col gap-4">
      <SampleNote report={report} />
      <Panel aria-labelledby="shift-headline">
        <PanelHead title="Shift report" meta={windowLabel(report)} />
        <h1 id="shift-headline" className="sr-only">
          Shift report
        </h1>
        <HeadlineRun report={report} />
        <HandoverLine report={report} />
      </Panel>
      <SupplierPanel report={report} />
    </div>
  );
}

/** Honesty label: scripted data is always named as such. */
function SampleNote({ report }: { report: ShiftReport }) {
  if (report.sample_records === 0) return null;
  return (
    <div
      role="note"
      className="flex items-start gap-2.5 rounded-[10px] border border-seam-strong bg-raised px-4 py-2.5 text-[13px] text-muted"
    >
      <span aria-hidden="true" className="mt-[7px] h-1.5 w-1.5 shrink-0 rounded-full bg-dot-warn" />
      {report.sample ? (
        <p className="m-0">
          <strong className="font-semibold text-ink">Sample shift</strong> — scripted
          demo data.
        </p>
      ) : (
        <p className="m-0">
          <strong className="font-semibold text-ink">Includes scripted data</strong> —{" "}
          <span className="figure">{report.sample_records}</span> of{" "}
          <span className="figure">{report.trucks}</span> trucks.
        </p>
      )}
    </div>
  );
}

/** The headline figures: trucks, rejected, prevented loss. */
function HeadlineRun({ report }: { report: ShiftReport }) {
  const rejected = report.by_verdict.reject ?? 0;
  const prevented = report.prevented_loss_idr;
  const parts: { key: string; value: string; label: string; tone?: string; title?: string }[] = [
    { key: "trucks", value: String(report.trucks), label: report.trucks === 1 ? "truck" : "trucks" },
    { key: "rejected", value: String(rejected), label: "rejected", tone: rejected > 0 ? "text-verdict-red" : undefined },
    {
      key: "prevented",
      value: formatRupiahCompact(prevented),
      title: prevented > 0 ? formatRupiah(prevented) : undefined,
      label: "prevented loss",
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
    `prevented loss ${formatRupiah(report.prevented_loss_idr)}`,
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
    <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-3 border-t border-seam px-4 py-4">
      <p className="m-0 flex min-w-0 flex-1 items-center gap-2.5 text-[13px]">
        <span
          aria-hidden="true"
          className={cn(
            "h-1.5 w-1.5 shrink-0 rounded-full",
            open > 0 ? "bg-amber" : "bg-dot-ok",
          )}
        />
        {open > 0 ? (
          <span className="text-ink">
            <span className="figure font-semibold">{open}</span>{" "}
            {open === 1 ? "truck needs" : "trucks need"} resolution before
            handover{" "}
            <Link
              href="/inspections"
              className="text-amber underline underline-offset-2"
            >
              view in ledger
            </Link>
          </span>
        ) : (
          <span className="text-muted">
            All trucks resolved: nothing is pending for the next shift.
          </span>
        )}
      </p>
      <Button
        variant="default"
        size="sm"
        className="shrink-0"
        onClick={() => void copySummary()}
      >
        {copied ? "Copied" : "Copy shift summary"}
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
            <SupplierTableRows key={row.supplier} row={row} report={report} />
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
            {row.explanation ? (
              <Explanation row={row} report={report} className="mt-3 border-t border-seam pt-3" />
            ) : null}
          </li>
        ))}
      </ul>

      <p
        title="Risk = (rejected + 0.5 × escalated) ÷ trucks. Prevented loss counts rejected and escalated loads only (impact model, docs/research/realcase-indonesia.md)."
        className="m-0 border-t border-seam px-4 py-2.5 text-[12px] text-muted"
      >
        A supplier is flagged at ≥ {FLAG_MIN_TRUCKS} trucks and risk ≥{" "}
        {FLAG_MIN_RISK.toFixed(2)} (tick on the bar).
      </p>
    </Panel>
  );
}

function SupplierTableRows({ row, report }: { row: SupplierRow; report: ShiftReport }) {
  return (
    <>
      <TableRow className={cn("hover:bg-transparent", row.explanation && "border-b-0")}>
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
      {row.explanation ? (
        <TableRow className="hover:bg-transparent">
          <TableCell colSpan={6} className="pt-0 pb-4">
            <Explanation row={row} report={report} className="max-w-[78ch]" />
          </TableCell>
        </TableRow>
      ) : null}
    </>
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

/** The actionable sentence for a flagged supplier. */
function Explanation({
  row,
  className,
}: {
  row: SupplierRow;
  report: ShiftReport;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col gap-1", className)}>
      <p className="m-0 max-w-[78ch] text-[13.5px] leading-relaxed text-ink">
        {row.explanation}
      </p>
    </div>
  );
}
