/**
 * DeclaredObserved: what the waybill declared next to what the gate saw
 * and weighed, row by row. This is the dispute-proof part of the verdict:
 * every "observed" value names where it came from.
 */

import type { InspectResponse } from "@/lib/inspect-api";
import type { Sampling } from "@/lib/ops-api";
import { cn } from "@/lib/utils";
import { parseFieldNumber } from "@/lib/waybill-api";
import { visionHard, visionLight } from "./vision-findings";
import { IconCheck, IconDash, IconInfo, IconWarn, IconCross } from "./gate-icons";
import type { RunSnapshot } from "./use-inspection";
import { formatKg, formatPct, formatPercent } from "./units";
import { WEIGHT_TOLERANCE } from "./weighbridge-block";

type RowStatus = "match" | "conflict" | "check" | "info" | "none";

interface Row {
  field: string;
  declared: string;
  observed: string;
  source: string;
  status: RowStatus;
  word: string;
  /** Measurements render in mono. */
  mono?: boolean;
}

/** Visual moisture is "wetter than declared" at +15 points (backend rule). */
const MOISTURE_MARGIN_PTS = 15;
const ARITHMETIC_TOLERANCE = 0.01;

const STATUS: Record<RowStatus, { cls: string; Icon: typeof IconCheck }> = {
  match: { cls: "text-verdict-green", Icon: IconCheck },
  conflict: { cls: "text-verdict-red", Icon: IconCross },
  check: { cls: "text-amber", Icon: IconWarn },
  info: { cls: "text-muted", Icon: IconInfo },
  none: { cls: "text-faint", Icon: IconDash },
};

const words = (list: string[]) => list.map((s) => s.replace(/_/g, " ")).join(", ");

function rowsOf(data: InspectResponse, snap: RunSnapshot, sampling: Sampling | null): Row[] {
  const v = snap.waybill.values;
  const hard = visionHard(data);
  const light = visionLight(data);
  const detected = data.ai_outputs.vlm?.detected as Record<string, unknown> | null | undefined;
  const visualMoisture = typeof detected?.moisture === "number" ? detected.moisture * 100 : null;
  const declaredMoisture = parseFieldNumber(v.moisture_pct);
  const declaredNet = parseFieldNumber(v.net_kg);
  const gross = parseFieldNumber(v.gross_kg);
  const tare = parseFieldNumber(v.tare_kg);
  const scaleNet = snap.scale.netKg;
  const rows: Row[] = [];

  // Load type vs what the camera saw.
  rows.push({
    field: "Load",
    declared: v.load_type.trim() || "—",
    observed: hard.length
      ? `${cap(words(hard))} seen`
      : light.length
        ? `No hard items · ${words(light)}`
        : data.ai_outputs.vlm
          ? "No hard items seen"
          : "No vision reading",
    source: "load photo",
    status: hard.length ? "conflict" : light.length ? "check" : data.ai_outputs.vlm ? "match" : "none",
    word: hard.length ? "Conflict" : light.length ? "Check" : data.ai_outputs.vlm ? "Matches" : "—",
  });

  // Moisture: declared vs visual estimate.
  const wetter =
    visualMoisture !== null && declaredMoisture !== null && visualMoisture >= declaredMoisture + MOISTURE_MARGIN_PTS;
  rows.push({
    field: "Moisture",
    mono: true,
    declared: declaredMoisture !== null ? formatPercent(declaredMoisture) : "—",
    observed: visualMoisture !== null ? `≈ ${Math.round(visualMoisture)} % visual` : "—",
    source: "visual estimate, not a lab value",
    status: visualMoisture === null || declaredMoisture === null ? "none" : wetter ? "check" : "match",
    word: visualMoisture === null || declaredMoisture === null ? "—" : wetter ? "Wetter" : "Plausible",
  });

  // Net weight: declared vs scale.
  const delta = declaredNet && declaredNet > 0 ? (scaleNet - declaredNet) / declaredNet : null;
  rows.push({
    field: "Net weight",
    mono: true,
    declared: formatKg(declaredNet),
    // Non-breaking inside the delta so "(+0.0 %)" never splits on mobile.
    observed: `${formatKg(scaleNet)}${delta !== null ? ` (${formatPct(delta).replace(/ /g, " ")})` : ""}`,
    source: snap.scale.source === "manual_entry" ? "typed by operator" : snap.scale.source === "weighbridge_simulated" ? "weighbridge, simulated feed" : "weighbridge",
    status: delta === null ? "none" : Math.abs(delta) <= WEIGHT_TOLERANCE ? "match" : "check",
    word: delta === null ? "—" : Math.abs(delta) <= WEIGHT_TOLERANCE ? "Within 5 %" : "Correct ticket",
  });

  // The ticket's own arithmetic.
  if (gross !== null && tare !== null && declaredNet !== null) {
    const diff = gross - tare - declaredNet;
    const ok = Math.abs(diff) <= ARITHMETIC_TOLERANCE * declaredNet;
    rows.push({
      field: "Gross − tare",
      mono: true,
      declared: `${formatKg(gross, false)} − ${formatKg(tare, false)}`,
      observed: ok ? `= ${formatKg(gross - tare)}` : `= ${formatKg(gross - tare)}, net says ${formatKg(declaredNet)}`,
      source: "waybill arithmetic",
      status: ok ? "match" : "check",
      word: ok ? "Adds up" : "Off",
    });
  }

  // Plate: waybill vs the truck on the scale.
  const scalePlate = snap.scale.reading?.plate?.trim();
  if (v.plate.trim()) {
    const same = scalePlate ? norm(scalePlate) === norm(v.plate) : null;
    rows.push({
      field: "Plate",
      declared: v.plate.trim(),
      observed: scalePlate ?? "—",
      source: scalePlate ? "weighbridge" : "no scale plate",
      status: same === null ? "none" : same ? "match" : "check",
      word: same === null ? "—" : same ? "Same truck" : "Differs",
    });
  }

  // Supplier record (risk-based sampling).
  if (v.carrier.trim()) {
    rows.push({
      field: "Supplier",
      declared: v.carrier.trim(),
      observed: sampling ? `${cap(sampling.tier)} risk${sampling.label ? ` · ${sampling.label}` : ""}` : "—",
      source: "supplier record",
      status: sampling ? (sampling.sample_this_truck ? "check" : "info") : "none",
      word: sampling ? (sampling.sample_this_truck ? "Sample" : sampling.tier === "new" ? "New" : "Known") : "—",
    });
  }
  return rows;
}

function norm(plate: string): string {
  return plate.replace(/\s+/g, "").toUpperCase();
}

function cap(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

export function DeclaredObserved({
  data,
  snapshot,
}: {
  data: InspectResponse;
  snapshot: RunSnapshot;
}) {
  const rows = rowsOf(data, snapshot, data.sampling);
  return (
    <section aria-labelledby="declared-title" className="flex min-w-0 flex-col gap-2">
      <h3 id="declared-title" className="smallcaps m-0">
        Declared vs observed
      </h3>
      <div className="overflow-hidden rounded-[10px] border border-seam">
        {/* Below sm each row stacks: the field as a line, then waybill |
            seen | status, so measurements never wrap mid-number. */}
        <table className="block w-full border-collapse text-[13px] sm:table">
          <thead className="hidden sm:table-header-group">
            <tr className="bg-raised text-left">
              <th scope="col" className="px-3 py-2 text-[11px] font-bold tracking-[1px] text-muted uppercase">
                Field
              </th>
              <th scope="col" className="px-3 py-2 text-[11px] font-bold tracking-[1px] text-muted uppercase">
                Waybill
              </th>
              <th scope="col" className="px-3 py-2 text-[11px] font-bold tracking-[1px] text-muted uppercase">
                Seen / measured
              </th>
              <th scope="col" className="px-3 py-2 text-right text-[11px] font-bold tracking-[1px] text-muted uppercase">
                <span className="sr-only sm:not-sr-only">Status</span>
              </th>
            </tr>
          </thead>
          <tbody className="block sm:table-row-group">
            {rows.map((r) => {
              const s = STATUS[r.status];
              return (
                <tr
                  key={r.field}
                  className="grid grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)_auto] border-t border-seam align-top first:border-t-0 sm:table-row sm:first:border-t"
                >
                  <th
                    scope="row"
                    className="col-span-3 px-3 pt-2 text-left font-semibold whitespace-nowrap text-muted sm:table-cell sm:py-2"
                  >
                    {r.field}
                  </th>
                  <td className={cn("px-3 py-2 break-words text-ink", r.mono && "figure text-[12.5px]")}>
                    <span className="block font-sans text-[10.5px] font-semibold tracking-[0.6px] text-faint uppercase sm:hidden">
                      Waybill
                    </span>
                    {r.declared}
                  </td>
                  <td className="px-3 py-2">
                    <span className="block font-sans text-[10.5px] font-semibold tracking-[0.6px] text-faint uppercase sm:hidden">
                      Seen
                    </span>
                    <span className={cn("block break-words text-ink", r.mono && "figure text-[12.5px]")}>{r.observed}</span>
                    <span className="block text-[11.5px] text-faint">{r.source}</span>
                  </td>
                  <td className={cn("px-3 py-2 text-right whitespace-nowrap", s.cls)}>
                    <span className="inline-flex items-center gap-1 text-[12.5px] font-semibold">
                      <s.Icon size={13} />
                      <span className="hidden sm:inline">{r.word}</span>
                      <span className="sr-only sm:hidden">{r.word}</span>
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
