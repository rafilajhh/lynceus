"use client";

/**
 * IntakeForm: the "02 Waybill & register" card. Waybill photo upload
 * (+ sample), then the weighbridge register: truck_id, supplier, weight,
 * stream, moisture, age, and the Inspect / Reset actions. The load photo
 * upload lives in the "01 Incoming load" card (WorkspaceClient). The
 * declared waybill text is synthesized by the parent from stream + weight.
 */

import type { FormEvent } from "react";
import { FileScan, Info, RotateCcw, ScanLine, Upload, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { WASTE_STREAMS } from "@/lib/demo-cases";
import { cn } from "@/lib/utils";

export interface IntakeValues {
  truck_id: string;
  supplier: string;
  weight_kg: string;
  stream: string;
  moisture_pct: string;
  age_h: string;
}

/** Uploaded photo state, owned by the parent (bytes go into the payload). */
export interface UploadSlot {
  /** object URL for the preview; null = no upload. */
  previewUrl: string | null;
  filename: string | null;
}

/** Field label: 12px medium muted, 6px above the control. */
function FieldLabel({ htmlFor, children }: { htmlFor: string; children: React.ReactNode }) {
  return (
    <label htmlFor={htmlFor} className="mb-1.5 block text-[12px] font-medium text-fg-muted">
      {children}
    </label>
  );
}

export function IntakeForm({
  values,
  onChange,
  onSubmit,
  onReset,
  onWaybillPhoto,
  onQuickWaybill,
  quickWaybillBusy,
  waybillPhoto,
  loading,
  formError,
}: {
  values: IntakeValues;
  onChange: (patch: Partial<IntakeValues>) => void;
  onSubmit: () => void;
  /** Clear the whole gate (form, uploads, photo, verdict) — the same
      reset the result's "Next truck" button performs. */
  onReset: () => void;
  /** Upload handler receives the picked File (or null to clear). */
  onWaybillPhoto: (file: File | null) => void;
  /** Quick-pick: load the site waybill photo through onWaybillPhoto. */
  onQuickWaybill: () => void;
  quickWaybillBusy: boolean;
  waybillPhoto: UploadSlot;
  loading: boolean;
  formError: string | null;
}) {
  const field = "input disabled:cursor-not-allowed disabled:opacity-50";

  const handleSubmit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    onSubmit();
  };

  const hasWaybill = Boolean(waybillPhoto.filename);

  return (
    <section aria-labelledby="register-title" className="card flex flex-col">
      <div className="flex items-center gap-2.5 border-b border-line px-5 py-4">
        <span className="font-mono text-[12px] text-brand-deep" aria-hidden="true">
          02
        </span>
        <h2 id="register-title" className="m-0 font-display text-[17px] font-medium text-fg">
          Waybill &amp; register
        </h2>
      </div>

      <form
        id="inspect-form"
        onSubmit={handleSubmit}
        aria-label="Truck intake form"
        className="flex flex-1 flex-col"
      >
        <div className="flex flex-col gap-3 px-5 py-4">
          {/* Waybill photo: optional evidence bytes; the declared text is
              synthesized from stream + weight below. */}
          <div className="flex flex-col gap-3 rounded-[10px] border border-line-strong bg-surface-subtle p-4">
            <div className="flex items-center gap-3">
              <span
                aria-hidden="true"
                className="flex h-10 w-10 shrink-0 items-center justify-center rounded-[10px] border border-line-strong bg-surface text-fg"
              >
                <FileScan className="h-[18px] w-[18px]" />
              </span>
              <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                <span className="text-[14px] font-medium break-words text-fg">
                  {hasWaybill ? (
                    <span className="font-mono text-[13px]">{waybillPhoto.filename}</span>
                  ) : (
                    "Upload waybill photo"
                  )}
                </span>
                <span className="text-[12px] text-fg-muted">
                  {hasWaybill ? "Waybill photo attached" : "JPEG or PNG of the paper waybill"}
                </span>
              </div>
              <div className="flex shrink-0 items-center gap-1.5">
                <input
                  id="waybill-photo-upload"
                  type="file"
                  accept="image/*"
                  className="sr-only"
                  disabled={loading}
                  onChange={(e) => onWaybillPhoto(e.target.files?.[0] ?? null)}
                />
                <label
                  htmlFor="waybill-photo-upload"
                  className={cn(
                    "inline-flex h-8 cursor-pointer items-center justify-center gap-1.5 rounded-[8px] border border-line-strong bg-surface px-3 text-[13px] font-medium text-fg shadow-control transition-colors duration-100 select-none hover:bg-surface-subtle",
                    loading && "pointer-events-none opacity-50",
                  )}
                >
                  <Upload aria-hidden="true" className="h-3.5 w-3.5" />
                  {hasWaybill ? "Replace" : "Upload"}
                </label>
                {hasWaybill ? (
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className="h-8 w-8"
                    onClick={() => onWaybillPhoto(null)}
                    disabled={loading}
                    aria-label="Clear waybill photo"
                    title="Clear waybill photo"
                  >
                    <X aria-hidden="true" className="h-3.5 w-3.5" />
                  </Button>
                ) : null}
              </div>
            </div>
            <div className="flex items-center gap-2 border-t border-line pt-2.5">
              <p className="m-0 flex flex-1 items-center gap-2 text-[12px] text-fg-muted">
                <Info aria-hidden="true" className="h-3.5 w-3.5 shrink-0 text-brand" />
                Copy the truck ID, supplier, weight and stream from the waybill into the register.
              </p>
              {hasWaybill ? null : (
                <button
                  type="button"
                  disabled={loading || quickWaybillBusy}
                  onClick={onQuickWaybill}
                  className="shrink-0 cursor-pointer text-[12px] font-medium text-brand hover:underline disabled:pointer-events-none disabled:opacity-50"
                >
                  {quickWaybillBusy ? "Loading…" : "Use sample"}
                </button>
              )}
            </div>
          </div>

          <div className="flex items-center gap-2 pt-1">
            <span className="text-[13px] font-medium text-fg">Register</span>
            <span
              className={cn(
                "rounded-full px-2 py-px text-[11px] font-medium",
                hasWaybill ? "bg-success-tint text-success" : "bg-surface-subtle text-fg-muted",
              )}
            >
              {hasWaybill ? "Waybill attached" : "Waiting for waybill"}
            </span>
          </div>

          <div>
            <FieldLabel htmlFor="truck_id">Truck ID</FieldLabel>
            <input
              id="truck_id"
              className={field}
              value={values.truck_id}
              onChange={(e) => onChange({ truck_id: e.target.value })}
              placeholder="e.g. B 9174 KT"
              disabled={loading}
              autoComplete="off"
            />
          </div>
          <div>
            <FieldLabel htmlFor="supplier">Supplier</FieldLabel>
            <input
              id="supplier"
              className={field}
              value={values.supplier}
              onChange={(e) => onChange({ supplier: e.target.value })}
              placeholder="Hauler on the waybill"
              disabled={loading}
              autoComplete="off"
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <FieldLabel htmlFor="weight_kg">Weight (kg)</FieldLabel>
              <input
                id="weight_kg"
                type="number"
                min={0}
                step="any"
                className={cn(field, "figure")}
                value={values.weight_kg}
                onChange={(e) => onChange({ weight_kg: e.target.value })}
                placeholder="e.g. 15500"
                disabled={loading}
              />
            </div>
            <div>
              <FieldLabel htmlFor="stream">Stream</FieldLabel>
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
              <FieldLabel htmlFor="moisture_pct">Moisture (%)</FieldLabel>
              <input
                id="moisture_pct"
                type="number"
                min={0}
                max={100}
                step="any"
                className={cn(field, "figure")}
                value={values.moisture_pct}
                onChange={(e) => onChange({ moisture_pct: e.target.value })}
                placeholder="e.g. 18"
                disabled={loading}
              />
            </div>
            <div>
              <FieldLabel htmlFor="age_h">Age (h)</FieldLabel>
              <input
                id="age_h"
                type="number"
                min={0}
                step="any"
                className={cn(field, "figure")}
                value={values.age_h}
                onChange={(e) => onChange({ age_h: e.target.value })}
                placeholder="e.g. 36"
                disabled={loading}
              />
            </div>
          </div>

          {formError ? (
            <p
              role="alert"
              className="m-0 rounded-[8px] border border-danger/25 bg-danger-tint px-3 py-2 text-[13px] text-danger"
            >
              {formError}
            </p>
          ) : null}
        </div>

        <div className="mt-auto flex items-center gap-2 border-t border-line px-5 py-4">
          <Button type="submit" variant="primary" disabled={loading} className="h-10 flex-1">
            <ScanLine aria-hidden="true" className="h-3.5 w-3.5" />
            {loading ? "Evaluating…" : "Inspect load"}
          </Button>
          <Button
            type="button"
            variant="ghost"
            disabled={loading}
            onClick={onReset}
            className="h-10 text-fg"
          >
            <RotateCcw aria-hidden="true" className="h-3.5 w-3.5" />
            Reset
          </Button>
        </div>
      </form>
    </section>
  );
}
