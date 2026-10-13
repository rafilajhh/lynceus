"use client";

import { useEffect, useRef, useState } from "react";
import {
  ApiError,
  fetchInspectionDetail,
  type GateState,
  type InspectionDetail,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import { formatRupiah, formatWeight, relativeTime } from "@/lib/format";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Panel, PanelHead } from "@/components/ui/panel";

/**
 * Inline detail panel (not a modal): opens beneath the ledger when a row is
 * selected. Fetches GET /inspections/{record_id}, shows digest, gates,
 * inputs, reasoning, and offers the raw audit record as a JSON download.
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
  ocr_confidence: "OCR Confidence",
  weight_plausibility: "Weight Plausibility",
  gas_plausibility: "Gas Plausibility",
  manifest_crosscheck: "Manifest Cross-check",
};

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
        meta={state.kind === "ready" ? "audit record" : "loading"}
      >
      </PanelHead>
      <div className="relative px-4 py-4">
        <button
          type="button"
          onClick={onClose}
          aria-label="Close detail panel"
          className="absolute top-3 right-4 cursor-pointer rounded-[6px] border border-seam px-2.5 py-1 text-[12px] text-muted transition-colors duration-100 hover:border-seam-strong hover:text-ink"
        >
          ✕
        </button>

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
  const sha = detail.digest?.record_sha256 ?? "—";
  const decision = detail.verdict?.decision ?? "unknown";
  const reasoning = detail.ai_outputs?.llm?.reasoning;
  const uncertainty = detail.verdict?.uncertainty;
  const reasons = detail.reasons ?? [];
  const gasReadings = detail.inputs?.gas?.readings_ppm;
  const photo = detail.inputs?.photo;

  return (
    <div className="flex flex-col gap-5">
      {/* ---- digest ---- */}
      <section>
        <h3 className="smallcaps mb-2">Record digest (SHA-256)</h3>
        <p className="figure rounded-[6px] border border-seam bg-ground px-3 py-2.5 text-[12px] break-all text-muted">
          {sha}
        </p>
      </section>

      {/* ---- gates grid ---- */}
      {detail.gates ? (
        <section>
          <h3 className="smallcaps mb-2">Gates</h3>
          <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 xl:grid-cols-5 gap-2">
            {Object.entries(detail.gates).map(([name, gate]) => (
              <div
                key={name}
                className={`min-w-0 rounded-[6px] border bg-raised px-3 py-2 ${GATE_STATE_CLASS[gate.state]}`}
              >
                <div className="text-[12px] font-bold tracking-[0.6px] uppercase break-words">
                  {GATE_LABEL[name] ?? name}
                </div>
                <div className="mt-0.5 text-[12.5px] font-bold">
                  {GATE_STATE_LABEL[gate.state]}
                </div>
                {gate.value !== null ? (
                  <div className="figure mt-0.5 text-[11px] text-muted break-words">
                    value {typeof gate.value === "number" ? gate.value.toFixed(3) : gate.value}
                    {gate.threshold !== null ? ` · threshold ${gate.threshold}` : ""}
                  </div>
                ) : null}
                {gate.reason ? (
                  <div className="mt-1 text-[13px] leading-snug text-muted break-words">
                    {gate.reason}
                  </div>
                ) : null}
              </div>
            ))}
          </div>
        </section>
      ) : null}

      {/* ---- inputs ---- */}
      <section>
        <h3 className="smallcaps mb-2">Inputs</h3>
        <div className="grid gap-3 [grid-template-columns:repeat(auto-fit,minmax(180px,1fr))]">
          <div className="rounded-[8px] border border-seam bg-ground px-3 py-2.5">
            <div className="smallcaps mb-1">Truck</div>
            <div className="figure text-[13px] text-ink">
              {detail.inputs?.truck_id ?? "—"}
            </div>
          </div>

          <div className="rounded-[8px] border border-seam bg-ground px-3 py-2.5">
            <div className="smallcaps mb-1">Weight</div>
            <div className="figure text-[13px] text-ink">
              {formatWeight(detail.inputs?.weight?.value_kg ?? 0)}
            </div>
            <div className="mt-0.5 text-[12px] text-muted">
              {detail.inputs?.weight?.source ?? "—"}
            </div>
          </div>

          <div className="rounded-[8px] border border-seam bg-ground px-3 py-2.5">
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
                {detail.inputs?.gas?.source ?? "not measured"}
              </div>
            )}
          </div>

          {/* photo thumbnail: only when the API exposes a relative path */}
          {photo?.path ? (
            <div className="rounded-[8px] border border-seam bg-ground px-3 py-2.5">
              <div className="smallcaps mb-1">Photo</div>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={photo.path}
                alt={`Load photo for ${detail.record_id}`}
                className="mt-1 block max-h-[170px] max-w-full rounded-[6px] border border-seam"
              />
              <div className="figure mt-1 text-[11px] break-all text-muted">
                {photo.sha256 ?? ""}
              </div>
            </div>
          ) : null}
        </div>
      </section>

      {/* ---- verdict ---- */}
      <section className="flex flex-wrap items-center gap-3">
        <Badge
          variant={
            decision === "escalate_human"
              ? "escalate"
              : decision === "refuse_insufficient_input"
                ? "refuse"
                : decision === "accept" || decision === "reject"
                  ? decision
                  : "default"
          }
          className="text-[12px]"
        >
          {detail.verdict?.decision?.replace(/_/g, " ") ?? "unknown"}
        </Badge>
        <span className="text-[12.5px] text-muted">
          decided {relativeTime(detail.verdict?.decided_at_utc ?? "")}
        </span>
        {detail.verdict?.classification ? (
          <span className="figure text-[12px] text-muted">
            {detail.verdict.classification}
          </span>
        ) : null}
      </section>

      {/* ---- reasoning ---- */}
      {reasoning || reasons.length > 0 || uncertainty ? (
        <section>
          <h3 className="smallcaps mb-2">Reasoning</h3>
          <div className="rounded-[8px] border border-seam bg-ground px-3.5 py-3 text-[13.5px] leading-relaxed text-muted">
            {reasoning ? <p className="m-0">{reasoning}</p> : null}
            {reasons.length > 0 ? (
              <ul className="mt-2 mb-0 list-disc space-y-1 pl-5">
                {reasons.map((reason) => (
                  <li key={reason}>{reason}</li>
                ))}
              </ul>
            ) : null}
            {uncertainty ? (
              <p className="mt-2 mb-0 text-[12px] text-verdict-amber">
                {uncertainty}
              </p>
            ) : null}
          </div>
        </section>
      ) : null}

      {/* ---- actions ---- */}
      <div className="flex flex-wrap gap-2.5">
        <Button variant="default" size="sm" onClick={() => downloadJSON(detail)}>
          Download JSON
        </Button>
        <span className="self-center text-[12px] text-muted">
          Tamper-evident audit record: saved as {detail.record_id}.json
        </span>
      </div>
    </div>
  );
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
