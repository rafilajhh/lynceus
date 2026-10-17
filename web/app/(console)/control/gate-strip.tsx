import type { KilnIntake, ShiftNow } from "@/lib/control-api";
import { cn } from "@/lib/utils";
import { num } from "@/components/ops/format";

/**
 * The instrument strip under the control room's headline: chlorine load
 * against the shift budget (the one wide cell, with its 80 % and 100 %
 * marks), alternative-fuel energy, gate outcomes, time to a decision and
 * staff time freed. Hairline-separated cells in one band, not a card grid.
 */

/** The bar's scale runs past 100 % so an overrun stays visible. */
const SCALE_PCT = 120;
const WARN_PCT = 80;

const STATUS: Record<NonNullable<KilnIntake["chlorine_status"]>, { word: string; bar: string; text: string }> = {
  ok: { word: "within budget", bar: "bg-muted", text: "text-ink" },
  warn: { word: `over ${WARN_PCT} % of budget`, bar: "bg-verdict-amber", text: "text-verdict-amber" },
  over: { word: "budget exceeded", bar: "bg-verdict-red", text: "text-verdict-red" },
};

function Cell({ className, children }: { className?: string; children: React.ReactNode }) {
  return <div className={cn("flex min-w-0 flex-col gap-1.5 bg-panel px-5 py-4", className)}>{children}</div>;
}

function Label({ children }: { children: React.ReactNode }) {
  return <dt className="text-[12.5px] font-semibold text-muted">{children}</dt>;
}

function Note({ children, title }: { children: React.ReactNode; title?: string }) {
  return (
    <dd title={title} className="m-0 text-[12px] leading-snug text-faint">
      {children}
    </dd>
  );
}

function ChlorineCell({ kiln }: { kiln: KilnIntake | null }) {
  const pct = kiln?.chlorine_budget_pct ?? null;
  const status = kiln?.chlorine_status ? STATUS[kiln.chlorine_status] : null;
  const at = (v: number) => `${(Math.min(v, SCALE_PCT) / SCALE_PCT) * 100}%`;

  return (
    <Cell className="col-span-2 lg:col-span-1">
      <Label>Chlorine load · this shift</Label>
      <dd className="m-0 flex flex-wrap items-baseline gap-x-2">
        <span className={cn("figure text-[26px] leading-tight font-semibold", status?.text ?? "text-ink")}>
          {kiln?.chlorine_kg != null ? `${num(kiln.chlorine_kg, 0)} kg` : "—"}
        </span>
        {kiln?.chlorine_budget_kg != null ? (
          <span className="figure text-[13px] text-faint">/ {num(kiln.chlorine_budget_kg, 0)} kg budget</span>
        ) : null}
      </dd>
      {pct !== null ? (
        <dd className="m-0 pt-1">
          <div
            role="meter"
            aria-label="Chlorine load against the shift budget"
            aria-valuemin={0}
            aria-valuemax={Math.max(100, Math.round(pct))}
            aria-valuenow={Math.round(pct)}
            aria-valuetext={`${num(pct)} % of the shift budget${status ? `, ${status.word}` : ""}`}
            className="relative h-2.5 rounded-full border border-seam bg-raised"
          >
            <div
              className={cn("absolute inset-y-0 left-0 rounded-full", status?.bar ?? "bg-muted")}
              style={{ width: at(pct) }}
            />
            {[WARN_PCT, 100].map((mark) => (
              <span
                key={mark}
                aria-hidden="true"
                className={cn("absolute -top-1 -bottom-1 w-px", mark === 100 ? "bg-ink" : "bg-muted")}
                style={{ left: at(mark) }}
              />
            ))}
          </div>
          <div aria-hidden="true" className="figure relative mt-1 h-4 text-[11px] text-faint">
            <span className="absolute -translate-x-1/2" style={{ left: at(WARN_PCT) }}>
              {WARN_PCT}%
            </span>
            <span className="absolute -translate-x-1/2" style={{ left: at(100) }}>
              100%
            </span>
          </div>
        </dd>
      ) : null}
      <Note title={kiln?.chlorine_budget_note ?? undefined}>
        {pct !== null ? (
          <>
            <span className={cn("figure font-semibold", status?.text ?? "text-muted")}>{num(pct)} %</span>
            {status ? ` · ${status.word}` : ""}
            {kiln?.method_mix ? ` · ${kiln.method_mix}` : ""}
            {kiln?.weight_unknown_loads != null && kiln.weight_unknown_loads > 0 ? (
              <span className="text-muted">
                {" "}· weight unknown: {num(kiln.weight_unknown_loads, 0)}{" "}
                {kiln.weight_unknown_loads === 1 ? "load" : "loads"}
              </span>
            ) : null}
          </>
        ) : (
          "Chlorine load not available"
        )}
      </Note>
    </Cell>
  );
}

export function GateStrip({ shift, kiln }: { shift: ShiftNow | null; kiln: KilnIntake | null }) {
  const accepted = shift?.auto_cleared ?? null;
  const outcomes = [
    { key: "accepted", label: "accepted", value: accepted, tone: "bg-verdict-green" },
    { key: "held", label: "held", value: shift?.held ?? null, tone: "bg-verdict-amber" },
    { key: "rejected", label: "rejected", value: shift?.rejected ?? null, tone: "bg-verdict-red" },
  ];

  return (
    <dl className="m-0 grid grid-cols-2 gap-px border-t border-seam bg-seam lg:grid-cols-[1.75fr_1fr_1.15fr_1fr_1fr]">
      <ChlorineCell kiln={kiln} />

      <Cell>
        <Label>Alternative-fuel energy</Label>
        <dd className="figure m-0 text-[26px] leading-tight font-semibold text-ink">
          {kiln?.energy_gj != null ? num(kiln.energy_gj, 0) : "—"}
          <span className="ml-1.5 text-[13px] font-normal text-faint">GJ</span>
        </dd>
        <Note>
          {kiln?.trucks_accepted != null && kiln.accepted_t != null
            ? `${kiln.trucks_accepted} accepted loads · ${num(kiln.accepted_t, 0)} t`
            : "accepted loads, net t × NCV"}
        </Note>
      </Cell>

      <Cell>
        <Label>Gate outcomes</Label>
        <dd className="m-0 flex flex-wrap items-baseline gap-x-3 gap-y-1">
          {outcomes.map((o) => (
            <span key={o.key} className="inline-flex items-baseline gap-1.5">
              <span aria-hidden="true" className={cn("inline-block size-2 -translate-y-px rounded-full", o.tone)} />
              <span className="figure text-[22px] leading-tight font-semibold text-ink">
                {o.value !== null ? o.value : "—"}
              </span>
              <span className="text-[12px] text-muted">{o.label}</span>
            </span>
          ))}
        </dd>
        <Note>{shift?.trucks != null ? `of ${shift.trucks} trucks this shift` : "this shift"}</Note>
      </Cell>

      <Cell>
        <Label>Time to a decision</Label>
        <dd className="figure m-0 text-[26px] leading-tight font-semibold text-ink">
          {shift?.median_decision_s != null ? `${num(shift.median_decision_s)} s` : "—"}
        </dd>
        <Note>
          {shift?.p95_decision_s != null ? `median · p95 ${num(shift.p95_decision_s)} s` : "median, record start to seal"}
        </Note>
      </Cell>

      <Cell>
        <Label>Gate time freed</Label>
        <dd className="figure m-0 text-[26px] leading-tight font-semibold text-ink">
          {shift?.staff_minutes_freed != null ? `${num(shift.staff_minutes_freed, 0)} min` : "—"}
        </dd>
        <Note>
          {shift?.manual_check_minutes_assumed != null && shift.hand_checks_avoided != null
            ? `assumes ${num(shift.manual_check_minutes_assumed)} min per hand check × ${shift.hand_checks_avoided}`
            : "hand checks the gate took over"}
        </Note>
      </Cell>
    </dl>
  );
}
