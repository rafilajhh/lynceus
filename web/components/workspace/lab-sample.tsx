"use client";

/**
 * LabSample: the risk-based lab sample (SOP-RDF-5.4) and its result. When
 * the supplier record says this truck is sampled, the callout leads; the
 * result (moisture, NCV, chlorine) is sealed onto the record and priced
 * against the example supply contract: breaches, adjusted price, deduction.
 */

import { useId, useState } from "react";
import { Button } from "@/components/ui/button";
import { formatRupiah, formatRupiahCompact } from "@/lib/format";
import { postLabResult, type ContractEval, type Followup, type Sampling } from "@/lib/ops-api";
import { cn } from "@/lib/utils";
import { parseFieldNumber } from "@/lib/waybill-api";
import { SealedLine, followupError } from "./sealed-line";

const FIELDS = [
  { key: "moisture_pct", label: "Moisture %", placeholder: "31.5", required: true },
  { key: "ncv_mj_kg", label: "NCV MJ/kg", placeholder: "12.4", required: true },
  { key: "chlorine_pct", label: "Chlorine %", placeholder: "0.7", required: true },
  { key: "ash_pct", label: "Ash %", placeholder: "optional", required: false },
] as const;

type Key = (typeof FIELDS)[number]["key"];

const PARAM_LABEL: Record<string, string> = {
  moisture_pct: "Moisture",
  ncv_mj_kg: "NCV",
  chlorine_pct: "Chlorine",
  declaration: "Declaration",
};

export function LabSample({ recordId, sampling }: { recordId: string; sampling: Sampling | null }) {
  const required = Boolean(sampling?.sample_this_truck);
  const [open, setOpen] = useState(required);
  const [values, setValues] = useState<Record<Key, string>>({ moisture_pct: "", ncv_mj_kg: "", chlorine_pct: "", ash_pct: "" });
  const [sampleId, setSampleId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [invalid, setInvalid] = useState<Key | null>(null);
  const [sealed, setSealed] = useState<Followup | null>(null);
  const base = useId();

  const submit = async () => {
    const parsed = {} as Record<Key, number | null>;
    for (const f of FIELDS) {
      parsed[f.key] = parseFieldNumber(values[f.key]);
      if (f.required && parsed[f.key] === null) {
        setInvalid(f.key);
        setError(`${f.label} is empty: enter the lab value.`);
        document.getElementById(`${base}-${f.key}`)?.focus();
        return;
      }
    }
    setInvalid(null);
    setBusy(true);
    setError(null);
    try {
      const f = await postLabResult(recordId, {
        moisture_pct: parsed.moisture_pct!,
        ncv_mj_kg: parsed.ncv_mj_kg!,
        chlorine_pct: parsed.chlorine_pct!,
        ash_pct: parsed.ash_pct,
        sample_id: sampleId.trim() || undefined,
      });
      setSealed(f);
    } catch (err) {
      setError(followupError(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-col gap-3">
      {required ? (
        <div className="rounded-[10px] border border-amber-line bg-amber-dim px-4 py-3">
          <p className="m-0 text-[14px] font-semibold text-ink">Lab sample required for this truck</p>
          <p className="m-0 mt-0.5 text-[13px] leading-snug text-muted">
            {[sampling?.label, sampling?.reason].filter(Boolean).join(" · ")}
            {sampling?.reason?.includes("SOP-RDF-5.4") ? "" : " (SOP-RDF-5.4: risk-based sampling)."}
          </p>
        </div>
      ) : sampling ? (
        <p className="m-0 text-[13px] text-muted">
          Not sampled this time{sampling.label ? ` · ${sampling.label}` : ""}. A lab result can still be recorded.
        </p>
      ) : null}

      {sealed && sealed.kind === "lab_result" ? (
        <>
          <ContractResult evalResult={sealed.body.contract_eval} />
          <SealedLine followup={sealed} />
        </>
      ) : open ? (
        <div className="flex flex-col gap-3">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
            {FIELDS.map((f) => (
              <div key={f.key} className="flex flex-col gap-1">
                <label htmlFor={`${base}-${f.key}`} className="text-[11px] font-semibold tracking-[0.6px] text-muted uppercase">
                  {f.label}
                </label>
                <input
                  id={`${base}-${f.key}`}
                  inputMode="decimal"
                  value={values[f.key]}
                  onChange={(e) => setValues((v) => ({ ...v, [f.key]: e.target.value }))}
                  placeholder={f.placeholder}
                  disabled={busy}
                  aria-invalid={invalid === f.key || undefined}
                  className={cn("input figure text-[13px]", invalid === f.key && "border-verdict-red")}
                />
              </div>
            ))}
            <div className="flex flex-col gap-1">
              <label htmlFor={`${base}-id`} className="text-[11px] font-semibold tracking-[0.6px] text-muted uppercase">
                Sample ID
              </label>
              <input
                id={`${base}-id`}
                value={sampleId}
                onChange={(e) => setSampleId(e.target.value)}
                placeholder="auto"
                disabled={busy}
                className="input figure text-[13px]"
              />
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <Button type="button" variant={required ? "primary" : "default"} disabled={busy} onClick={() => void submit()}>
              {busy ? "Sealing…" : "Seal lab result"}
            </Button>
            <span className="text-[12px] text-faint">Priced against the example supply contract (SOP-RDF-5.3).</span>
          </div>
        </div>
      ) : (
        <div>
          <Button type="button" size="sm" onClick={() => setOpen(true)}>
            Record a lab result
          </Button>
        </div>
      )}

      {error ? (
        <p role="alert" className="m-0 text-[13px] text-verdict-red">
          {error}
        </p>
      ) : null}
    </div>
  );
}

const TIER_NAME: Record<string, string> = { A: "Premium", B: "Base", C: "Deductions" };
const TIER_TONE: Record<string, string> = {
  A: "border-verdict-green text-verdict-green",
  B: "border-seam-strong text-ink",
  C: "border-amber-line text-amber",
};

function ContractResult({ evalResult }: { evalResult: ContractEval }) {
  // Settlement fields (tier, settlement_idr, iso21640) are optional on the
  // shared type: absent on an older backend.
  const e = evalResult;
  const breached = e.breaches.length > 0;
  return (
    <div className="flex flex-col gap-2.5">
      {e.tier ? (
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <span
            className={cn(
              "rounded-[6px] border px-2 py-0.5 text-[12px] font-bold tracking-[0.6px] uppercase",
              TIER_TONE[e.tier] ?? "border-seam-strong text-ink",
            )}
          >
            Tier {e.tier}
            {TIER_NAME[e.tier] ? ` · ${TIER_NAME[e.tier]}` : ""}
          </span>
          {typeof e.settlement_idr === "number" ? (
            <span className="text-[14px] font-semibold text-ink">
              Settles at <span className="figure">{formatRupiah(e.settlement_idr)}</span>
            </span>
          ) : null}
          {e.tier_reason ? <span className="text-[13px] text-muted">{e.tier_reason}</span> : null}
        </div>
      ) : null}
      {breached ? (
        <ul className="m-0 flex list-none flex-col gap-1 p-0">
          {e.breaches.map((b) => (
            <li key={b.param} className="flex flex-wrap items-baseline gap-x-2 text-[13px]">
              <span className="font-semibold text-amber">{PARAM_LABEL[b.param] ?? b.param}</span>
              <span className="figure text-ink">
                {b.value} vs limit {b.limit}
              </span>
              <span className="text-muted">{b.effect}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="m-0 text-[13px] text-ink">Within every contract spec: full price.</p>
      )}
      <dl className="figure m-0 grid grid-cols-2 gap-px overflow-hidden rounded-[10px] border border-seam bg-seam text-[12.5px] sm:grid-cols-4">
        <Cell label="Base price" value={`${formatRupiah(e.base_price_idr_per_t)}/t`} />
        <Cell
          label="Adjusted"
          value={`${formatRupiah(e.adjusted_price_idr_per_t)}/t`}
          sub={e.adjustment_pct ? `${e.adjustment_pct > 0 ? "+" : ""}${e.adjustment_pct.toFixed(1)} %` : undefined}
        />
        <Cell label="Payable" value={formatRupiahCompact(e.payable_idr)} sub={`${e.net_t.toFixed(2)} t net`} />
        <Cell label="Deduction" value={e.deduction_idr > 0 ? formatRupiahCompact(e.deduction_idr) : "Rp 0"} strong={e.deduction_idr > 0} />
      </dl>
      {e.iso21640?.code ? (
        <p className="m-0 text-[13px] text-muted">
          ISO 21640 class (indicative): <span className="figure text-ink">{e.iso21640.code}</span>
          {e.iso21640.label ? <span className="block text-[11.5px] text-faint">{e.iso21640.label}</span> : null}
        </p>
      ) : null}
      <p className="m-0 text-[11.5px] text-faint">
        Example supply contract and example settlement tiers: terms are set per contract (SOP-RDF-5.3).
      </p>
    </div>
  );
}

function Cell({ label, value, sub, strong }: { label: string; value: string; sub?: string; strong?: boolean }) {
  return (
    <div className="flex flex-col gap-0.5 bg-panel px-3 py-2">
      <dt className="font-sans text-[11px] font-semibold tracking-[0.6px] text-muted uppercase">{label}</dt>
      <dd className={cn("m-0 text-[14px] font-semibold", strong ? "text-amber" : "text-ink")}>{value}</dd>
      {sub ? <dd className="m-0 text-[11.5px] text-muted">{sub}</dd> : null}
    </div>
  );
}
