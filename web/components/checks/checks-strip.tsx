import type { Check, CheckStatus } from "@/lib/ops-api";
import { cn } from "@/lib/utils";

/**
 * ChecksStrip: the operator checks of one inspection (backend checks.py) as
 * a strip of indicator cells split by hairline seams. Shared by the gate
 * (/app verdict) and the audit trail detail, so a check reads the same in
 * both places.
 *
 * Status carries meaning by colour AND by glyph shape (tick, cross, bang,
 * "i", dash), never by colour alone. `info` stays neutral: it is a note,
 * not a green clearance. `skipped` is grey.
 */

const STATUS_WORD: Record<CheckStatus, string> = {
  pass: "Pass",
  warn: "Check",
  fail: "Fail",
  info: "Note",
  skipped: "Skipped",
};

const CELL_TONE: Record<CheckStatus, string> = {
  pass: "bg-raised",
  warn: "bg-[color-mix(in_srgb,var(--color-amber)_9%,var(--color-raised))]",
  fail: "bg-[color-mix(in_srgb,var(--color-verdict-red)_10%,var(--color-raised))]",
  info: "bg-raised",
  skipped: "bg-panel",
};

const FINDING_TONE: Record<CheckStatus, string> = {
  pass: "text-ink",
  warn: "text-verdict-amber",
  fail: "text-verdict-red",
  info: "text-ink",
  skipped: "text-faint",
};

const GLYPH_TONE: Record<CheckStatus, string> = {
  pass: "text-verdict-green",
  warn: "text-verdict-amber",
  fail: "text-verdict-red",
  info: "text-muted",
  skipped: "text-faint",
};

/** 14px authored status glyphs, one stroke weight. */
export function CheckGlyph({ status, className }: { status: CheckStatus; className?: string }) {
  return (
    <svg
      viewBox="0 0 16 16"
      width={14}
      height={14}
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      className={cn("shrink-0", GLYPH_TONE[status], className)}
    >
      <circle cx="8" cy="8" r="6.6" strokeWidth="1.3" opacity={status === "skipped" ? 0.7 : 1} />
      {status === "pass" ? <path d="m5.2 8.2 1.9 1.9 3.8-4" /> : null}
      {status === "fail" ? <path d="m5.6 5.6 4.8 4.8m0-4.8-4.8 4.8" /> : null}
      {status === "warn" ? (
        <>
          <path d="M8 4.6v4.2" />
          <path d="M8 11.2v.2" />
        </>
      ) : null}
      {status === "info" ? (
        <>
          <path d="M8 7.4v4" />
          <path d="M8 4.8v.2" />
        </>
      ) : null}
      {status === "skipped" ? <path d="M5.4 8h5.2" /> : null}
    </svg>
  );
}

export function ChecksStrip({
  checks,
  showDetail = false,
  className,
  label = "Operator checks",
}: {
  checks: Check[];
  /** Print each check's one-sentence detail under its finding (the audit
      detail has the room; the gate keeps it as a tooltip). */
  showDetail?: boolean;
  className?: string;
  label?: string;
}) {
  if (checks.length === 0) return null;
  return (
    <ul
      aria-label={label}
      className={cn(
        // gap-px over a seam-coloured ground draws hairlines between cells
        // at every wrap, with no doubled borders.
        "m-0 grid list-none grid-cols-2 gap-px overflow-hidden rounded-[10px] border border-seam bg-seam p-0 sm:grid-cols-3",
        checks.length >= 5 ? "xl:grid-cols-6" : null,
        className,
      )}
    >
      {checks.map((check) => (
        <li
          key={check.key}
          title={showDetail ? undefined : check.detail || undefined}
          className={cn("flex min-w-0 flex-col gap-1.5 px-3 py-2.5", CELL_TONE[check.status])}
        >
          <span className="text-[11.5px] font-semibold tracking-[0.6px] text-muted uppercase">
            {check.label}
          </span>
          <span className="flex min-w-0 items-start gap-1.5">
            <CheckGlyph status={check.status} className="mt-[3px]" />
            <span
              className={cn(
                "min-w-0 text-[13px] leading-snug font-semibold break-words",
                FINDING_TONE[check.status],
              )}
            >
              <span className="sr-only">{STATUS_WORD[check.status]}: </span>
              {check.finding || STATUS_WORD[check.status]}
            </span>
          </span>
          {showDetail && check.detail ? (
            <span className="text-[12px] leading-snug text-muted">{check.detail}</span>
          ) : null}
        </li>
      ))}
    </ul>
  );
}
