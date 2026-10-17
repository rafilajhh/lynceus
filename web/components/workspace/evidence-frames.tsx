"use client";

/**
 * EvidenceFrames: the photos this verdict is about, with the regions each
 * model marked. One frame shows directly; two or three get tabs (arrow keys
 * move between them), each tab showing only that frame's boxes.
 */

import { useId, useRef, useState, type KeyboardEvent } from "react";
import type { InspectResponse } from "@/lib/inspect-api";
import { cn } from "@/lib/utils";
import { PhotoEvidence } from "./photo-evidence";

export function EvidenceFrames({
  frames,
  data,
  sourceNote,
}: {
  frames: { src: string; filename: string }[];
  data: InspectResponse;
  sourceNote: string | null;
}) {
  const [active, setActive] = useState(0);
  const base = useId();
  const tabs = useRef<(HTMLButtonElement | null)[]>([]);
  const vlm = data.ai_outputs.vlm;
  const detector = data.ai_outputs.detector;
  const multi = frames.length > 1;
  const onFrame = (f: number | null | undefined) => (f ?? 0) === active;
  const frame = frames[active] ?? frames[0];

  const onKey = (e: KeyboardEvent<HTMLButtonElement>) => {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    e.preventDefault();
    const next = (active + (e.key === "ArrowRight" ? 1 : frames.length - 1)) % frames.length;
    setActive(next);
    tabs.current[next]?.focus();
  };

  const evidence = (
    <PhotoEvidence
      src={frame?.src ?? null}
      alt={frame ? `Load photo ${frame.filename}` : "Load photo"}
      boxes={(vlm?.boxes ?? []).filter((b) => !multi || onFrame(b.frame))}
      localisation={vlm?.localisation}
      model={vlm?.model}
      detector={
        detector && multi ? { ...detector, boxes: detector.boxes.filter((b) => onFrame(b.frame)) } : detector
      }
      sourceNote={sourceNote}
    />
  );

  return (
    <section aria-label="Photo evidence" className="flex min-w-0 flex-col gap-2">
      <div className="flex items-center justify-between gap-3">
        <h3 className="smallcaps m-0">Evidence</h3>
        {multi ? (
          <div role="tablist" aria-label="Camera angles" className="flex gap-1">
            {frames.map((f, i) => (
              <button
                key={f.src}
                ref={(el) => {
                  tabs.current[i] = el;
                }}
                id={`${base}-tab-${i}`}
                type="button"
                role="tab"
                aria-selected={i === active}
                aria-controls={`${base}-panel`}
                tabIndex={i === active ? 0 : -1}
                onClick={() => setActive(i)}
                onKeyDown={onKey}
                className={cn(
                  "figure cursor-pointer rounded-[6px] border px-2.5 py-1 text-[11.5px] font-semibold transition-colors duration-100",
                  i === active
                    ? "border-amber bg-amber-soft text-ink"
                    : "border-seam text-muted hover:border-seam-strong hover:text-ink",
                )}
              >
                {i === 0 ? "Main" : `Angle ${i + 1}`}
              </button>
            ))}
          </div>
        ) : null}
      </div>
      {multi ? (
        <div id={`${base}-panel`} role="tabpanel" aria-labelledby={`${base}-tab-${active}`}>
          {evidence}
        </div>
      ) : (
        evidence
      )}
    </section>
  );
}
