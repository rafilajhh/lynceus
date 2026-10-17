"use client";

/**
 * LoadPhotos: the main load photo plus up to two more camera angles. Each
 * photo is its own upload target (click or keyboard); every frame is
 * inspected, and the verdict shows them as tabs.
 */

/* eslint-disable @next/next/no-img-element -- object URLs; static export has no image optimizer */

import { cn } from "@/lib/utils";
import { BlockHead } from "./block-head";
import { IconCamera, IconPlus } from "./gate-icons";
import type { PhotoSlot } from "./use-intake";

const ACCEPT = "image/jpeg,image/png";

export function LoadPhotos({
  photos,
  disabled,
  invalid,
  onPick,
}: {
  photos: (PhotoSlot | null)[];
  disabled: boolean;
  /** The inspect attempt failed for want of a photo. */
  invalid: boolean;
  onPick: (index: number, file: File | null) => void;
}) {
  const main = photos[0];
  const filled = photos.filter(Boolean).length;
  // Angle slots open one at a time, after the main photo.
  const angleSlots = main ? [1, 2].filter((i) => i <= filled) : [];

  return (
    <section aria-labelledby="load-photos-title" className="flex min-w-0 flex-col gap-3 p-4">
      <BlockHead id="load-photos-title" icon={<IconCamera />} title="Load photos">
        <span className="figure text-[11.5px] text-faint">
          {filled > 0 ? `${filled} of 3 angles` : "up to 3 angles"}
        </span>
      </BlockHead>

      <PhotoTarget
        id="load-photo-0"
        slot={main}
        disabled={disabled}
        invalid={invalid}
        onPick={(f) => onPick(0, f)}
        large
      />

      {angleSlots.length > 0 ? (
        <div className="grid grid-cols-2 gap-2">
          {angleSlots.map((i) => (
            <PhotoTarget
              key={i}
              id={`load-photo-${i}`}
              slot={photos[i]}
              disabled={disabled}
              invalid={false}
              onPick={(f) => onPick(i, f)}
            />
          ))}
        </div>
      ) : null}

      {main ? (
        <p className="figure m-0 truncate text-[11px] text-muted" title={main.filename}>
          {photos
            .filter((p): p is PhotoSlot => p !== null)
            .map((p) => p.filename)
            .join(" · ")}
        </p>
      ) : null}
    </section>
  );
}

function PhotoTarget({
  id,
  slot,
  disabled,
  invalid,
  onPick,
  large = false,
}: {
  id: string;
  slot: PhotoSlot | null;
  disabled: boolean;
  invalid: boolean;
  onPick: (file: File | null) => void;
  large?: boolean;
}) {
  return (
    <div className="group/slot relative">
      <input
        id={id}
        type="file"
        accept={ACCEPT}
        className="peer sr-only"
        disabled={disabled}
        aria-invalid={invalid || undefined}
        aria-label={slot ? `Replace photo ${slot.filename}` : large ? "Add the load photo" : "Add another camera angle"}
        onChange={(e) => {
          onPick(e.target.files?.[0] ?? null);
          e.target.value = "";
        }}
      />
      <label
        htmlFor={id}
        className={cn(
          "relative block cursor-pointer overflow-hidden border transition-colors duration-150",
          large ? "rounded-[12px]" : "rounded-[8px]",
          "peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-amber",
          slot ? "border-seam hover:border-amber-line" : "border-dashed border-seam-strong hover:border-amber-line",
          invalid && "border-verdict-red",
          disabled && "pointer-events-none opacity-60",
        )}
      >
        {slot ? (
          <>
            <img
              src={slot.previewUrl}
              alt=""
              className="aspect-[4/3] w-full object-cover transition-opacity duration-150 group-hover/slot:opacity-70"
            />
            <span
              aria-hidden="true"
              className="absolute inset-x-0 bottom-0 bg-[rgba(10,12,16,0.72)] px-2.5 py-1 text-[11.5px] font-semibold text-ink opacity-0 transition-opacity duration-150 group-hover/slot:opacity-100"
            >
              Replace
            </span>
          </>
        ) : (
          <span
            className={cn(
              "flex aspect-[4/3] w-full flex-col items-center justify-center gap-1.5 bg-raised/40 text-muted transition-colors duration-150 group-hover/slot:text-ink",
            )}
          >
            {large ? <IconCamera size={22} /> : <IconPlus size={16} />}
            <span className={cn("font-semibold", large ? "text-[13px]" : "text-[11.5px]")}>
              {large ? "Add the load photo" : "Add an angle"}
            </span>
            {large ? (
              <span className="text-[12px] text-faint">JPEG or PNG from the gate camera</span>
            ) : null}
          </span>
        )}
      </label>
      {slot && !large ? (
        <button
          type="button"
          onClick={() => onPick(null)}
          disabled={disabled}
          aria-label={`Remove angle ${slot.filename}`}
          className="absolute top-1 right-1 cursor-pointer rounded-[4px] bg-[rgba(10,12,16,0.78)] px-1.5 py-0.5 text-[11px] font-semibold text-muted transition-colors duration-100 hover:text-ink disabled:pointer-events-none"
        >
          Remove
        </button>
      ) : null}
    </div>
  );
}
