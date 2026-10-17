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
  return `Located by ${model || "the vision model"}`;
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
  /** CPU detector second opinion; null = it did not run (nothing drawn). */
  detector?: DetectorOutput | null;
  /** Where non-live regions came from ("Scripted sample", "Scripted
      fallback"), prefixed to the caption; null makes no provenance claim. */
  sourceNote?: string | null;
  /** Inspection still running: show the photo, hold the regions back. */
  pending?: boolean;
  className?: string;
}) {
  const shown = pending ? [] : boxes;
  const detectorShown =
    pending || !detector
      ? []
      : detector.boxes.filter((b) => detectorFlags(b, detector));
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
        ? `${items.length} marked region${items.length === 1 ? "" : "s"}: ${items.join(", ")}.`
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
            {detectorShown.map((d, i) => {
              const [x0, y0, x1, y1] = d.box;
              const hard = isHardContaminant(d.label);
              // The YOLO tag hangs under the box (VLM chips sit above), inside
              // it when the box reaches the bottom edge.
              const tagInside = y1 > 0.92;
              const tagRight = x0 > 0.7;
              return (
                <span
                  key={`yolo-${d.label}-${i}`}
                  aria-hidden="true"
                  className={cn(
                    "absolute rounded-[3px] border-2 border-dashed",
                    hard ? "border-verdict-red" : "border-amber",
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
                      "figure absolute rounded-[3px] border bg-ground/85 px-1 py-px text-[10px] font-semibold tracking-[0.4px] whitespace-nowrap uppercase",
                      hard
                        ? "border-verdict-red text-verdict-red"
                        : "border-amber text-amber",
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
        {detectorShown.length > 0 ? (
          <span className="inline-flex items-center gap-1.5">
            <span aria-hidden="true" className="h-2.5 w-2.5 rounded-[2px] border-2 border-dashed border-muted" />
            {`${yolo} detector`}
          </span>
        ) : null}
      </figcaption>
    </figure>
  );
}
