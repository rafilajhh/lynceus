"use client";

/**
 * WeighbridgeBlock: the scale indicator reading for this truck. In the demo
 * the feed is simulated (a site reads the indicator over RS-232/Modbus) and
 * says so. The net on the scale is compared with the net on the waybill:
 * within ±5 % passes; beyond it the ticket needs correcting.
 */

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { BlockHead, SourceTag } from "./block-head";
import { IconCheck, IconScale, IconWarn } from "./gate-icons";
import type { ScaleState } from "./use-intake";
import { formatKg, formatPct } from "./units";

/** Same tolerance as the decision rules (backend WEIGHT_TOLERANCE). */
export const WEIGHT_TOLERANCE = 0.05;

export function WeighbridgeBlock({
  scale,
  netKg,
  declaredNetKg,
  plate,
  disabled,
  invalid,
  onCapture,
  onManual,
  onManualNet,
}: {
  scale: ScaleState;
  /** The net the gate will use (reading or typed). */
  netKg: number | null;
  declaredNetKg: number | null;
  plate: string;
  disabled: boolean;
  invalid: boolean;
  onCapture: () => void;
  onManual: () => void;
  onManualNet: (value: string) => void;
}) {
  const r = scale.status === "live" ? scale.reading : null;
  const simulated = r?.source === "simulated";
  const delta =
    netKg !== null && declaredNetKg !== null && declaredNetKg > 0
      ? (netKg - declaredNetKg) / declaredNetKg
      : null;
  const within = delta !== null && Math.abs(delta) <= WEIGHT_TOLERANCE;

  return (
    <section aria-labelledby="scale-title" className="flex min-w-0 flex-col gap-3 p-4">
      <BlockHead id="scale-title" icon={<IconScale />} title="Weighbridge">
        {simulated ? (
          <SourceTag title={r?.note ?? "Simulated scale feed for the demo."}>Simulated feed</SourceTag>
        ) : scale.status === "manual" ? (
          <SourceTag>Typed by operator</SourceTag>
        ) : r ? (
          <SourceTag>Indicator feed</SourceTag>
        ) : null}
      </BlockHead>

      {scale.status === "idle" ? (
        <p className="m-0 text-[13px] leading-relaxed text-muted">
          Waiting for the plate from the waybill, then the indicator reading is captured.
        </p>
      ) : null}

      {scale.status === "reading" ? (
        <p role="status" className="figure m-0 inline-flex items-center gap-2 text-[12.5px] text-amber">
          <span aria-hidden="true" className="h-1.5 w-1.5 animate-[gate-pulse_1.1s_ease-in-out_infinite] rounded-full bg-amber" />
          Reading the indicator for {plate || "this truck"}
        </p>
      ) : null}

      {r ? (
        <div className="flex flex-col gap-2">
          <p className="figure m-0 flex items-center gap-2 text-[11.5px] text-muted">
            <span>{r.scale}</span>
            <span aria-hidden="true">·</span>
            <span className="text-ink">{r.plate}</span>
            {r.stable ? (
              <span className="inline-flex items-center gap-1 text-faint">
                <span aria-hidden="true" className="h-1.5 w-1.5 rounded-full bg-muted" />
                stable
              </span>
            ) : null}
          </p>
          <p className="m-0 flex items-baseline gap-2">
            <span className="figure text-[28px] leading-none font-semibold text-ink">{formatKg(r.net_kg, false)}</span>
            <span className="text-[13px] text-muted">kg net</span>
          </p>
          <dl className="figure m-0 grid grid-cols-2 gap-x-3 text-[12px]">
            <div className="flex justify-between gap-2 border-t border-seam pt-1.5">
              <dt className="text-muted">Gross</dt>
              <dd className="m-0 text-ink">{formatKg(r.gross_kg)}</dd>
            </div>
            <div className="flex justify-between gap-2 border-t border-seam pt-1.5">
              <dt className="text-muted">Tare</dt>
              <dd className="m-0 text-ink">{formatKg(r.tare_kg)}</dd>
            </div>
          </dl>
        </div>
      ) : null}

      {scale.status === "manual" ? (
        <div className="flex flex-col gap-1.5">
          {scale.message ? <p className="m-0 text-[12.5px] leading-snug text-muted">{scale.message}</p> : null}
          <label htmlFor="scale-net" className="text-[11px] font-semibold tracking-[0.6px] text-muted uppercase">
            Net weight on the indicator
          </label>
          <div className="flex items-center gap-2">
            <input
              id="scale-net"
              value={scale.manualNet}
              onChange={(e) => onManualNet(e.target.value)}
              inputMode="decimal"
              autoComplete="off"
              disabled={disabled}
              aria-invalid={invalid || undefined}
              className={cn("input figure text-[15px]", invalid && "border-verdict-red")}
              placeholder="16340"
            />
            <span className="text-[13px] text-muted">kg</span>
          </div>
        </div>
      ) : null}

      {/* Declared vs scale: the one comparison the weighbridge owns. */}
      {netKg !== null && declaredNetKg !== null ? (
        <div
          className={cn(
            "flex flex-col gap-1 rounded-[8px] border px-3 py-2",
            within ? "border-seam" : "border-amber-line bg-amber-dim",
          )}
        >
          <p className="figure m-0 flex justify-between gap-2 text-[12px] text-muted">
            <span>Waybill net</span>
            <span className="text-ink">{formatKg(declaredNetKg)}</span>
          </p>
          <p className={cn("m-0 flex items-center gap-1.5 text-[12.5px] font-semibold", within ? "text-ink" : "text-amber")}>
            {within ? <IconCheck size={13} /> : <IconWarn size={13} />}
            <span className="figure">{formatPct(delta)}</span>
            <span className="font-normal text-muted">
              {within ? "within the ±5 % tolerance" : "outside ±5 %: correct the ticket"}
            </span>
          </p>
        </div>
      ) : null}

      {scale.status !== "idle" ? (
        <div className="flex flex-wrap gap-1.5">
          <Button
            type="button"
            size="sm"
            onClick={onCapture}
            disabled={disabled || scale.status === "reading" || !plate.trim()}
          >
            {r ? "Capture again" : "Capture reading"}
          </Button>
          {scale.status !== "manual" ? (
            <Button type="button" size="sm" variant="ghost" onClick={onManual} disabled={disabled}>
              Type the weight
            </Button>
          ) : null}
        </div>
      ) : null}

      {r?.note ? <p className="m-0 text-[11px] leading-relaxed text-faint">{r.note}</p> : null}
    </section>
  );
}
