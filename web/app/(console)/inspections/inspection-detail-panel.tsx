"use client";

import { useEffect, useRef, useState } from "react";
import {
  ApiError,
  fetchInspectionDetail,
  type GateState,
  type InspectionDetail,
  type PhotoInput,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import { formatMilliseconds, formatWeight } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Panel, PanelHead } from "@/components/ui/panel";
import { PythiaPanel, pythiaSuggestions } from "@/components/assist/pythia-panel";
import { NextSteps } from "@/components/workspace/next-steps";
import { PhotoEvidence } from "@/components/workspace/photo-evidence";

/**
 * Inline detail panel (not a modal): opens beneath the ledger when a row is
 * selected. Fetches GET /inspections/{record_id}, shows digest, gates,
 * inputs, photo evidence, next steps, AI provenance, reasoning and Pythia,
 * and offers the raw audit record as a JSON download.
 */

const GATE_STATE_CLASS: Record<GateState, string> = {
  passed: "border-[rgba(46,204,113,0.45)] text-verdict-green",
  failed: "border-[rgba(231,76,60,0.45)] text-verdict-red",
  not_run: "border-seam-strong text-muted",
  not_evaluated: "border-seam-strong text-muted",
};

const GATE_STATE_LABEL: Record<GateState, string> = {
  passed: "PASSED",
  failed: "FAILED",
  not_run: "NOT RUN",
  not_evaluated: "NOT EVALUATED",
};

const GATE_LABEL: Record<string, string> = {
  vlm_confidence: "VLM Confidence",
  ocr_confidence: "Manifest confidence",
  weight_plausibility: "Weight Plausibility",
  gas_plausibility: "Gas Plausibility",
  manifest_crosscheck: "Manifest Cross-check",
  detector_second_opinion: "Detector second opinion",
};

/**
 * Record uncertainty carries raw pipeline diagnostics ("AI provenance: …,
 * Live AI failed (ReadTimeout: …)"). Only a live failure is worth surfacing;
 * for live verdicts the boilerplate screening disclaimer adds nothing.
 */
function uncertaintyNote(uncertainty: string): string | null {
  const match = /Live AI failed \(([^)]*)\)/i.exec(uncertainty);
  if (!match) return null;
  const detail = match[1].replace(/^[A-Za-z]+Error:\s*/i, "");
  return `Live AI failed (${detail}) — scripted fallback used.`;
}

/** Demo photos are public assets: a record whose photo came from one can
    show it again. A record with a stored evidence path serves it from the
    authenticated API; anything else has no photo to show. */
const DEMO_PHOTO_PATH = /^\/demo\/[a-z0-9-]+\.(jpe?g|png)$/i;

function photoSrc(
  photo: PhotoInput | undefined,
  recordId: string | undefined,
): string | null {
  if (!photo) return null;
  if (photo.path && recordId) {
    return `/inspections/${encodeURIComponent(recordId)}/evidence/photo`;
  }
  return DEMO_PHOTO_PATH.test(photo.filename) ? photo.filename : null;
}

/** "Scripted sample" / "Scripted fallback" for stub output, else null. The
    record's verdict.uncertainty states a live failure ("Live AI failed"). */
function scriptedNote(model: string | null | undefined, uncertainty: string | undefined) {
  if (!(model ?? "").startsWith("stub")) return null;
  return (uncertainty ?? "").includes("Live AI failed") ? "Scripted fallback" : "Scripted sample";
}

type DetailLoad =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ready"; detail: InspectionDetail };

export function InspectionDetailPanel({
  recordId,
  onClose,
  className,
}: {
  recordId: string;
  onClose: () => void;
  className?: string;
}) {
  const [state, setState] = useState<DetailLoad>({ kind: "loading" });
  const [retryCount, setRetryCount] = useState(0);
  const panelRef = useRef<HTMLElement>(null);

  /* P1b: Move focus into panel on open; P0b: scroll into view (nearest), honoring reduced motion */
  useEffect(() => {
    const el = panelRef.current;
    if (!el) return;
    const prefersReducedMotion =
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    el.scrollIntoView({
      block: "nearest",
      behavior: prefersReducedMotion ? "auto" : "smooth",
    });
    el.focus({ preventScroll: true });
  }, [recordId]);

  /* P0a: Re-fetch when recordId or retryCount changes */
  useEffect(() => {
    let cancelled = false;
    setState({ kind: "loading" });
    fetchInspectionDetail(recordId)
      .then((detail) => {
        if (!cancelled) setState({ kind: "ready", detail });
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        const message =
          err instanceof ApiError || err instanceof Error
            ? err.message
            : "Unexpected error.";
        setState({ kind: "error", message });
      });
    return () => {
      cancelled = true;
    };
  }, [recordId, retryCount]);

  return (
    <Panel ref={panelRef} tabIndex={-1} className={cn("focus:outline-none", className)}>
      <PanelHead
        title={`Record · ${recordId}`}
        meta={
          state.kind === "ready" && state.detail.digest?.record_sha256
            ? `sha256 ${shortHash(state.detail.digest.record_sha256)}`
            : "audit record"
        }
      >
        <button
          type="button"
          onClick={onClose}
          aria-label="Close detail panel"
          className="cursor-pointer rounded-[6px] border border-seam px-2.5 py-1 text-[12px] text-muted normal-case tracking-normal transition-colors duration-100 hover:border-seam-strong hover:text-ink"
        >
          ✕
        </button>
      </PanelHead>
      <div className="px-4 py-4">

        {state.kind === "loading" ? (
          <div
            role="status"
            className="flex flex-col items-center gap-3 py-10 text-center"
          >
            <span
              aria-hidden="true"
              className="h-6 w-6 animate-spin rounded-full border-2 border-seam border-t-amber"
            />
            <span className="sr-only">Loading</span>
            <p className="text-[13px] text-muted">
              Fetching audit record {recordId}…
            </p>
          </div>
        ) : state.kind === "error" ? (
          <div role="alert" className="flex flex-col items-center gap-3 py-10 text-center">
            <p className="max-w-[52ch] text-[13.5px] text-verdict-red">
              Could not load {recordId}. {state.message}
            </p>
            <Button
              size="sm"
              onClick={() => setRetryCount((c) => c + 1)}
            >
              Retry
            </Button>
          </div>
        ) : (
          <DetailBody detail={state.detail} />
        )}
      </div>
    </Panel>
  );
}

function DetailBody({ detail }: { detail: InspectionDetail }) {
  const decision = detail.verdict?.decision ?? "unknown";
  const reasoning = detail.ai_outputs?.llm?.reasoning;
  const reasoningText = reasoning
    ? reasoning.replace(/\s*AI provenance:[^]*$/i, "").trim()
    : undefined;
  const uncertainty = detail.verdict?.uncertainty;
  const failureNote = uncertainty ? uncertaintyNote(uncertainty) : null;
  const reasons = detail.reasons ?? [];
  const gasReadings = detail.inputs?.gas?.readings_ppm;
  const gasInstrument = detail.ai_outputs?.gas?.instrument;
  const gasModelBasis = detail.ai_outputs?.gas?.model_basis;
  const gasSource = detail.inputs?.gas?.source;
  const photo = detail.inputs?.photo;
  const supplier = detail.inputs?.supplier;
  const vlm = detail.ai_outputs?.vlm;
  const detector = detail.ai_outputs?.detector;
  const steps = detail.engine_outputs?.recommendation?.actions ?? [];

  return (
    <div className="flex flex-col gap-5">
      {/* ---- gates grid ---- */}
      {detail.gates ? (
        <section aria-label="Gates">
          <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-2">
            {Object.entries(detail.gates).map(([name, gate]) => {
              const measured =
                gate.value !== null
                  ? `value ${typeof gate.value === "number" ? gate.value.toFixed(3) : gate.value}${gate.threshold !== null ? ` · threshold ${gate.threshold}` : ""}`
                  : null;
              const tip = [measured, gate.reason].filter(Boolean).join(" — ");
              return (
                <div
                  key={name}
                  title={tip || undefined}
                  className={`flex min-w-0 flex-col justify-center rounded-[6px] border bg-raised px-3 py-2.5 ${GATE_STATE_CLASS[gate.state]}`}
                >
                  <div className="text-[12px] font-bold tracking-[0.6px] uppercase break-words">
                    {GATE_LABEL[name] ?? name}
                  </div>
                  <div className="mt-1 text-[12.5px] font-bold">
                    {GATE_STATE_LABEL[gate.state]}
                  </div>
                </div>
              );
            })}
          </div>
        </section>
      ) : null}

      {/* ---- inputs ---- */}
      <section>
        <h3 className="smallcaps mb-2">Inputs</h3>
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="rounded-[8px] border border-seam bg-ground px-3 py-2.5">
            <div className="smallcaps mb-1">Truck</div>
            <div className="figure text-[13px] text-ink">
              {detail.inputs?.truck_id ?? "—"}
            </div>
            {supplier ? (
              <div className="mt-0.5 text-[12px] text-muted">{supplier}</div>
            ) : null}
          </div>

          <div className="rounded-[8px] border border-seam bg-ground px-3 py-2.5">
            <div className="smallcaps mb-1">Weight</div>
            <div className="figure text-[13px] text-ink">
              {formatWeight(detail.inputs?.weight?.value_kg ?? 0)}
            </div>
          </div>

          <div
            className="rounded-[8px] border border-seam bg-ground px-3 py-2.5 sm:col-span-2"
            title={[
              gasInstrument?.model
                ? `Instrument: ${gasInstrument.model}${gasInstrument.technology ? ` (${gasInstrument.technology})` : ""}`
                : null,
              gasModelBasis ? `Model basis: ${gasModelBasis}` : null,
            ]
              .filter(Boolean)
              .join(" · ") || undefined}
          >
            <div className="smallcaps mb-1">Gas readings</div>
            {gasReadings && Object.keys(gasReadings).length > 0 ? (
              <ul className="figure m-0 list-none p-0 text-[12px] text-ink">
                {Object.entries(gasReadings).map(([gas, ppm]) => (
                  <li
                    key={gas}
                    className="flex justify-between gap-3 leading-relaxed"
                  >
                    <span className="text-muted">{gas}</span>
                    <span>{ppm} ppm</span>
                  </li>
                ))}
              </ul>
            ) : (
              <div className="text-[12.5px] text-muted">
                {gasSource ?? "not measured"}
              </div>
            )}
          </div>
        </div>
      </section>

      {/* ---- evidence, reasoning, next steps — one reading column ---- */}
      <section>
        <h3 className="smallcaps mb-2">Evidence</h3>
        <PhotoEvidence
          src={photoSrc(photo, detail.record_id)}
          alt={`Load photo for ${detail.record_id}`}
          boxes={vlm?.boxes ?? []}
          localisation={vlm?.localisation}
          model={vlm?.model}
          detector={detector}
          sourceNote={scriptedNote(vlm?.model, uncertainty)}
        />
        {detector ? (
          <p className="figure mt-1.5 mb-0 text-[12px] text-muted">
            Detector ·{" "}
            {[detector.model, detector.runtime, formatMilliseconds(detector.latency_ms)]
              .filter(Boolean)
              .join(" · ")}
          </p>
        ) : null}
      </section>

      {reasoningText || reasons.length > 0 || failureNote ? (
        <section>
          <h3 className="smallcaps mb-2">Reasoning</h3>
          <div className="rounded-[8px] border border-seam bg-ground px-3.5 py-3 text-[13.5px] leading-relaxed text-muted">
            {reasoningText ? <p className="m-0">{reasoningText}</p> : null}
            {reasons.length > 0 ? (
              <ul className="mt-2 mb-0 list-disc space-y-1 pl-5">
                {reasons.map((reason) => (
                  <li key={reason}>{reason}</li>
                ))}
              </ul>
            ) : null}
            {failureNote ? (
              <p className="mt-2 mb-0 text-[12px] text-verdict-amber">
                {failureNote}
              </p>
            ) : null}
          </div>
        </section>
      ) : null}

      <NextSteps
        steps={steps}
        emptyText="Not recorded: this record predates SOP-cited next steps."
      />

      {detail.record_id ? (
        <PythiaPanel
          key={detail.record_id}
          recordId={detail.record_id}
          suggestions={pythiaSuggestions(decision)}
        />
      ) : null}

      {/* ---- actions ---- */}
      <div className="flex flex-wrap gap-2.5">
        <Button variant="default" size="sm" onClick={() => downloadJSON(detail)}>
          Download {detail.record_id}.json
        </Button>
      </div>
    </div>
  );
}

/** 8 + 8 chars around an ellipsis; the full digest stays in the JSON download. */
function shortHash(sha: string): string {
  const clean = sha.replace(/^sha256:/, "");
  return clean.length > 19 ? `${clean.slice(0, 8)}…${clean.slice(-8)}` : clean;
}

/** Blob-download the audit record exactly as the API returned it. */
function downloadJSON(detail: InspectionDetail) {
  const blob = new Blob([JSON.stringify(detail, null, 2)], {
    type: "application/json",
  });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `${detail.record_id}.json`;
  anchor.click();
  URL.revokeObjectURL(url);
}
