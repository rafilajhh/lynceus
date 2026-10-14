"use client";

/**
 * IntakeForm: the weighbridge register: truck_id, supplier, waybill
 * photo, weight, stream select, moisture, age. Fields use the
 * foundation's .input token. The load photo upload lives beside the
 * hero image in the parent (WorkspaceClient).
 */

import type { FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { WASTE_STREAMS } from "@/lib/demo-cases";
import { cn } from "@/lib/utils";

export interface IntakeValues {
  truck_id: string;
  supplier: string;
  manifest_text: string;
  weight_kg: string;
  stream: string;
  moisture_pct: string;
  age_h: string;
}

/** Uploaded photo state, owned by the parent (bytes go into the payload). */
export interface UploadSlot {
  /** object URL for the preview; null = no upload (demo photo shows). */
  previewUrl: string | null;
  filename: string | null;
}

export function IntakeForm({
  values,
  onChange,
  onSubmit,
  onReset,
  onWaybillPhoto,
  waybillPhoto,
  loading,
  formError,
}: {
  values: IntakeValues;
  onChange: (patch: Partial<IntakeValues>) => void;
  onSubmit: () => void;
  /** Clear the whole gate (form, uploads, photo, verdict) — the same
      reset the verdict's "Next truck" button performs. */
  onReset: () => void;
  /** Upload handler receives the picked File (or null to clear). The load
      photo upload lives beside the hero image, not in this form. */
  onWaybillPhoto: (file: File | null) => void;
  waybillPhoto: UploadSlot;
  loading: boolean;
  formError: string | null;
}) {
  const field =
    "input disabled:opacity-50 disabled:cursor-not-allowed";

  const handleSubmit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    onSubmit();
  };

  /** Shared file-input row: hidden input + ghost button + clear. */
  const uploadRow = (
    id: string,
    label: string,
    slot: UploadSlot,
    onPick: (file: File | null) => void,
  ) => (
    <div className="flex items-center gap-2">
      <input
        id={id}
        type="file"
        accept="image/*"
        className="sr-only"
        disabled={loading}
        onChange={(e) => onPick(e.target.files?.[0] ?? null)}
      />
      <label
        htmlFor={id}
        className={cn(
          "inline-flex cursor-pointer items-center justify-center gap-2 rounded-[6px] border border-seam-strong bg-raised px-3 py-1.5 text-xs font-semibold text-ink transition-colors duration-100 select-none hover:border-amber-line hover:bg-seam",
          loading && "pointer-events-none opacity-50",
        )}
      >
        {label}
      </label>
      {slot.filename ? (
        <>
          <span className="figure min-w-0 flex-1 truncate text-[12px] text-muted">
            {slot.filename}
          </span>
          <button
            type="button"
            onClick={() => onPick(null)}
            disabled={loading}
            className="cursor-pointer rounded-[6px] px-2 py-1 text-[12px] font-semibold text-muted transition-colors duration-100 hover:bg-seam hover:text-ink"
          >
            Clear
          </button>
        </>
      ) : null}
    </div>
  );

  return (
    <div className="flex h-full flex-col">
      <form
        id="inspect-form"
        onSubmit={handleSubmit}
        aria-label="Truck intake form"
        className="flex flex-1 flex-col gap-3 px-4 py-4"
      >
        <div className="grid grid-cols-2 gap-3">
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
            <label htmlFor="supplier" className="smallcaps mb-1 block">
              Supplier
            </label>
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
        </div>

        {/* Waybill: an optional photo plus the declared text. The text is
            what the LLM cross-checks against the photo, so without it the
            gate honestly refuses (insufficient input). */}
        <div className="flex items-center gap-3">
          <span className="smallcaps shrink-0">Waybill</span>
          {uploadRow(
            "waybill-photo-upload",
            waybillPhoto.filename ? "Replace photo" : "Upload photo",
            waybillPhoto,
            onWaybillPhoto,
          )}
        </div>
        <div>
          <label htmlFor="manifest_text" className="smallcaps mb-1 block">
            Waybill text <span className="text-muted normal-case">(declared)</span>
          </label>
          <textarea
            id="manifest_text"
            rows={2}
            className={cn(field, "resize-none")}
            value={values.manifest_text}
            onChange={(e) => onChange({ manifest_text: e.target.value })}
            placeholder="What the waybill declares, e.g. 'Dry shredded RDF, no metal, declared 5200 kg, moisture 18%'"
            disabled={loading}
            autoComplete="off"
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

        {/* CTA row anchors the panel bottom (mt-auto): primary Inspect +
            a quiet Reset to clear the gate before any verdict exists. */}
        <div className="mt-auto flex gap-2">
          <Button
            type="submit"
            variant="primary"
            size="lg"
            disabled={loading}
            className="flex-1"
          >
            {loading ? "Evaluating interlock…" : "Inspect Load"}
          </Button>
          <Button
            type="button"
            variant="default"
            size="lg"
            disabled={loading}
            onClick={onReset}
          >
            Reset
          </Button>
        </div>
      </form>
    </div>
  );
}
