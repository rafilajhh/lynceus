"use client";

/**
 * SupervisorActions: the human closes the loop on the AI's call, and the
 * decision is sealed onto the record (POST /inspections/{id}/resolution).
 *
 * - REJECT: confirm the refusal, or override it with a reason.
 * - HOLD: accept, sort then accept, or reject, with a note.
 * - ACCEPT: nothing to do; a spot-check can still be logged.
 * - REFUSED: record a retake.
 */

import { useId, useState } from "react";
import { Button } from "@/components/ui/button";
import {
  postResolution,
  type Followup,
  type ResolutionBody,
  type ResolutionDecision,
} from "@/lib/ops-api";
import { cn } from "@/lib/utils";
import { SealedLine, followupError } from "./sealed-line";
import type { VerdictTone } from "./verdict-banner";

const LABEL: Record<ResolutionDecision, string> = {
  accept: "Accept",
  sort_then_accept: "Sort, then accept",
  reject: "Reject",
  retake: "Retake photo",
};

const COPY: Record<VerdictTone, { lead: string; options: ResolutionDecision[]; quick?: ResolutionDecision; quickLabel?: string; openLabel?: string }> = {
  reject: {
    lead: "A supervisor confirms the refusal, or overrides it with a reason. Either way it is sealed onto this record.",
    options: ["accept", "sort_then_accept"],
    quick: "reject",
    quickLabel: "Confirm refusal",
    openLabel: "Override",
  },
  escalate: {
    lead: "Held for a supervisor. Decide after the checks the SOP steps ask for; the decision is sealed onto this record.",
    options: ["accept", "sort_then_accept", "reject"],
  },
  accept: {
    lead: "Cleared to tip: no hand check needed. A spot-check can still be logged against this record.",
    options: ["accept", "sort_then_accept", "reject"],
    openLabel: "Log a spot-check",
  },
  refuse: {
    lead: "No verdict was issued because an input is missing. Record the retake, then inspect again with the missing input.",
    options: [],
    quick: "retake",
    quickLabel: "Record a retake",
  },
  unknown: { lead: "Record what the supervisor decided.", options: ["accept", "sort_then_accept", "reject"] },
};

function agreementText(body: ResolutionBody): string {
  if (body.agrees_with_ai === true) return "Agrees with the AI";
  if (body.agrees_with_ai === false) return "Overrides the AI";
  return "Human call on a held truck";
}

export function SupervisorActions({ recordId, tone }: { recordId: string; tone: VerdictTone }) {
  const copy = COPY[tone];
  const [open, setOpen] = useState(copy.options.length > 0 && !copy.openLabel);
  const [choice, setChoice] = useState<ResolutionDecision | null>(null);
  const [note, setNote] = useState("");
  const [minutes, setMinutes] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sealed, setSealed] = useState<Followup | null>(null);
  const base = useId();
  // Overriding the AI needs a reason on the record.
  const overriding = tone === "reject" && choice !== null && choice !== "reject";

  const submit = async (decision: ResolutionDecision) => {
    if (overriding && !note.trim()) {
      setError("Give the reason for the override: it is sealed with the decision.");
      document.getElementById(`${base}-note`)?.focus();
      return;
    }
    setBusy(true);
    setError(null);
    const m = Number(minutes);
    try {
      const f = await postResolution(recordId, {
        decision,
        note: note.trim() || undefined,
        hand_check_minutes: minutes.trim() && Number.isFinite(m) && m >= 0 ? m : null,
      });
      setSealed(f);
    } catch (err) {
      setError(followupError(err));
    } finally {
      setBusy(false);
    }
  };

  if (sealed && sealed.kind === "resolution") {
    return (
      <div className="flex flex-col gap-2">
        <p className="m-0 text-[14px] text-ink">
          <span className="font-semibold">Supervisor: {LABEL[sealed.body.decision] ?? sealed.body.decision}</span>
          <span className="text-muted"> · {agreementText(sealed.body)}</span>
        </p>
        {sealed.body.note ? <p className="m-0 text-[13px] leading-snug text-muted">&ldquo;{sealed.body.note}&rdquo;</p> : null}
        <SealedLine followup={sealed} />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <p className="m-0 max-w-[62ch] text-[13px] leading-relaxed text-muted">{copy.lead}</p>

      <div className="flex flex-wrap items-center gap-2">
        {copy.quick ? (
          <Button type="button" variant="primary" disabled={busy} onClick={() => void submit(copy.quick!)}>
            {busy && !choice ? "Sealing…" : copy.quickLabel}
          </Button>
        ) : null}
        {copy.openLabel && !open ? (
          <Button type="button" onClick={() => setOpen(true)} disabled={busy}>
            {copy.openLabel}
          </Button>
        ) : null}
      </div>

      {open && copy.options.length > 0 ? (
        <fieldset className="m-0 flex flex-col gap-3 border-0 p-0">
          <legend className="sr-only">Supervisor decision</legend>
          <div role="radiogroup" aria-label="Decision" className="flex flex-wrap gap-1.5">
            {copy.options.map((o) => (
              <button
                key={o}
                type="button"
                role="radio"
                aria-checked={choice === o}
                onClick={() => setChoice(o)}
                disabled={busy}
                className={cn(
                  "cursor-pointer rounded-[6px] border px-3 py-1.5 text-[13px] font-semibold transition-colors duration-100 disabled:pointer-events-none disabled:opacity-50",
                  choice === o
                    ? "border-amber bg-amber-soft text-ink"
                    : "border-seam-strong bg-raised text-muted hover:border-amber-line hover:text-ink",
                )}
              >
                {LABEL[o]}
              </button>
            ))}
          </div>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-[minmax(0,1fr)_150px]">
            <div className="flex flex-col gap-1">
              <label htmlFor={`${base}-note`} className="text-[11px] font-semibold tracking-[0.6px] text-muted uppercase">
                Note {overriding ? "(required)" : "(optional)"}
              </label>
              <textarea
                id={`${base}-note`}
                rows={2}
                maxLength={500}
                value={note}
                onChange={(e) => setNote(e.target.value)}
                disabled={busy}
                className="input resize-y text-[13px] leading-snug"
                placeholder="What the hand check found"
              />
            </div>
            <div className="flex flex-col gap-1">
              <label htmlFor={`${base}-min`} className="text-[11px] font-semibold tracking-[0.6px] text-muted uppercase">
                Hand check, min
              </label>
              <input
                id={`${base}-min`}
                inputMode="decimal"
                value={minutes}
                onChange={(e) => setMinutes(e.target.value)}
                disabled={busy}
                className="input figure text-[13px]"
                placeholder="optional"
              />
            </div>
          </div>
          <div>
            <Button type="button" variant="primary" disabled={busy || !choice} onClick={() => choice && void submit(choice)}>
              {busy ? "Sealing…" : choice ? `Seal: ${LABEL[choice]}` : "Choose a decision"}
            </Button>
          </div>
        </fieldset>
      ) : null}

      {error ? (
        <p role="alert" className="m-0 text-[13px] text-verdict-red">
          {error}
        </p>
      ) : null}
    </div>
  );
}
