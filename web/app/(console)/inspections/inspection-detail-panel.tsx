"use client";

import { useEffect, useRef, useState } from "react";
import {
  ArrowLeft,
  Ban,
  Check,
  ChevronDown,
  ChevronUp,
  CircleAlert,
  CircleCheck,
  CircleDashed,
  CircleHelp,
  CircleX,
  Copy,
  FileJson,
  GitCompare,
  OctagonX,
  ShieldAlert,
  ShieldCheck,
  TriangleAlert,
  type LucideIcon,
} from "lucide-react";
import {
  ApiError,
  fetchInspectionDetail,
  type Decision,
  type GateState,
  type InspectionDetail,
  type PhotoInput,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import { formatMilliseconds, formatWeight, relativeTime } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { PageBody, PageHeader } from "@/components/shell/page-header";
import { PythiaPanel, pythiaSuggestions } from "@/components/assist/pythia-panel";
import { NextSteps } from "@/components/workspace/next-steps";
import { PhotoEvidence } from "@/components/workspace/photo-evidence";
import type { FollowupAction } from "@/lib/followup-api";
import { FollowupCard } from "./followup-card";
import { GATE_LABEL, orderedGates } from "./gate-labels";

/**
 * Audit record screen: replaces the ledger while ?record= is set. Fetches
 * GET /inspections/{record_id} (the API re-verifies the record's SHA-256
 * on every read), then shows the verdict banner with the digest, the
 * evidence photo with its regions, reasoning, inputs, the gate checklist,
 * SOP next steps, the follow-up log and Pythia, and offers the raw record as a JSON download.
 */

type GateTone = { Icon: LucideIcon; icon: string; row: string; label: string };

const GATE_TONE: Record<GateState, GateTone> = {
  passed: { Icon: CircleCheck, icon: "text-success", row: "bg-success/5", label: "Passed" },
  failed: { Icon: CircleX, icon: "text-danger", row: "bg-danger/5", label: "Failed" },
  not_run: { Icon: CircleDashed, icon: "text-fg-subtle", row: "bg-surface-subtle", label: "Not run" },
  not_evaluated: {
    Icon: CircleDashed,
    icon: "text-fg-subtle",
    row: "bg-surface-subtle",
    label: "Not evaluated",
  },
};

type VerdictTone = { label: string; Icon: LucideIcon; pill: string; frame: string };

const VERDICT_TONE: Record<Decision, VerdictTone> = {
  reject: {
    label: "Rejected",
    Icon: OctagonX,
    pill: "bg-danger",
    frame:
      "border-danger/25 bg-[linear-gradient(180deg,rgba(234,38,48,0.06)_0%,rgba(234,38,48,0)_100%)]",
  },
  escalate_human: {
    label: "Escalated",
    Icon: TriangleAlert,
    pill: "bg-warning",
    frame:
      "border-warning/25 bg-[linear-gradient(180deg,rgba(229,113,0,0.06)_0%,rgba(229,113,0,0)_100%)]",
  },
  accept: {
    label: "Accepted",
    Icon: CircleCheck,
    pill: "bg-success",
    frame:
      "border-success/25 bg-[linear-gradient(180deg,rgba(0,171,56,0.06)_0%,rgba(0,171,56,0)_100%)]",
  },
  refuse_insufficient_input: {
    label: "Refused",
    Icon: Ban,
    pill: "bg-fg-muted",
    frame: "border-line-strong",
  },
  unknown: { label: "Unknown", Icon: CircleHelp, pill: "bg-fg-muted", frame: "border-line-strong" },
};

/** Gas keys as recorded ("ch4") → chemical notation. */
const GAS_LABEL: Record<string, string> = {
  ch4: "CH₄",
  co2: "CO₂",
  h2s: "H₂S",
  nh3: "NH₃",
  tvoc: "TVOC",
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

/** String list from the VLM's free-form `detected` block ("organic_residue" → "organic residue"). */
function labelList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value
    .filter((v): v is string => typeof v === "string" && v.trim() !== "")
    .map((v) => v.replace(/_/g, " "));
}

/** Banner sentence: the operator instruction for the verdict, then what drove it. */
function verdictSummary(detail: InspectionDetail): string {
  const decision = detail.verdict?.decision ?? "unknown";
  const engineHeadline = detail.engine_outputs?.recommendation?.headline;
  const head =
    decision === "reject"
      ? "Load rejected: do not admit to RDF processing."
      : decision === "escalate_human"
        ? "Human review required before unloading."
        : decision === "refuse_insufficient_input"
          ? "Insufficient input: inspection cannot proceed."
          : (typeof engineHeadline === "string" && engineHeadline) || "Inspection completed.";
  const vlm = detail.ai_outputs?.vlm;
  const hard = labelList(vlm?.detected?.hard_contaminants);
  const light = labelList(vlm?.detected?.light_contaminants);
  if (hard.length > 0) {
    const confidence =
      typeof vlm?.confidence === "number" ? ` (VLM confidence ${vlm.confidence.toFixed(2)})` : "";
    return `${head} Hard contamination detected: ${hard.join(", ")}${confidence}.`;
  }
  if (light.length > 0 && decision !== "accept") {
    return `${head} Light or ambiguous contamination: ${light.join(", ")}.`;
  }
  const failed = Object.values(detail.gates ?? {}).find((gate) => gate.state === "failed");
  return failed?.reason ? `${head} ${failed.reason}` : head;
}

type DetailLoad =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ready"; detail: InspectionDetail };

export function InspectionDetailPanel({
  recordId,
  onClose,
  position,
  prevId,
  nextId,
  onNavigate,
  onFollowupLogged,
}: {
  recordId: string;
  onClose: () => void;
  /** Place in the ledger as filtered; null while the ledger is not loaded. */
  position: { index: number; total: number } | null;
  prevId: string | null;
  nextId: string | null;
  onNavigate: (recordId: string) => void;
  /** A follow-up action was appended to this record's log. */
  onFollowupLogged?: (action: FollowupAction) => void;
}) {
  const [state, setState] = useState<DetailLoad>({ kind: "loading" });
  const [retryCount, setRetryCount] = useState(0);
  const rootRef = useRef<HTMLDivElement>(null);

  /* New record on screen: start at the top, focus inside the screen. */
  useEffect(() => {
    window.scrollTo({ top: 0 });
    rootRef.current?.focus({ preventScroll: true });
  }, [recordId]);

  /* Re-fetch when recordId or retryCount changes */
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

  const detail = state.kind === "ready" ? state.detail : null;
  const sha = detail?.digest?.record_sha256 ?? null;

  return (
    <div
      ref={rootRef}
      tabIndex={-1}
      aria-label={`Audit record ${recordId}`}
      className="focus:outline-none"
    >
      <PageHeader
        className="pl-[68px]! md:pl-[82px]!"
        crumb={
          <>
            Audit trail / Records
            <button
              type="button"
              onClick={onClose}
              aria-label="Back to audit trail"
              title="Back to audit trail (Esc)"
              className="absolute top-[18px] left-5 flex h-9 w-9 cursor-pointer items-center justify-center rounded-[8px] border border-line-strong bg-surface text-fg transition-colors duration-100 hover:bg-surface-subtle md:left-8"
            >
              <ArrowLeft aria-hidden="true" className="h-4 w-4" />
            </button>
          </>
        }
        title={recordId}
      >
        <div className="flex items-center gap-1">
          <Button
            variant="default"
            size="icon"
            className="h-8 w-8 shadow-none"
            disabled={!prevId}
            onClick={() => prevId && onNavigate(prevId)}
            aria-label="Previous record in ledger"
            title={prevId ?? undefined}
          >
            <ChevronUp aria-hidden="true" className="h-4 w-4" />
          </Button>
          <Button
            variant="default"
            size="icon"
            className="h-8 w-8 shadow-none"
            disabled={!nextId}
            onClick={() => nextId && onNavigate(nextId)}
            aria-label="Next record in ledger"
            title={nextId ?? undefined}
          >
            <ChevronDown aria-hidden="true" className="h-4 w-4" />
          </Button>
          {position ? (
            <span className="figure ml-1 text-[12px] whitespace-nowrap text-fg-muted">
              {position.index + 1} of {position.total}
            </span>
          ) : null}
        </div>
        <CopyHashButton sha={sha} />
        <Button
          variant="default"
          disabled={!detail}
          onClick={() => detail && downloadJSON(detail)}
          title={`Download ${recordId}.json`}
        >
          <FileJson aria-hidden="true" className="h-3.5 w-3.5" />
          Download JSON
        </Button>
      </PageHeader>

      <PageBody>
        {state.kind === "loading" ? (
          <div className="card">
            <div role="status" className="flex flex-col items-center gap-3 py-12 text-center">
              <span
                aria-hidden="true"
                className="h-6 w-6 animate-spin rounded-full border-2 border-line-strong border-t-brand"
              />
              <span className="sr-only">Loading</span>
              <p className="text-[13px] text-fg-muted">Fetching audit record {recordId}…</p>
            </div>
          </div>
        ) : state.kind === "error" ? (
          <div className="card">
            <div role="alert" className="flex flex-col items-center gap-3 px-4 py-12 text-center">
              <p className="max-w-[52ch] text-[14px] text-danger">
                Could not load {recordId}. {state.message}
              </p>
              <div className="flex gap-2">
                <Button size="sm" onClick={() => setRetryCount((c) => c + 1)}>
                  Retry
                </Button>
                <Button size="sm" variant="ghost" onClick={onClose}>
                  Back to audit trail
                </Button>
              </div>
            </div>
          </div>
        ) : (
          <DetailBody detail={state.detail} onFollowupLogged={onFollowupLogged} />
        )}
      </PageBody>
    </div>
  );
}

function CopyHashButton({ sha }: { sha: string | null }) {
  const [status, setStatus] = useState<"idle" | "copied" | "failed">("idle");

  useEffect(() => {
    if (status === "idle") return;
    const timer = window.setTimeout(() => setStatus("idle"), 1600);
    return () => window.clearTimeout(timer);
  }, [status]);

  const copy = () => {
    if (!sha) return;
    const hex = sha.replace(/^sha256:/, "");
    if (!navigator.clipboard) {
      setStatus("failed");
      return;
    }
    navigator.clipboard.writeText(hex).then(
      () => setStatus("copied"),
      () => setStatus("failed"),
    );
  };

  const label =
    status === "copied" ? "Record hash copied" : status === "failed" ? "Copy failed" : "Copy record hash";
  return (
    <>
      <Button
        variant="default"
        size="icon"
        disabled={!sha}
        onClick={copy}
        aria-label={label}
        title={label}
      >
        {status === "copied" ? (
          <Check aria-hidden="true" className="h-4 w-4 text-success" />
        ) : (
          <Copy aria-hidden="true" className="h-4 w-4" />
        )}
      </Button>
      <span aria-live="polite" className="sr-only">
        {status === "idle" ? "" : label}
      </span>
    </>
  );
}

function SectionCard({
  title,
  className,
  children,
}: {
  title: string;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <section className={cn("card flex flex-col gap-3.5 p-5 md:p-6", className)}>
      <h2 className="eyebrow m-0">{title}</h2>
      {children}
    </section>
  );
}

function DetailBody({
  detail,
  onFollowupLogged,
}: {
  detail: InspectionDetail;
  onFollowupLogged?: (action: FollowupAction) => void;
}) {
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
  const gates = orderedGates(detail.gates ?? {});
  const passedCount = gates.filter(([, gate]) => gate.state === "passed").length;
  const weightKg = detail.inputs?.weight?.value_kg ?? 0;
  const tone = VERDICT_TONE[decision];
  const sha = detail.digest?.record_sha256;
  const detectorFlags = detector
    ? [...detector.hard_contaminants, ...detector.light_contaminants]
    : [];
  const ReasonIcon = decision === "accept" ? CircleCheck : CircleAlert;
  const reasonIconClass =
    decision === "accept"
      ? "text-success"
      : decision === "reject"
        ? "text-danger"
        : decision === "escalate_human"
          ? "text-warning"
          : "text-fg-muted";

  return (
    <div className="flex flex-col gap-4">
      {/* ---- verdict banner + digest ---- */}
      <section
        aria-label="Verdict"
        className={cn(
          "flex flex-col gap-4 overflow-hidden rounded-[14px] border bg-surface p-5 md:p-7",
          tone.frame,
        )}
      >
        <div className="flex flex-wrap items-center gap-x-3.5 gap-y-2">
          <span
            className={cn(
              "inline-flex shrink-0 items-center gap-1.5 rounded-full px-3 py-[5px] font-mono text-[12px] font-medium tracking-[0.8px] text-white uppercase",
              tone.pill,
            )}
          >
            <tone.Icon aria-hidden="true" className="h-3.5 w-3.5" />
            {tone.label}
          </span>
          <div className="flex min-w-0 flex-col gap-px">
            <span className="font-display text-[22px] leading-tight font-medium break-words text-fg md:text-[26px]">
              {detail.inputs?.truck_id ?? "—"}
            </span>
            <span className="text-[13px] text-fg-muted">
              {[
                supplier,
                weightKg > 0 ? formatWeight(weightKg) : null,
                detail.verdict?.decided_at_utc ? relativeTime(detail.verdict.decided_at_utc) : null,
              ]
                .filter(Boolean)
                .join(" · ")}
            </span>
          </div>
        </div>
        <p className="m-0 text-[15px] leading-[23px] text-fg-muted">{verdictSummary(detail)}</p>
        <div className="flex flex-wrap items-center gap-x-2.5 gap-y-2 rounded-[10px] border border-line-strong bg-surface px-3 py-2.5">
          {sha ? (
            <>
              <ShieldCheck aria-hidden="true" className="h-4 w-4 shrink-0 text-success" />
              <span className="flex min-w-0 flex-1 items-center gap-2" title={sha}>
                <span className="figure text-[12px] text-fg-subtle">SHA-256</span>
                <span className="figure truncate text-[12px] text-fg">{shortHash(sha)}</span>
              </span>
              <span
                className="inline-flex shrink-0 items-center gap-1.5 rounded-full bg-success-tint px-2.5 py-[3px] text-[12px] font-medium text-success"
                title="The API recomputes this SHA-256 over the record on every read; a record whose body no longer matches its digest is not served."
              >
                <span aria-hidden="true" className="h-1.5 w-1.5 rounded-full bg-current" />
                Digest verified
              </span>
            </>
          ) : (
            <>
              <ShieldAlert aria-hidden="true" className="h-4 w-4 shrink-0 text-fg-subtle" />
              <span className="text-[12px] text-fg-muted">No digest on this record.</span>
            </>
          )}
        </div>
      </section>

      <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,688fr)_minmax(0,408fr)]">
        {/* ---- left: evidence, reasoning, inputs ---- */}
        <div className="flex min-w-0 flex-col gap-4">
          <SectionCard title="Evidence">
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
              <div className="flex items-start gap-2.5 rounded-[8px] bg-surface-subtle px-3 py-2.5 text-[12px] leading-[17px] text-fg-muted">
                <GitCompare aria-hidden="true" className="mt-px h-3.5 w-3.5 shrink-0" />
                <span className="min-w-0 break-words">
                  Second opinion ·{" "}
                  {[detector.model, detector.runtime, formatMilliseconds(detector.latency_ms)]
                    .filter(Boolean)
                    .join(" · ")}{" "}
                  —{" "}
                  {detectorFlags.length > 0
                    ? `flagged ${detectorFlags.map((l) => l.replace(/_/g, " ")).join(", ")}`
                    : "no metal, glass or organic boxes"}
                </span>
              </div>
            ) : null}
          </SectionCard>

          {reasoningText || reasons.length > 0 || failureNote ? (
            <SectionCard title="Reasoning">
              {reasons.length > 0 ? (
                <ul className="m-0 flex list-none flex-col gap-3.5 p-0">
                  {reasons.map((reason) => (
                    <li key={reason} className="flex items-start gap-2.5">
                      <ReasonIcon
                        aria-hidden="true"
                        className={cn("mt-[3px] h-3.5 w-3.5 shrink-0", reasonIconClass)}
                      />
                      <span className="text-[14px] leading-[21px] text-fg">{reason}</span>
                    </li>
                  ))}
                </ul>
              ) : null}
              {reasoningText ? (
                <p className="m-0 text-[14px] leading-[21px] text-fg">{reasoningText}</p>
              ) : null}
              {failureNote ? (
                <p className="m-0 flex items-start gap-2 text-[12px] text-warning">
                  <TriangleAlert aria-hidden="true" className="mt-px h-3.5 w-3.5 shrink-0" />
                  {failureNote}
                </p>
              ) : null}
            </SectionCard>
          ) : null}

          <SectionCard title="Inputs">
            <dl className="m-0 grid grid-cols-1 gap-2 sm:grid-cols-3">
              <InputCell term="Truck" value={detail.inputs?.truck_id ?? "—"} />
              <InputCell term="Supplier" value={supplier || "—"} />
              <InputCell term="Weight" value={formatWeight(weightKg)} mono />
            </dl>
            <h3
              className="m-0 text-[13px] font-medium text-fg"
              title={
                [
                  gasInstrument?.model
                    ? `Instrument: ${gasInstrument.model}${gasInstrument.technology ? ` (${gasInstrument.technology})` : ""}`
                    : null,
                  gasModelBasis ? `Model basis: ${gasModelBasis}` : null,
                ]
                  .filter(Boolean)
                  .join(" · ") || undefined
              }
            >
              Gas readings at the gate
            </h3>
            {gasReadings && Object.keys(gasReadings).length > 0 ? (
              <dl className="m-0 grid grid-cols-2 gap-2 sm:grid-cols-4">
                {Object.entries(gasReadings).map(([gas, ppm]) => (
                  <div
                    key={gas}
                    className="flex min-w-0 flex-col gap-1 rounded-[8px] bg-surface-subtle px-3 py-2.5"
                  >
                    <dt className="text-[12px] text-fg-muted">
                      {GAS_LABEL[gas.toLowerCase()] ?? gas}
                    </dt>
                    <dd className="m-0 flex items-baseline gap-1">
                      <span className="figure truncate text-[20px] leading-tight font-light text-fg">
                        {ppm}
                      </span>
                      <span className="figure text-[11px] text-fg-subtle">ppm</span>
                    </dd>
                  </div>
                ))}
              </dl>
            ) : (
              <p className="m-0 rounded-[8px] bg-surface-subtle px-3 py-2.5 text-[13px] text-fg-muted">
                {gasSource ?? "not measured"}
              </p>
            )}
          </SectionCard>
        </div>

        {/* ---- right: checks, next steps, follow-up, Pythia ---- */}
        <div className="flex min-w-0 flex-col gap-4">
          <SectionCard
            title={
              gates.length > 0
                ? `Checks · ${passedCount} of ${gates.length} passed`
                : "Checks"
            }
            className="gap-2.5"
          >
            {gates.length > 0 ? (
              <ul className="m-0 flex list-none flex-col gap-1.5 p-0">
                {gates.map(([name, gate]) => {
                  const gateTone = GATE_TONE[gate.state];
                  const measured =
                    gate.value !== null
                      ? `value ${typeof gate.value === "number" ? gate.value.toFixed(3) : gate.value}${gate.threshold !== null ? ` · threshold ${gate.threshold}` : ""}`
                      : null;
                  const tip = [measured, gate.reason].filter(Boolean).join(" — ");
                  return (
                    <li
                      key={name}
                      title={tip || undefined}
                      className={cn("flex flex-col gap-1 rounded-[8px] px-3 py-2.5", gateTone.row)}
                    >
                      <div className="flex items-center gap-2">
                        <gateTone.Icon
                          aria-hidden="true"
                          className={cn("h-3.5 w-3.5 shrink-0", gateTone.icon)}
                        />
                        <span className="min-w-0 flex-1 text-[13px] text-fg">
                          {GATE_LABEL[name] ?? name}
                        </span>
                        {gate.state === "passed" ? (
                          <span className="sr-only">{gateTone.label}</span>
                        ) : (
                          <span className={cn("shrink-0 text-[12px] font-medium", gateTone.icon)}>
                            {gateTone.label}
                          </span>
                        )}
                      </div>
                      {gate.state !== "passed" && gate.reason ? (
                        <p className="m-0 pl-[22px] text-[12px] leading-[17px] text-fg-muted">
                          {gate.reason}
                        </p>
                      ) : null}
                    </li>
                  );
                })}
              </ul>
            ) : (
              <p className="m-0 text-[13px] text-fg-muted">No checks recorded on this record.</p>
            )}
          </SectionCard>

          <div className="card p-5 md:p-6">
            <NextSteps
              steps={steps}
              emptyText="Not recorded: this record predates SOP-cited next steps."
            />
          </div>

          {detail.record_id ? (
            <FollowupCard
              key={`followup-${detail.record_id}`}
              recordId={detail.record_id}
              onLogged={onFollowupLogged}
            />
          ) : null}

          {detail.record_id ? (
            <PythiaPanel
              key={detail.record_id}
              recordId={detail.record_id}
              suggestions={pythiaSuggestions(decision)}
            />
          ) : null}
        </div>
      </div>
    </div>
  );
}

function InputCell({ term, value, mono = false }: { term: string; value: string; mono?: boolean }) {
  return (
    <div className="flex min-w-0 flex-col gap-1 rounded-[8px] border border-line-strong px-3 py-2.5">
      <dt className="text-[12px] text-fg-muted">{term}</dt>
      <dd className={cn("m-0 truncate text-[14px] font-medium text-fg", mono && "figure")}>
        {value}
      </dd>
    </div>
  );
}

/** 8 + 8 chars around an ellipsis; the full digest stays in the title and the JSON download. */
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
