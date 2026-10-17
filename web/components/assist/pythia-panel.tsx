"use client";

/**
 * PythiaPanel: the gate assistant. Pythia looks things up in the plant's own
 * records (inspection ledger, supplier scorecard, example contract, kiln
 * intake, gate SOP) and answers from those lookups only. Every answer shows
 * the records it cites (linked), how Pythia found it (the tool trace), and
 * whether it passed the grounding check; an answer the backend could not
 * ground is shown as such, never dressed up.
 */

import Link from "next/link";
import { useCallback, useEffect, useId, useRef, useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import {
  AssistError,
  QUESTION_MAX_CHARS,
  askPythiaStreaming,
  sourceHref,
  type PythiaProgress,
  type AssistResponse,
  type AssistSource,
  type AssistStep,
} from "@/lib/assist-api";
import { liveProvenance } from "@/lib/format";
import { useElapsedSeconds } from "@/lib/use-elapsed";
import { cn } from "@/lib/utils";

type Turn =
  | { id: number; question: string; status: "pending"; steps: AssistStep[]; turn: number | null }
  | { id: number; question: string; status: "answered"; response: AssistResponse }
  | { id: number; question: string; status: "error"; message: string };

/**
 * Suggestion and Ask buttons are never `disabled` while a question is in
 * flight: disabling the focused button drops keyboard focus to <body>.
 * They stay focusable with aria-disabled, look inactive, and ask() ignores
 * presses until the answer lands.
 */
const AWAITING = "aria-disabled:cursor-not-allowed aria-disabled:opacity-50";

/** Older turns scroll away: the panel shows the latest exchanges only. */
const MAX_TURNS = 4;

/** Where the panel sits: one truck's verdict, or the shift / control room. */
export type PythiaContext = "verdict" | "shift";

/** Verdict context: the first question follows the verdict. */
export function pythiaSuggestions(decision: string | undefined): string[] {
  const d = String(decision ?? "").toLowerCase();
  const why = d.startsWith("reject")
    ? "Why was this truck rejected?"
    : d.startsWith("accept")
      ? "Why was this truck accepted?"
      : d.startsWith("escalate")
        ? "Why was this truck held?"
        : d.startsWith("refuse")
          ? "Why was this inspection refused?"
          : "Why did this truck get this verdict?";
  return [why, "Has this supplier done this before?", "What does the SOP say about this load?"];
}

/** Shift / control-room context: questions about the whole gate. */
export const SHIFT_SUGGESTIONS = [
  "Which supplier should I sample next?",
  "How close are we to the chlorine budget?",
  "Which trucks were rejected in the last 8 hours?",
];

const TOOL_NAMES: Record<string, string> = {
  find_inspections: "Searched the inspection ledger",
  get_inspection: "Read the inspection record",
  supplier_profile: "Read the supplier scorecard",
  contract_terms: "Read the supply contract",
  kiln_intake: "Read the kiln intake",
  sop_clause: "Read the SOP clause",
  search_sop: "Searched the gate SOP",
};

function provenanceLine(r: AssistResponse): string {
  const p = r.provenance;
  if (p.provider === "stub-extractive") {
    return "Extractive · quoted from the plant records · no language model";
  }
  return liveProvenance(p.provider, p.model, r.latency_ms ?? p.latency_ms);
}

function sourceTitle(s: AssistSource): string {
  switch (s.kind) {
    case "record":
      return `Inspection record ${s.id}: open it in the ledger`;
    case "supplier":
      return `Supplier ${s.id}: open its trucks in the ledger`;
    case "contract":
      return "Example supply contract (terms are set per contract)";
    case "kiln":
      return "Kiln fuel intake";
    default:
      return s.id.startsWith("REG-") ? `Regulation note ${s.id}` : `Reference gate SOP clause ${s.id}`;
  }
}

function argsText(args: AssistStep["args"]): string {
  const parts = Object.entries(args).map(([k, v]) => `${k}: ${typeof v === "string" ? v : JSON.stringify(v)}`);
  return parts.length ? parts.join(", ") : "no arguments";
}

const CHIP = "figure rounded-[4px] border border-seam-strong bg-raised px-1.5 py-0.5 text-[12px] text-ink";

export function SourceChip({ source }: { source: AssistSource }) {
  const href = sourceHref(source);
  const text = source.kind === "sop" ? source.id : source.label || source.id;
  return href ? (
    <Link href={href} title={sourceTitle(source)} className={cn(CHIP, "underline-offset-2 hover:border-amber hover:underline")}>
      {text}
    </Link>
  ) : (
    <span title={sourceTitle(source)} className={CHIP}>
      {text}
    </span>
  );
}

export function GroundedBadge({ grounded }: { grounded: boolean }) {
  return grounded ? (
    <span
      title="Every number in this answer appears in a record Pythia looked up, and it cites those records."
      className="figure rounded-[4px] border border-verdict-green px-1.5 py-0.5 text-[11px] text-verdict-green"
    >
      Grounded
    </span>
  ) : (
    <span
      title="This answer did not pass the grounding check: read the cited records before acting on it."
      className="figure rounded-[4px] border border-verdict-amber px-1.5 py-0.5 text-[11px] text-verdict-amber"
    >
      Not grounded
    </span>
  );
}

function Trace({ steps }: { steps: AssistStep[] }) {
  if (steps.length === 0) return null;
  return (
    <details className="group text-[12.5px] text-muted">
      <summary className="cursor-pointer select-none hover:text-ink">
        How Pythia found this ({steps.length} {steps.length === 1 ? "lookup" : "lookups"})
      </summary>
      <ol className="m-0 mt-1.5 flex list-none flex-col gap-1 p-0">
        {steps.map((s, i) => (
          <li key={i} className="flex flex-wrap items-baseline gap-x-2">
            <span className="figure text-faint">{i + 1}.</span>
            <span className="text-ink">{TOOL_NAMES[s.tool] ?? s.tool}</span>
            <span className="figure text-[11.5px] text-faint">
              {s.tool}({argsText(s.args)})
            </span>
            {s.summary ? <span className="text-[12px]">→ {s.summary}</span> : null}
            {s.ms != null ? <span className="figure text-[11.5px] text-faint">{Math.round(s.ms)} ms</span> : null}
          </li>
        ))}
      </ol>
    </details>
  );
}

/** One finished lookup as the operator reads it: "Read the supplier scorecard · UD Sinar Abadi → tier high". */
function stepLine(step: AssistStep): string {
  const subject = Object.values(step.args).find((v): v is string => typeof v === "string" && v.trim() !== "");
  return `${TOOL_NAMES[step.tool] ?? step.tool}${subject ? ` · ${subject}` : ""}${step.summary ? ` → ${step.summary}` : ""}`;
}

function PendingLine({ steps, turn }: { steps: AssistStep[]; turn: number | null }) {
  const seconds = useElapsedSeconds(true);
  const doing =
    turn === null
      ? "Looking it up in the plant records…"
      : steps.length === 0
        ? "Pythia is choosing what to look up…"
        : "Pythia is reading what it found…";
  return (
    <div className="flex flex-col gap-1">
      {steps.length > 0 ? (
        <ol aria-label="Lookups so far" className="m-0 flex list-none flex-col gap-0.5 p-0 text-[12.5px] text-muted">
          {steps.map((s, i) => (
            <li key={i} className="flex items-baseline gap-2">
              <span aria-hidden="true" className="text-verdict-green">
                ✓
              </span>
              <span>{stepLine(s)}</span>
            </li>
          ))}
        </ol>
      ) : null}
      <p className="m-0 flex items-center gap-2 text-[13px] text-muted">
        <span
          aria-hidden="true"
          className="h-2 w-2 shrink-0 animate-[gate-pulse_1.1s_ease-in-out_infinite] rounded-full bg-amber"
        />
        {doing}
        {/* aria-hidden: a ticking clock inside the live region would be
            re-announced every second */}
        <span className="figure text-[12px] text-faint" aria-hidden="true">
          {seconds} s
        </span>
      </p>
    </div>
  );
}

function Answer({ response }: { response: AssistResponse }) {
  const sources: AssistSource[] = response.sources.length
    ? response.sources
    : response.citations.map((id) => ({ kind: "sop" as const, id, label: id }));
  const grounded = response.grounded && sources.length > 0;
  return (
    <div className="flex flex-col gap-2">
      <p className={cn("m-0 text-[14px] leading-relaxed", grounded ? "text-ink" : "text-muted")}>
        {response.answer || "No answer returned."}
      </p>
      <div className="flex flex-wrap items-center gap-1.5">
        <GroundedBadge grounded={grounded} />
        {sources.length > 0 ? (
          <ul aria-label="Records cited" className="m-0 flex list-none flex-wrap gap-1.5 p-0">
            {sources.map((s) => (
              <li key={`${s.kind}:${s.id}`}>
                <SourceChip source={s} />
              </li>
            ))}
          </ul>
        ) : (
          <span className="text-[12px] text-faint">No record cited.</span>
        )}
      </div>
      <Trace steps={response.steps} />
      <p className="figure m-0 text-[11px] text-faint">{provenanceLine(response)}</p>
    </div>
  );
}

export function PythiaPanel({
  recordId,
  context = recordId ? "verdict" : "shift",
  suggestions,
  className,
}: {
  /** Audit record the questions are about; omit for gate-wide questions. */
  recordId?: string;
  /** Picks the default suggestions; follows `recordId` when omitted. */
  context?: PythiaContext;
  /** Overrides the context's suggested questions. */
  suggestions?: string[];
  className?: string;
}) {
  const shown = suggestions ?? (context === "verdict" ? pythiaSuggestions(undefined) : SHIFT_SUGGESTIONS);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState("");
  const nextId = useRef(1);
  const inflight = useRef<AbortController | null>(null);
  const headingId = useId();
  const inputId = useId();
  const pending = turns.some((t) => t.status === "pending");

  // Leaving the screen (or switching record) cancels an unanswered question.
  useEffect(() => () => inflight.current?.abort(), []);

  const ask = useCallback(
    async (raw: string) => {
      const question = raw.trim();
      if (!question || pending) return;
      const id = nextId.current++;
      const controller = new AbortController();
      inflight.current = controller;
      setDraft("");
      setTurns((prev) =>
        [...prev, { id, question, status: "pending" as const, steps: [], turn: null }].slice(-MAX_TURNS),
      );
      const onProgress = (p: PythiaProgress) =>
        setTurns((prev) =>
          prev.map((t) =>
            t.id !== id || t.status !== "pending"
              ? t
              : p.kind === "step"
                ? { ...t, steps: [...t.steps, p.step] }
                : { ...t, turn: p.turn },
          ),
        );
      let settled: Turn;
      try {
        const response = await askPythiaStreaming(question, recordId, onProgress, controller.signal);
        settled = { id, question, status: "answered", response };
      } catch (err) {
        if (controller.signal.aborted) return;
        settled = {
          id,
          question,
          status: "error",
          message: err instanceof AssistError ? err.message : "Pythia could not answer right now.",
        };
      }
      if (inflight.current === controller) inflight.current = null;
      setTurns((prev) => prev.map((t) => (t.id === id ? settled : t)));
    },
    [pending, recordId],
  );

  const onSubmit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    void ask(draft);
  };

  return (
    <section
      aria-labelledby={headingId}
      className={cn("flex flex-col rounded-[10px] border border-seam", className)}
    >
      <header className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 border-b border-seam px-4 py-3">
        <h3 id={headingId} className="smallcaps m-0">
          Ask Pythia
        </h3>
        <span className="text-[12px] text-muted">
          Looks up the plant&apos;s records{recordId ? ", starting with this truck" : ""}: inspections,
          suppliers, contract, kiln intake and the gate SOP. Every number is checked against them.
        </span>
      </header>

      <div aria-live="polite" className="flex flex-col">
        {turns.map((turn) => (
          <div key={turn.id} className="flex flex-col gap-2 border-b border-seam px-4 py-3">
            <p className="m-0 text-[13px] font-semibold text-muted">{turn.question}</p>
            {turn.status === "pending" ? (
              <PendingLine steps={turn.steps} turn={turn.turn} />
            ) : turn.status === "error" ? (
              <p role="alert" className="m-0 text-[13px] text-verdict-red">
                {turn.message}
              </p>
            ) : (
              <Answer response={turn.response} />
            )}
          </div>
        ))}
      </div>

      <div className="flex flex-col gap-3 px-4 py-3">
        {shown.length > 0 ? (
          <div className="flex flex-wrap gap-2" role="group" aria-label="Suggested questions">
            {shown.map((s) => (
              <Button
                key={s}
                type="button"
                variant="default"
                size="sm"
                aria-disabled={pending}
                onClick={() => void ask(s)}
                className={cn("text-left font-medium", AWAITING)}
              >
                {s}
              </Button>
            ))}
          </div>
        ) : null}
        <form onSubmit={onSubmit} className="flex gap-2">
          <label htmlFor={inputId} className="sr-only">
            Question for Pythia
          </label>
          <input
            id={inputId}
            className="input min-w-0 flex-1"
            value={draft}
            maxLength={QUESTION_MAX_CHARS}
            onChange={(e) => setDraft(e.target.value)}
            placeholder={
              recordId ? "Ask about this truck, its supplier or the gate SOP" : "Ask about trucks, suppliers, the contract or the SOP"
            }
            autoComplete="off"
          />
          <Button
            type="submit"
            variant="default"
            aria-disabled={pending || !draft.trim()}
            className={AWAITING}
          >
            Ask
          </Button>
        </form>
      </div>
    </section>
  );
}
