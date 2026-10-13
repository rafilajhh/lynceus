"use client";

/**
 * PythiaPanel: the gate assistant. Answers only from the plant documents
 * (reference gate SOP, regulation notes) and, when a record id is given,
 * that truck's audit record. Every answer shows the sources it cites and
 * how it was produced (live model + latency, or extractive quote); an
 * answer the backend could not ground is shown as such, never dressed up.
 */

import { useCallback, useEffect, useId, useRef, useState, type FormEvent } from "react";
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
    <p className="m-0 flex items-center gap-2 text-[13px] text-muted">
      <span
        aria-hidden="true"
        className="h-2 w-2 shrink-0 animate-[gate-pulse_1.1s_ease-in-out_infinite] rounded-full bg-amber"
      />
      Checking the plant documents…
      {/* aria-hidden: a ticking clock inside the live region would be
          re-announced every second */}
      <span className="figure text-[12px] text-faint" aria-hidden="true">
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
      <p className={cn("m-0 text-[14px] leading-relaxed", grounded ? "text-ink" : "text-muted")}>
        {response.answer || "No answer returned."}
      </p>
      {grounded ? (
        <ul aria-label="Sources cited" className="m-0 flex list-none flex-wrap gap-1.5 p-0">
          {response.citations.map((id) => (
            <li
              key={id}
              title={citationTitle(id, recordId)}
              className="figure rounded-[4px] border border-seam-strong bg-raised px-1.5 py-0.5 text-[12px] text-ink"
            >
              {id}
            </li>
          ))}
        </ul>
      ) : (
        <p className="m-0 text-[12px] text-faint">No source cited: not answered from the documents.</p>
      )}
      <p className="figure m-0 text-[11px] text-faint">{provenanceLine(response.provenance)}</p>
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
    <section
      aria-labelledby={headingId}
      className={cn("flex flex-col rounded-[10px] border border-seam", className)}
    >
      <header className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 border-b border-seam px-4 py-3">
        <h3 id={headingId} className="smallcaps m-0">
          Ask Pythia
        </h3>
        <span className="text-[12px] text-muted">
          Answers only from the gate SOP, regulation notes
          {recordId ? " and this audit record" : ""}, with sources.
        </span>
      </header>

      <div aria-live="polite" className="flex flex-col">
        {turns.map((turn) => (
          <div key={turn.id} className="flex flex-col gap-2 border-b border-seam px-4 py-3">
            <p className="m-0 text-[13px] font-semibold text-muted">{turn.question}</p>
            {turn.status === "pending" ? (
              <PendingLine />
            ) : turn.status === "error" ? (
              <p role="alert" className="m-0 text-[13px] text-verdict-red">
                {turn.message}
              </p>
            ) : (
              <Answer response={turn.response} recordId={recordId} />
            )}
          </div>
        ))}
      </div>

      <div className="flex flex-col gap-3 px-4 py-3">
        {suggestions.length > 0 ? (
          <div className="flex flex-wrap gap-2" role="group" aria-label="Suggested questions">
            {suggestions.map((s) => (
              <Button
                key={s}
                type="button"
                variant="default"
                size="sm"
                disabled={pending}
                onClick={() => void ask(s)}
                className="text-left font-medium"
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
            placeholder="Ask about this truck or the gate SOP"
            autoComplete="off"
          />
          <Button type="submit" variant="default" disabled={pending || !draft.trim()}>
            Ask
          </Button>
        </form>
      </div>
    </section>
  );
}
