"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { CircleCheck, Copy, FileDown, Info, ListChecks, TriangleAlert } from "lucide-react";
import { formatUsd, formatUsdCompact } from "@/lib/format";
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
  | { kind: "error"; message: string }
  | { kind: "ready"; report: ShiftReport };

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** Money in US dollars: compact by default, full for tooltips/rates. */
type Money = (idr: number, opts?: { full?: boolean }) => string;

/** IDR figures convert at the backend's stated rate (impact.py USD_IDR_RATE). */
const money: Money = (idr, opts) =>
  !Number.isFinite(idr) ? "—" : opts?.full ? formatUsd(idr) : formatUsdCompact(idr);

/** "2026-10-13T09:53:07Z" → { day: "13 Oct", time: "09:53" } (UTC, no locale drift). */
function utcParts(iso: string | null | undefined): { day: string; time: string } | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(iso ?? "");
  if (!m) return null;
  return { day: `${Number(m[3])} ${MONTHS[Number(m[2]) - 1] ?? m[2]}`, time: `${m[4]}:${m[5]}` };
}

/** "13 Oct, 09:53–17:40 UTC" from the first and last truck of the window. */
function windowLabel(report: ShiftReport): string {
  const first = utcParts(report.window.first_truck_utc);
  const last = utcParts(report.window.last_truck_utc);
  if (!first || !last) return "no trucks";
  return first.day === last.day
    ? `${first.day}, ${first.time}–${last.time} UTC`
    : `${first.day} ${first.time} – ${last.day} ${last.time} UTC`;
}

/** "UD Sinar Abadi" → "US"; "PT. Hijau Lestari" → "PH". */
function initials(name: string): string {
  const words = name.split(/\s+/).map((w) => w.replace(/[^\p{L}\p{N}]/gu, "")).filter(Boolean);
  return words.slice(0, 2).map((w) => w[0]!.toUpperCase()).join("") || "?";
}

/** Drill-through: the flag is an accusation; make its evidence one click away. */
function SupplierLink({ name, className }: { name: string; className?: string }) {
  return (
    <Link
      href={`/inspections?supplier=${encodeURIComponent(name)}`}
      title={`View ${name} trucks in the audit trail`}
      className={cn(
        "underline-offset-2 transition-colors duration-100 hover:text-brand hover:underline",
        className,
      )}
    >
      {name}
    </Link>
  );
}

/** Loading / error / empty states share the page frame and one centred card. */
function StateFrame({ crumb, children }: { crumb?: string; children: React.ReactNode }) {
  return (
    <>
      <PageHeader crumb={crumb ?? "Console / Reports"} title="Shift report" />
      <PageBody>
        <section className="card">{children}</section>
      </PageBody>
    </>
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
      <StateFrame>
        <div role="status" className="flex flex-col items-center gap-3 px-4 py-12 text-center">
          <span
            aria-hidden="true"
            className="h-6 w-6 animate-spin rounded-full border-2 border-line-strong border-t-brand"
          />
          <p className="text-[13px] text-fg-muted">
            Loading the shift report. Flagged suppliers may take a few seconds while the
            assist model writes their explanation.
          </p>
        </div>
      </StateFrame>
    );
  }

  if (state.kind === "error") {
    return (
      <StateFrame>
        <div role="alert" className="flex flex-col items-center gap-3 px-4 py-12 text-center">
          <p className="max-w-[52ch] text-[13.5px] text-fg-muted">
            The shift report could not be loaded. {state.message}
          </p>
          <Button variant="default" size="sm" onClick={() => void load()}>
            Retry
          </Button>
        </div>
      </StateFrame>
    );
  }

  const { report } = state;
  if (report.trucks === 0) {
    return (
      <StateFrame crumb="Console / Reports · no trucks">
        <p className="mx-auto max-w-[46ch] px-4 py-12 text-center text-[13.5px] text-fg-muted">
          No completed inspections yet: run one in the{" "}
          <Link href="/app" className="text-brand underline underline-offset-2">
            Inspection console
          </Link>
          .
        </p>
      </StateFrame>
    );
  }

  return (
    <>
      <PageHeader crumb={`Console / Reports · ${windowLabel(report)}`} title="Shift report">
        {report.sample_records > 0 ? (
          <span className="figure inline-flex items-center rounded-full border border-line-strong px-2.5 py-[5px] text-[12px] font-medium whitespace-nowrap text-fg-muted">
            {report.sample_records} / {report.trucks} scripted
          </span>
        ) : null}
        <CopySummaryButton report={report} />
        <Button variant="primary" onClick={() => window.print()}>
          <FileDown aria-hidden="true" className="h-3.5 w-3.5" />
          Export PDF
        </Button>
      </PageHeader>
      <PageBody className="flex flex-col gap-6">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-stretch">
          <SummaryCard report={report} />
          <ResolutionCard report={report} />
        </div>
        <SupplierPanel report={report} />
      </PageBody>
    </>
  );
}

/** Headline figures plus the verdict distribution bar. */
function SummaryCard({ report }: { report: ShiftReport }) {
  const rejected = report.by_verdict.reject ?? 0;
  const escalated = report.by_verdict.escalate_human ?? 0;
  const accepted = report.by_verdict.accept ?? 0;
  const prevented = report.loss_exposure_idr ?? report.prevented_loss_idr;
  const stats: { key: string; label: string; value: string; tone?: string; title?: string }[] = [
    { key: "trucks", label: "Trucks inspected", value: String(report.trucks) },
    {
      key: "rejected",
      label: "Rejected at gate",
      value: String(rejected),
      tone: rejected > 0 ? "text-danger" : undefined,
    },
    {
      key: "exposure",
      label: "Worst-case exposure",
      value: money(prevented),
      title:
        prevented > 0
          ? `${money(prevented, { full: true })}: each reject booked as certain shredder damage plus 1 h of kiln downtime.`
          : undefined,
    },
  ];
  const segments = [
    { key: "accept", label: "Accepted", count: accepted, color: "bg-success" },
    { key: "escalate", label: "Escalated", count: escalated, color: "bg-warning" },
    { key: "reject", label: "Rejected", count: rejected, color: "bg-danger" },
  ];
  const other = Math.max(0, report.trucks - accepted - escalated - rejected);
  if (other > 0) segments.push({ key: "other", label: "Other", count: other, color: "bg-fg-faint" });

  return (
    <section
      aria-label="Shift summary"
      className="card flex min-w-0 flex-1 flex-col justify-between gap-6 p-6"
    >
      <dl className="m-0 grid grid-cols-1 gap-4 sm:grid-cols-3 sm:gap-0">
        {stats.map((s, i) => (
          <div
            key={s.key}
            className={cn("flex min-w-0 flex-col gap-1.5", i > 0 && "sm:border-l sm:border-line sm:px-6")}
          >
            <dt className="text-[13px] text-fg-muted">{s.label}</dt>
            <dd
              title={s.title}
              className={cn(
                "figure m-0 truncate text-[clamp(28px,3vw,40px)] leading-tight font-light tracking-[-0.8px] text-fg",
                s.tone,
              )}
            >
              {s.value}
            </dd>
          </div>
        ))}
      </dl>
      <div className="flex flex-col gap-2.5">
        <div
          role="img"
          aria-label={segments.map((s) => `${s.label} ${s.count}`).join(", ")}
          className="flex h-2.5 w-full gap-[3px]"
        >
          {segments
            .filter((s) => s.count > 0)
            .map((s) => (
              <div
                key={s.key}
                className={cn("h-full min-w-[3px] rounded-[3px]", s.color)}
                style={{ flexGrow: s.count, flexBasis: 0 }}
              />
            ))}
        </div>
        <ul className="m-0 flex list-none flex-wrap gap-x-5 gap-y-1 p-0" aria-hidden="true">
          {segments.map((s) => (
            <li key={s.key} className="flex items-center gap-1.5 text-[12px] text-fg-muted">
              <span className={cn("h-2 w-2 rounded-full", s.color)} />
              {s.label} {s.count}
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

/** Dark call-to-action card: how many trucks still need a decision. */
function ResolutionCard({ report }: { report: ShiftReport }) {
  const rejected = report.by_verdict.reject ?? 0;
  const escalated = report.by_verdict.escalate_human ?? 0;
  const open = rejected + escalated;
  return (
    <section
      aria-label="Needs resolution"
      className="flex shrink-0 flex-col justify-between gap-5 rounded-[14px] bg-fg bg-[radial-gradient(ellipse_80%_80%_at_100%_0%,#2563EB4D_0%,#2563EB00_100%)] p-6 lg:w-[360px]"
    >
      <div className="flex flex-col gap-2">
        <div className="flex items-center gap-2 text-[13px] font-medium text-white/68">
          {open > 0 ? (
            <TriangleAlert aria-hidden="true" className="h-4 w-4 text-brand-soft" />
          ) : (
            <CircleCheck aria-hidden="true" className="h-4 w-4 text-success" />
          )}
          {open > 0 ? "Needs resolution" : "All resolved"}
        </div>
        <p className="m-0 font-display text-[36px] leading-tight font-medium text-white">
          {open > 0 ? `${open} ${open === 1 ? "truck" : "trucks"}` : "0 trucks"}
        </p>
        <p className="m-0 text-[13px] leading-5 text-white/68">
          {open > 0
            ? `${escalated} escalated and ${rejected} rejected ${open === 1 ? "load is" : "loads are"} waiting for a supervisor decision before the shift closes.`
            : "Every truck this shift has a final verdict. Nothing is waiting for a supervisor."}
        </p>
      </div>
      <Link
        href="/inspections"
        className="inline-flex h-9 w-full items-center justify-center gap-1.5 rounded-[8px] bg-brand px-3.5 text-[14px] font-medium text-white transition-colors duration-100 hover:bg-brand-deep"
      >
        <ListChecks aria-hidden="true" className="h-3.5 w-3.5" />
        {open > 0 ? "Open review queue" : "Open audit trail"}
      </Link>
    </section>
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

function CopySummaryButton({ report }: { report: ShiftReport }) {
  const [copied, setCopied] = useState(false);

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
    <Button variant="default" onClick={() => void copySummary()}>
      <Copy aria-hidden="true" className="h-3.5 w-3.5" />
      <span aria-live="polite">{copied ? "Copied" : "Copy summary"}</span>
    </Button>
  );
}

type SortKey = "risk" | "volume";

function SupplierPanel({ report }: { report: ShiftReport }) {
  const [sort, setSort] = useState<SortKey>("risk");
  const flaggedCount = report.suppliers.filter((s) => s.flagged).length;
  const rows = useMemo(() => {
    const copy = [...report.suppliers];
    copy.sort((a, b) =>
      sort === "risk"
        ? Number(b.flagged) - Number(a.flagged) || b.risk_score - a.risk_score || b.trucks - a.trucks
        : b.trucks - a.trucks || b.risk_score - a.risk_score,
    );
    return copy;
  }, [report.suppliers, sort]);

  return (
    <section className="card" aria-labelledby="supplier-risk-title">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-5 py-[18px]">
        <div className="flex min-w-0 flex-col gap-0.5">
          <h2 id="supplier-risk-title" className="m-0 font-display text-[18px] font-medium text-fg">
            Supplier risk
          </h2>
          <p className="m-0 text-[13px] text-fg-muted">
            {report.suppliers.length} {report.suppliers.length === 1 ? "supplier" : "suppliers"} this
            shift · {flaggedCount} flagged for review before next delivery
          </p>
        </div>
        <div role="group" aria-label="Sort suppliers" className="flex gap-0.5 rounded-full bg-surface-subtle p-[3px]">
          {(
            [
              ["risk", "By risk"],
              ["volume", "By volume"],
            ] as const
          ).map(([key, label]) => (
            <button
              key={key}
              type="button"
              aria-pressed={sort === key}
              onClick={() => setSort(key)}
              className={cn(
                "cursor-pointer rounded-full px-3 py-[5px] text-[13px] font-medium transition-colors duration-100",
                sort === key ? "bg-fg text-white" : "text-fg-muted hover:text-fg",
              )}
            >
              {label}
            </button>
          ))}
        </div>
      </div>
      <p className="sr-only">
        Risk = (rejected + 0.5 × escalated) ÷ trucks. Flagged at ≥{" "}
        {FLAG_MIN_TRUCKS} trucks and risk ≥ {FLAG_MIN_RISK.toFixed(2)}.
      </p>

      {/* Desktop table */}
      <Table className="hidden md:table">
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead className="pl-5">Supplier</TableHead>
            <TableHead className="w-[90px]">Trucks</TableHead>
            <TableHead className="w-[90px]">Rejected</TableHead>
            <TableHead className="w-[90px]">Escalated</TableHead>
            <TableHead className="w-[220px]">Risk score</TableHead>
            <TableHead className="w-[130px] pr-5">Status</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => (
            <SupplierTableRow key={row.supplier} row={row} />
          ))}
        </TableBody>
      </Table>

      {/* Mobile stacked rows */}
      <ul className="m-0 flex list-none flex-col gap-2 p-3 md:hidden">
        {rows.map((row) => (
          <li
            key={row.supplier}
            className={cn(
              "rounded-[10px] border border-line p-3",
              row.flagged ? "bg-danger/[0.03]" : "bg-surface",
            )}
          >
            <div className="flex items-start justify-between gap-3">
              <div className="flex min-w-0 items-center gap-2.5">
                <SupplierAvatar name={row.supplier} />
                <SupplierLink name={row.supplier} className="text-[14px] font-medium text-fg" />
              </div>
              <StatusMark row={row} />
            </div>
            <p className="m-0 mt-2 text-[12.5px] text-fg-muted">
              <span className="figure text-fg">{row.trucks}</span> trucks ·{" "}
              <span className={cn("figure", row.reject > 0 ? "text-danger" : "text-fg")}>
                {row.reject}
              </span>{" "}
              rejected · <span className="figure text-fg">{row.escalate}</span> escalated
            </p>
            <div className="mt-2">
              <RiskBar row={row} />
            </div>
            {row.flagged && row.explanation ? (
              <p className="m-0 mt-2 text-[12.5px] leading-snug text-fg-muted">{row.explanation}</p>
            ) : null}
          </li>
        ))}
      </ul>

      <div className="flex items-start gap-2 border-t border-line bg-surface-subtle px-5 py-3 text-[12px] text-fg-muted">
        <Info aria-hidden="true" className="mt-px h-3.5 w-3.5 shrink-0" />
        <p className="m-0">
          Suppliers with fewer than {FLAG_MIN_TRUCKS} trucks are marked “Few trucks” and are not
          flagged.
        </p>
      </div>
    </section>
  );
}

function SupplierAvatar({ name }: { name: string }) {
  return (
    <span
      aria-hidden="true"
      className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-line bg-surface-muted text-[11px] font-medium text-fg"
    >
      {initials(name)}
    </span>
  );
}

function SupplierTableRow({ row }: { row: SupplierRow }) {
  return (
    <TableRow className={cn(row.flagged ? "bg-danger/[0.03] hover:bg-danger/[0.05]" : "")}>
      <TableCell className="py-2 pl-5">
        <div className="flex items-center gap-2.5">
          <SupplierAvatar name={row.supplier} />
          <div className="flex min-w-0 flex-col">
            <SupplierLink name={row.supplier} className="text-[14px] font-medium text-fg" />
            {row.flagged && row.explanation ? (
              <p className="m-0 max-w-[60ch] text-[12px] leading-snug text-fg-muted">
                {row.explanation}
              </p>
            ) : null}
          </div>
        </div>
      </TableCell>
      <TableCell className="figure text-[13px] text-fg">{row.trucks}</TableCell>
      <TableCell className={cn("figure text-[13px]", row.reject > 0 ? "text-danger" : "text-fg")}>
        {row.reject}
      </TableCell>
      <TableCell className="figure text-[13px] text-fg">{row.escalate}</TableCell>
      <TableCell className="pr-10">
        <RiskBar row={row} />
      </TableCell>
      <TableCell className="whitespace-nowrap pr-5">
        <StatusMark row={row} />
      </TableCell>
    </TableRow>
  );
}

/** Risk 0..1 bar: red when flagged, orange at/over the threshold, green below. */
function RiskBar({ row }: { row: SupplierRow }) {
  const pct = Math.round(Math.min(1, Math.max(0, row.risk_score)) * 100);
  const color = row.flagged
    ? "bg-danger"
    : row.risk_score >= FLAG_MIN_RISK
      ? "bg-warning"
      : "bg-success";
  return (
    <div className="flex items-center gap-2.5">
      <div aria-hidden="true" className="relative h-1.5 flex-1 overflow-hidden rounded-[3px] bg-surface-muted">
        <div className={cn("h-full rounded-[3px]", color)} style={{ width: `${pct}%` }} />
      </div>
      <span className="figure text-[12px] text-fg-muted">
        <span className="sr-only">risk score </span>
        {row.risk_score.toFixed(2)}
      </span>
    </div>
  );
}

function StatusMark({ row }: { row: SupplierRow }) {
  if (row.flagged) return <Badge variant="reject">Flagged</Badge>;
  if (row.trucks < FLAG_MIN_TRUCKS) {
    return (
      <Badge variant="default" dot={false}>
        Few trucks
      </Badge>
    );
  }
  return <Badge variant="accept">Within limit</Badge>;
}
