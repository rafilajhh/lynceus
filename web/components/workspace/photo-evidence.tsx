/**
 * PhotoEvidence: the load photo with the contaminant regions the vision
 * model reported, outlined in place. Hard contaminants (they damage the
 * shredder or kiln) are outlined in danger red with a light tint,
 * everything else in warning orange; each region carries its label tag
 * in its top-left corner. `annotated={false}` shows the original photo
 * (no overlay).
 *
 * Boxes are normalised 0..1 from the top-left corner, so the overlay sits
 * on a wrapper that shrink-wraps the image at its natural aspect ratio
 * (no object-cover crop, which would shift every box).
 *
 * Honesty: the caption always says how the regions were produced:
 * a 3×3 zone marking (coarse), a model's own boxes, or a scripted sample.
 *
 * The CPU detector's second opinion (YOLO26) is drawn alongside in a
 * distinct style: dashed outline, "YOLO" tag under the box. Only the boxes
 * the gate acts on are drawn: metal at/above the hard threshold, glass and
 * organic at/above the light one (the record's ``thresholds``, else 0.25);
 * feedstock detections (paper, plastic, textile) never flag a load.
 */

import type { DetectorBox, DetectorOutput, EvidenceBox } from "@/lib/api";
import { cn } from "@/lib/utils";

/** Detector classes the gate acts on (backend detector.HARD/LIGHT_LABELS). */
const DETECTOR_HARD_LABELS = new Set(["metal"]);
const DETECTOR_LIGHT_LABELS = new Set(["glass", "organic"]);
/** Records written before the backend sent ``thresholds`` were all judged at
    0.25 (the first model's defaults); newer records carry their own. */
const DEFAULT_DETECTOR_CONF = 0.25;

/** A detector box the gate would act on: a hard class at/above the hard
    threshold, a light class at/above the light one; feedstock never. */
function detectorFlags(box: DetectorBox, detector: DetectorOutput): boolean {
  const t = detector.thresholds;
  if (DETECTOR_HARD_LABELS.has(box.label)) {
    return box.confidence >= (t?.hard ?? DEFAULT_DETECTOR_CONF);
  }
  if (DETECTOR_LIGHT_LABELS.has(box.label)) {
    return box.confidence >= (t?.light ?? DEFAULT_DETECTOR_CONF);
  }
  return false;
}

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
  return `Boxes located by ${model || "the vision model"}`;
}

/** "yolo26m-realwaste-taco" → "YOLO26m" (older records: "YOLO26s"); unknown ids are shown as sent. */
export function detectorName(model: string | null | undefined): string {
  if (!model) return "the detector";
  const size = /^yolo26([nsmlx])/i.exec(model);
  return size ? `YOLO26${size[1].toLowerCase()}` : model;
}

export function PhotoEvidence({
  src,
  alt,
  boxes,
  localisation,
  model,
  detector = null,
  sourceNote = null,
  pending = false,
  annotated = true,
  className,
}: {
  /** Photo URL (public sample asset or data: URL); null = no photo on file. */
  src: string | null;
  /** What the photo shows, for the accessible name. */
  alt: string;
  boxes: EvidenceBox[];
  localisation: "box" | "zone" | null | undefined;
  /** Vision model id, named when it drew the boxes itself. */
  model?: string | null;
  /** CPU detector second opinion; null = it did not run (nothing drawn). */
  detector?: DetectorOutput | null;
  /** Where non-live regions came from ("Scripted sample", "Scripted
      fallback"), prefixed to the caption; null makes no provenance claim. */
  sourceNote?: string | null;
  /** Inspection still running: show the photo, hold the regions back. */
  pending?: boolean;
  /** false = the original photo, regions not drawn (caption unchanged). */
  annotated?: boolean;
  className?: string;
}) {
  const shown = pending ? [] : boxes;
  const detectorShown =
    pending || !detector
      ? []
      : detector.boxes.filter((b) => detectorFlags(b, detector));
  const drawn = annotated ? shown : [];
  const detectorDrawn = annotated ? detectorShown : [];
  const yolo = detectorName(detector?.model);
  const items = [
    ...shown.map(
      (b) => `${b.label}${isHardContaminant(b.label) ? " (hard contaminant)" : ""}`,
    ),
    ...detectorShown.map(
      (b) => `${yolo} detector: ${b.label} ${b.confidence.toFixed(2)}`,
    ),
  ];
  const ariaLabel =
    `${alt}. ` +
    (pending
      ? "Inspection in progress."
      : items.length > 0
        ? `${items.length} marked region${items.length === 1 ? "" : "s"}${
            annotated ? "" : " (not drawn in this view)"
          }: ${items.join(", ")}.`
        : "No contaminant regions marked.");
  const vlmCaption = captionFor({ pending, boxes: shown, localisation, model });
  // Both models named: the VLM's regions are solid, the detector's dashed.
  const caption =
    pending || !detector
      ? vlmCaption
      : `${vlmCaption}${shown.length > 0 ? " (solid)" : ""} · ` +
        (detectorShown.length > 0
          ? `${yolo} on CPU (dashed): ${detectorShown.length} region${detectorShown.length === 1 ? "" : "s"}`
          : `${yolo} on CPU: no metal, glass or organic boxes`);
  const hasHard =
    shown.some((b) => isHardContaminant(b.label)) ||
    detectorShown.some((b) => isHardContaminant(b.label));
  const hasLight =
    shown.some((b) => !isHardContaminant(b.label)) ||
    detectorShown.some((b) => !isHardContaminant(b.label));

  return (
    <figure className={cn("m-0 flex flex-col gap-3.5", className)}>
      <div className="flex justify-center overflow-hidden rounded-[10px] bg-surface-subtle">
        {src ? (
          <div role="img" aria-label={ariaLabel} className="relative inline-block max-w-full">
            {/* eslint-disable-next-line @next/next/no-img-element -- local sample asset or data: URL; static export has no image optimizer */}
            <img
              src={src}
              alt=""
              className={cn(
                "block h-auto max-h-[520px] w-auto max-w-full transition-opacity duration-200",
                pending && "opacity-60",
              )}
            />
            {!pending && annotated && localisation === "zone" && shown.length > 0
              ? ZONE_GUIDES.map((at) => (
                  <span key={at} aria-hidden="true">
                    <span
                      className="absolute inset-y-0 border-l border-dashed border-fg/25"
                      style={{ left: at }}
                    />
                    <span
                      className="absolute inset-x-0 border-t border-dashed border-fg/25"
                      style={{ top: at }}
                    />
                  </span>
                ))
              : null}
            {drawn.map((b, i) => {
              const hard = isHardContaminant(b.label);
              // Tag sits inside the box's top corner; right-anchored when
              // the box hugs the right edge.
              const tagRight = b.x0 > 0.7;
              return (
                <span
                  key={`${b.label}-${i}`}
                  aria-hidden="true"
                  className={cn(
                    "absolute rounded-[6px] border-solid",
                    hard ? "border-[2.5px] border-danger bg-danger/8" : "border-2 border-warning",
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
                      "absolute top-1 rounded-[4px] px-1.5 py-0.5 font-mono text-[11px] font-medium tracking-[0.4px] whitespace-nowrap text-white uppercase",
                      hard ? "bg-danger" : "bg-warning",
                      tagRight ? "right-1" : "left-1",
                    )}
                  >
                    {b.label}
                  </span>
                </span>
              );
            })}
            {detectorDrawn.map((d, i) => {
              const [x0, y0, x1, y1] = d.box;
              const hard = isHardContaminant(d.label);
              // The YOLO tag hangs under the box (VLM tags sit inside its
              // top), inside it when the box reaches the bottom edge.
              const tagInside = y1 > 0.92;
              const tagRight = x0 > 0.7;
              return (
                <span
                  key={`yolo-${d.label}-${i}`}
                  aria-hidden="true"
                  className={cn(
                    "absolute rounded-[6px] border-2 border-dashed",
                    hard ? "border-danger" : "border-warning",
                  )}
                  style={{
                    left: `${x0 * 100}%`,
                    top: `${y0 * 100}%`,
                    width: `${(x1 - x0) * 100}%`,
                    height: `${(y1 - y0) * 100}%`,
                  }}
                >
                  <span
                    className={cn(
                      "absolute rounded-[4px] border bg-surface/90 px-1 py-px font-mono text-[10px] font-medium tracking-[0.4px] whitespace-nowrap uppercase",
                      hard ? "border-danger text-danger" : "border-warning text-warning",
                      tagInside ? "bottom-0" : "top-full mt-0.5",
                      tagRight ? "right-0" : "left-0",
                    )}
                  >
                    {`YOLO ${d.label} ${d.confidence.toFixed(2)}`}
                  </span>
                </span>
              );
            })}
          </div>
        ) : (
          <p className="m-0 flex min-h-[120px] w-full items-center justify-center px-4 py-6 text-center text-[13px] text-fg-muted">
            {items.length > 0
              ? `No load photo on file. Recorded regions: ${items.join(", ")}.`
              : "No load photo on file for this inspection."}
          </p>
        )}
      </div>

      <figcaption className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1.5 text-[12px] text-fg-muted">
        {hasHard || hasLight || detectorShown.length > 0 ? (
          <span className="flex flex-wrap items-center gap-x-4 gap-y-1">
            {hasHard ? (
              <span className="inline-flex items-center gap-1.5">
                <span aria-hidden="true" className="h-2.5 w-2.5 rounded-[2px] bg-danger" />
                Hard contaminant
              </span>
            ) : null}
            {hasLight ? (
              <span className="inline-flex items-center gap-1.5">
                <span aria-hidden="true" className="h-2.5 w-2.5 rounded-[2px] bg-warning" />
                Other contaminant
              </span>
            ) : null}
            {detectorShown.length > 0 ? (
              <span className="inline-flex items-center gap-1.5">
                <span
                  aria-hidden="true"
                  className="h-2.5 w-2.5 rounded-[2px] border-2 border-dashed border-fg-muted"
                />
                {`${yolo} detector`}
              </span>
            ) : null}
          </span>
        ) : null}
        <span className="text-fg-subtle">
          {sourceNote && !pending ? `${sourceNote} · ${caption}` : caption}
        </span>
      </figcaption>
    </figure>
  );
}
