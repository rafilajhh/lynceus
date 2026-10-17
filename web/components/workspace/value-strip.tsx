"use client";

/**
 * ValueStrip: what this one decision was worth, measured or sourced.
 * Decision time is measured in this browser. The money figure is the
 * backend's impact estimate (impact.py), each row of its basis cited; the
 * hand-check time saved on an ACCEPT is an assumption and says so.
 */

import type { ImpactEstimate } from "@/lib/api";
import { formatRupiah, formatRupiahCompact } from "@/lib/format";
import { useCountUp } from "@/lib/use-count-up";
import { cn } from "@/lib/utils";
import type { VerdictTone } from "./verdict-banner";
import { formatSecs } from "./units";

/** Manual hand-check time, an assumption (docs/BUSINESS.md value model). */
const HAND_CHECK_MIN = 3;

export function ValueStrip({
  tone,
  elapsedMs,
  impact,
  runKey,
}: {
  tone: VerdictTone;
  elapsedMs: number | null;
  impact: ImpactEstimate | undefined;
  runKey: number;
}) {
  const idr = impact?.prevented_loss_idr ?? 0;
  const [shown] = useCountUp(idr, idr > 0 ? runKey : 0);
  const basis = impact?.basis ?? [];

  const money =
    idr > 0 && tone === "reject"
      ? { label: "Exposure if it had tipped", sub: "Up to: shredder + 1 kiln hour, worst case" }
      : idr > 0 && tone === "escalate"
        ? { label: "Energy lost if tipped wet", sub: "Water evaporated in the kiln, priced as RDF" }
        : idr > 0 && tone === "accept"
          ? { label: "Load value forwarded", sub: "Market value of the RDF, not a saving" }
          : null;

  return (
    <section aria-label="Value of this decision" className="flex flex-col gap-2">
      <div className="grid grid-cols-1 gap-px overflow-hidden rounded-[10px] border border-seam bg-seam sm:grid-cols-[minmax(0,0.8fr)_minmax(0,1.3fr)_minmax(0,1fr)]">
        <Figure
          value={formatSecs(elapsedMs !== null ? elapsedMs / 1000 : null)}
          label="Decided in"
          sub="Inspect to verdict, measured here"
        />
        {money ? (
          <Figure
            value={idr > 0 ? (tone === "reject" ? `Up to ${formatRupiahCompact(shown)}` : formatRupiahCompact(shown)) : "—"}
            title={formatRupiah(idr)}
            label={money.label}
            sub={money.sub}
          />
        ) : (
          <Figure value="—" label="No money figure" sub="Nothing sourced to estimate for this verdict" muted />
        )}
        {tone === "accept" ? (
          <Figure value={`~${HAND_CHECK_MIN} min`} label="Hand check not needed" sub="Gate time per truck, an assumption" />
        ) : tone === "reject" || tone === "escalate" ? (
          <Figure value="Before tipping" label="Stopped at the gate" sub="The load never reached the bunker" />
        ) : (
          <Figure value="—" label="Nothing decided" sub="Re-inspect with the missing input" muted />
        )}
      </div>
      {basis.length > 0 || impact?.note ? (
        <details className="text-[12.5px] text-muted">
          <summary className="cursor-pointer select-none hover:text-ink">How the money figure is built</summary>
          <div className="mt-2 flex flex-col gap-2">
            {impact?.note ? <p className="m-0 max-w-[80ch] leading-relaxed">{impact.note}</p> : null}
            <ul className="m-0 flex list-none flex-col gap-1 p-0">
              {basis.map((b) => (
                <li key={b.label} className="flex flex-wrap gap-x-2">
                  <span className="text-ink">{b.label}</span>
                  <span className="figure">{b.value}</span>
                  {/^https?:\/\//.test(b.source_url) ? (
                    <a
                      href={b.source_url}
                      target="_blank"
                      rel="noreferrer"
                      className="text-muted underline decoration-seam-strong underline-offset-2 hover:text-ink hover:decoration-amber-line"
                    >
                      source
                    </a>
                  ) : (
                    <span className="text-faint">{b.source_url}</span>
                  )}
                </li>
              ))}
            </ul>
          </div>
        </details>
      ) : null}
    </section>
  );
}

function Figure({
  value,
  label,
  sub,
  title,
  muted = false,
}: {
  value: string;
  label: string;
  sub: string;
  title?: string;
  muted?: boolean;
}) {
  return (
    <div className="flex min-w-0 flex-col gap-0.5 bg-panel px-4 py-3">
      <span className="text-[11px] font-bold tracking-[1px] text-muted uppercase">{label}</span>
      <span title={title} className={cn("figure text-[22px] leading-tight font-semibold", muted ? "text-faint" : "text-ink")}>
        {value}
      </span>
      <span className="text-[12px] leading-snug text-faint">{sub}</span>
    </div>
  );
}
