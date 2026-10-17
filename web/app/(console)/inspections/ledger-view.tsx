"use client";

import { Suspense, useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import {
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  ChevronLeft,
  ChevronRight,
  CircleArrowUp,
  Download,
  Lock,
  Plus,
  Search,
  Send,
  SlidersHorizontal,
  X,
} from "lucide-react";
import {
  ApiError,
  fetchInspections,
  type Decision,
  type InspectionSummary,
} from "@/lib/api";
import type { FollowupAction } from "@/lib/followup-api";
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

/** Period filter over decided_at_utc. "today" is the current UTC day,
    matching the UTC timestamps used across the console. */
type PeriodKey = "all" | "today" | "24h" | "7d";

const PERIODS: readonly { key: PeriodKey; label: string }[] = [
  { key: "all", label: "All time" },
  { key: "today", label: "Today (UTC)" },
  { key: "24h", label: "Last 24 h" },
  { key: "7d", label: "Last 7 days" },
] as const;

const HOUR_MS = 60 * 60 * 1000;

function inPeriod(item: InspectionSummary, period: PeriodKey, now: number): boolean {
  if (period === "all") return true;
  const t = Date.parse(item.decided_at_utc);
  if (!Number.isFinite(t)) return false;
  if (period === "today") {
    const start = new Date(now);
    start.setUTCHours(0, 0, 0, 0);
    return t >= start.getTime();
  }
  return now - t <= (period === "24h" ? 24 : 7 * 24) * HOUR_MS;
}

const hasFailedCheck = (item: InspectionSummary) =>
  Object.values(item.gate_states).includes("failed");

const hasFollowup = (item: InspectionSummary) =>
  item.followups.notify_supplier > 0 || item.followups.escalate > 0;

/** Screen-reader suffix for a row's follow-up indicators. */
function followupLabel(item: InspectionSummary): string {
  return [
    item.followups.notify_supplier > 0 ? ", supplier notified" : "",
    item.followups.escalate > 0 ? ", escalated" : "",
  ].join("");
}

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
  const [period, setPeriod] = useState<PeriodKey>("all");
  const [failedOnly, setFailedOnly] = useState(false);
  const [followupOnly, setFollowupOnly] = useState(false);
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

  /** Rows in the filter popover's scope (supplier, period, failed check,
      follow-up): stat cards and tab counts are computed here, before
      verdict/search. */
  const scoped = useMemo(() => {
    const now = Date.now();
    return ready.filter(
      (item) =>
        (!supplierFilter || (item.supplier ?? "").trim() === supplierFilter) &&
        inPeriod(item, period, now) &&
        (!failedOnly || hasFailedCheck(item)) &&
        (!followupOnly || hasFollowup(item)),
    );
  }, [ready, supplierFilter, period, failedOnly, followupOnly]);

  /** Distinct suppliers in the loaded ledger, for the filter's select. */
  const suppliers = useMemo(() => {
    const names = new Set<string>();
    for (const item of ready) {
      const name = (item.supplier ?? "").trim();
      if (name) names.add(name);
    }
    if (supplierFilter) names.add(supplierFilter);
    return [...names].sort((a, b) => a.localeCompare(b));
  }, [ready, supplierFilter]);

  const activeFilterCount =
    (supplierFilter ? 1 : 0) +
    (period !== "all" ? 1 : 0) +
    (failedOnly ? 1 : 0) +
    (followupOnly ? 1 : 0);

  /** Supplier filter and ?supplier= move together, so a refresh or a
      shared link keeps the scope. */
  const changeSupplier = useCallback((next: string) => {
    setSupplierFilter(next);
    setPage(1);
    const url = new URL(window.location.href);
    if (next) url.searchParams.set("supplier", next);
    else url.searchParams.delete("supplier");
    window.history.replaceState(null, "", url.toString());
  }, []);

  const clearFilters = useCallback(() => {
    changeSupplier("");
    setPeriod("all");
    setFailedOnly(false);
    setFollowupOnly(false);
  }, [changeSupplier]);

  /** An action logged from the record screen: bump that row's counts so the
      indicators and the follow-up filter are current without a reload. */
  const onFollowupLogged = useCallback((action: FollowupAction) => {
    setState((prev) =>
      prev.kind !== "ready"
        ? prev
        : {
            kind: "ready",
            inspections: prev.inspections.map((item) =>
              item.record_id === action.record_id
                ? {
                    ...item,
                    followups: {
                      ...item.followups,
                      [action.kind]: item.followups[action.kind] + 1,
                    },
                  }
                : item,
            ),
          },
    );
  }, []);

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
      if (e.key !== "Escape") return;
      // Esc inside a text field (follow-up note, Pythia question) belongs
      // to that field: closing the record there would drop unsent text.
      const target = e.target as HTMLElement | null;
      if (target?.closest("input, textarea, select, [contenteditable='true']")) return;
      e.preventDefault();
      closeDetail();
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
        onFollowupLogged={onFollowupLogged}
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
                      onClick={() => changeSupplier("")}
                      aria-label={`Clear supplier filter ${supplierFilter}`}
                      title="Clear supplier filter"
                      className="inline-flex h-9 cursor-pointer items-center gap-1.5 rounded-full border border-brand/25 bg-brand/5 px-3 text-[13px] font-medium text-fg transition-colors duration-100 hover:border-brand/50"
                    >
                      Supplier: <span>{supplierFilter}</span>
                      <X aria-hidden="true" className="h-3.5 w-3.5 text-fg-muted" />
                    </button>
                  ) : null}
                  <div className="flex w-full items-center gap-2 sm:w-auto">
                    <div className="relative min-w-0 flex-1 sm:w-[280px] sm:flex-none">
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
                    <FilterPopover
                      activeCount={activeFilterCount}
                      suppliers={suppliers}
                      supplier={supplierFilter}
                      onSupplierChange={changeSupplier}
                      period={period}
                      onPeriodChange={(next) => {
                        setPeriod(next);
                        setPage(1);
                      }}
                      failedOnly={failedOnly}
                      onFailedOnlyChange={(next) => {
                        setFailedOnly(next);
                        setPage(1);
                      }}
                      followupOnly={followupOnly}
                      onFollowupOnlyChange={(next) => {
                        setFollowupOnly(next);
                        setPage(1);
                      }}
                      onClear={clearFilters}
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
                      aria-label={`Open ${row.record_id}, ${row.truck_id}, ${VERDICT_LABEL[row.decision]}${followupLabel(row)}`}
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
                      <TableCell className="max-w-0 text-[13px] text-fg-muted">
                        <span className="flex min-w-0 items-center gap-2">
                          <span className="min-w-0 truncate">{rowReason(row)}</span>
                          <FollowupIndicators item={row} />
                        </span>
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
                    <div className="mt-1 flex min-w-0 items-center gap-2 text-[12px] text-fg-subtle">
                      <span className="min-w-0 truncate">{rowReason(row)}</span>
                      <FollowupIndicators item={row} />
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

/** Small icons beside the Reason when the record has follow-up actions. */
function FollowupIndicators({ item }: { item: InspectionSummary }) {
  const { notify_supplier: notified, escalate: escalated } = item.followups;
  if (notified <= 0 && escalated <= 0) return null;
  return (
    <span className="flex shrink-0 items-center gap-1.5">
      {notified > 0 ? (
        <span
          title={notified > 1 ? `Supplier notified (${notified} times)` : "Supplier notified"}
          className="inline-flex items-center gap-0.5 text-brand"
        >
          <Send aria-hidden="true" className="h-3.5 w-3.5" />
          <span className="sr-only">Supplier notified</span>
          {notified > 1 ? <span className="figure text-[11px]">{notified}</span> : null}
        </span>
      ) : null}
      {escalated > 0 ? (
        <span
          title={escalated > 1 ? `Escalated (${escalated} times)` : "Escalated"}
          className="inline-flex items-center gap-0.5 text-warning"
        >
          <CircleArrowUp aria-hidden="true" className="h-3.5 w-3.5" />
          <span className="sr-only">Escalated</span>
          {escalated > 1 ? <span className="figure text-[11px]">{escalated}</span> : null}
        </span>
      ) : null}
    </span>
  );
}

/**
 * Sliders button + non-modal popover with the ledger filters. Esc and a
 * click outside close it; Esc and "Done" return focus to the button.
 */
function FilterPopover({
  activeCount,
  suppliers,
  supplier,
  onSupplierChange,
  period,
  onPeriodChange,
  failedOnly,
  onFailedOnlyChange,
  followupOnly,
  onFollowupOnlyChange,
  onClear,
}: {
  activeCount: number;
  suppliers: string[];
  supplier: string;
  onSupplierChange: (next: string) => void;
  period: PeriodKey;
  onPeriodChange: (next: PeriodKey) => void;
  failedOnly: boolean;
  onFailedOnlyChange: (next: boolean) => void;
  followupOnly: boolean;
  onFollowupOnlyChange: (next: boolean) => void;
  onClear: () => void;
}) {
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const firstFieldRef = useRef<HTMLSelectElement>(null);
  const popoverId = useId();
  const supplierId = useId();
  const periodId = useId();

  const close = useCallback((restoreFocus: boolean) => {
    setOpen(false);
    if (restoreFocus) triggerRef.current?.focus();
  }, []);

  useEffect(() => {
    if (!open) return;
    firstFieldRef.current?.focus();
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        close(true);
      }
    };
    const onPointerDown = (e: PointerEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) close(false);
    };
    document.addEventListener("keydown", onKeyDown);
    document.addEventListener("pointerdown", onPointerDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.removeEventListener("pointerdown", onPointerDown);
    };
  }, [open, close]);

  const label = activeCount > 0 ? `Filters, ${activeCount} active` : "Filters";

  return (
    <div ref={wrapRef} className="relative shrink-0">
      <button
        ref={triggerRef}
        type="button"
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-controls={open ? popoverId : undefined}
        aria-label={label}
        title={label}
        onClick={() => (open ? close(false) : setOpen(true))}
        className={cn(
          "relative flex h-9 w-9 cursor-pointer items-center justify-center rounded-[8px] border bg-surface text-fg transition-colors duration-100 hover:bg-surface-subtle",
          activeCount > 0 || open ? "border-brand/50" : "border-line-strong",
        )}
      >
        <SlidersHorizontal aria-hidden="true" className="h-4 w-4" />
        {activeCount > 0 ? (
          <span
            aria-hidden="true"
            className="figure absolute -top-1.5 -right-1.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-brand px-1 text-[10px] leading-none text-white"
          >
            {activeCount}
          </span>
        ) : null}
      </button>
      {open ? (
        <div
          id={popoverId}
          role="dialog"
          aria-label="Filter inspections"
          className="absolute top-full right-0 z-30 mt-2 flex w-[300px] max-w-[calc(100vw-32px)] flex-col gap-4 rounded-[14px] border border-line-strong bg-surface p-4 shadow-card"
        >
          <div className="flex flex-col gap-1.5">
            <label htmlFor={supplierId} className="text-[13px] font-medium text-fg">
              Supplier
            </label>
            <select
              id={supplierId}
              ref={firstFieldRef}
              value={supplier}
              onChange={(e) => onSupplierChange(e.target.value)}
              className="input h-9! cursor-pointer"
            >
              <option value="">All suppliers</option>
              {suppliers.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
          </div>
          <div className="flex flex-col gap-1.5">
            <label htmlFor={periodId} className="text-[13px] font-medium text-fg">
              Period
            </label>
            <select
              id={periodId}
              value={period}
              onChange={(e) => onPeriodChange(e.target.value as PeriodKey)}
              className="input h-9! cursor-pointer"
            >
              {PERIODS.map(({ key, label: periodLabel }) => (
                <option key={key} value={key}>
                  {periodLabel}
                </option>
              ))}
            </select>
          </div>
          <div className="flex flex-col gap-2.5">
            <FilterSwitch
              label="Has a failed check"
              checked={failedOnly}
              onChange={onFailedOnlyChange}
            />
            <FilterSwitch
              label="Has follow-up"
              checked={followupOnly}
              onChange={onFollowupOnlyChange}
            />
          </div>
          <div className="flex items-center justify-between gap-2 border-t border-line pt-3">
            <Button variant="ghost" size="sm" disabled={activeCount === 0} onClick={onClear}>
              Clear filters
            </Button>
            <Button variant="primary" size="sm" onClick={() => close(true)}>
              Done
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function FilterSwitch({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (next: boolean) => void;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className="flex cursor-pointer items-center justify-between gap-3 text-left text-[13px] text-fg"
    >
      {label}
      <span
        aria-hidden="true"
        className={cn(
          "relative h-5 w-9 shrink-0 rounded-full transition-colors duration-100",
          checked ? "bg-brand" : "bg-line-strong",
        )}
      >
        <span
          className={cn(
            "absolute top-0.5 left-0.5 h-4 w-4 rounded-full bg-white shadow-control transition-transform duration-100",
            checked && "translate-x-4",
          )}
        />
      </span>
    </button>
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
