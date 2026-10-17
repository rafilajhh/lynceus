/**
 * Engine notes: the honesty notes that sit next to the verdict (scripted
 * fallback, detector-only mode, what ran) and, folded away, the engine's
 * reasons, caveats and the language model's narrative. The narrative never
 * changes the verdict; it is kept for the record.
 */

import type { InspectResponse } from "@/lib/inspect-api";
import { formatSeconds, providerName } from "@/lib/format";

/** One line of what produced the vision answer, or why it was not live. */
export function ProvenanceNote({ data }: { data: InspectResponse }) {
  const vlm = data.ai_outputs.vlm;
  if (data.provenance === "stub") {
    return (
      <p className="m-0 text-[12.5px] text-faint">
        Offline mode: the model outputs are the scripted sample for this photo, not a live AI reading.
      </p>
    );
  }
  if (data.provenance === "stub_fallback_live_error") {
    return (
      <p role="note" className="m-0 rounded-[8px] border border-amber-line bg-amber-dim px-3 py-2 text-[13px] leading-snug text-ink">
        <span className="font-semibold text-amber">Live AI failed: scripted fallback shown.</span> This verdict uses
        the scripted sample, not a live reading of this photo. Inspect again once the live endpoint responds.
      </p>
    );
  }
  if (data.provenance === "detector_only_degraded") {
    return (
      <p role="note" className="m-0 rounded-[8px] border border-amber-line bg-amber-dim px-3 py-2 text-[13px] leading-snug text-ink">
        <span className="font-semibold text-amber">
          {data.failed_stage === "llm" ? "Waybill model unavailable" : "Vision model unavailable"}: detector-only
          verdict.
        </span>{" "}
        Detector-only mode never accepts or rejects a load; it holds the truck for a person. Inspect again once the
        live endpoint responds.
      </p>
    );
  }
  if (data.provenance === "live" && vlm?.model) {
    return (
      <p className="figure m-0 text-[12px] text-faint">
        {[
          `Vision: ${vlm.model}`,
          vlm.provider ? `on ${providerName(vlm.provider)}` : null,
          formatSeconds(vlm.latency_ms),
        ]
          .filter(Boolean)
          .join(" · ")}
      </p>
    );
  }
  return null;
}

/** Engine field names → operator language. */
const FIELD_LABELS: Record<string, string> = {
  ncv_mj_per_kg: "heating value",
  ash_fraction: "ash content",
  chlorine_fraction: "chlorine content",
  "mixed-msw": "mixed municipal waste",
  mixed_msw: "mixed municipal waste",
};

function humanize(text: string): string {
  let out = text;
  for (const [field, label] of Object.entries(FIELD_LABELS)) out = out.replaceAll(field, label);
  return out;
}

function unique(list: string[]): string[] {
  return [...new Set(list.map((s) => s.trim()).filter(Boolean))];
}

export function EngineNotes({ data }: { data: InspectResponse }) {
  const reasons = unique([...(data.engine_outputs?.recommendation?.reasons ?? []), ...(data.reasons ?? [])]);
  const caveats = unique([
    ...(data.engine_outputs?.recommendation?.caveats ?? []),
    ...(data.caveats ?? []),
    ...(data.verdict?.uncertainty ? [data.verdict.uncertainty] : []),
  ]);
  const narrative = data.ai_outputs.llm?.reasoning ?? null;
  if (reasons.length === 0 && caveats.length === 0 && !narrative) return null;

  return (
    <details className="group rounded-[10px] border border-seam px-4 py-3 text-[13px] text-muted">
      <summary className="cursor-pointer font-semibold text-ink select-none">
        Rule reasons and caveats
        <span className="ml-2 font-normal text-faint">
          {reasons.length} {reasons.length === 1 ? "reason" : "reasons"} · {caveats.length}{" "}{caveats.length === 1 ? "caveat" : "caveats"}
        </span>
      </summary>
      <div className="mt-3 flex flex-col gap-3">
        {reasons.length > 0 ? (
          <div>
            <h4 className="smallcaps m-0 mb-1.5">Reasons</h4>
            <ul className="m-0 flex list-disc flex-col gap-1 pl-5 marker:text-amber">
              {reasons.map((r) => (
                <li key={r} className="leading-snug">
                  {humanize(r)}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
        {caveats.length > 0 ? (
          <div>
            <h4 className="smallcaps m-0 mb-1.5">Caveats</h4>
            <ul className="m-0 flex list-disc flex-col gap-1 pl-5 marker:text-faint">
              {caveats.map((c) => (
                <li key={c} className="leading-snug">
                  {humanize(c)}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
        {narrative ? (
          <div>
            <h4 className="smallcaps m-0 mb-1.5">Language model notes (do not change the verdict)</h4>
            <p className="m-0 max-w-[80ch] leading-relaxed">{narrative}</p>
          </div>
        ) : null}
      </div>
    </details>
  );
}
