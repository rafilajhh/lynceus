import type { Carbon } from "@/lib/control-api";
import { Panel, PanelHead } from "@/components/ui/panel";
import { num, plainWords } from "./format";

/**
 * CarbonPanel: this shift's alternative-fuel CO2 under the GCCA protocol.
 * Net avoided = coal CO2 the fuel's heat displaced − the fuel's fossil CO2
 * (gross emissions). Biogenic CO2 is a memo item. The biogenic share is an
 * assumption until a C-14 result exists, and the panel says so.
 */

const t = (v: number | null | undefined) => (v === null || v === undefined ? "—" : `${num(v, 0)} t`);

export function CarbonPanel({ carbon, className }: { carbon: Carbon | null; className?: string }) {
  if (!carbon) {
    return (
      <Panel className={className}>
        <PanelHead title="Carbon" />
        <p className="m-0 px-5 py-6 text-[13px] text-muted">The carbon estimate is unavailable on this backend.</p>
      </Panel>
    );
  }

  const gross = carbon.gcca?.gross_emissions_from_af_t ?? carbon.af_fossil_co2_t;
  const memo = carbon.gcca?.biogenic_memo_item_t ?? carbon.af_biogenic_co2_t;
  const net = carbon.gcca?.net_co2_avoided_t ?? carbon.net_co2_avoided_t;
  const rows = [
    {
      key: "coal",
      label: "Coal CO₂ displaced",
      source: "the fuel's heat, replacing sub-bituminous coal",
      value: t(carbon.coal_co2_displaced_t),
    },
    {
      key: "gross",
      label: "Fossil CO₂ from the fuel",
      source: "gross emissions (GCCA)",
      value: t(gross),
    },
    {
      key: "memo",
      label: "Biogenic CO₂",
      source: "memo item, climate neutral under GCCA",
      value: t(memo),
    },
    {
      key: "heat",
      label: "Alternative-fuel heat",
      source: "accepted loads, net t × NCV",
      value: carbon.af_energy_gj != null ? `${num(carbon.af_energy_gj, 0)} GJ` : "—",
    },
  ];
  const factors = Object.entries(carbon.factors);
  const sources = Object.entries(carbon.sources);

  return (
    <Panel className={className} aria-labelledby="carbon-head">
      <PanelHead title="Carbon" meta="this shift · GCCA" />
      <div className="flex flex-col gap-1.5 px-5 pt-4 pb-4">
        <p className="m-0 flex items-baseline gap-2">
          <span className="figure text-[34px] leading-none font-semibold tracking-[-0.01em] text-ink">
            {net != null ? num(net, 0) : "—"}
          </span>
          <span className="figure text-[14px] text-faint">t CO₂</span>
        </p>
        <h2 id="carbon-head" className="m-0 text-[14px] font-semibold text-ink">
          net CO₂ avoided by burning this shift&apos;s fuel instead of coal
        </h2>
        {carbon.biogenic_share_note ? (
          <p className="m-0 text-[12px] leading-relaxed text-faint">
            <span className="font-semibold text-muted">Assumption.</span> {carbon.biogenic_share_note}
          </p>
        ) : null}
      </div>
      <dl className="m-0 flex flex-col border-t border-seam">
        {rows.map((row) => (
          <div
            key={row.key}
            className="flex items-start justify-between gap-4 border-b border-seam px-5 py-2.5 last:border-b-0"
          >
            <div className="flex min-w-0 flex-col gap-0.5">
              <dt className="text-[13px] font-semibold text-ink">{row.label}</dt>
              <dd className="m-0 text-[12px] text-faint">{row.source}</dd>
            </div>
            <dd className="figure m-0 shrink-0 text-[16px] font-semibold text-ink">{row.value}</dd>
          </div>
        ))}
      </dl>
      <details className="group border-t border-seam px-5 py-2.5">
        <summary className="cursor-pointer text-[12.5px] font-semibold text-muted hover:text-ink">
          Factors, sources and limits
        </summary>
        <div className="mt-2 mb-1 flex flex-col gap-2 text-[12.5px] leading-relaxed text-muted">
          {factors.length > 0 ? (
            <p className="m-0">
              {factors
                .map(([k, v]) => `${k.replace(/_/g, " ").replace("co2", "CO₂").replace("t per tj", "t/TJ")} ${num(v, 1)}`)
                .join(" · ")}
            </p>
          ) : null}
          {carbon.tsr?.note ? <p className="m-0">{carbon.tsr.note}</p> : null}
          <ul className="m-0 flex list-disc flex-col gap-1 pl-5">
            {carbon.notes.map((note) => (
              <li key={note}>{plainWords(note)}</li>
            ))}
            {sources.map(([k, v]) => (
              <li key={k} className="break-words">
                {v}
              </li>
            ))}
          </ul>
        </div>
      </details>
    </Panel>
  );
}
