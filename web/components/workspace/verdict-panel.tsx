"use client";

/**
 * VerdictPanel: verdict banner (lights only after all six gates
 * resolve) with its headline, a one-line live-AI provenance note, gate strip, photo
 * evidence beside the SOP-cited next steps, impact counter, reasons,
 * caveats, Pythia, and the audit-record link.
 * States: idle placeholder | evaluating | resolved | error.
 */

import type { ReactNode } from "react";
import { Panel, PanelHead } from "@/components/ui/panel";
import { Button } from "@/components/ui/button";
import { PythiaPanel, pythiaSuggestions } from "@/components/assist/pythia-panel";
import { GateStrip, type GateDisplay, type GatePhase } from "./gate-strip";

import { AuditModal } from "./audit-modal";
import { NextSteps } from "./next-steps";
import { PhotoEvidence, detectorName } from "./photo-evidence";
import type { InspectResponse } from "@/lib/inspect-api";
import {
  LIVE_LATENCY_COPY,
  formatMilliseconds,
  formatSeconds,
  providerName,
} from "@/lib/format";
import { useElapsedSeconds } from "@/lib/use-elapsed";
import { cn } from "@/lib/utils";

/** How the operator asked for this inspection to run. Only "live" (the
    Run live on AMD Token Factory action) may say a live model is working;
    whether one actually ran is stated afterwards by the photo-evidence
    source note. */
export type RunMode = "scripted" | "live" | "other";

/** Why the inspection request failed (see InspectError in lib/inspect-api). */
export interface ResultError {
  /** "network": backend never reached; "http": backend answered with an error. */
  kind: "network" | "http";
  message: string;
}

const EVALUATING_COPY: Record<RunMode, string> = {
  scripted: "Running the scripted sample through the decision engine.",
  live: `Inspecting on AMD Token Factory — ${LIVE_LATENCY_COPY}.`,
  other: "Running the inspection…",
};

/** Honest wait copy plus a real elapsed clock (no fake progress bar). */
function EvaluatingNote({ runMode }: { runMode: RunMode }) {
  const seconds = useElapsedSeconds(true);
  return (
    <p className="m-0 flex flex-wrap items-baseline gap-x-3 gap-y-1 text-[13px] text-muted">
      <span>{EVALUATING_COPY[runMode]}</span>
      <span className="figure text-[12px] text-faint" aria-hidden="true">
        {seconds} s elapsed
      </span>
    </p>
  );
}

type VerdictTone = "accept" | "escalate" | "reject" | "refuse" | "unknown";

const VERDICT_STYLE: Record<VerdictTone, { label: string; cls: string }> = {
  accept: {
    label: "ACCEPT",
    cls: "bg-green-dim border-verdict-green text-verdict-green",
  },
  escalate: {
    label: "ESCALATE",
    cls: "bg-amber-dim border-amber text-amber",
  },
  reject: {
    label: "REJECT",
    cls: "bg-red-dim border-verdict-red text-verdict-red",
  },
  refuse: {
    label: "REFUSED",
    cls: "bg-amber-dim border-amber text-amber",
  },
  unknown: {
    label: "UNKNOWN",
    cls: "bg-raised border-seam-strong text-muted",
  },
};

export function verdictTone(decision: string | undefined): VerdictTone {
  const d = String(decision || "").toLowerCase();
  if (d.startsWith("accept")) return "accept";
  if (d.startsWith("reject")) return "reject";
  if (d.startsWith("escalate")) return "escalate";
  if (d.startsWith("refuse")) return "refuse";
  return "unknown";
}

function headlineFor(
  decision: string | undefined,
  data: InspectResponse | null,
): string {
  const tone = verdictTone(decision);
  if (tone === "reject") return "Load rejected: do not admit to RDF processing.";
  if (tone === "escalate") return "Human review required before unloading.";
  if (tone === "refuse") return "Insufficient input: inspection cannot proceed.";
  const engine =
    data?.engine_outputs?.recommendation?.headline || data?.headline || "";
  return engine || "Inspection completed.";
}

/** Design-review finding 5: the REFUSED verdict needs explaining. */
const REFUSE_EXPLANATION =
  "REFUSED means the gate did not receive enough usable input to inspect " +
  "this load honestly: no photo (or demo-case photo) and/or no waybill " +
  "text. Rather than guessing, the engine declines to issue a verdict: " +
  "the truck is held at the gate until the missing input is supplied and " +
  "the inspection is re-run. No impact figure is invented for a refusal.";

/** "Second opinion (YOLO26m, CPU, 640 ms): flagged metal, not confirmed by
    the vision model; held for a manual check." (the hold clause only on an
    escalate verdict). Null when the backend sent neither a detector block
    nor its gate (an older backend). */
function secondOpinionLine(
  data: InspectResponse | null,
  gates: GateDisplay[],
): string | null {
  const detector = data?.ai_outputs.detector ?? null;
  const gate = gates.find((g) => g.key === "detector_second_opinion");
  if (!detector) {
    return data?.gates && "detector_second_opinion" in data.gates
      ? "Second opinion (CPU detector): did not run for this photo."
      : null;
  }
  const head = [detectorName(detector.model), "CPU", formatMilliseconds(detector.latency_ms)]
    .filter(Boolean)
    .join(", ");
  const findings = [...detector.hard_contaminants, ...detector.light_contaminants]
    .map((name) => name.replaceAll("_", " "));
  const found = findings.length > 0 ? `flagged ${findings.join(", ")}` : "no metal, glass or organic found";
  // The hold wording only when the verdict really is a hold: a REJECT or a
  // REFUSE decided on other grounds outranks the detector's finding.
  const decision = data?.verdict?.decision ?? data?.decision;
  const held = decision === "escalate_human";
  let verdict = "";
  if (data?.provenance === "detector_only_degraded") {
    const down =
      data.failed_stage === "llm"
        ? "; the waybill model was unavailable, so the vision answer was discarded"
        : "; the vision model was unavailable";
    verdict = held ? `${down} and the truck is held for a human` : down;
  } else if (gate?.state === "failed") {
    verdict = held
      ? ", not confirmed by the vision model; held for a manual check"
      : decision === "reject"
        ? ", not confirmed by the vision model; the load is rejected on other grounds"
        : ", not confirmed by the vision model";
  } else if (gate?.state === "passed" && findings.length > 0) {
    // Passed = the vision model agreed, or light findings are set not to
    // escalate (the gate reason says which); either way no verdict change.
    verdict = "; it did not change the verdict";
  }
  return `Second opinion (${head}): ${found}${verdict}.`;
}

/** Reasons from every place the backend may put them. */
function collectReasons(data: InspectResponse | null): string[] {
  if (!data) return [];
  const out: string[] = [];
  const llmReasoning = data.ai_outputs?.llm?.reasoning;
  if (typeof llmReasoning === "string" && llmReasoning) out.push(llmReasoning);
  const engineReasons = data.engine_outputs?.recommendation?.reasons;
  if (Array.isArray(engineReasons)) out.push(...engineReasons);
  if (Array.isArray(data.reasons)) out.push(...data.reasons);
  return out;
}

function collectCaveats(data: InspectResponse | null): string[] {
  if (!data) return [];
  const out: string[] = [];
  const engineCaveats = data.engine_outputs?.recommendation?.caveats;
  if (Array.isArray(engineCaveats)) out.push(...engineCaveats);
  if (Array.isArray(data.caveats)) out.push(...data.caveats);
  const uncertainty = data.verdict?.uncertainty;
  if (typeof uncertainty === "string" && uncertainty) out.push(uncertainty);
  return out;
}

/** Engine field names → operator language (critique P2: snake_case must
    not leak into caveats on the most-read surface). */
const FIELD_LABELS: Record<string, string> = {
  ncv_mj_per_kg: "heating value",
  ash_fraction: "ash content",
  chlorine_fraction: "chlorine content",
  mixed_msw: "mixed municipal waste",
};

function humanizeCaveat(caveat: string): string {
  let out = caveat;
  for (const [field, label] of Object.entries(FIELD_LABELS)) {
    out = out.replaceAll(field, label);
  }
  out = out.replaceAll("mixed-msw", "mixed municipal waste");
  return out;
}

/** Near-duplicate detector: caveats arrive from two sources (engine +
    fusion) that state the same fact twice with different wording
    (follow-up: fuel-grade lab analysis appeared twice). Two caveats are
    duplicates when they share a long content token (≥7 chars) — short
    generic words ("fuel", "needs") are too common to dedupe on. */
const STOP_TOKENS = new Set([
  "require", "requires", "analysis", "laboratory", "established", "needs",
]);

function tokensOf(caveat: string): string[] {
  return caveat
    .toLowerCase()
    .replace(/[^a-z0-9 ]/g, " ")
    .split(/\s+/)
    .filter((w) => w.length >= 7 && !STOP_TOKENS.has(w));
}

function dedupeCaveats(caveats: string[]): string[] {
  const claimed = new Set<string>();
  const out: string[] = [];
  for (const c of caveats) {
    const toks = tokensOf(c);
    if (toks.length > 0 && toks.some((t) => claimed.has(t))) continue;
    toks.forEach((t) => claimed.add(t));
    out.push(c);
  }
  return out;
}

export function VerdictPanel({
  phase,
  gates,
  data,
  decision,
  bannerLit,
  onAllResolved,
  onReset,
  error,
  evidence,
  runMode,
  children,
}: {
  phase: GatePhase;
  gates: GateDisplay[];
  data: InspectResponse | null;
  decision: string | undefined;
  /** Verdict banner may only light after all gates resolve. */
  bannerLit: boolean;
  onAllResolved: () => void;
  /** Reset the stage for the next truck (gate flow is truck-by-truck). */
  onReset?: () => void;
  error: ResultError | null;
  /** The photo submitted with this inspection (snapshot at submit). */
  evidence: { src: string | null; alt: string };
  /** How this inspection was submitted (drives the wait copy only). */
  runMode: RunMode;
  /** Optional extra below the next steps (impact note). */
  children?: ReactNode;
}) {
  const tone = verdictTone(decision);
  const style = VERDICT_STYLE[tone];
  const reasons = collectReasons(data);
  const caveats = dedupeCaveats(collectCaveats(data));
  const vlm = data?.ai_outputs.vlm ?? null;
  const secondOpinion = secondOpinionLine(data, gates);
  const degraded = data?.provenance === "detector_only_degraded";
  // Evidence and steps arrive with the verdict word, never before it.
  const verdictShown = phase === "resolved" && data !== null && bannerLit;

  return (
    <Panel className="flex flex-col">
      <PanelHead
        title="Inspection verdict"
        meta={data?.record_id ? `record: ${data.record_id}` : "gate A"}
      />

      <div className="flex flex-col gap-4 px-4 py-4">
        {/* Verdict banner: only rendered once evaluating/resolved. Idle
            is handled by the parent (quiet directive line). */}
        {phase !== "idle" ? (
          <div
            role="status"
            aria-live="polite"
            className={cn(
              "flex items-center justify-between gap-3 rounded-[10px] border px-4 py-3 transition-opacity duration-200",
              bannerLit
                ? cn(style.cls, "opacity-100")
                : "border-seam bg-raised text-faint opacity-70",
            )}
          >
            <span className="text-[20px] font-bold tracking-[4px]">
              {bannerLit ? style.label : "— — —"}
            </span>
            {phase === "resolved" && onReset ? (
              <Button type="button" size="sm" onClick={onReset} className="shrink-0 text-[13px]">
                Next truck
              </Button>
            ) : null}
          </div>
        ) : null}

        {/* Headline: directive sentence sits just under the verdict word */}
        {phase !== "idle" ? (
          <p className="m-0 text-[17px] font-semibold leading-snug text-ink">
            {phase === "resolved" && data
              ? headlineFor(decision, data)
              : "Evaluating interlock…"}
          </p>
        ) : null}

        {phase === "evaluating" ? <EvaluatingNote runMode={runMode} /> : null}

        {/* One quiet line of what ran: live results only. */}
        {phase === "resolved" && data?.provenance === "live" && vlm?.model ? (
          <p className="figure m-0 text-[12px] text-faint">
            {[
              vlm.model.replace(/-\d+B(-A\d+B)?$/, ""),
              vlm.provider ? `on ${providerName(vlm.provider)}` : null,
              formatSeconds(vlm.latency_ms),
            ]
              .filter(Boolean)
              .join(" · ")}
          </p>
        ) : null}

        {/* Live AI failed and the backend fell back to the scripted
            sample: say so plainly, next to the verdict it affects. */}
        {phase === "resolved" && data?.provenance === "stub_fallback_live_error" ? (
          <p
            role="note"
            className="m-0 rounded-[10px] border border-amber-line bg-amber-dim px-4 py-2.5 text-[13px] leading-snug text-ink"
          >
            <span className="font-semibold text-amber">
              Live AI failed — scripted fallback shown.
            </span>{" "}
            This verdict uses the scripted sample, not a live reading of this
            photo; re-run the inspection once the live endpoint responds.
          </p>
        ) : null}

        {/* A live model down, detector answered: degraded, not dark. A
            refusal is about a missing input, not the detector's findings. */}
        {phase === "resolved" && degraded ? (
          <p
            role="note"
            className="m-0 rounded-[10px] border border-amber-line bg-amber-dim px-4 py-2.5 text-[13px] leading-snug text-ink"
          >
            {decision === "refuse_insufficient_input" ? (
              <>
                <span className="font-semibold text-amber">
                  Live AI unavailable — inspection refused: a mandatory input is missing.
                </span>{" "}
                Supply the missing input (the reasons below name it) and re-run
                once the live endpoint responds.
              </>
            ) : (
              <>
                <span className="font-semibold text-amber">
                  {data?.failed_stage === "llm"
                    ? "Waybill model unavailable — detector-only verdict."
                    : "Vision model unavailable — detector-only verdict."}
                </span>{" "}
                {data?.failed_stage === "llm"
                  ? "The live waybill model did not answer, so the vision answer was discarded unfused and"
                  : "The live vision model did not answer, so"}{" "}
                this truck is held for a human on the CPU detector alone (the
                reasons below say why). Detector-only mode never accepts or
                rejects a load; re-run once the live endpoint responds.
              </>
            )}
          </p>
        ) : null}

        {/* One line for the CPU detector's second opinion. */}
        {phase === "resolved" && secondOpinion ? (
          <p className="figure m-0 text-[12px] text-faint">{secondOpinion}</p>
        ) : null}

        {/* The interlock gate strip: only while evaluating or resolved.
            Idle shows nothing — the parent handles the quiet directive. */}
        {phase !== "idle" ? (
          <GateStrip
            gates={gates}
            phase={phase}
            onAllResolved={onAllResolved}
          />
        ) : null}

        {/* Evidence + what to do now: shown from submit so the long
            live wait has the photo on stage. */}
        {phase === "evaluating" || phase === "resolved" ? (
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <PhotoEvidence
              src={evidence.src}
              alt={evidence.alt}
              boxes={vlm?.boxes ?? []}
              localisation={vlm?.localisation}
              model={vlm?.model}
              detector={data?.ai_outputs.detector}
              sourceNote={
                data?.provenance === "stub"
                  ? "Scripted sample"
                  : data?.provenance === "stub_fallback_live_error"
                    ? "Scripted fallback"
                    : degraded
                      ? data?.failed_stage === "llm"
                        ? "Vision answer discarded"
                        : "Vision model unavailable"
                      : null
              }
              pending={!verdictShown}
            />
            {verdictShown ? (
              <NextSteps steps={data.actions} emptyText="The backend returned no next steps." />
            ) : null}
          </div>
        ) : null}

        {children}

        {/* REFUSED: explain what refuse_insufficient_input means
            (review finding 5: unexplained term) */}
        {phase === "resolved" && tone === "refuse" ? (
          <div className="rounded-[10px] border border-amber/50 bg-amber-dim px-4 py-3">
            <h3 className="smallcaps mt-0 mb-1.5">Why REFUSED?</h3>
            <p className="m-0 text-[13px] leading-relaxed text-muted">
              {REFUSE_EXPLANATION}
            </p>
          </div>
        ) : null}

        {/* Error state: inline red panel with recovery */}
        {error ? (
          <div
            role="alert"
            className="rounded-[10px] border border-verdict-red/60 bg-red-dim px-4 py-3"
          >
            <p className="m-0 text-[13.5px] font-semibold text-verdict-red">
              {error.kind === "network"
                ? "Backend unreachable: is the server running?"
                : "Inspection could not run"}
            </p>
            <p className="figure m-0 mt-1 text-[13px] leading-relaxed break-words text-muted">
              {error.message}
            </p>
            <p className="m-0 mt-1.5 text-[12px] text-muted">
              {error.kind === "network"
                ? "Start the FastAPI backend (it serves this app as static files), then press Inspect Load again."
                : "Fix the input above if needed, then press Inspect Load again."}
            </p>
          </div>
        ) : null}

        {/* Reasons: dot leaders */}
        {phase === "resolved" && data ? (
          <div>
            <h3 className="smallcaps mb-2 mt-0">Reasons</h3>
            <ul className="m-0 flex list-none flex-col gap-1.5 p-0">
              {reasons.length === 0 ? (
                <li className="text-[13px] text-muted">
                  No reasoning returned by the backend.
                </li>
              ) : (
                reasons.map((r, i) => (
                  <li
                    key={i}
                    className="flex items-baseline gap-2 text-[13px] leading-snug text-muted"
                  >
                    <span
                      aria-hidden="true"
                      className="mt-[6px] h-[5px] w-[5px] shrink-0 rounded-full bg-amber"
                    />
                    <span>{String(r)}</span>
                  </li>
                ))
              )}
            </ul>
          </div>
        ) : null}

        {/* Caveats */}
        {phase === "resolved" && data && caveats.length > 0 ? (
          <div>
            <h3 className="smallcaps mb-2 mt-0">Caveats</h3>
            <ul className="m-0 flex list-none flex-col gap-1.5 p-0">
              {caveats.map((c, i) => (
                <li
                  key={i}
                  className="text-[13px] leading-snug text-muted"
                >
                  {humanizeCaveat(String(c))}
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        {/* Pythia: questions about this truck, answered from the plant
            documents and this record (keyed so a new truck starts clean) */}
        {verdictShown ? (
          <PythiaPanel
            key={data.record_id ?? "no-record"}
            recordId={data.record_id}
            suggestions={pythiaSuggestions(decision)}
          />
        ) : null}

        {/* Audit record link */}
        {phase === "resolved" && data?.record_id ? (
          <AuditModal recordId={data.record_id} data={data} />
        ) : null}
      </div>
    </Panel>
  );
}
