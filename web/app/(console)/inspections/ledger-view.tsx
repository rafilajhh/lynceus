"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  ApiError,
  fetchInspections,
  type Decision,
  type InspectionSummary,
} from "@/lib/api";
import { formatRupiah, relativeTime } from "@/lib/format";
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
import { InspectionDetailPanel } from "./inspection-detail-panel";

/** Filter keys map 1:1 onto Decision, plus "all". */
type FilterKey = Decision | "all";
type LoadState =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ready"; inspections: InspectionSummary[] };



const FILTERS: readonly { key: FilterKey; label: string }[] = [
  { key: "all", label: "All" },
  { key: "accept", label: "Accepted" },
  { key: "escalate_human", label: "Escalated" },
  { key: "reject", label: "Rejected" },
  { key: "refuse_insufficient_input", label: "Refused" },
] as const;

const VERDICT_LABEL: Record<Decision, string> = {
  accept: "Accepted",
  reject: "Rejected",
  escalate_human: "Escalated",
  refuse_insufficient_input: "Refused",
  unknown: "Unknown",
};

/** Decision → Badge variant (shadcn Badge names differ from the API enum). */
const DECISION_BADGE = {
  accept: "accept",
  reject: "reject",
  escalate_human: "escalate",
  refuse_insufficient_input: "refuse",
  unknown: "default",
} as const;

/** Natural sort for inspection-NNNNNN ids: numeric tail, not lexicographic. */
function recordNumber(recordId: string): number {
  const match = /(\d+)$/.exec(recordId);
  return match ? Number.parseInt(match[1], 10) : Number.MAX_SAFE_INTEGER;
}
type SortColumn = "record" | "when";
type SortDir = "asc" | "desc";

export function LedgerView() {
  const [state, setState] = useState<LoadState>({ kind: "loading" });
  const [filter, setFilter] = useState<FilterKey>("all");
  const [sort, setSort] = useState<{ column: SortColumn; dir: SortDir }>({
    column: "record",
    dir: "desc",
  });
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setState({ kind: "loading" });
    try {
      const inspections = await fetchInspections();
      setState({ kind: "ready", inspections });
    } catch (err) {
      const message =
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : "Unexpected error loading the ledger.";
      setState({ kind: "error", message });
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const ready = state.kind === "ready" ? state.inspections : [];

  /** Summary hairline figures: computed over ALL rows, not the filtered view. */
  const summary = useMemo(() => {
    const rejected = ready.filter(
      (item) => item.decision === "reject",
    ).length;
    const prevented = ready.reduce(
      (total, item) => total + item.prevented_loss_idr,
      0,
    );
    return { total: ready.length, rejected, prevented };
  }, [ready]);

  const counts = useMemo(() => {
    const counts: Partial<Record<FilterKey, number>> = { all: ready.length };
    for (const item of ready) {
      counts[item.decision] = (counts[item.decision] ?? 0) + 1;
    }
    return counts;
  }, [ready]);

  const rows = useMemo(() => {
    const filtered =
      filter === "all"
        ? ready
        : ready.filter((item) => item.decision === filter);
    const direction = sort.dir === "asc" ? 1 : -1;
    return [...filtered].sort((a, b) => {
      if (sort.column === "record") {
        return (recordNumber(a.record_id) - recordNumber(b.record_id)) * direction;
      }
      return (Date.parse(a.decided_at_utc) - Date.parse(b.decided_at_utc)) * direction;
    });
  }, [ready, filter, sort]);

  function toggleSort(column: SortColumn) {
    setSort((prev) =>
      prev.column === column
        ? { column, dir: prev.dir === "asc" ? "desc" : "asc" }
        : { column, dir: "desc" },
    );
  }

  function sortIndicator(column: SortColumn): string {
    if (sort.column !== column) return "↕";
    return sort.dir === "asc" ? "▲" : "▼";
  }

  function onRowClick(recordId: string) {
    // Clicking the selected row again collapses the detail panel.
    setSelectedId((prev) => (prev === recordId ? null : recordId));
  }

  return (
    <div className="flex flex-col gap-4">
      <Panel>
        <PanelHead title="Audit trail" meta="immutable ledger" />

        {/* ---- states: loading / error ---- */}
        {state.kind === "loading" ? (
          <LedgerLoading />
        ) : state.kind === "error" ? (
          <LedgerError message={state.message} onRetry={load} />
        ) : ready.length === 0 ? (
          <LedgerEmpty />
        ) : (
          <>
            {/* ---- summary hairline ---- */}
            <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1 border-b border-seam px-4 py-2.5 text-[13px] text-muted">
              <span>
                <strong className="font-semibold text-ink figure">
                  {summary.total}
                </strong>{" "}
                inspection{summary.total === 1 ? "" : "s"}
              </span>
              <span className="text-faint">·</span>
              <span>
                <strong className="font-semibold text-verdict-red figure">
                  {summary.rejected}
                </strong>{" "}
                rejected
              </span>
              <span className="text-faint">·</span>
              <span className="figure text-verdict-green">
                {formatRupiah(summary.prevented)} prevented
              </span>
            </div>

            {/* ---- filter chips ---- */}
            <div
              className="flex flex-wrap gap-2 px-4 py-3"
              role="group"
              aria-label="Filter inspections by verdict"
            >
              {FILTERS.map(({ key, label }) => (
                <button
                  key={key}
                  type="button"
                  aria-pressed={filter === key}
                  onClick={() => setFilter(key)}
                  className={`cursor-pointer rounded-full border px-3 py-1 text-[12.5px] font-semibold transition-colors duration-100 ${
                    filter === key
                      ? "border-amber bg-amber-soft text-ink"
                      : "border-seam text-muted hover:border-seam-strong hover:text-ink"
                  }`}
                >
                  {label}
                  <span className="figure ml-1.5 text-[12px] text-muted">
                    {counts[key] ?? 0}
                  </span>
                </button>
              ))}
            </div>

            {/* ---- ledger table (desktop) ---- */}
            <Table>
              <TableHeader>
                <TableRow className="hover:bg-raised">
                  <TableHead>
                    <SortButton
                      active={sort.column === "record"}
                      indicator={sortIndicator("record")}
                      onClick={() => toggleSort("record")}
                    >
                      Record
                    </SortButton>
                  </TableHead>
                  <TableHead>Truck</TableHead>
                  <TableHead>Verdict</TableHead>
                  <TableHead>
                    <SortButton
                      active={sort.column === "when"}
                      indicator={sortIndicator("when")}
                      onClick={() => toggleSort("when")}
                    >
                      When
                    </SortButton>
                  </TableHead>
                  <TableHead className="text-right">Prevented loss</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((row) => (
                  <TableRow
                    key={row.record_id}
                    onClick={() => onRowClick(row.record_id)}
                    tabIndex={0}
                    role="button"
                    aria-expanded={selectedId === row.record_id}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        onRowClick(row.record_id);
                      }
                    }}
                    className={`cursor-pointer ${
                      selectedId === row.record_id
                        ? "bg-raised shadow-[inset_3px_0_0_0_var(--color-amber)]"
                        : ""
                    }`}
                  >
                    <TableCell className="figure text-[12.5px] text-ink">
                      {row.record_id}
                    </TableCell>
                    <TableCell className="figure text-[12.5px] text-muted">
                      {row.truck_id}
                    </TableCell>
                    <TableCell>
                      <Badge variant={DECISION_BADGE[row.decision]}>
                        <span
                          aria-hidden="true"
                          className="h-1.5 w-1.5 rounded-full bg-current"
                        />
                        {VERDICT_LABEL[row.decision]}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-[12.5px] whitespace-nowrap text-muted">
                      {relativeTime(row.decided_at_utc)}
                    </TableCell>
                    <TableCell
                      className={`figure text-right text-[12.5px] ${
                        row.prevented_loss_idr > 0
                          ? "text-verdict-green"
                          : "text-muted"
                      }`}
                    >
                      {formatRupiah(row.prevented_loss_idr)}
                    </TableCell>
                  </TableRow>
                ))}
                {rows.length === 0 ? (
                  <TableRow className="hover:bg-transparent">
                    <TableCell
                      colSpan={5}
                      className="py-10 text-center text-[13px] text-muted"
                    >
                      No inspections match this filter.
                    </TableCell>
                  </TableRow>
                ) : null}
              </TableBody>
            </Table>

            {/* ---- stacked cards (mobile) ---- */}
            <div className="flex flex-col gap-2 p-3 md:hidden">
              {rows.map((row) => (
                <button
                  key={row.record_id}
                  type="button"
                  onClick={() => onRowClick(row.record_id)}
                  aria-expanded={selectedId === row.record_id}
                  className={`cursor-pointer rounded-[10px] border border-seam bg-raised p-3 text-left transition-colors duration-100 ${
                    selectedId === row.record_id
                      ? "border-amber-line"
                      : "hover:border-seam-strong"
                  }`}
                >
                  <div className="flex items-center justify-between gap-3">
                    <span className="figure text-[12.5px] text-ink">
                      {row.record_id}
                    </span>
                    <Badge variant={DECISION_BADGE[row.decision]}>
                      {VERDICT_LABEL[row.decision]}
                    </Badge>
                  </div>
                  <div className="mt-2 flex items-center justify-between gap-3 text-[12.5px] text-muted">
                    <span className="figure">{row.truck_id}</span>
                    <span>{relativeTime(row.decided_at_utc)}</span>
                  </div>
                  <div
                    className={`mt-1 text-right figure text-[12px] ${
                      row.prevented_loss_idr > 0
                        ? "text-verdict-green"
                        : "text-muted"
                    }`}
                  >
                    {formatRupiah(row.prevented_loss_idr)}
                  </div>
                </button>
              ))}
              {rows.length === 0 ? (
                <p className="py-8 text-center text-[13px] text-muted">
                  No inspections match this filter.
                </p>
              ) : null}
            </div>
          </>
        )}
      </Panel>

      {/* ---- detail panel (inline, not a modal) ---- */}
      {selectedId ? (
        <InspectionDetailPanel
          recordId={selectedId}
          onClose={() => setSelectedId(null)}
        />
      ) : null}
    </div>
  );
}

function SortButton({
  active,
  indicator,
  onClick,
  children,
}: {
  active: boolean;
  indicator: string;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={`${children}: toggle sort order`}
      className={`cursor-pointer uppercase transition-colors duration-100 hover:text-ink ${
        active ? "text-ink" : ""
      }`}
    >
      {children}
      <span
        aria-hidden="true"
        className={`ml-1.5 inline-flex items-center rounded-[4px] px-1 py-0.5 text-[12px] ${active ? "text-amber" : "text-muted"}`}
      >
        {indicator}
      </span>
    </button>
  );
}

function LedgerLoading() {
  return (
    <div className="flex flex-col items-center gap-3 px-4 py-12 text-center">
      <span
        aria-hidden="true"
        className="h-6 w-6 animate-spin rounded-full border-2 border-seam border-t-amber"
      />
      <p className="text-[13px] text-muted">Loading inspection records…</p>
    </div>
  );
}

function LedgerEmpty() {
  return (
    <div className="flex flex-col items-center gap-3 px-4 py-12 text-center">
      <div
        className="figure text-[30px] leading-none text-faint"
        aria-hidden="true"
      >
        ≡
      </div>
      <p className="max-w-[46ch] text-[13.5px] text-muted">
        No inspections yet: run one in the{" "}
        <Link href="/app" className="text-amber underline underline-offset-2">
          Inspection console
        </Link>
        .
      </p>
    </div>
  );
}

function LedgerError({
  message,
  onRetry,
}: {
  message: string;
  onRetry: () => void;
}) {
  return (
    <div
      role="alert"
      className="flex flex-col items-center gap-3 px-4 py-12 text-center"
    >
      <div
        className="figure text-[30px] leading-none text-verdict-red"
        aria-hidden="true"
      >
        ✕
      </div>
      <p className="max-w-[52ch] text-[13.5px] text-muted">
        The ledger could not be loaded. {message} Start the FastAPI backend
        (see README), then retry: records are read live from the API, so
        nothing is lost.
      </p>
      <Button variant="default" size="sm" onClick={onRetry}>
        Retry
      </Button>
    </div>
  );
}
