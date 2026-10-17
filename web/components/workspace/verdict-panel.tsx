"use client";

/**
 * VerdictPanel: the inspection result body (redesign frame HX9C5).
 *
 * Verdict banner card: verdict pill (lights only after all six gates
 * resolve), record id, headline, summary, live-AI provenance meta, the
 * submitted register, and the gate check row along its bottom edge.
 * Below, two columns: evidence photo with outlined contaminants + the
 * CPU detector's second opinion, "Why this verdict" (reasons / caveats)
 * on the left; SOP-cited next steps, the submitted load and Ask Pythia
 * on the right.
 * States: evaluating (pulsing gates, photo under inspection, real
 * elapsed clock) | resolved. Idle and request errors live in the parent.
 */

import { useState } from "react";
import {
  CircleCheck,
  CircleDot,
  CircleHelp,
  CircleMinus,
  CircleSlash,
  Cpu,
  FileText,
  GitCompare,
  Info,
  OctagonX,
  Pencil,
  Server,
  Timer,
  TriangleAlert,
  type LucideIcon,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { PythiaPanel, pythiaSuggestions } from "@/components/assist/pythia-panel";
import { GateStrip, type GateDisplay, type GatePhase } from "./gate-strip";
import { NextSteps } from "./next-steps";
import { FollowupActions } from "./followup-actions";
import { PhotoEvidence, detectorName } from "./photo-evidence";
import { Segmented } from "./segmented";
import type { InspectResponse } from "@/lib/inspect-api";
import {
  LIVE_LATENCY_COPY,
  formatMilliseconds,
  formatSeconds,
  providerName,
} from "@/lib/format";
import { useElapsedSeconds } from "@/lib/use-elapsed";
import { cn } from "@/lib/utils";

/** How the operator asked for this inspection to run. Only "live" may
    say a live model is working; whether one actually ran is stated
    afterwards by the provenance meta and the photo-evidence source note. */
export type RunMode = "scripted" | "live" | "other";

/** Why the inspection request failed (see InspectError in lib/inspect-api). */
export interface ResultError {
  /** "network": backend never reached; "http": backend answered with an error. */
  kind: "network" | "http";
  message: string;
}

/** The register and file names as submitted (snapshot at submit). */
export interface SubmittedLoad {
  truck_id: string;
  supplier: string;
  weight_kg: number;
  moisture_pct: number;
  age_h: number;
  loadFilename: string | null;
  waybillFilename: string | null;
  /** The register was auto-filled from the waybill photo (OCR). */
  waybillOcr: boolean;
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
    <p className="m-0 flex flex-wrap items-baseline gap-x-3 gap-y-1 text-[15px] text-fg-muted">
      <span>{EVALUATING_COPY[runMode]}</span>
      <span className="figure text-[12px] text-fg-subtle" aria-hidden="true">
        {seconds} s elapsed
      </span>
    </p>
  );
}

type VerdictTone = "accept" | "escalate" | "reject" | "refuse" | "unknown";

/** Banner + pill styling per verdict. Full class strings (Tailwind scans
    them literally). Refuse is neutral, matching the foundation Badge. */
const VERDICT_STYLE: Record<
  VerdictTone,
  { label: string; icon: LucideIcon; pill: string; banner: string; wash: string }
> = {
  accept: {
    label: "ACCEPT",
    icon: CircleCheck,
    pill: "bg-success text-white",
    banner: "border-success/25 shadow-[0_8px_24px_#00AB3814]",
    wash: "bg-[linear-gradient(-90deg,var(--color-success-tint)_0%,transparent_100%)]",
  },
  escalate: {
    label: "ESCALATE",
    icon: TriangleAlert,
    pill: "bg-warning text-white",
    banner: "border-warning/25 shadow-[0_8px_24px_#E5710014]",
    wash: "bg-[linear-gradient(-90deg,var(--color-warning-tint)_0%,transparent_100%)]",
  },
  reject: {
    label: "REJECT",
    icon: OctagonX,
    pill: "bg-danger text-white",
    banner: "border-danger/25 shadow-[0_8px_24px_#EA263014]",
    wash: "bg-[linear-gradient(-90deg,var(--color-danger-tint)_0%,transparent_100%)]",
  },
  refuse: {
    label: "REFUSED",
    icon: CircleSlash,
    pill: "bg-fg-muted text-white",
    banner: "border-line-strong shadow-card",
    wash: "bg-[linear-gradient(-90deg,var(--color-surface-subtle)_0%,transparent_100%)]",
  },
  unknown: {
    label: "UNKNOWN",
    icon: CircleHelp,
    pill: "bg-surface-subtle text-fg-muted",
    banner: "border-line-strong shadow-card",
    wash: "",
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
  "this load honestly: no photo and/or no waybill text. Rather than " +
  "guessing, the engine declines to issue a verdict: the truck is held at " +
  "the gate until the missing input is supplied and the inspection is " +
  "re-run. No impact figure is invented for a refusal.";

/** The CPU detector's second opinion as a title + one sentence:
    "Second opinion · YOLO26m on CPU (640 ms)" / "Flagged metal, not
    confirmed by the vision model; held for a manual check." (the hold
    clause only on an escalate verdict). Null when the backend sent
    neither a detector block nor its gate (an older backend). */
function secondOpinion(
  data: InspectResponse | null,
  gates: GateDisplay[],
): { title: string; body: string } | null {
  const detector = data?.ai_outputs.detector ?? null;
  const gate = gates.find((g) => g.key === "detector_second_opinion");
  if (!detector) {
    return data?.gates && "detector_second_opinion" in data.gates
      ? { title: "Second opinion · CPU detector", body: "Did not run for this photo." }
      : null;
  }
  const latency = formatMilliseconds(detector.latency_ms);
  const title = `Second opinion · ${detectorName(detector.model)} on CPU${latency ? ` (${latency})` : ""}`;
  const findings = [...detector.hard_contaminants, ...detector.light_contaminants]
    .map((name) => name.replaceAll("_", " "));
  const found =
    findings.length > 0 ? `Flagged ${findings.join(", ")}` : "No metal, glass or organic found";
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
  return { title, body: `${found}${verdict}.` };
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

/** One-line summary under the headline: the backend's first stated
    reason (the fused verdict's own, before the model's long reasoning). */
function summaryOf(data: InspectResponse | null): string | null {
  if (!data) return null;
  const first =
    (Array.isArray(data.reasons) && data.reasons[0]) ||
    data.engine_outputs?.recommendation?.reasons?.[0] ||
    null;
  return typeof first === "string" && first ? first : null;
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

const fmtNumber = (n: number) => new Intl.NumberFormat("en-US").format(n);

/** Amber note inside the banner: live AI fell back or degraded. */
function BannerNote({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <p
      role="note"
      className="m-0 w-full rounded-[10px] border border-warning/30 bg-warning-tint px-4 py-2.5 text-[13px] leading-snug text-fg"
    >
      <span className="font-medium text-warning">{title}</span> {children}
    </p>
  );
}

/** Card shell with the redesign's 16/20 head. */
function Card({
  title,
  sub,
  action,
  children,
  className,
}: {
  title: string;
  sub?: React.ReactNode;
  action?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section className={cn("card w-full", className)} aria-label={title}>
      <div className="flex items-center justify-between gap-3 border-b border-line px-5 py-4">
        <div className="flex min-w-0 flex-col gap-0.5">
          <h2 className="m-0 font-display text-[17px] font-medium text-fg">{title}</h2>
          {sub ? <p className="m-0 truncate text-[12px] text-fg-muted">{sub}</p> : null}
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}

export function VerdictPanel({
  phase,
  gates,
  data,
  decision,
  bannerLit,
  onAllResolved,
  onEdit,
  evidence,
  submitted,
  runMode,
}: {
  phase: GatePhase;
  gates: GateDisplay[];
  data: InspectResponse | null;
  decision: string | undefined;
  /** Verdict banner may only light after all gates resolve. */
  bannerLit: boolean;
  onAllResolved: () => void;
  /** Back to the intake with the register and photos kept. */
  onEdit?: () => void;
  /** The photo submitted with this inspection (snapshot at submit). */
  evidence: { src: string | null; alt: string };
  /** The register as submitted (snapshot at submit). */
  submitted: SubmittedLoad;
  /** How this inspection was submitted (drives the wait copy only). */
  runMode: RunMode;
}) {
  const [annotated, setAnnotated] = useState<"annotated" | "original">("annotated");
  const tone = verdictTone(decision);
  const style = VERDICT_STYLE[tone];
  const reasons = collectReasons(data);
  const caveats = dedupeCaveats(collectCaveats(data));
  const vlm = data?.ai_outputs.vlm ?? null;
  const second = secondOpinion(data, gates);
  const degraded = data?.provenance === "detector_only_degraded";
  const resolved = phase === "resolved" && data !== null;
  // Evidence and steps arrive with the verdict word, never before it.
  const verdictShown = resolved && bannerLit;
  const summary = summaryOf(data);
  const PillIcon = style.icon;

  const register: [string, string, boolean][] = [
    ["Truck", submitted.truck_id || "—", false],
    ["Supplier", submitted.supplier || "—", false],
    ["Weight", `${fmtNumber(submitted.weight_kg)} kg`, true],
    ["Moisture", `${fmtNumber(submitted.moisture_pct)} %`, true],
    ["Age", `${fmtNumber(submitted.age_h)} h`, true],
  ];

  return (
    <div className="flex flex-col gap-6">
      {/* ============ Verdict banner ============ */}
      <section
        aria-label="Inspection verdict"
        className={cn(
          "overflow-hidden rounded-[20px] border bg-surface transition-[border-color,box-shadow] duration-200",
          bannerLit ? style.banner : "border-line-strong shadow-card",
        )}
      >
        <div
          className={cn(
            "flex flex-col gap-6 p-5 md:p-7 lg:flex-row lg:items-center lg:gap-8",
            bannerLit && style.wash,
          )}
        >
          <div className="flex min-w-0 flex-1 flex-col items-start gap-3.5">
            <div role="status" aria-live="polite" className="flex flex-wrap items-center gap-3">
              <span
                className={cn(
                  "inline-flex items-center gap-2 rounded-full px-3.5 py-1.5 font-mono text-[14px] font-medium tracking-[1px] transition-colors duration-200",
                  bannerLit ? style.pill : "bg-surface-subtle text-fg-subtle",
                )}
              >
                {bannerLit ? <PillIcon aria-hidden="true" className="h-4 w-4" /> : null}
                {bannerLit ? style.label : "— — —"}
              </span>
              {data?.record_id ? (
                <span className="font-mono text-[12px] text-fg-muted">{`${data.record_id} · sealed`}</span>
              ) : null}
            </div>

            <h2 className="m-0 font-display text-[26px] leading-[1.15] font-medium tracking-[-0.5px] text-fg md:text-[32px] md:leading-[37px]">
              {resolved && bannerLit ? headlineFor(decision, data) : "Evaluating interlock…"}
            </h2>

            {phase === "evaluating" ? <EvaluatingNote runMode={runMode} /> : null}
            {verdictShown && summary ? (
              <p className="m-0 text-[15px] text-fg-muted">{summary}</p>
            ) : null}

            {/* What ran: live results only. */}
            {resolved && data.provenance === "live" && vlm?.model ? (
              <ul className="m-0 flex list-none flex-wrap items-center gap-x-4 gap-y-1.5 p-0 font-mono text-[12px] text-fg-muted">
                <li className="flex items-center gap-1.5">
                  <Cpu aria-hidden="true" className="h-3.5 w-3.5" />
                  {vlm.model.replace(/-\d+B(-A\d+B)?$/, "")}
                </li>
                {vlm.provider ? (
                  <li className="flex items-center gap-1.5">
                    <Server aria-hidden="true" className="h-3.5 w-3.5" />
                    {providerName(vlm.provider)}
                  </li>
                ) : null}
                {formatSeconds(vlm.latency_ms) ? (
                  <li className="flex items-center gap-1.5">
                    <Timer aria-hidden="true" className="h-3.5 w-3.5" />
                    {formatSeconds(vlm.latency_ms)}
                  </li>
                ) : null}
              </ul>
            ) : null}

            {/* Live AI failed and the backend fell back to the scripted
                sample: say so plainly, next to the verdict it affects. */}
            {resolved && data.provenance === "stub_fallback_live_error" ? (
              <BannerNote title="Live AI failed — scripted fallback shown.">
                This verdict uses the scripted sample, not a live reading of this
                photo; re-run the inspection once the live endpoint responds.
              </BannerNote>
            ) : null}

            {/* A live model down, detector answered: degraded, not dark. A
                refusal is about a missing input, not the detector's findings. */}
            {resolved && degraded ? (
              decision === "refuse_insufficient_input" ? (
                <BannerNote title="Live AI unavailable — inspection refused: a mandatory input is missing.">
                  Supply the missing input (the reasons below name it) and re-run
                  once the live endpoint responds.
                </BannerNote>
              ) : (
                <BannerNote
                  title={
                    data.failed_stage === "llm"
                      ? "Waybill model unavailable — detector-only verdict."
                      : "Vision model unavailable — detector-only verdict."
                  }
                >
                  {data.failed_stage === "llm"
                    ? "The live waybill model did not answer, so the vision answer was discarded unfused and"
                    : "The live vision model did not answer, so"}{" "}
                  this truck is held for a human on the CPU detector alone (the
                  reasons below say why). Detector-only mode never accepts or
                  rejects a load; re-run once the live endpoint responds.
                </BannerNote>
              )
            ) : null}
          </div>

          <dl className="m-0 w-full shrink-0 rounded-[14px] border border-line-strong bg-surface px-[18px] py-1.5 lg:w-[380px]">
            {register.map(([k, v, mono], i) => (
              <div
                key={k}
                className={cn(
                  "flex items-center justify-between gap-4 py-2.5 text-[13px]",
                  i < register.length - 1 && "border-b border-line",
                )}
              >
                <dt className="text-fg-muted">{k}</dt>
                <dd className={cn("m-0 truncate font-medium text-fg", mono && "font-mono")}>{v}</dd>
              </div>
            ))}
          </dl>
        </div>

        <GateStrip
          gates={gates}
          phase={phase}
          onAllResolved={onAllResolved}
          className="border-t border-line"
        />
      </section>

      {/* ============ Columns ============ */}
      <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-[minmax(0,1fr)_400px]">
        <div className="flex min-w-0 flex-col gap-4">
          <Card
            title="Evidence"
            sub={submitted.loadFilename ? `Uploaded photo · ${submitted.loadFilename}` : "Load photo"}
            action={
              <Segmented
                label="Evidence view"
                options={[
                  { value: "annotated", label: "Annotated" },
                  { value: "original", label: "Original" },
                ]}
                value={annotated}
                onSelect={setAnnotated}
                disabled={!verdictShown || !evidence.src}
                className="shrink-0"
              />
            }
          >
            <div className="flex flex-col gap-3.5 p-5">
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
                annotated={annotated === "annotated"}
              />
              {verdictShown && second ? (
                <div className="flex items-start gap-2.5 rounded-[10px] bg-surface-subtle px-3.5 py-3">
                  <GitCompare aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0 text-fg-muted" />
                  <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                    <p className="m-0 text-[13px] font-medium text-fg">{second.title}</p>
                    <p className="m-0 text-[12px] leading-[17px] text-fg-muted">{second.body}</p>
                  </div>
                </div>
              ) : null}
            </div>
          </Card>

          {verdictShown ? (
            <Card title="Why this verdict">
              {tone === "refuse" ? (
                <div className="border-b border-line px-5 py-4">
                  <h3 className="eyebrow mt-0 mb-1.5">Why refused?</h3>
                  <p className="m-0 text-[13px] leading-relaxed text-fg-muted">{REFUSE_EXPLANATION}</p>
                </div>
              ) : null}
              <div className={cn("grid grid-cols-1", caveats.length > 0 && "md:grid-cols-2")}>
                <div className="flex flex-col gap-3 p-5">
                  <h3 className="eyebrow m-0 tracking-[1px]">Reasons</h3>
                  <ul className="m-0 flex list-none flex-col gap-3 p-0">
                    {reasons.length === 0 ? (
                      <li className="text-[13px] text-fg-muted">No reasoning returned by the backend.</li>
                    ) : (
                      reasons.map((r, i) => (
                        <li key={i} className="flex items-start gap-2.5 text-[13px] leading-5 text-fg">
                          <CircleDot aria-hidden="true" className="mt-[3px] h-3.5 w-3.5 shrink-0 text-fg-subtle" />
                          <span className="min-w-0 flex-1">{String(r)}</span>
                        </li>
                      ))
                    )}
                  </ul>
                </div>
                {caveats.length > 0 ? (
                  <div className="flex flex-col gap-3 border-t border-line p-5 md:border-t-0 md:border-l">
                    <h3 className="eyebrow m-0 tracking-[1px]">Caveats</h3>
                    <ul className="m-0 flex list-none flex-col gap-3 p-0">
                      {caveats.map((c, i) => (
                        <li key={i} className="flex items-start gap-2.5 text-[13px] leading-5 text-fg">
                          <Info aria-hidden="true" className="mt-[3px] h-3.5 w-3.5 shrink-0 text-fg-subtle" />
                          <span className="min-w-0 flex-1">{humanizeCaveat(String(c))}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}
              </div>
            </Card>
          ) : null}
        </div>

        <div className="flex min-w-0 flex-col gap-4">
          {verdictShown ? (
            <NextSteps
              variant="card"
              steps={data.actions}
              emptyText="The backend returned no next steps."
            >
              {data.record_id ? (
                <FollowupActions key={data.record_id} recordId={data.record_id} />
              ) : null}
            </NextSteps>
          ) : null}

          <Card
            title="Submitted load"
            action={
              resolved && onEdit ? (
                <Button type="button" variant="ghost" size="sm" onClick={onEdit} className="shrink-0 text-fg">
                  <Pencil aria-hidden="true" className="h-3.5 w-3.5" />
                  Edit &amp; re-inspect
                </Button>
              ) : null
            }
          >
            <ul className="m-0 flex list-none flex-col gap-3 p-5">
              <li className="flex items-center gap-3 rounded-[10px] border border-line-strong p-2.5">
                {evidence.src ? (
                  // eslint-disable-next-line @next/next/no-img-element -- data: URL snapshot; static export has no image optimizer
                  <img src={evidence.src} alt="" className="h-10 w-10 shrink-0 rounded-[8px] object-cover" />
                ) : (
                  <span aria-hidden="true" className="h-10 w-10 shrink-0 rounded-[8px] bg-surface-muted" />
                )}
                <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                  <span className="truncate font-mono text-[13px] text-fg">
                    {submitted.loadFilename ?? "No load photo"}
                  </span>
                  <span className="text-[12px] text-fg-muted">Load photo</span>
                </span>
                {evidence.src ? (
                  <CircleCheck aria-label="Attached" className="h-4 w-4 shrink-0 text-success" />
                ) : (
                  <CircleMinus aria-label="Not attached" className="h-4 w-4 shrink-0 text-fg-subtle" />
                )}
              </li>
              <li className="flex items-center gap-3 rounded-[10px] border border-line-strong p-2.5">
                <span
                  aria-hidden="true"
                  className="flex h-10 w-10 shrink-0 items-center justify-center rounded-[8px] bg-surface-muted text-fg-muted"
                >
                  <FileText className="h-[18px] w-[18px]" />
                </span>
                <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                  <span className="truncate font-mono text-[13px] text-fg">
                    {submitted.waybillFilename ?? "No waybill photo"}
                  </span>
                  <span className="text-[12px] text-fg-muted">
                    {submitted.waybillOcr ? "Waybill · OCR" : "Waybill photo"}
                  </span>
                </span>
                {submitted.waybillFilename ? (
                  <CircleCheck aria-label="Attached" className="h-4 w-4 shrink-0 text-success" />
                ) : (
                  <CircleMinus aria-label="Not attached" className="h-4 w-4 shrink-0 text-fg-subtle" />
                )}
              </li>
            </ul>
          </Card>

          {/* Pythia: questions about this truck, answered from the plant
              documents and this record (keyed so a new truck starts clean) */}
          {verdictShown ? (
            <PythiaPanel
              key={data.record_id ?? "no-record"}
              recordId={data.record_id}
              suggestions={pythiaSuggestions(decision)}
            />
          ) : null}
        </div>
      </div>
    </div>
  );
}
