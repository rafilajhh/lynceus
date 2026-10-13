"use client";

/**
 * IntakeForm: the weighbridge register: truck_id, waybill textarea,
 * weight, stream select, moisture, age. Plus the three demo-case
 * buttons (Green/Amber/Red) with their real labels. Fields use the
 * foundation's .input token. Race-guarded demo loading is handled by
 * the parent (WorkspaceClient).
 */

import type { FormEvent, ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { WASTE_STREAMS, DEMO_CASES } from "@/lib/demo-cases";
import { cn } from "@/lib/utils";

export interface IntakeValues {
  truck_id: string;
  manifest_text: string;
  weight_kg: string;
  stream: string;
  moisture_pct: string;
  age_h: string;
}

const DEMO_BTN_TONE: Record<string, string> = {
  green: "border-verdict-green/70 text-verdict-green hover:bg-green-dim",
  amber: "border-amber/70 text-amber hover:bg-amber-dim",
  red: "border-verdict-red/70 text-verdict-red hover:bg-red-dim",
};

export function IntakeForm({
  values,
  onChange,
  onDemo,
  onSubmit,
  loading,
  formError,
  activeDemo,
  photoSlot,
}: {
  values: IntakeValues;
  onChange: (patch: Partial<IntakeValues>) => void;
  onDemo: (key: "green" | "amber" | "red") => void;
  onSubmit: () => void;
  loading: boolean;
  formError: string | null;
  activeDemo: string | null;
  /** Hero photo figure is rendered between the demo row and the form. */
  photoSlot: ReactNode;
}) {
  const field =
    "input disabled:opacity-50 disabled:cursor-not-allowed";

  const handleSubmit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    onSubmit();
  };

  return (
    <div className="flex flex-col">
      {/* Demo-case row */}
      <div className="flex flex-wrap items-center gap-2 border-b border-dashed border-seam px-4 py-3">
        <span className="smallcaps">Demo cases</span>
        {(["green", "amber", "red"] as const).map((key) => (
          <Button
            key={key}
            variant="ghost"
            size="sm"
            type="button"
            disabled={loading}
            aria-pressed={activeDemo === key}
            className={cn(
              "border",
              DEMO_BTN_TONE[key],
              activeDemo === key && "bg-seam/60",
            )}
            onClick={() => onDemo(key)}
          >
            {DEMO_CASES[key].label}
          </Button>
        ))}
      </div>

      {photoSlot}

      <form
        id="inspect-form"
        onSubmit={handleSubmit}
        aria-label="Truck intake form"
        className="flex flex-col gap-3 px-4 py-4"
      >
        <div>
          <label htmlFor="truck_id" className="smallcaps mb-1 block">
            Truck ID <span className="text-muted normal-case">(plate)</span>
          </label>
          <input
            id="truck_id"
            className={field}
            value={values.truck_id}
            onChange={(e) => onChange({ truck_id: e.target.value })}
            placeholder="B 9174 KT"
            disabled={loading}
            autoComplete="off"
          />
        </div>

        <div>
          <label htmlFor="manifest_text" className="smallcaps mb-1 block">
            Waybill
          </label>
          <textarea
            id="manifest_text"
            className={cn(field, "figure text-[13px] leading-relaxed")}
            rows={7}
            value={values.manifest_text}
            onChange={(e) => onChange({ manifest_text: e.target.value })}
            placeholder="WAYBILL / WEIGHBRIDGE TICKET…"
            disabled={loading}
          />
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label htmlFor="weight_kg" className="smallcaps mb-1 block">
              Weight <span className="text-muted normal-case">kg</span>
            </label>
            <input
              id="weight_kg"
              type="number"
              min={0}
              step="any"
              className={cn(field, "figure")}
              value={values.weight_kg}
              onChange={(e) => onChange({ weight_kg: e.target.value })}
              disabled={loading}
            />
          </div>
          <div>
            <label htmlFor="stream" className="smallcaps mb-1 block">
              Stream
            </label>
            <select
              id="stream"
              className={cn(field, "figure")}
              value={values.stream}
              onChange={(e) => onChange({ stream: e.target.value })}
              disabled={loading}
            >
              {WASTE_STREAMS.map((s) => (
                <option key={s.value} value={s.value}>
                  {s.label}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label htmlFor="moisture_pct" className="smallcaps mb-1 block">
              Moisture <span className="text-muted normal-case">%</span>
            </label>
            <input
              id="moisture_pct"
              type="number"
              min={0}
              max={100}
              step="any"
              className={cn(field, "figure")}
              value={values.moisture_pct}
              onChange={(e) => onChange({ moisture_pct: e.target.value })}
              disabled={loading}
            />
          </div>
          <div>
            <label htmlFor="age_h" className="smallcaps mb-1 block">
              Age <span className="text-muted normal-case">h</span>
            </label>
            <input
              id="age_h"
              type="number"
              min={0}
              step="any"
              className={cn(field, "figure")}
              value={values.age_h}
              onChange={(e) => onChange({ age_h: e.target.value })}
              disabled={loading}
            />
          </div>
        </div>

        {formError ? (
          <p
            role="alert"
            className="rounded-[6px] border border-verdict-red/60 bg-red-dim px-3 py-2 text-[12.5px] text-verdict-red"
          >
            {formError}
          </p>
        ) : null}

        <Button
          type="submit"
          variant="primary"
          size="lg"
          disabled={loading}
          className="mt-1 w-full"
        >
          {loading ? "Evaluating interlock…" : "Inspect Load"}
        </Button>
      </form>
    </div>
  );
}
