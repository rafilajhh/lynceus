/**
 * PhotoEvidence: the load photo with the contaminant regions the vision
 * model reported, outlined in place. Hard contaminants (they damage the
 * shredder or kiln) are outlined in verdict red, everything else in
 * amber; each region carries its label chip.
 *
 * Boxes are normalised 0..1 from the top-left corner, so the overlay sits
 * on a wrapper that shrink-wraps the image at its natural aspect ratio
 * (no object-cover crop, which would shift every box).
 *
 * Honesty: the caption always says how the regions were produced:
 * a 3×3 zone marking (coarse), a model's own boxes, or a scripted sample.
 */

import type { EvidenceBox } from "@/lib/api";
import { cn } from "@/lib/utils";

const HARD_CONTAMINANTS = new Set([
  "metal",
  "rock",
  "concrete",
  "tire",
  "tyre",
  "e-waste",
]);

function isHardContaminant(label: string): boolean {
  return HARD_CONTAMINANTS.has(label.trim().toLowerCase().replace(/[_\s]+/g, "-"));
}

/** Third-grid guides shown in zone mode: the marking is that coarse. */
const ZONE_GUIDES = ["33.333%", "66.667%"];

function captionFor({
  pending,
  boxes,
  localisation,
  model,
}: {
  pending: boolean;
  boxes: EvidenceBox[];
  localisation: "box" | "zone" | null | undefined;
  model: string | null | undefined;
}): string {
  if (pending) return "Photo under inspection · regions appear with the verdict";
  if (boxes.length === 0) {
    return localisation ? "No contaminant regions marked" : "No contaminant regions recorded";
  }
  if (localisation === "zone") return "Zone marking (3×3 grid)";
  return `Located by ${model || "the vision model"}`;
}

export function PhotoEvidence({
  src,
  alt,
  boxes,
  localisation,
  model,
  sourceNote = null,
  pending = false,
  className,
}: {
  /** Photo URL (public demo asset or data: URL); null = no photo on file. */
  src: string | null;
  /** What the photo shows, for the accessible name. */
  alt: string;
  boxes: EvidenceBox[];
  localisation: "box" | "zone" | null | undefined;
  /** Vision model id, named when it drew the boxes itself. */
  model?: string | null;
  /** Where non-live regions came from ("Scripted sample", "Scripted
      fallback"), prefixed to the caption; null makes no provenance claim. */
  sourceNote?: string | null;
  /** Inspection still running: show the photo, hold the regions back. */
  pending?: boolean;
  className?: string;
}) {
  const shown = pending ? [] : boxes;
  const items = shown.map(
    (b) => `${b.label}${isHardContaminant(b.label) ? " (hard contaminant)" : ""}`,
  );
  const ariaLabel =
    `${alt}. ` +
    (pending
      ? "Inspection in progress."
      : items.length > 0
        ? `${items.length} marked region${items.length === 1 ? "" : "s"}: ${items.join(", ")}.`
        : "No contaminant regions marked.");
  const caption = captionFor({ pending, boxes: shown, localisation, model });
  const hasHard = shown.some((b) => isHardContaminant(b.label));
  const hasLight = shown.some((b) => !isHardContaminant(b.label));

  return (
    <figure className={cn("m-0 flex flex-col gap-2", className)}>
      <div className="flex justify-center overflow-hidden rounded-[10px] border border-seam bg-ground">
        {src ? (
          <div role="img" aria-label={ariaLabel} className="relative inline-block max-w-full">
            {/* eslint-disable-next-line @next/next/no-img-element -- local demo asset or data: URL; static export has no image optimizer */}
            <img
              src={src}
              alt=""
              className={cn(
                "block h-auto max-h-[380px] w-auto max-w-full transition-opacity duration-200",
                pending && "opacity-60",
              )}
            />
            {!pending && localisation === "zone" && shown.length > 0
              ? ZONE_GUIDES.map((at) => (
                  <span key={at} aria-hidden="true">
                    <span
                      className="absolute inset-y-0 border-l border-dashed border-ink/25"
                      style={{ left: at }}
                    />
                    <span
                      className="absolute inset-x-0 border-t border-dashed border-ink/25"
                      style={{ top: at }}
                    />
                  </span>
                ))
              : null}
            {shown.map((b, i) => {
              const hard = isHardContaminant(b.label);
              // Chip sits above the box; inside it when the box touches the
              // top edge, right-anchored when the box hugs the right edge.
              const chipInside = b.y0 < 0.08;
              const chipRight = b.x0 > 0.7;
              return (
                <span
                  key={`${b.label}-${i}`}
                  aria-hidden="true"
                  className={cn(
                    "absolute rounded-[3px] border-2 outline outline-1 outline-[rgba(10,12,16,0.55)]",
                    hard ? "border-verdict-red" : "border-amber",
                  )}
                  style={{
                    left: `${b.x0 * 100}%`,
                    top: `${b.y0 * 100}%`,
                    width: `${(b.x1 - b.x0) * 100}%`,
                    height: `${(b.y1 - b.y0) * 100}%`,
                  }}
                >
                  <span
                    className={cn(
                      "figure absolute rounded-[3px] px-1.5 py-px text-[11px] font-semibold tracking-[0.4px] whitespace-nowrap text-ground uppercase",
                      hard ? "bg-verdict-red" : "bg-amber",
                      chipInside ? "top-0" : "bottom-full mb-0.5",
                      chipRight ? "right-0" : "left-0",
                    )}
                  >
                    {b.label}
                  </span>
                </span>
              );
            })}
          </div>
        ) : (
          <p className="m-0 flex min-h-[120px] w-full items-center justify-center px-4 py-6 text-center text-[13px] text-muted">
            {items.length > 0
              ? `No load photo on file. Recorded regions: ${items.join(", ")}.`
              : "No load photo on file for this inspection."}
          </p>
        )}
      </div>

      <figcaption className="figure flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] leading-relaxed text-muted">
        <span>{sourceNote && !pending ? `${sourceNote} · ${caption}` : caption}</span>
        {hasHard ? (
          <span className="inline-flex items-center gap-1.5">
            <span aria-hidden="true" className="h-2.5 w-2.5 rounded-[2px] border-2 border-verdict-red" />
            hard contaminant
          </span>
        ) : null}
        {hasLight ? (
          <span className="inline-flex items-center gap-1.5">
            <span aria-hidden="true" className="h-2.5 w-2.5 rounded-[2px] border-2 border-amber" />
            other contaminant
          </span>
        ) : null}
      </figcaption>
    </figure>
  );
}
