import Link from "next/link";
import type { Alert, AlertSeverity } from "@/lib/control-api";
import type { CheckStatus } from "@/lib/ops-api";
import { cn } from "@/lib/utils";
import { CheckGlyph } from "@/components/checks/checks-strip";
import { Panel, PanelHead } from "@/components/ui/panel";
import { plural, utcClock } from "@/components/ops/format";

/**
 * AlarmBand: the backend's alarm feed (control.py ALERT_RULES), critical
 * first. Severity reads by glyph and word as well as colour, in the same
 * glyph language as the operator checks. An alarm about one truck links to
 * its record; one about a supplier links to that supplier's loads.
 */

const GLYPH: Record<AlertSeverity, CheckStatus> = { critical: "fail", warning: "warn", info: "info" };

const SEVERITY_WORD: Record<AlertSeverity, string> = {
  critical: "Critical",
  warning: "Warning",
  info: "Notice",
};

const KIND_LABEL: Record<string, string> = {
  chlorine_budget: "Chlorine budget",
  supplier_out_of_spec: "Supplier out of spec",
  hold_unresolved: "Hold waiting",
  declaration_conflict: "Declaration conflict",
  reject_unconfirmed: "Reject unconfirmed",
};

const ROW_TONE: Record<AlertSeverity, string> = {
  critical: "bg-[color-mix(in_srgb,var(--color-verdict-red)_9%,var(--color-panel))]",
  warning: "bg-[color-mix(in_srgb,var(--color-amber)_6%,var(--color-panel))]",
  info: "bg-panel",
};

/** Alarms about a supplier's pattern, not one truck: link to its loads. */
const SUPPLIER_KINDS = new Set(["supplier_out_of_spec", "declaration_conflict"]);

const recordHref = (id: string) => `/inspections?record=${encodeURIComponent(id)}`;
const supplierHref = (name: string) => `/inspections?supplier=${encodeURIComponent(name)}`;

function meta(alerts: Alert[]): string {
  if (alerts.length === 0) return "all clear";
  const by = (s: AlertSeverity) => alerts.filter((a) => a.severity === s).length;
  return [
    by("critical") ? `${by("critical")} critical` : null,
    by("warning") ? `${by("warning")} ${plural(by("warning"), "warning", "warnings")}` : null,
    by("info") ? `${by("info")} ${plural(by("info"), "notice", "notices")}` : null,
  ]
    .filter(Boolean)
    .join(" · ");
}

export function AlarmBand({ alerts, className }: { alerts: Alert[] | null; className?: string }) {
  return (
    <Panel className={className} aria-labelledby="alarms-head">
      <PanelHead title="Alarms" meta={alerts ? meta(alerts) : undefined} />
      <h2 id="alarms-head" className="sr-only">
        Alarms
      </h2>
      {alerts === null ? (
        <p className="m-0 px-5 py-4 text-[13px] text-muted">The alarm feed is not available on this backend.</p>
      ) : alerts.length === 0 ? (
        <p className="m-0 flex items-center gap-2 px-5 py-4 text-[13px] text-muted">
          <CheckGlyph status="pass" />
          No alarms: chlorine within budget, no hold waiting over 20 min, no supplier out of spec.
        </p>
      ) : (
        <ul className="m-0 flex list-none flex-col p-0">
          {alerts.map((alert) => (
            <li
              key={alert.id}
              className={cn(
                "grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 border-b border-seam px-5 py-3 last:border-b-0 sm:grid-cols-[auto_1fr_auto]",
                ROW_TONE[alert.severity],
              )}
            >
              <CheckGlyph status={GLYPH[alert.severity]} className="mt-[3px]" />
              <div className="flex min-w-0 flex-col gap-0.5">
                <p className="m-0 text-[11.5px] font-semibold tracking-[0.5px] text-muted uppercase">
                  <span className="sr-only">{SEVERITY_WORD[alert.severity]}: </span>
                  {KIND_LABEL[alert.kind] ?? alert.kind.replace(/_/g, " ")}
                </p>
                <p className="m-0 text-[14px] leading-snug font-semibold text-ink">{alert.title}</p>
                {alert.detail ? (
                  <p className="m-0 text-[12.5px] leading-relaxed break-words text-muted">{alert.detail}</p>
                ) : null}
              </div>
              <div className="col-start-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[12.5px] sm:col-start-3 sm:row-start-1 sm:flex-col sm:items-end sm:justify-start">
                <span className="figure text-faint">{utcClock(alert.at_utc)}</span>
                {alert.supplier && (SUPPLIER_KINDS.has(alert.kind) || !alert.record_id) ? (
                  <Link
                    href={supplierHref(alert.supplier)}
                    className="font-semibold text-amber underline-offset-2 hover:underline"
                  >
                    Supplier loads
                  </Link>
                ) : alert.record_id ? (
                  <Link
                    href={recordHref(alert.record_id)}
                    className="font-semibold text-amber underline-offset-2 hover:underline"
                  >
                    Open record
                  </Link>
                ) : null}
              </div>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}
