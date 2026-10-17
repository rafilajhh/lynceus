"use client";

/**
 * SensorsRow: the gate instruments this verdict answered to (the audit's
 * inputs.observations), each tagged real / simulated / not installed with
 * its status. Without observations it lists the plug-ins from GET /sensors,
 * so the integration points stay visible. The plug-in list's integration
 * note sits behind a disclosure.
 */

import { useEffect, useState } from "react";
import { fetchSensors, type Observation, type SensorsResponse } from "@/lib/inspect-api";
import { cn } from "@/lib/utils";
import { formatKg } from "./units";

const KIND_NAME: Record<string, string> = {
  image_quality: "Photo quality",
  weighbridge: "Weighbridge",
  plate: "Plate camera",
  radiation: "Radiation portal",
  nir_analyzer: "NIR analyser",
};

const STATUS: Record<Observation["status"], { word: string; cls: string }> = {
  ok: { word: "OK", cls: "text-verdict-green" },
  poor: { word: "Poor", cls: "text-amber" },
  mismatch: { word: "Mismatch", cls: "text-amber" },
  not_installed: { word: "Not installed", cls: "text-faint" },
  unavailable: { word: "Unavailable", cls: "text-faint" },
};

function origin(o: Observation): { word: string; cls: string } {
  if (o.status === "not_installed") return { word: "Not installed", cls: "border-seam text-faint" };
  if (o.simulated) return { word: "Simulated", cls: "border-amber-line text-amber" };
  if (o.source === "operator") return { word: "Typed", cls: "border-seam-strong text-muted" };
  return { word: "Real", cls: "border-seam-strong text-ink" };
}

function reading(o: Observation): string {
  const v = o.value;
  if (v === null || v === undefined) return "—";
  if (o.kind === "weighbridge" && typeof v === "number") return formatKg(v);
  if (o.kind === "image_quality" && typeof v === "object") {
    const m = v as Record<string, unknown>;
    const parts = [
      typeof m.sharpness === "number" ? `sharpness ${Math.round(m.sharpness)}` : null,
      typeof m.brightness === "number" ? `brightness ${Math.round(m.brightness)}` : null,
      typeof m.width_px === "number" && typeof m.height_px === "number" ? `${m.width_px}×${m.height_px}` : null,
    ];
    return parts.filter(Boolean).join(" · ") || "—";
  }
  if (typeof v === "string" || typeof v === "number") return `${v}${o.unit ? ` ${o.unit}` : ""}`;
  return "—";
}

function name(o: Observation): string {
  const base = KIND_NAME[o.kind] ?? o.kind.replace(/_/g, " ");
  return o.kind === "image_quality" && o.frame !== null ? `${base} · photo ${o.frame + 1}` : base;
}

export function SensorsRow({ observations }: { observations: Observation[] }) {
  const [plugins, setPlugins] = useState<SensorsResponse | null>(null);
  useEffect(() => {
    let live = true;
    void fetchSensors().then((r) => live && setPlugins(r));
    return () => {
      live = false;
    };
  }, []);

  // No observations on this record (older backend): show the plug-in list.
  const rows: Observation[] =
    observations.length > 0
      ? observations
      : (plugins?.sensors ?? []).map((p) => ({
          source: p.source ?? "",
          kind: p.kind,
          value: null,
          unit: p.unit,
          uncertainty: null,
          status: p.status === "not_installed" ? "not_installed" : "unavailable",
          measured_at_utc: null,
          sha256: null,
          simulated: p.status === "simulated",
          note: p.note,
          frame: null,
        }));
  if (rows.length === 0) return null;

  return (
    <section aria-labelledby="sensors-title" className="flex min-w-0 flex-col gap-2">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 id="sensors-title" className="smallcaps m-0">
          Gate sensors
        </h3>
        {observations.length === 0 ? (
          <span className="text-[12px] text-faint">This record kept no sensor readings: plug-ins listed</span>
        ) : null}
      </div>
      <ul className="m-0 grid list-none grid-cols-1 gap-px overflow-hidden rounded-[10px] border border-seam bg-seam p-0 sm:grid-cols-2 xl:grid-cols-3">
        {rows.map((o, i) => {
          const tag = origin(o);
          const status = STATUS[o.status];
          return (
            <li key={`${o.kind}-${o.frame ?? i}`} className="flex min-w-0 flex-col gap-1 bg-panel px-3 py-2.5" title={o.note ?? undefined}>
              <span className="flex flex-wrap items-center justify-between gap-2">
                <span className="text-[13px] font-semibold text-ink">{name(o)}</span>
                <span className={cn("rounded-[6px] border px-1.5 py-px text-[10.5px] font-bold tracking-[0.6px] uppercase", tag.cls)}>
                  {tag.word}
                </span>
              </span>
              {o.status !== "not_installed" ? (
                <span className="flex flex-wrap items-baseline gap-x-2">
                  <span className="figure text-[12.5px] text-ink">{reading(o)}</span>
                  <span className={cn("text-[12px] font-semibold", status.cls)}>{status.word}</span>
                </span>
              ) : null}
              {o.note ? <span className="line-clamp-2 text-[12px] leading-snug text-muted">{o.note}</span> : null}
            </li>
          );
        })}
      </ul>
      {plugins?.integration_note ? (
        <details className="text-[12.5px] text-muted">
          <summary className="cursor-pointer text-faint select-none">How a site connects its own sensors</summary>
          <p className="m-0 mt-1.5 max-w-[80ch] leading-relaxed">{plugins.integration_note}</p>
        </details>
      ) : null}
    </section>
  );
}
