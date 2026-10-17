"use client";

/**
 * WaybillBlock: the supplier's paper waybill (surat jalan). The photo goes
 * to the vision model, which reads every field; the fields fill in one by
 * one with their read confidence. Anything below 0.6 is amber for the
 * operator to check; any field changed after the read is marked "edited"
 * and travels with the record as `edited_fields`.
 */

/* eslint-disable @next/next/no-img-element -- object URL preview; static export has no image optimizer */

import { formatSeconds, providerName } from "@/lib/format";
import { useElapsedSeconds } from "@/lib/use-elapsed";
import { cn } from "@/lib/utils";
import {
  LOW_CONFIDENCE,
  WAYBILL_FIELDS,
  type WaybillFieldKey,
} from "@/lib/waybill-api";
import { BlockHead, SourceTag } from "./block-head";
import { IconCheck, IconDocument, IconWarn } from "./gate-icons";
import type { WaybillState } from "./use-intake";

export function waybillFieldId(key: WaybillFieldKey): string {
  return `wb-${key}`;
}

/** "DeepSeek-V4-Flash-Vision-Exp" stays; "Qwen3-VL-8B-Instruct" → "Qwen3-VL". */
function shortModel(model: string | null | undefined): string {
  if (!model) return "the vision model";
  return model.replace(/-\d+B(-A\d+B)?(-Instruct)?$/i, "");
}

export function WaybillBlock({
  waybill,
  editedFields,
  disabled,
  invalidField,
  onPhoto,
  onEdit,
}: {
  waybill: WaybillState;
  editedFields: WaybillFieldKey[];
  disabled: boolean;
  /** The field an inspect attempt found empty. */
  invalidField: WaybillFieldKey | null;
  onPhoto: (file: File | null) => void;
  onEdit: (key: WaybillFieldKey, value: string) => void;
}) {
  const { status, read, confidence, values } = waybill;
  const reading = status === "reading";
  const readCount = read ? WAYBILL_FIELDS.filter((f) => (confidence[f.key] ?? 0) > 0).length : 0;
  const unsure = read
    ? WAYBILL_FIELDS.filter((f) => values[f.key] && (confidence[f.key] ?? 0) < LOW_CONFIDENCE).length
    : 0;

  return (
    <section aria-labelledby="waybill-title" className="@container flex min-w-0 flex-col gap-3 p-4">
      <BlockHead id="waybill-title" icon={<IconDocument />} title="Waybill">
        <ReadStatus waybill={waybill} />
      </BlockHead>

      <div className="flex min-w-0 flex-col gap-3 @[460px]:flex-row">
        {/* Photo: click to add or replace. */}
        <div className="flex shrink-0 flex-row items-start gap-3 @[460px]:w-[104px] @[460px]:flex-col">
          <input
            id="waybill-photo"
            type="file"
            accept="image/jpeg,image/png"
            className="peer sr-only"
            disabled={disabled || reading}
            aria-label={waybill.photo ? "Replace the waybill photo" : "Add the waybill photo"}
            onChange={(e) => {
              onPhoto(e.target.files?.[0] ?? null);
              e.target.value = "";
            }}
          />
          <label
            htmlFor="waybill-photo"
            className={cn(
              "group relative block w-[104px] cursor-pointer overflow-hidden rounded-[8px] border transition-colors duration-150",
              "peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-amber",
              waybill.photo ? "border-seam hover:border-amber-line" : "border-dashed border-seam-strong hover:border-amber-line",
              (disabled || reading) && "pointer-events-none",
            )}
          >
            {waybill.photo ? (
              <img
                src={waybill.photo.previewUrl}
                alt="Waybill photo"
                className={cn("aspect-[3/4] w-full object-cover", reading && "opacity-70")}
              />
            ) : (
              <span className="flex aspect-[3/4] w-full flex-col items-center justify-center gap-1.5 bg-raised/40 px-2 text-center text-muted transition-colors duration-150 group-hover:text-ink">
                <IconDocument size={20} />
                <span className="text-[11.5px] leading-tight font-semibold">Add waybill photo</span>
              </span>
            )}
          </label>
          <p className="m-0 text-[11.5px] leading-snug text-faint @[460px]:w-[104px]">
            {status === "empty"
              ? "The AI reads plate, supplier, weights and moisture."
              : read
                ? `${readCount} of ${WAYBILL_FIELDS.length} fields read${unsure ? ` · ${unsure} unsure` : ""}${
                    editedFields.length ? ` · ${editedFields.length} edited` : ""
                  }`
                : null}
          </p>
        </div>

        {/* Fields */}
        <div className="flex min-w-0 flex-1 flex-col gap-2.5">
          {waybill.message ? (
            <p
              role="note"
              className="m-0 rounded-[6px] border border-amber-line bg-amber-dim px-2.5 py-1.5 text-[12.5px] leading-snug text-ink"
            >
              {waybill.message}
            </p>
          ) : null}
          <dl className="m-0 grid grid-cols-1 gap-x-3 gap-y-2 @[300px]:grid-cols-2">
            {WAYBILL_FIELDS.map((f, i) => (
              <Field
                key={f.key}
                fieldKey={f.key}
                label={f.label}
                numeric={f.kind === "number"}
                value={values[f.key]}
                confidence={status === "read" ? confidence[f.key] ?? 0 : null}
                edited={editedFields.includes(f.key)}
                pending={reading || (status === "read" && i >= waybill.revealed)}
                invalid={invalidField === f.key}
                disabled={disabled}
                wide={f.key === "remarks"}
                onChange={(v) => onEdit(f.key, v)}
              />
            ))}
          </dl>
        </div>
      </div>
    </section>
  );
}

function ReadStatus({ waybill }: { waybill: WaybillState }) {
  const seconds = useElapsedSeconds(waybill.status === "reading");
  if (waybill.status === "reading") {
    return (
      <span className="figure inline-flex items-center gap-1.5 text-[11.5px] text-amber" role="status">
        <span aria-hidden="true" className="h-1.5 w-1.5 animate-[gate-pulse_1.1s_ease-in-out_infinite] rounded-full bg-amber" />
        Reading with AI vision · {seconds} s
      </span>
    );
  }
  if (waybill.status === "read" && waybill.read) {
    const r = waybill.read;
    const stub = r.provenance === "stub";
    return (
      <span
        className="figure inline-flex flex-wrap items-center gap-x-1.5 text-[11.5px] text-muted"
        title={[r.model, r.provider ? providerName(r.provider) : null].filter(Boolean).join(" · ")}
      >
        {stub ? (
          <SourceTag title="The live reader was unavailable; the offline reader returned the bundled sample's fields.">
            Offline reader
          </SourceTag>
        ) : null}
        <span>
          {stub ? "Sample fields" : `Read by ${shortModel(r.model)}`}
          {!stub && r.provider ? ` on ${providerName(r.provider)}` : ""}
          {formatSeconds(r.latency_ms) ? ` · ${formatSeconds(r.latency_ms)}` : ""}
        </span>
      </span>
    );
  }
  if (waybill.status === "typed") return <SourceTag>Typed by operator</SourceTag>;
  if (waybill.status === "offline") return <SourceTag>Reader offline · typed</SourceTag>;
  return null;
}

function Field({
  fieldKey,
  label,
  numeric,
  value,
  confidence,
  edited,
  pending,
  invalid,
  disabled,
  wide,
  onChange,
}: {
  fieldKey: WaybillFieldKey;
  label: string;
  numeric: boolean;
  value: string;
  /** Read confidence; null when the field was typed, not read. */
  confidence: number | null;
  edited: boolean;
  /** Still filling in after the read (or reading). */
  pending: boolean;
  invalid: boolean;
  disabled: boolean;
  wide: boolean;
  onChange: (value: string) => void;
}) {
  const id = waybillFieldId(fieldKey);
  const low = confidence !== null && value !== "" && confidence < LOW_CONFIDENCE;
  const missing = confidence !== null && value === "";
  const noteId = `${id}-conf`;

  return (
    <div className={cn("flex min-w-0 flex-col gap-1", wide && "@[300px]:col-span-2")}>
      <dt className="flex items-center justify-between gap-2">
        <label htmlFor={id} className="text-[11px] font-semibold tracking-[0.6px] text-muted uppercase">
          {label}
        </label>
        {!pending ? (
          <span id={noteId} className="figure inline-flex items-center gap-1 text-[10.5px]">
            {edited ? (
              <span className="text-ink">edited</span>
            ) : missing ? (
              <span className="text-amber">not found</span>
            ) : confidence !== null ? (
              <span className={cn("inline-flex items-center gap-0.5", low ? "text-amber" : "text-faint")}>
                {low ? <IconWarn size={11} /> : <IconCheck size={11} />}
                {confidence.toFixed(2)}
                <span className="sr-only">{low ? " read confidence, check this field" : " read confidence"}</span>
              </span>
            ) : null}
          </span>
        ) : null}
      </dt>
      <dd className="m-0">
        {pending ? (
          <span
            aria-hidden="true"
            className="block h-[31px] animate-[gate-pulse_1.1s_ease-in-out_infinite] rounded-[6px] border border-seam bg-raised"
          />
        ) : (
          <input
            id={id}
            value={value}
            title={value || undefined}
            onChange={(e) => onChange(e.target.value)}
            disabled={disabled}
            inputMode={numeric ? "decimal" : undefined}
            autoComplete="off"
            spellCheck={false}
            aria-invalid={invalid || undefined}
            aria-describedby={confidence !== null || edited ? noteId : undefined}
            className={cn(
              "input py-1.5 text-[13px] disabled:cursor-not-allowed disabled:opacity-60",
              numeric && "figure",
              (low || missing) && !edited && "border-amber-line bg-amber-dim",
              edited && "border-ink/40",
              invalid && "border-verdict-red",
            )}
          />
        )}
      </dd>
    </div>
  );
}
