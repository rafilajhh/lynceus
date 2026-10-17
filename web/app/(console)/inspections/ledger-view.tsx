"use client";

import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import {
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  ChevronLeft,
  ChevronRight,
  Download,
  Lock,
  Plus,
  Search,
  X,
} from "lucide-react";
import {
  ApiError,
  fetchInspections,
  type Decision,
  type InspectionSummary,
} from "@/lib/api";
import { relativeTime } from "@/lib/format";
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
import { GATE_LABEL, orderedGates } from "./gate-labels";
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

/** Decision → Badge variant (Badge names differ from the API enum). */
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

/** "inspection-000014", "inspection-14", "inspection 14", "INSPECTION–000014". */
const RECORD_REF = /^inspection[\s#_-]*0*(\d+)$/;

/**
 * Search over record id and plate. A full record reference matches that
 * record by number (so "inspection-000014" and "inspection-14" both find
 * it); anything else matches as a substring, also with separators
 * stripped ("b9174" finds "B 9174 KT", "000014" finds the record).
 */
function matchesSearch(item: InspectionSummary, rawTerm: string): boolean {
  const term = rawTerm.trim().toLowerCase().replace(/[‐-―]/g, "-");
  if (!term) return true;
  const ref = RECORD_REF.exec(term);
  if (ref && recordNumber(item.record_id) === Number.parseInt(ref[1], 10)) {
    return true;
  }
  const normTerm = term.replace(/[^a-z0-9]/g, "");
  return [item.record_id, item.truck_id].some((value) => {
    const lower = value.toLowerCase();
    if (lower.includes(term)) return true;
    return normTerm !== "" && lower.replace(/[^a-z0-9]/g, "").includes(normTerm);
  });
}

/** One line of what the gate checks said: failed checks by name, else the
    pass count. Read from the summary's gate_states (no extra fetch). */
function checksSummary(item: InspectionSummary): string {
  const gates = orderedGates(item.gate_states);
  const failed = gates
    .filter(([, state]) => state === "failed")
    .map(([name]) => GATE_LABEL[name] ?? name);
  if (failed.length > 0) return `${failed.join(" · ")} failed`;
  if (item.decision === "refuse_insufficient_input") return "Insufficient input";
  if (gates.length === 0) return "No checks recorded";
  const passed = gates.filter(([, state]) => state === "passed").length;
  return passed === gates.length
    ? `All ${gates.length} checks passed`
    : `${passed} of ${gates.length} checks passed`;
}

/** Ledger reason: the backend's one-liner, else the gate-check summary
    (older backends that do not send `reason`). */
function rowReason(item: InspectionSummary): string {
  return item.reason || checksSummary(item);
}

/** "7f3a…c21e" from `sha256:<hex>`; null when the list has no digest. */
function sealShort(digest: string | null | undefined): string | null {
  const hex = digest?.replace(/^sha256:/, "");
  return hex && hex.length >= 8 ? `${hex.slice(0, 4)}…${hex.slice(-4)}` : null;
}

const pad2 = (n: number) => String(n).padStart(2, "0");

/** "since 04:32 UTC" today, "since 15 Oct, 04:32 UTC" for older ledgers. */
function sinceLabel(items: InspectionSummary[]): string {
  const times = items
    .map((item) => Date.parse(item.decided_at_utc))
    .filter((t) => Number.isFinite(t));
  if (times.length === 0) return "no timestamps recorded";
  const first = new Date(Math.min(...times));
  const hhmm = `${pad2(first.getUTCHours())}:${pad2(first.getUTCMinutes())} UTC`;
  const today = new Date();
  const sameDay =
    first.getUTCFullYear() === today.getUTCFullYear() &&
    first.getUTCMonth() === today.getUTCMonth() &&
    first.getUTCDate() === today.getUTCDate();
  if (sameDay) return `since ${hhmm}`;
  const date = first.toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    timeZone: "UTC",
  });
  return `since ${date}, ${hhmm}`;
}

/** CSV of the rows currently in view (filter, search and sort applied). */
function downloadCsv(items: InspectionSummary[]) {
  const cell = (raw: string) => {
    // Spreadsheet formula guard, then RFC 4180 quoting.
    const value = /^[=+\-@\t\r]/.test(raw) ? `'${raw}` : raw;
    return /[",\n\r]/.test(value) ? `"${value.replace(/"/g, '""')}"` : value;
  };
  const lines = [
    ["record_id", "truck_id", "supplier", "decision", "decided_at_utc", "reason", "record_sha256"].join(","),
    ...items.map((item) =>
      [
        item.record_id,
        item.truck_id,
        item.supplier ?? "",
        item.decision,
        item.decided_at_utc,
        rowReason(item),
        item.record_sha256 ?? "",
      ]
        .map(cell)
        .join(","),
    ),
  ];
  const blob = new Blob([`${lines.join("\r\n")}\r\n`], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `lynceus-audit-trail-${new Date().toISOString().slice(0, 10)}.csv`;
  anchor.click();
  URL.revokeObjectURL(url);
}

export function LedgerView() {
  return (
    <Suspense
      fallback={
        <>
          <LedgerHeader />
          <PageBody>
            <div className="card">
              <LedgerLoading />
            </div>
          </PageBody>
        </>
      }
    >
      <LedgerViewInner />
    </Suspense>
  );
}

function LedgerHeader({ onExport }: { onExport?: () => void }) {
  return (
    <PageHeader crumb="Console / Records" title="Audit trail">
      <Button
        variant="default"
        onClick={onExport}
        disabled={!onExport}
        title="Download the rows in view as CSV"
      >
        <Download aria-hidden="true" className="h-3.5 w-3.5" />
        Export CSV
      </Button>
      <Link href="/app" className={buttonVariants({ variant: "primary" })}>
        <Plus aria-hidden="true" className="h-3.5 w-3.5" />
        New inspection
      </Link>
    </PageHeader>
  );
}

function LedgerViewInner() {
  const searchParams = useSearchParams();
  const supplierParam = (searchParams.get("supplier") ?? "").trim();
  /** The open record lives in ?record= so a refresh or a shared link
      reopens it; Back returns to the ledger with filters intact. */
  const selectedId = (searchParams.get("record") ?? "").trim() || null;
  const [supplierFilter, setSupplierFilter] = useState(supplierParam);
  const [state, setState] = useState<LoadState>({ kind: "loading" });
  const [filter, setFilter] = useState<FilterKey>("all");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [sort, setSort] = useState<{ column: SortColumn; dir: SortDir }>({
    column: "record",
    dir: "desc",
  });
  /** True when this session pushed the ?record= entry (Back can pop it). */
  const openedHere = useRef(false);
  /** Row to refocus once the ledger is back on screen. */
  const restoreFocusId = useRef<string | null>(null);

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

  const ready = useMemo(
    () => (state.kind === "ready" ? state.inspections : []),
    [state],
  );

  /** Rows in the supplier's scope (all rows without a supplier chip):
      stat cards and tab counts are computed here, before verdict/search. */
  const scoped = useMemo(
    () =>
      supplierFilter
        ? ready.filter((item) => (item.supplier ?? "").trim() === supplierFilter)
        : ready,
    [ready, supplierFilter],
  );

  const counts = useMemo(() => {
    const counts: Partial<Record<FilterKey, number>> = { all: scoped.length };
    for (const item of scoped) {
      counts[item.decision] = (counts[item.decision] ?? 0) + 1;
    }
    return counts;
  }, [scoped]);

  const rows = useMemo(() => {
    const filteredByVerdict =
      filter === "all" ? scoped : scoped.filter((item) => item.decision === filter);
    const filtered = search.trim()
      ? filteredByVerdict.filter((item) => matchesSearch(item, search))
      : filteredByVerdict;
    const direction = sort.dir === "asc" ? 1 : -1;
    return [...filtered].sort((a, b) => {
      if (sort.column === "record") {
        return (recordNumber(a.record_id) - recordNumber(b.record_id)) * direction;
      }
      return (Date.parse(a.decided_at_utc) - Date.parse(b.decided_at_utc)) * direction;
    });
  }, [scoped, filter, search, sort]);

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

  const setRecordParam = useCallback(
    (recordId: string | null, mode: "push" | "replace") => {
      const url = new URL(window.location.href);
      if (recordId) url.searchParams.set("record", recordId);
      else url.searchParams.delete("record");
      if (mode === "push") window.history.pushState(null, "", url.toString());
      else window.history.replaceState(null, "", url.toString());
    },
    [],
  );

  const openRecord = (recordId: string) => {
    openedHere.current = true;
    setRecordParam(recordId, "push");
  };

  /** Records the detail's ↑/↓ step through: the ledger as filtered and
      sorted, or the whole ledger when the open record is filtered out. */
  const navList = useMemo(() => {
    if (!selectedId) return [];
    if (rows.some((item) => item.record_id === selectedId)) return rows;
    return [...ready].sort((a, b) => recordNumber(b.record_id) - recordNumber(a.record_id));
  }, [rows, ready, selectedId]);
  const navIndex = selectedId
    ? navList.findIndex((item) => item.record_id === selectedId)
    : -1;

  const closeDetail = useCallback(() => {
    if (!selectedId) return;
    restoreFocusId.current = selectedId;
    // Land on the page that holds the record just read.
    const idx = rows.findIndex((item) => item.record_id === selectedId);
    if (idx !== -1) setPage(Math.floor(idx / PAGE_SIZE) + 1);
    if (openedHere.current) {
      openedHere.current = false;
      window.history.back();
    } else {
      setRecordParam(null, "replace");
    }
  }, [selectedId, rows, setRecordParam]);

  // Back on the ledger: return focus to the row that was open.
  useEffect(() => {
    if (selectedId || !restoreFocusId.current) return;
    const recordId = restoreFocusId.current;
    const focusRow = () => {
      const targets = document.querySelectorAll<HTMLElement>(
        `[data-record-id="${CSS.escape(recordId)}"]`,
      );
      for (const el of targets) {
        if (el.getClientRects().length > 0) {
          restoreFocusId.current = null;
          el.focus();
          return;
        }
      }
    };
    focusRow();
    const frame = requestAnimationFrame(focusRow);
    return () => cancelAnimationFrame(frame);
  }, [selectedId, state, currentPage]);

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

  if (selectedId) {
    const prevId = navIndex > 0 ? navList[navIndex - 1].record_id : null;
    const nextId =
      navIndex !== -1 && navIndex < navList.length - 1
        ? navList[navIndex + 1].record_id
        : null;
    return (
      <InspectionDetailPanel
        recordId={selectedId}
        onClose={closeDetail}
        position={navIndex === -1 ? null : { index: navIndex, total: navList.length }}
        prevId={prevId}
        nextId={nextId}
        onNavigate={(recordId) => setRecordParam(recordId, "replace")}
      />
    );
  }

  const ariaSort = (column: SortColumn) =>
    sort.column === column ? (sort.dir === "asc" ? "ascending" : "descending") : "none";

  const total = scoped.length;
  const accepted = counts.accept ?? 0;
  const escalated = counts.escalate_human ?? 0;
  const rejected = counts.reject ?? 0;

  return (
    <>
      <LedgerHeader
        onExport={state.kind === "ready" && rows.length > 0 ? () => downloadCsv(rows) : undefined}
      />
      <PageBody className="flex flex-col gap-6">
        {state.kind === "loading" ? (
          <div className="card">
            <LedgerLoading />
          </div>
        ) : state.kind === "error" ? (
          <div className="card">
            <LedgerError message={state.message} onRetry={load} />
          </div>
        ) : ready.length === 0 ? (
          <div className="card">
            <LedgerEmpty />
          </div>
        ) : (
          <>
            {/* ---- stat cards: counts over the loaded ledger ---- */}
            <section
              aria-label="Ledger summary"
              className="grid grid-cols-2 gap-3 md:gap-4 xl:grid-cols-4"
            >
              <StatCard label="Inspections" value={total} dot="bg-fg" note={sinceLabel(scoped)} />
              <StatCard
                label="Accepted"
                value={accepted}
                dot="bg-success"
                note={total > 0 ? `${Math.round((accepted / total) * 100)}% of trucks` : "no trucks yet"}
              />
              <StatCard
                label="Escalated"
                value={escalated}
                dot="bg-warning"
                note="need a human decision"
              />
              <StatCard
                label="Rejected"
                value={rejected}
                dot="bg-danger"
                note="turned away at gate"
              />
            </section>

            <section aria-label="Inspection records" className="card shadow-none">
              {/* ---- toolbar: verdict tabs + search ---- */}
              <div className="flex flex-col gap-3 border-b border-line px-4 py-3.5 lg:flex-row lg:items-center lg:justify-between">
                <div
                  role="group"
                  aria-label="Filter inspections by verdict"
                  className="-mx-1 flex items-center gap-0.5 overflow-x-auto px-1"
                >
                  {FILTERS.filter(
                    ({ key }) =>
                      key !== "refuse_insufficient_input" ||
                      (counts[key] ?? 0) > 0 ||
                      filter === key,
                  ).map(({ key, label }) => {
                    const active = filter === key;
                    return (
                      <button
                        key={key}
                        type="button"
                        aria-pressed={active}
                        onClick={() => onFilterChange(key)}
                        className={cn(
                          "shrink-0 cursor-pointer rounded-full px-3.5 py-2 text-[13px] font-medium whitespace-nowrap transition-colors duration-100",
                          active
                            ? "bg-fg text-white"
                            : "text-fg-muted hover:bg-surface-subtle hover:text-fg",
                        )}
                      >
                        {label} · <span className="figure">{counts[key] ?? 0}</span>
                      </button>
                    );
                  })}
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  {supplierFilter ? (
                    <button
                      type="button"
                      onClick={() => setSupplierFilter("")}
                      aria-label={`Clear supplier filter ${supplierFilter}`}
                      title="Clear supplier filter"
                      className="inline-flex h-9 cursor-pointer items-center gap-1.5 rounded-full border border-brand/25 bg-brand/5 px-3 text-[13px] font-medium text-fg transition-colors duration-100 hover:border-brand/50"
                    >
                      Supplier: <span>{supplierFilter}</span>
                      <X aria-hidden="true" className="h-3.5 w-3.5 text-fg-muted" />
                    </button>
                  ) : null}
                  <div className="relative w-full sm:w-[280px]">
                    <Search
                      aria-hidden="true"
                      className="pointer-events-none absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2 text-fg-subtle"
                    />
                    <input
                      type="search"
                      value={search}
                      onChange={(e) => onSearchChange(e.target.value)}
                      placeholder="Search record or plate…"
                      aria-label="Search record or plate"
                      className="input h-9! pl-9! placeholder:text-fg-faint"
                    />
                  </div>
                </div>
              </div>

              {/* ---- ledger table (desktop) ---- hidden below md: the stacked
                  cards replace it there. */}
              <Table className="hidden md:table">
                <TableHeader>
                  <TableRow className="hover:bg-transparent">
                    <TableHead aria-sort={ariaSort("record")}>
                      <SortButton
                        active={sort.column === "record"}
                        dir={sort.dir}
                        onClick={() => toggleSort("record")}
                      >
                        Record
                      </SortButton>
                    </TableHead>
                    <TableHead>Truck</TableHead>
                    <TableHead>Verdict</TableHead>
                    <TableHead className="w-full">Reason</TableHead>
                    <TableHead>Audit seal</TableHead>
                    <TableHead aria-sort={ariaSort("when")}>
                      <SortButton
                        active={sort.column === "when"}
                        dir={sort.dir}
                        onClick={() => toggleSort("when")}
                      >
                        When
                      </SortButton>
                    </TableHead>
                    <TableHead className="w-9">
                      <span className="sr-only">Open</span>
                    </TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {pagedRows.map((row) => (
                    <TableRow
                      key={row.record_id}
                      data-record-id={row.record_id}
                      onClick={() => openRecord(row.record_id)}
                      tabIndex={0}
                      role="button"
                      aria-label={`Open ${row.record_id}, ${row.truck_id}, ${VERDICT_LABEL[row.decision]}`}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault();
                          openRecord(row.record_id);
                        }
                      }}
                      className="group cursor-pointer hover:bg-brand/[0.04] focus-visible:bg-brand/[0.04] focus-visible:outline-none"
                    >
                      <TableCell className="figure text-[13px] whitespace-nowrap text-fg">
                        {row.record_id}
                      </TableCell>
                      <TableCell className="text-[14px] font-medium whitespace-nowrap text-fg">
                        {row.truck_id}
                      </TableCell>
                      <TableCell>
                        <Badge variant={DECISION_BADGE[row.decision]} className="px-2.5">
                          {VERDICT_LABEL[row.decision]}
                        </Badge>
                      </TableCell>
                      <TableCell className="max-w-0 truncate text-[13px] text-fg-muted">
                        {rowReason(row)}
                      </TableCell>
                      <TableCell className="whitespace-nowrap">
                        {sealShort(row.record_sha256) ? (
                          <span
                            className="figure inline-flex items-center gap-1.5 text-[12px] text-fg-muted"
                            title={row.record_sha256 ?? undefined}
                          >
                            <Lock aria-hidden="true" className="h-3 w-3 text-fg-subtle" />
                            {sealShort(row.record_sha256)}
                          </span>
                        ) : (
                          <span className="text-[12px] text-fg-subtle">—</span>
                        )}
                      </TableCell>
                      <TableCell className="text-[13px] whitespace-nowrap text-fg-muted">
                        {relativeTime(row.decided_at_utc)}
                      </TableCell>
                      <TableCell className="pl-0 text-fg-subtle">
                        <ChevronRight
                          aria-hidden="true"
                          className="h-4 w-4 transition-transform duration-100 group-hover:translate-x-0.5"
                        />
                      </TableCell>
                    </TableRow>
                  ))}
                  {pagedRows.length === 0 ? (
                    <TableRow className="hover:bg-transparent">
                      <TableCell
                        colSpan={7}
                        className="py-10 text-center text-[13px] text-fg-muted"
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
                  <button
                    key={row.record_id}
                    type="button"
                    data-record-id={row.record_id}
                    onClick={() => openRecord(row.record_id)}
                    className="cursor-pointer rounded-[10px] border border-line-strong bg-surface p-3 text-left transition-colors duration-100 hover:bg-surface-subtle"
                  >
                    <div className="flex items-center justify-between gap-3">
                      <span className="figure text-[13px] text-fg">{row.record_id}</span>
                      <Badge variant={DECISION_BADGE[row.decision]}>
                        {VERDICT_LABEL[row.decision]}
                      </Badge>
                    </div>
                    <div className="mt-2 flex items-center justify-between gap-3 text-[13px] text-fg-muted">
                      <span className="font-medium text-fg">{row.truck_id}</span>
                      <span>{relativeTime(row.decided_at_utc)}</span>
                    </div>
                    <div className="mt-1 truncate text-[12px] text-fg-subtle">
                      {rowReason(row)}
                    </div>
                  </button>
                ))}
                {pagedRows.length === 0 ? (
                  <p className="py-8 text-center text-[13px] text-fg-muted">
                    No inspections match this filter.
                  </p>
                ) : null}
              </div>

              {/* ---- pagination footer ---- */}
              <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line px-4 py-3">
                <span className="text-[13px] text-fg-muted">
                  Showing{" "}
                  <span className="figure">
                    {rows.length === 0 ? "0" : `${startIdx + 1}–${endIdx}`}
                  </span>{" "}
                  of <span className="figure">{rows.length}</span> records
                </span>
                <div className="flex items-center gap-2">
                  <Button
                    variant="default"
                    size="sm"
                    disabled={currentPage <= 1}
                    onClick={() => setPage((p) => Math.max(1, p - 1))}
                  >
                    <ChevronLeft aria-hidden="true" className="h-3.5 w-3.5" />
                    Previous
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
            </section>
          </>
        )}
      </PageBody>
    </>
  );
}

function StatCard({
  label,
  value,
  dot,
  note,
}: {
  label: string;
  value: number;
  dot: string;
  note: string;
}) {
  return (
    <div className="flex min-w-0 flex-col gap-1.5 rounded-[10px] border border-line-strong bg-surface p-4 md:p-5">
      <span className="text-[13px] text-fg-muted">{label}</span>
      <span className="figure text-[26px] leading-tight font-light text-fg md:text-[30px]">
        {value}
      </span>
      <span className="flex min-w-0 items-center gap-1.5 text-[12px] text-fg-muted">
        <span aria-hidden="true" className={cn("h-1.5 w-1.5 shrink-0 rounded-full", dot)} />
        <span className="truncate">{note}</span>
      </span>
    </div>
  );
}

function SortButton({
  active,
  dir,
  onClick,
  children,
}: {
  active: boolean;
  dir: SortDir;
  onClick: () => void;
  children: string;
}) {
  const Icon = !active ? ArrowUpDown : dir === "asc" ? ArrowUp : ArrowDown;
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={`${children}: toggle sort order`}
      className={cn(
        "inline-flex cursor-pointer items-center gap-1 transition-colors duration-100 hover:text-fg",
        active && "text-fg",
      )}
    >
      {children}
      <Icon
        aria-hidden="true"
        className={cn("h-3 w-3", active ? "text-fg-muted" : "text-fg-faint")}
      />
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
        className="h-6 w-6 animate-spin rounded-full border-2 border-line-strong border-t-brand"
      />
      <span className="sr-only">Loading</span>
      <p className="text-[13px] text-fg-muted">Loading inspection records…</p>
    </div>
  );
}

function LedgerEmpty() {
  return (
    <div className="flex flex-col items-center gap-3 px-4 py-12 text-center">
      <div
        className="figure text-[30px] leading-none text-fg-faint"
        aria-hidden="true"
      >
        ≡
      </div>
      <p className="max-w-[46ch] text-[14px] text-fg-muted">
        No inspections yet: run one in the{" "}
        <Link href="/app" className="text-brand underline underline-offset-2">
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
      <X aria-hidden="true" className="h-7 w-7 text-danger" />
      <p className="max-w-[52ch] text-[14px] text-fg-muted">
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
