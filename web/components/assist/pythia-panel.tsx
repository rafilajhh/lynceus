"use client";

/**
 * PythiaPanel: the gate assistant ("Ask Pythia" card). Answers only from the plant documents
 * (reference gate SOP, regulation notes) and, when a record id is given,
 * that truck's audit record. Every answer shows the sources it cites and
 * how it was produced (live model + latency, or extractive quote); an
 * answer the backend could not ground is shown as such, never dressed up.
 */

import { useCallback, useEffect, useId, useRef, useState, type FormEvent } from "react";
import { ArrowUp, MessageCircleQuestion, MessageSquare, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  AssistError,
  QUESTION_MAX_CHARS,
  askPythia,
  type AssistResponse,
} from "@/lib/assist-api";
import { liveProvenance } from "@/lib/format";
import { useElapsedSeconds } from "@/lib/use-elapsed";
import { cn } from "@/lib/utils";

type Turn =
  | { id: number; question: string; status: "pending" }
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

/** Suggested questions: the first follows the verdict, the rest are fixed. */
export function pythiaSuggestions(decision: string | undefined): string[] {
  const d = String(decision ?? "").toLowerCase();
  const why = d.startsWith("reject")
    ? "Why was this truck rejected?"
    : d.startsWith("accept")
      ? "Why was this truck accepted?"
      : d.startsWith("escalate")
        ? "Why does this truck need human review?"
        : d.startsWith("refuse")
          ? "Why was this inspection refused?"
          : "Why did this truck get this verdict?";
  return [why, "What does the SOP say about wet loads?", "What is the H2S exposure limit?"];
}

function provenanceLine(p: AssistResponse["provenance"]): string {
  if (p.provider === "stub-extractive") {
    return "Extractive · quoted from the plant documents · no language model";
  }
  return liveProvenance(p.provider, p.model, p.latency_ms);
}

function citationTitle(id: string, recordId: string | undefined): string {
  if (id === "RECORD") return recordId ? `Audit record ${recordId}` : "The audit record";
  if (id.startsWith("SOP-")) return `Reference gate SOP clause ${id}`;
  if (id.startsWith("REG-")) return `Regulation note ${id}`;
  return id;
}

function PendingLine() {
  const seconds = useElapsedSeconds(true);
  return (
    <p className="m-0 flex items-center gap-2 text-[13px] text-fg-muted">
      <span
        aria-hidden="true"
        className="h-2 w-2 shrink-0 animate-[gate-pulse_1.1s_ease-in-out_infinite] rounded-full bg-brand"
      />
      Checking the plant documents…
      {/* aria-hidden: a ticking clock inside the live region would be
          re-announced every second */}
      <span className="figure text-[12px] text-fg-subtle" aria-hidden="true">
        {seconds} s
      </span>
    </p>
  );
}

function Answer({
  response,
  recordId,
}: {
  response: AssistResponse;
  recordId: string | undefined;
}) {
  const grounded = response.grounded && response.citations.length > 0;
  return (
    <div className="flex flex-col gap-2">
      <p className={cn("m-0 text-[14px] leading-relaxed", grounded ? "text-fg" : "text-fg-muted")}>
        {response.answer || "No answer returned."}
      </p>
      {grounded ? (
        <ul aria-label="Sources cited" className="m-0 flex list-none flex-wrap gap-1.5 p-0">
          {response.citations.map((id) => (
            <li
              key={id}
              title={citationTitle(id, recordId)}
              className="rounded-full border border-line-strong bg-surface px-2 py-px font-mono text-[11px] font-medium text-fg-muted"
            >
              {id}
            </li>
          ))}
        </ul>
      ) : (
        <p className="m-0 text-[12px] text-fg-subtle">No source cited: not answered from the documents.</p>
      )}
      <p className="figure m-0 text-[11px] text-fg-subtle">{provenanceLine(response.provenance)}</p>
    </div>
  );
}

export function PythiaPanel({
  recordId,
  suggestions,
  className,
}: {
  /** Audit record the questions are about; omit for SOP-only questions. */
  recordId?: string;
  suggestions: string[];
  className?: string;
}) {
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
      setTurns((prev) => [...prev, { id, question, status: "pending" as const }].slice(-MAX_TURNS));
      let settled: Turn;
      try {
        const response = await askPythia(question, recordId, controller.signal);
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
    <section aria-labelledby={headingId} className={cn("card", className)}>
      <div className="flex flex-col gap-3.5 bg-[radial-gradient(ellipse_70%_60%_at_100%_0%,color-mix(in_srgb,var(--color-brand)_10%,transparent)_0%,transparent_100%)] p-5">
        <div className="flex items-center gap-2.5">
          <span
            aria-hidden="true"
            className="flex h-7 w-7 shrink-0 items-center justify-center rounded-[8px] bg-brand text-white"
          >
            <Sparkles className="h-3.5 w-3.5" />
          </span>
          <h3 id={headingId} className="m-0 font-display text-[17px] font-medium text-fg">
            Ask Pythia
          </h3>
        </div>
        <p className="m-0 text-[13px] leading-[19px] text-fg-muted">
          Answers only from the gate SOP, regulation notes
          {recordId ? " and this audit record" : ""} — always with sources.
        </p>

        {/* One persistent live region (a freshly mounted one is often not
            announced); it has no box until the first question. */}
        <div
          aria-live="polite"
          className={cn(
            "flex flex-col",
            turns.length > 0
              ? "divide-y divide-line rounded-[10px] border border-line-strong bg-surface"
              : "-mt-3.5", // empty: cancel the parent gap
          )}
        >
          {turns.map((turn) => (
            <div key={turn.id} className="flex flex-col gap-2 px-3.5 py-3">
              <p className="m-0 text-[13px] font-medium text-fg-muted">{turn.question}</p>
              {turn.status === "pending" ? (
                <PendingLine />
              ) : turn.status === "error" ? (
                <p role="alert" className="m-0 text-[13px] text-danger">
                  {turn.message}
                </p>
              ) : (
                <Answer response={turn.response} recordId={recordId} />
              )}
            </div>
          ))}
        </div>

        {suggestions.length > 0 ? (
          <div className="flex flex-col gap-1.5" role="group" aria-label="Suggested questions">
            {suggestions.map((s) => (
              <button
                key={s}
                type="button"
                aria-disabled={pending}
                onClick={() => void ask(s)}
                className={cn(
                  "flex w-full cursor-pointer items-center gap-2 rounded-[8px] border border-line-strong bg-surface px-3 py-2 text-left text-[13px] text-fg transition-colors duration-100 hover:bg-surface-subtle",
                  AWAITING,
                )}
              >
                <MessageCircleQuestion aria-hidden="true" className="h-3.5 w-3.5 shrink-0 text-fg-muted" />
                <span className="min-w-0 flex-1">{s}</span>
              </button>
            ))}
          </div>
        ) : null}

        <form onSubmit={onSubmit} className="flex gap-2">
          <label htmlFor={inputId} className="sr-only">
            Question for Pythia
          </label>
          <div className="relative min-w-0 flex-1">
            <MessageSquare
              aria-hidden="true"
              className="pointer-events-none absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2 text-fg-subtle"
            />
            <input
              id={inputId}
              className="input"
              style={{ paddingLeft: 36 }}
              value={draft}
              maxLength={QUESTION_MAX_CHARS}
              onChange={(e) => setDraft(e.target.value)}
              placeholder="Ask about this truck or the SOP"
              autoComplete="off"
            />
          </div>
          <Button
            type="submit"
            variant="brand"
            aria-disabled={pending || !draft.trim()}
            className={cn("h-10", AWAITING)}
          >
            <ArrowUp aria-hidden="true" className="h-3.5 w-3.5" />
            Ask
          </Button>
        </form>
      </div>
    </section>
  );
}
