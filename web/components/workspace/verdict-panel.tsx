"use client";

/**
 * VerdictPanel: verdict banner (lights only after all five gates
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
import { ImpactCounter } from "./impact-counter";
import { AuditModal } from "./audit-modal";
import { NextSteps } from "./next-steps";
import { PhotoEvidence } from "./photo-evidence";
import type { InspectResponse } from "@/lib/inspect-api";
import { LIVE_LATENCY_COPY, formatSeconds, providerName } from "@/lib/format";
import { useElapsedSeconds } from "@/lib/use-elapsed";
import { cn } from "@/lib/utils";

/** How the operator asked for this inspection to run. Only "live" (the
    Run live on AMD action) may say a live model is working; whether one
    actually ran is stated afterwards by the photo-evidence source note. */
export type RunMode = "scripted" | "live" | "other";

/** Why the inspection request failed (see InspectError in lib/inspect-api). */
export interface ResultError {
  /** "network": backend never reached; "http": backend answered with an error. */
  kind: "network" | "http";
  message: string;
}

const EVALUATING_COPY: Record<RunMode, string> = {
  scripted: "Running the scripted sample through the decision engine.",
  live:
    `Live run requested on AMD: a full inspection takes ${LIVE_LATENCY_COPY} ` +
    "(measured on the Validation page). The photo evidence states what actually ran.",
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
  preventedLossIdr,
  impactRunKey,
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
  preventedLossIdr: number;
  /** Increment per verdict; 0 = idle. */
  impactRunKey: number;
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
  /** Optional extra below the impact counter (impact note). */
  children?: ReactNode;
}) {
  const tone = verdictTone(decision);
  const style = VERDICT_STYLE[tone];
  const reasons = collectReasons(data);
  const caveats = dedupeCaveats(collectCaveats(data));
  const vlm = data?.ai_outputs.vlm ?? null;
  // Evidence and steps arrive with the verdict word, never before it.
  const verdictShown = phase === "resolved" && data !== null && bannerLit;

  return (
    <Panel className="flex flex-col">
      <PanelHead
        title="Inspection verdict"
        meta={data?.record_id ? `record: ${data.record_id}` : "gate A"}
      />

      <div className="flex flex-col gap-4 px-4 py-4">
        {/* Verdict banner: lights only after the five gates resolve.
            The reset control lives inside this row: after resolve it is
            the second-most-important action (critique P1 — it was buried
            mid-panel in the quietest variant). */}
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
          {/* 10px radius: matches --radius-card for the banner container.
              4px tracking: industrial register for the verdict label (small-caps companion). */}
          <span className="text-[20px] font-bold tracking-[4px]">
            {bannerLit ? style.label : "— — —"}
          </span>
          {phase === "resolved" && onReset ? (
            <Button type="button" size="sm" onClick={onReset} className="shrink-0 text-[13px]">
              Next truck
            </Button>
          ) : null}
        </div>

        {/* Headline: directive sentence sits just under the verdict word
            (critique: 15px was too quiet for the rushed operator) */}
        <p className="m-0 text-[17px] font-semibold leading-snug text-ink">
          {phase === "resolved" && data
            ? headlineFor(decision, data)
            : phase === "evaluating"
              ? "Evaluating interlock…"
              : "Upload a load photo, fill the register, then press Inspect Load."}
        </p>

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

        {/* The interlock gate strip: the decision theater comes before the
            money figure (critique: impact counter outranked the verdict
            evidence at decision time) */}
        <GateStrip
          gates={gates}
          phase={phase}
          onAllResolved={onAllResolved}
        />

        {/* Evidence + what to do now: the photo the verdict is about with
            the contaminants outlined, beside the SOP-cited steps. Shown
            from submit so the long live wait has the photo on stage. */}
        {phase !== "idle" ? (
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <PhotoEvidence
              src={evidence.src}
              alt={evidence.alt}
              boxes={vlm?.boxes ?? []}
              localisation={vlm?.localisation}
              model={vlm?.model}
              sourceNote={
                data?.provenance === "stub"
                  ? "Scripted sample"
                  : data?.provenance === "stub_fallback_live_error"
                    ? "Scripted fallback"
                    : null
              }
              pending={!verdictShown}
            />
            {verdictShown ? (
              <NextSteps steps={data.actions} emptyText="The backend returned no next steps." />
            ) : (
              <div className="flex flex-col gap-2">
                <h3 className="smallcaps m-0">Next steps</h3>
                <p className="m-0 rounded-[10px] border border-dashed border-seam-strong px-3.5 py-3 text-[13px] text-muted">
                  Steps appear with the verdict, each citing its SOP clause.
                </p>
              </div>
            )}
          </div>
        ) : null}

        {/* Impact counter: demoted below the gates; hidden while idle so
            the empty stage shows one placeholder, not three */}
        {phase !== "idle" ? (
          <ImpactCounter
            preventedLossIdr={preventedLossIdr}
            runKey={bannerLit ? impactRunKey : 0}
            label={tone === "accept" ? "RDF value admitted" : "Worst-case loss exposure"}
          />
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
