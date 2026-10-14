"use client";

import { Fragment, Suspense, useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
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

const PAGE_SIZE = 25;

export function LedgerView() {
  return (
    <Suspense
      fallback={
        <Panel>
          <PanelHead title="Audit trail" meta="tamper-evident ledger" />
          <LedgerLoading />
        </Panel>
      }
    >
      <LedgerViewInner />
    </Suspense>
  );
}

function LedgerViewInner() {
  const searchParams = useSearchParams();
  const supplierParam = (searchParams.get("supplier") ?? "").trim();
  const [supplierFilter, setSupplierFilter] = useState(supplierParam);
  const [state, setState] = useState<LoadState>({ kind: "loading" });
  const [filter, setFilter] = useState<FilterKey>("all");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
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

  // Keep the address bar honest with the supplier chip: clear ?supplier=
  // when the chip is dismissed so a refresh doesn't silently re-filter.
  useEffect(() => {
    if (supplierFilter || !supplierParam) return;
    const url = new URL(window.location.href);
    url.searchParams.delete("supplier");
    window.history.replaceState(null, "", url.toString());
  }, [supplierFilter, supplierParam]);

  const ready = state.kind === "ready" ? state.inspections : [];

  /** Summary hairline figures: computed over ALL rows, not the filtered view. */
  const summary = useMemo(() => {
    const rejected = ready.filter(
      (item) => item.decision === "reject",
    ).length;
    // Two different things, never summed: worst-case loss exposure avoided
    // by rejecting or escalating, and the market value of loads let through.
    const prevented = ready.reduce(
      (total, item) => total + item.prevented_loss_idr,
      0,
    );
    const admitted = ready.reduce(
      (total, item) => total + item.admitted_value_idr,
      0,
    );
    return { total: ready.length, rejected, prevented, admitted };
  }, [ready]);

  const counts = useMemo(() => {
    const counts: Partial<Record<FilterKey, number>> = { all: ready.length };
    for (const item of ready) {
      counts[item.decision] = (counts[item.decision] ?? 0) + 1;
    }
    return counts;
  }, [ready]);

  const rows = useMemo(() => {
    const filteredBySupplier = supplierFilter
      ? ready.filter((item) => (item.supplier ?? "").trim() === supplierFilter)
      : ready;
    const filteredByVerdict =
      filter === "all"
        ? filteredBySupplier
        : filteredBySupplier.filter((item) => item.decision === filter);
    const term = search.trim().toLowerCase();
    const normTerm = term.replace(/[-\s]/g, "");
    const matchesSearch = (val: string) => {
      const lower = val.toLowerCase();
      if (lower.includes(term)) return true;
      if (normTerm && lower.replace(/[-\s]/g, "").includes(normTerm)) return true;
      return false;
    };
    const filtered = term
      ? filteredByVerdict.filter(
          (item) =>
            matchesSearch(item.record_id) || matchesSearch(item.truck_id),
        )
      : filteredByVerdict;
    const direction = sort.dir === "asc" ? 1 : -1;
    return [...filtered].sort((a, b) => {
      if (sort.column === "record") {
        return (recordNumber(a.record_id) - recordNumber(b.record_id)) * direction;
      }
      return (Date.parse(a.decided_at_utc) - Date.parse(b.decided_at_utc)) * direction;
    });
  }, [ready, filter, search, sort, supplierFilter]);

  const totalPages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  const currentPage = Math.min(Math.max(1, page), totalPages);
  const startIdx = rows.length === 0 ? 0 : (currentPage - 1) * PAGE_SIZE;
  const endIdx = rows.length === 0 ? 0 : Math.min(startIdx + PAGE_SIZE, rows.length);
  const pagedRows = rows.slice(startIdx, endIdx);

  const onFilterChange = (nextFilter: FilterKey) => {
    setFilter(nextFilter);
    setPage(1);
  };

  const onSearchChange = (nextSearch: string) => {
    setSearch(nextSearch);
    setPage(1);
  };

  const toggleSort = (column: SortColumn) => {
    setSort((prev) =>
      prev.column === column
        ? { column, dir: prev.dir === "asc" ? "desc" : "asc" }
        : { column, dir: "desc" },
    );
    setPage(1);
  };

  function sortIndicator(column: SortColumn): string {
    if (sort.column !== column) return "↕";
    return sort.dir === "asc" ? "▲" : "▼";
  }

  const closeDetail = useCallback(() => {
    const closingId = selectedId;
    setSelectedId(null);
    if (closingId) {
      const focusRow = () => {
        const targets = document.querySelectorAll<HTMLElement>(
          `[data-record-id="${closingId}"]`,
        );
        for (const el of targets) {
          if (el.getClientRects().length > 0) {
            el.focus();
            return;
          }
        }
        if (targets[0]) targets[0].focus();
      };
      focusRow();
      requestAnimationFrame(focusRow);
    }
  }, [selectedId]);

  const onRowClick = (recordId: string) => {
    if (selectedId === recordId) {
      closeDetail();
    } else {
      setSelectedId(recordId);
    }
  };

  useEffect(() => {
    if (!selectedId) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        closeDetail();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [selectedId, closeDetail]);

  return (
    <div className="flex flex-col gap-4">
      <Panel>
        <PanelHead title="Audit trail" meta="tamper-evident ledger" />

        {/* ---- states: loading / error ---- */}
        {state.kind === "loading" ? (
          <LedgerLoading />
        ) : state.kind === "error" ? (
          <LedgerError message={state.message} onRetry={load} />
        ) : ready.length === 0 ? (
          <LedgerEmpty />
        ) : (
          <>
            {/* ---- summary hairline: figures in mono, one tight inline run ---- */}
            <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 border-b border-seam px-4 py-2.5 text-[13px] text-muted">
              <span className="whitespace-nowrap">
                <strong className="figure font-semibold text-ink">
                  {summary.total}
                </strong>{" "}
                inspections
              </span>
              <span aria-hidden="true" className="text-faint">
                ·
              </span>
              <span className="whitespace-nowrap">
                <strong className="figure font-semibold text-verdict-red">
                  {summary.rejected}
                </strong>{" "}
                rejected
              </span>
              <span aria-hidden="true" className="text-faint">
                ·
              </span>
              <span className="figure whitespace-nowrap text-verdict-green">
                {formatRupiah(summary.prevented)}{" "}
                <span
                  className="text-muted"
                  title="Each reject is booked as if the contaminant would certainly have damaged the shredder and stopped the kiln for an hour. The probability-weighted value is on the Shift report."
                >
                  worst-case exposure avoided
                </span>
              </span>
              <span aria-hidden="true" className="text-faint">
                ·
              </span>
              <span className="figure whitespace-nowrap text-ink">
                {formatRupiah(summary.admitted)}{" "}
                <span className="text-muted">RDF value admitted</span>
              </span>
            </div>

            {/* ---- search + verdict filter ---- */}
            <div className="flex flex-wrap items-center justify-end gap-3 px-4 py-3">
              {supplierFilter ? (
                <button
                  type="button"
                  onClick={() => setSupplierFilter("")}
                  aria-label={`Clear supplier filter ${supplierFilter}`}
                  title="Clear supplier filter"
                  className="inline-flex cursor-pointer items-center gap-1.5 rounded-full border border-amber bg-amber-soft px-3 py-1 text-[12.5px] font-semibold text-ink transition-colors duration-100 hover:border-amber-line"
                >
                  Supplier: <span className="text-ink">{supplierFilter}</span>
                  <span aria-hidden="true" className="text-muted">✕</span>
                </button>
              ) : null}
              <div className="w-full sm:w-auto sm:flex-1">
                <input
                  type="search"
                  value={search}
                  onChange={(e) => onSearchChange(e.target.value)}
                  placeholder="Search record or plate…"
                  aria-label="Search record or plate"
                  className="input w-full text-[13px]"
                />
              </div>
              <div>
                <select
                  value={filter}
                  onChange={(e) => onFilterChange(e.target.value as FilterKey)}
                  aria-label="Filter inspections by verdict"
                  className="input w-full sm:w-auto cursor-pointer text-[13px]"
                >
                  {FILTERS.map(({ key, label }) => (
                    <option key={key} value={key}>
                      {label} {counts[key] ?? 0}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            {/* ---- ledger table (desktop) ---- hidden below md: the stacked
                cards replace it there (both rendered at once before, so a
                phone showed every row and the open record twice). */}
            <Table className="hidden md:table">
              <TableHeader>
                <TableRow className="hover:bg-raised">
                  <TableHead
                    aria-sort={
                      sort.column === "record"
                        ? sort.dir === "asc"
                          ? "ascending"
                          : "descending"
                        : "none"
                    }
                  >
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
                  <TableHead
                    aria-sort={
                      sort.column === "when"
                        ? sort.dir === "asc"
                          ? "ascending"
                          : "descending"
                        : "none"
                    }
                  >
                    <SortButton
                      active={sort.column === "when"}
                      indicator={sortIndicator("when")}
                      onClick={() => toggleSort("when")}
                    >
                      When
                    </SortButton>
                  </TableHead>
                  <TableHead className="text-right">Worst-case exposure</TableHead>
                  <TableHead className="text-right">RDF value admitted</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {pagedRows.map((row) => (
                  <Fragment key={row.record_id}>
                    <TableRow
                      data-record-id={row.record_id}
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
                      <TableCell
                        className={`figure text-right text-[12.5px] ${
                          row.admitted_value_idr > 0 ? "text-ink" : "text-muted"
                        }`}
                      >
                        {formatRupiah(row.admitted_value_idr)}
                      </TableCell>
                    </TableRow>
                    {selectedId === row.record_id ? (
                      <TableRow className="hover:bg-transparent">
                        <TableCell colSpan={6} className="p-2 sm:p-3">
                          <InspectionDetailPanel
                            recordId={row.record_id}
                            onClose={closeDetail}
                          />
                        </TableCell>
                      </TableRow>
                    ) : null}
                  </Fragment>
                ))}
                {pagedRows.length === 0 ? (
                  <TableRow className="hover:bg-transparent">
                    <TableCell
                      colSpan={6}
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
              {pagedRows.map((row) => (
                <Fragment key={row.record_id}>
                  <button
                    type="button"
                    data-record-id={row.record_id}
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
                          : row.admitted_value_idr > 0
                            ? "text-ink"
                            : "text-muted"
                      }`}
                    >
                      {row.admitted_value_idr > 0
                        ? `${formatRupiah(row.admitted_value_idr)} RDF value admitted`
                        : `${formatRupiah(row.prevented_loss_idr)} worst-case exposure`}
                    </div>
                  </button>
                  {selectedId === row.record_id ? (
                    <div className="py-1">
                      <InspectionDetailPanel
                        recordId={row.record_id}
                        onClose={closeDetail}
                      />
                    </div>
                  ) : null}
                </Fragment>
              ))}
              {pagedRows.length === 0 ? (
                <p className="py-8 text-center text-[13px] text-muted">
                  No inspections match this filter.
                </p>
              ) : null}
            </div>

            {/* ---- pagination footer ---- */}
            <div className="flex flex-wrap items-center justify-between gap-3 border-t border-seam px-4 py-3">
              <span className="figure text-[12.5px] text-muted">
                Showing{" "}
                {rows.length === 0
                  ? "0 of 0"
                  : `${startIdx + 1}–${endIdx} of ${rows.length}`}
              </span>
              <div className="flex items-center gap-2">
                <Button
                  variant="default"
                  size="sm"
                  disabled={currentPage <= 1}
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                >
                  Prev
                </Button>
                <Button
                  variant="default"
                  size="sm"
                  disabled={currentPage >= totalPages}
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                >
                  Next
                </Button>
              </div>
            </div>
          </>
        )}
      </Panel>
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
    <div
      role="status"
      className="flex flex-col items-center gap-3 px-4 py-12 text-center"
    >
      <span
        aria-hidden="true"
        className="h-6 w-6 animate-spin rounded-full border-2 border-seam border-t-amber"
      />
      <span className="sr-only">Loading</span>
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
