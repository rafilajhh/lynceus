"use client";

import Link from "next/link";
import { OpsError, fetchContract, fetchSuppliers } from "@/lib/ops-api";
import {
  parseContract,
  parseScorecard,
  type ContractTerms,
  type Scorecard,
  type SupplierRow,
  type SupplierScore,
} from "@/lib/shift-api";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Panel, PanelHead } from "@/components/ui/panel";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { num, plural, rp, rpFull } from "./format";

/** The scorecard is a second service: its failure never blanks the report. */
export type ScoreState =
  | { kind: "loading" }
  | { kind: "unavailable"; reason: string }
  | { kind: "ready"; scorecard: Scorecard; contract: ContractTerms | null };

export async function loadScorecard(signal?: AbortSignal): Promise<ScoreState> {
  try {
    const [raw, contractRaw] = await Promise.all([
      fetchSuppliers(),
      fetchContract().catch(() => null),
    ]);
    if (signal?.aborted) return { kind: "loading" };
    const scorecard = parseScorecard(raw);
    if (!scorecard) return { kind: "unavailable", reason: "unreadable" };
    const contract = (contractRaw ? parseContract(contractRaw) : null) ?? scorecard.contract ?? null;
    return { kind: "ready", scorecard, contract };
  } catch (err) {
    return {
      kind: "unavailable",
      reason: err instanceof OpsError && err.status === 404 ? "absent" : "error",
    };
  }
}

/* ---------------------------------------------------- supplier scorecard */

const TIER_ORDER: Record<SupplierScore["tier"], number> = { high: 0, medium: 1, new: 2, low: 3 };
const TIER_LABEL: Record<SupplierScore["tier"], string> = {
  high: "High risk",
  medium: "Medium risk",
  low: "Low risk",
  new: "New supplier",
};

/** Lab spec limits, read from the contract only: null when it does not state one. */
export interface Limits {
  moisture: number | null;
  ncv: number | null;
  chlorine: number | null;
}

export function limitsFrom(contract: ContractTerms | null | undefined): Limits {
  const limits: Limits = { moisture: null, ncv: null, chlorine: null };
  for (const [key, value] of Object.entries(contract?.specs ?? {})) {
    const v = typeof value === "number" ? value : typeof value === "object" && value ? pickNumber(value) : null;
    if (v === null) continue;
    const k = key.toLowerCase();
    // "chlorine_pct_warn" is a warning band, not the spec limit.
    if (k.includes("warn")) continue;
    if (k.includes("moist")) limits.moisture = v;
    else if (k.includes("ncv") || k.includes("calor")) limits.ncv = v;
    else if (k.includes("chlor") || k === "cl") limits.chlorine = v;
  }
  return limits;
}

function pickNumber(obj: object): number | null {
  for (const key of ["limit", "max", "min", "value"]) {
    const v = (obj as Record<string, unknown>)[key];
    if (typeof v === "number") return v;
  }
  return null;
}

interface ScoreRow {
  supplier: string;
  tier: SupplierScore["tier"] | null;
  tierReason: string | null;
  sampling: string | null;
  trucks: number;
  accepted: number;
  held: number;
  rejected: number;
  conflicts: number | null;
  labSamples: number | null;
  moisture: number | null;
  ncv: number | null;
  chlorine: number | null;
  breaches: number | null;
  deductions: number | null;
  fees: number | null;
  explanation: string | null;
  explanationSource: "model" | "rule" | null;
}

function samplingLabel(s: SupplierScore): string | null {
  if (s.sampling?.label) return s.sampling.label;
  if (!s.sampling) return null;
  return s.sampling.every_n <= 1 ? "Sample every truck" : `Sample 1 in ${s.sampling.every_n}`;
}

function scoreRows(score: ScoreState, shiftSuppliers: SupplierRow[]): ScoreRow[] {
  const explain = new Map(shiftSuppliers.map((s) => [s.supplier, s]));
  if (score.kind === "ready") {
    return [...score.scorecard.suppliers]
      .sort((a, b) => TIER_ORDER[a.tier] - TIER_ORDER[b.tier] || b.trucks - a.trucks)
      .map((s) => ({
        supplier: s.supplier,
        tier: s.tier,
        tierReason: s.tier_reason ?? null,
        sampling: samplingLabel(s),
        trucks: s.trucks,
        accepted: s.accepted,
        held: s.escalated,
        rejected: s.rejected,
        conflicts: s.declaration_conflicts,
        labSamples: s.lab_samples,
        moisture: s.avg_moisture_pct ?? null,
        ncv: s.avg_ncv_mj_kg ?? null,
        chlorine: s.avg_chlorine_pct ?? null,
        breaches: s.spec_breaches,
        deductions: s.deductions_idr,
        fees: s.breach_fees_idr,
        explanation: explain.get(s.supplier)?.explanation ?? null,
        explanationSource: explain.get(s.supplier)?.explanation_source ?? null,
      }));
  }
  // Scorecard service absent: the shift report's verdict counts still stand.
  return [...shiftSuppliers]
    .sort((a, b) => b.risk_score - a.risk_score || b.trucks - a.trucks)
    .map((s) => ({
      supplier: s.supplier,
      tier: null,
      tierReason: null,
      sampling: null,
      trucks: s.trucks,
      accepted: Math.max(0, s.trucks - s.reject - s.escalate),
      held: s.escalate,
      rejected: s.reject,
      conflicts: null,
      labSamples: null,
      moisture: null,
      ncv: null,
      chlorine: null,
      breaches: null,
      deductions: null,
      fees: null,
      explanation: s.explanation ?? null,
      explanationSource: s.explanation_source ?? null,
    }));
}

/** Drill-through: a supplier's standing is one click from its trucks. */
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

function TierChip({ tier, reason }: { tier: SupplierScore["tier"]; reason?: string | null }) {
  return (
    <Badge
      title={reason ?? undefined}
      variant={tier === "high" ? "escalate" : "default"}
      className="px-2 py-0.5 text-[11px]"
    >
      {TIER_LABEL[tier]}
    </Badge>
  );
}

/** Accept / hold / reject as one proportion bar (verdict colours: meaning). */
function OutcomeBar({ row }: { row: ScoreRow }) {
  const total = Math.max(1, row.accepted + row.held + row.rejected);
  const seg = (n: number) => `${(n / total) * 100}%`;
  return (
    <div className="flex min-w-[140px] flex-col gap-1.5">
      <div aria-hidden="true" className="flex h-1.5 w-full gap-px overflow-hidden rounded-full bg-seam">
        {row.accepted > 0 ? <span className="h-full bg-verdict-green/80" style={{ width: seg(row.accepted) }} /> : null}
        {row.held > 0 ? <span className="h-full bg-verdict-amber" style={{ width: seg(row.held) }} /> : null}
        {row.rejected > 0 ? <span className="h-full bg-verdict-red" style={{ width: seg(row.rejected) }} /> : null}
      </div>
      <p className="figure m-0 text-[12px] text-muted">
        <span className="text-ink">{row.accepted}</span> accepted ·{" "}
        <span className="text-ink">{row.held}</span> held ·{" "}
        <span className={row.rejected > 0 ? "text-verdict-red" : "text-ink"}>{row.rejected}</span> rejected
      </p>
    </div>
  );
}

const limitText = (sign: string, limit: number | null) => (limit === null ? "no spec" : `${sign} ${num(limit)}`);
const over = (v: number | null, limit: number | null) => v !== null && limit !== null && v > limit;
const under = (v: number | null, limit: number | null) => v !== null && limit !== null && v < limit;

/** Lab averages against the contract spec; an out-of-spec average reads amber. */
function LabSpec({ row, limits }: { row: ScoreRow; limits: Limits }) {
  if (!row.labSamples) {
    return <span className="text-[12.5px] text-faint">No lab sample yet</span>;
  }
  const cells = [
    { key: "m", label: "Moisture", value: row.moisture, unit: "%", limit: limitText("≤", limits.moisture), bad: over(row.moisture, limits.moisture) },
    { key: "n", label: "NCV", value: row.ncv, unit: "MJ/kg", limit: limitText("≥", limits.ncv), bad: under(row.ncv, limits.ncv) },
    { key: "c", label: "Chlorine", value: row.chlorine, unit: "%", limit: limitText("≤", limits.chlorine), bad: over(row.chlorine, limits.chlorine) },
  ];
  return (
    <div className="flex flex-col gap-1">
      <dl className="m-0 grid grid-cols-3 gap-x-3">
        {cells.map((c) => (
          <div key={c.key} className="flex min-w-0 flex-col">
            <dt className="text-[11px] text-muted">{c.label}</dt>
            <dd
              className={cn(
                "figure m-0 text-[13px] font-semibold whitespace-nowrap",
                c.bad ? "text-verdict-amber" : "text-ink",
              )}
            >
              {c.value !== null ? num(c.value, c.key === "c" ? 2 : 1) : "—"}
              <span className="sr-only">
                {` ${c.unit}, spec ${c.limit}${c.bad ? ", out of spec" : ""}`}
              </span>
            </dd>
            <span aria-hidden="true" className="figure text-[11px] text-faint">
              {c.limit}
            </span>
          </div>
        ))}
      </dl>
      <span className="figure text-[11.5px] text-muted">
        {row.labSamples} {plural(row.labSamples, "sample", "samples")}
        {row.breaches ? ` · ${row.breaches} out of spec` : ""}
      </span>
    </div>
  );
}

function Deducted({ row }: { row: ScoreRow }) {
  const total = (row.deductions ?? 0) + (row.fees ?? 0);
  if (total <= 0) return <span className="figure text-[12.5px] text-faint">Rp 0</span>;
  return (
    <div className="flex flex-col items-end gap-0.5" title={rpFull(total)}>
      <span className="figure text-[13.5px] font-semibold text-ink">{rp(total)}</span>
      <span className="figure text-[11.5px] text-muted">
        {row.fees ? `incl. ${rp(row.fees)} fees` : "price deductions"}
      </span>
    </div>
  );
}

/** Pythia's grounded sentence on a supplier (assist model, number-checked). */
function Explain({ row, model }: { row: ScoreRow; model: string | null }) {
  if (!row.explanation) return null;
  return (
    <p className="m-0 flex flex-wrap items-baseline gap-x-2 text-[12.5px] leading-snug text-muted">
      <span className="text-[11.5px] font-semibold tracking-[0.4px] text-ink uppercase">Pythia</span>
      <span className="max-w-[90ch]">{row.explanation}</span>
      <span className="figure text-[11px] text-faint">
        {row.explanationSource === "model" ? (model ?? "assist model") : "rule-based sentence"}
      </span>
    </p>
  );
}

/**
 * The supplier scorecard: tier, risk-based sampling, gate outcomes, waybill
 * conflicts, lab averages against the contract spec and deductions. With
 * `limit`, only the riskiest rows show and a link leads to the full card on
 * /shift. Without the scorecard service it falls back to `shiftSuppliers`
 * (verdict counts from the shift report).
 */
export function SupplierScorecard({
  score,
  shiftSuppliers = [],
  explanationModel = null,
  limit,
  showContract = true,
}: {
  score: ScoreState;
  shiftSuppliers?: SupplierRow[];
  explanationModel?: string | null;
  limit?: number;
  showContract?: boolean;
}) {
  const allRows = scoreRows(score, shiftSuppliers);
  const rows = limit ? allRows.slice(0, limit) : allRows;
  const full = score.kind === "ready";
  const contract = score.kind === "ready" ? score.contract : null;
  const limits = limitsFrom(contract);
  const high = allRows.filter((r) => r.tier === "high").length;
  const model = explanationModel;

  return (
    <Panel aria-labelledby="scorecard-head">
      <PanelHead
        title="Supplier scorecard"
        meta={
          score.kind === "loading"
            ? "loading"
            : `${allRows.length} ${plural(allRows.length, "supplier", "suppliers")}${full ? ` · ${high} high risk` : ""}`
        }
      />
      <h2 id="scorecard-head" className="sr-only">
        Supplier scorecard
      </h2>
      <p className="m-0 border-b border-seam px-5 py-2.5 text-[13px] leading-relaxed text-muted">
        {full
          ? `${samplingSentence(contract)} Sorted riskiest first.`
          : score.kind === "loading"
            ? "Loading lab results and contract deductions…"
            : "Lab and contract figures are unavailable from this backend; showing verdict counts from the shift report."}
      </p>

      {rows.length === 0 ? (
        <p className="m-0 px-5 py-8 text-center text-[13px] text-muted">
          No supplier named on a waybill yet this shift.
        </p>
      ) : (
        <>
          {/* Desktop: ruled table */}
          <Table className="hidden lg:table">
            <TableHeader>
              <TableRow className="hover:bg-raised">
                <TableHead>Supplier</TableHead>
                <TableHead className="text-right">Trucks</TableHead>
                <TableHead>Gate outcome</TableHead>
                {full ? <TableHead className="text-right">Waybill conflicts</TableHead> : null}
                {full ? <TableHead>Lab average vs spec</TableHead> : null}
                {full ? <TableHead className="text-right">Deducted</TableHead> : null}
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((row) => (
                <ScoreTableRows key={row.supplier} row={row} full={full} limits={limits} model={model} />
              ))}
            </TableBody>
          </Table>

          {/* Below lg: one card per supplier */}
          <ul className="m-0 flex list-none flex-col gap-2 p-3 lg:hidden">
            {rows.map((row) => (
              <li key={row.supplier} className="flex flex-col gap-3 rounded-[10px] border border-seam bg-raised p-3.5">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div className="flex min-w-0 flex-col gap-0.5">
                    <SupplierLink name={row.supplier} className="text-[14px] font-semibold text-ink" />
                    <span className="figure text-[12px] text-muted">
                      {row.trucks} {plural(row.trucks, "truck", "trucks")}
                      {row.sampling ? ` · ${row.sampling}` : ""}
                    </span>
                  </div>
                  {row.tier ? <TierChip tier={row.tier} reason={row.tierReason} /> : null}
                </div>
                <OutcomeBar row={row} />
                {full ? (
                  <>
                    <div className="border-t border-seam pt-3">
                      <LabSpec row={row} limits={limits} />
                    </div>
                    <div className="flex items-center justify-between gap-3 border-t border-seam pt-3 text-[12.5px] text-muted">
                      <span>
                        Waybill conflicts{" "}
                        <span className={cn("figure font-semibold", row.conflicts ? "text-verdict-red" : "text-ink")}>
                          {row.conflicts ?? 0}
                        </span>
                      </span>
                      <Deducted row={row} />
                    </div>
                  </>
                ) : null}
                <Explain row={row} model={model} />
              </li>
            ))}
          </ul>
        </>
      )}

      {limit && allRows.length > rows.length ? (
        <p className="m-0 border-t border-seam px-5 py-2.5 text-[13px]">
          <Link href="/shift" className="text-amber underline underline-offset-2">
            All {allRows.length} suppliers on the shift report
          </Link>
        </p>
      ) : null}
      {full && showContract ? <ContractTermsDisclosure contract={contract} limits={limits} /> : null}
    </Panel>
  );
}

function ScoreTableRows({
  row,
  full,
  limits,
  model,
}: {
  row: ScoreRow;
  full: boolean;
  limits: Limits;
  model: string | null;
}) {
  const cols = full ? 6 : 3;
  return (
    <>
      <TableRow className={cn("hover:bg-transparent", row.explanation ? "border-b-0" : null)}>
        <TableCell className="align-top">
          <div className="flex flex-col items-start gap-1.5">
            <SupplierLink name={row.supplier} className="font-semibold whitespace-nowrap text-ink" />
            <div className="flex flex-wrap items-center gap-2">
              {row.tier ? <TierChip tier={row.tier} reason={row.tierReason} /> : null}
              {row.sampling ? <span className="text-[12px] text-muted">{row.sampling}</span> : null}
            </div>
          </div>
        </TableCell>
        <TableCell className="figure text-right align-top text-[13px] text-ink">{row.trucks}</TableCell>
        <TableCell className="align-top">
          <OutcomeBar row={row} />
        </TableCell>
        {full ? (
          <TableCell
            className={cn(
              "figure text-right align-top text-[13px]",
              row.conflicts ? "font-semibold text-verdict-red" : "text-ink",
            )}
          >
            {row.conflicts ?? 0}
          </TableCell>
        ) : null}
        {full ? (
          <TableCell className="align-top">
            <LabSpec row={row} limits={limits} />
          </TableCell>
        ) : null}
        {full ? (
          <TableCell className="text-right align-top">
            <Deducted row={row} />
          </TableCell>
        ) : null}
      </TableRow>
      {row.explanation ? (
        <TableRow className="hover:bg-transparent">
          <TableCell colSpan={cols} className="pt-0 pb-3">
            <Explain row={row} model={model} />
          </TableCell>
        </TableRow>
      ) : null}
    </>
  );
}

/* ---------------------------------------------------- contract terms */

const PARAM_LABEL: Record<string, string> = {
  moisture_pct: "Moisture",
  ncv_mj_kg: "Net calorific value",
  chlorine_pct: "Chlorine",
  declaration: "Declaration breach",
};

/** [{head, rule}] entries of a contract list (penalties, tier rules); others dropped. */
function ruleList(value: unknown, headKey: "param" | "tier"): { head: string; rule: string; every?: number }[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    if (!item || typeof item !== "object") return [];
    const o = item as Record<string, unknown>;
    if (typeof o.rule !== "string" || typeof o[headKey] !== "string") return [];
    return [
      {
        head: o[headKey] as string,
        rule: o.rule,
        every: typeof o.every_n === "number" ? o.every_n : undefined,
      },
    ];
  });
}

/** "Every truck for high risk, 1 in 3 for medium …": from the contract's tier rules. */
function samplingSentence(contract: ContractTerms | null): string {
  const tiers = ruleList(contract?.tier_rules, "tier");
  if (tiers.length === 0) return "Risk tier sets how often a supplier's trucks go to the lab.";
  const parts = tiers
    .filter((t) => t.every !== undefined)
    .sort((a, b) => a.every! - b.every!)
    .map((t) => `${t.every! <= 1 ? "every truck" : `1 in ${t.every}`} for ${(TIER_LABEL[t.head as SupplierScore["tier"]] ?? t.head).toLowerCase()}`);
  return `Risk tier sets how often a supplier's trucks go to the lab: ${parts.join(", ")}.`;
}

export function ContractTermsDisclosure({ contract, limits }: { contract: ContractTerms | null; limits: Limits }) {
  const penalties = ruleList(contract?.penalties, "param");
  const tiers = ruleList(contract?.tier_rules ?? contract?.sampling_rules ?? contract?.tiers, "tier");
  const source = typeof contract?.base_price_source === "string" ? contract.base_price_source : null;
  const formula = typeof contract?.risk_formula === "string" ? contract.risk_formula : null;
  const settlement = ruleList(contract?.settlement_tiers, "tier").map((t, i) => {
    const raw = (contract?.settlement_tiers as Record<string, unknown>[] | undefined)?.[i];
    return { tier: t.head, rule: t.rule, label: typeof raw?.label === "string" ? raw.label : null };
  });
  return (
    <details className="group border-t border-seam px-5 py-3">
      <summary className="cursor-pointer text-[13px] font-semibold text-ink transition-colors duration-100 select-none hover:text-amber">
        Contract terms and sampling rules
      </summary>
      <div className="flex flex-col gap-4 pt-3 text-[13px] leading-relaxed text-muted">
        <p className="m-0 max-w-[80ch]">
          {contract?.note ??
            "Example supply contract: terms are set per contract (SOP-RDF-5.3). Deductions and fees on this page are computed from these terms."}
        </p>
        <dl className="m-0 grid max-w-[640px] grid-cols-1 gap-x-8 sm:grid-cols-2">
          {contract?.base_price_idr_per_t ? (
            <div className="flex justify-between gap-4 border-b border-seam py-2">
              <dt>Base price</dt>
              <dd className="figure m-0 text-ink">{rp(contract.base_price_idr_per_t)} / t</dd>
            </div>
          ) : null}
          {limits.moisture !== null ? (
            <div className="flex justify-between gap-4 border-b border-seam py-2">
              <dt>Moisture</dt>
              <dd className="figure m-0 text-ink">≤ {num(limits.moisture)} %</dd>
            </div>
          ) : null}
          {limits.ncv !== null ? (
            <div className="flex justify-between gap-4 border-b border-seam py-2">
              <dt>Net calorific value</dt>
              <dd className="figure m-0 text-ink">≥ {num(limits.ncv)} MJ/kg</dd>
            </div>
          ) : null}
          {limits.chlorine !== null ? (
            <div className="flex justify-between gap-4 border-b border-seam py-2">
              <dt>Chlorine (dry)</dt>
              <dd className="figure m-0 text-ink">≤ {num(limits.chlorine)} %</dd>
            </div>
          ) : null}
        </dl>
        {source ? <p className="m-0 max-w-[80ch] text-[12px] break-words text-faint">Base price: {source}</p> : null}
        {penalties.length > 0 ? (
          <div>
            <h3 className="smallcaps m-0 mb-1.5">Price adjustments</h3>
            <dl className="m-0 flex max-w-[80ch] flex-col">
              {penalties.map((p) => (
                <div key={p.head} className="grid gap-x-6 border-b border-seam py-2 last:border-b-0 sm:grid-cols-[180px_1fr]">
                  <dt className="font-semibold text-ink">{PARAM_LABEL[p.head] ?? p.head}</dt>
                  <dd className="m-0">{p.rule}</dd>
                </div>
              ))}
            </dl>
          </div>
        ) : null}
        {settlement.length > 0 ? (
          <div>
            <h3 className="smallcaps m-0 mb-1.5">Settlement tiers (example)</h3>
            <dl className="m-0 flex max-w-[80ch] flex-col">
              {settlement.map((t) => (
                <div key={t.tier} className="grid gap-x-6 border-b border-seam py-2 last:border-b-0 sm:grid-cols-[180px_1fr]">
                  <dt className="font-semibold text-ink">
                    Tier {t.tier}
                    {t.label ? <span className="block text-[12px] font-normal text-muted">{t.label}</span> : null}
                  </dt>
                  <dd className="m-0">{t.rule}</dd>
                </div>
              ))}
            </dl>
          </div>
        ) : null}
        {tiers.length > 0 ? (
          <div>
            <h3 className="smallcaps m-0 mb-1.5">Risk tiers and lab sampling (SOP-RDF-5.4)</h3>
            <dl className="m-0 flex max-w-[80ch] flex-col">
              {tiers.map((t) => (
                <div key={t.head} className="grid gap-x-6 border-b border-seam py-2 last:border-b-0 sm:grid-cols-[180px_1fr]">
                  <dt className="font-semibold text-ink">
                    {TIER_LABEL[t.head as SupplierScore["tier"]] ?? t.head}
                    {t.every !== undefined ? (
                      <span className="figure block text-[12px] font-normal text-muted">
                        {t.every <= 1 ? "every truck" : `1 in ${t.every} trucks`}
                      </span>
                    ) : null}
                  </dt>
                  <dd className="m-0">{t.rule}</dd>
                </div>
              ))}
            </dl>
            {formula ? <p className="figure m-0 mt-2 text-[12px] text-faint">{formula}</p> : null}
          </div>
        ) : null}
      </div>
    </details>
  );
}

