"use client";

/**
 * FollowupActions: the Next steps card footer on a sealed result (frame
 * HX9C5): "Notify supplier" and "Escalate". Each posts to the record's
 * append-only follow-up log (the sealed record itself never changes) and
 * confirms inline; actions already logged for this record are loaded on
 * mount so a revisit shows them.
 */

import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import { Check, Copy, Send, ShieldAlert, UserRound } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  FOLLOWUP_NOTE_MAX,
  fetchActions,
  postAction,
  type FollowupAction,
  type FollowupKind,
} from "@/lib/followup-api";

/** "16:40 UTC" from an ISO timestamp; empty when unparsable. */
function utcTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const hh = String(d.getUTCHours()).padStart(2, "0");
  const mm = String(d.getUTCMinutes()).padStart(2, "0");
  return `${hh}:${mm} UTC`;
}

function withTime(label: string, iso: string): string {
  const t = utcTime(iso);
  return t ? `${label} · ${t}` : label;
}

function lastOf(actions: FollowupAction[], kind: FollowupKind): FollowupAction | null {
  for (let i = actions.length - 1; i >= 0; i--) if (actions[i].kind === kind) return actions[i];
  return null;
}

function NoticeConfirmation({ action }: { action: FollowupAction }) {
  const [copied, setCopied] = useState(false);
  const notice = action.notice;
  const label =
    action.delivery === "webhook" ? "Sent via webhook" : "Notice logged";

  const copy = async () => {
    if (!notice) return;
    try {
      await navigator.clipboard.writeText(`${notice.subject}\n\n${notice.body}`);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    } catch {
      // clipboard blocked: the preview text stays selectable
    }
  };

  return (
    <div className="flex flex-col gap-2 rounded-[10px] bg-success-tint px-3.5 py-2.5">
      <p className="m-0 flex items-center gap-2 text-[13px] font-medium text-fg">
        <Check aria-hidden="true" className="h-3.5 w-3.5 shrink-0 text-success" />
        {withTime(label, action.created_at_utc)}
      </p>
      {action.delivery_error ? (
        <p className="m-0 text-[12px] text-fg-muted">
          Webhook delivery failed ({action.delivery_error}); the notice is logged.
        </p>
      ) : null}
      {notice ? (
        <details className="group text-[12px]">
          <summary className="cursor-pointer font-medium text-brand select-none hover:underline">
            Preview notice
          </summary>
          <div className="mt-2 flex flex-col gap-2 rounded-[8px] border border-line-strong bg-surface p-3">
            <div className="flex items-start justify-between gap-2">
              <div className="flex min-w-0 flex-col gap-0.5">
                <span className="text-fg-muted">To {notice.to}</span>
                <span className="font-medium break-words text-fg">{notice.subject}</span>
              </div>
              <Button
                type="button"
                size="sm"
                onClick={() => void copy()}
                className="h-7 shrink-0 px-2 text-[12px]"
              >
                {copied ? (
                  <Check aria-hidden="true" className="h-3 w-3" />
                ) : (
                  <Copy aria-hidden="true" className="h-3 w-3" />
                )}
                {copied ? "Copied" : "Copy"}
              </Button>
            </div>
            <pre className="m-0 max-h-56 overflow-auto font-sans text-[12px] leading-[18px] whitespace-pre-wrap text-fg-muted">
              {notice.body}
            </pre>
          </div>
        </details>
      ) : null}
    </div>
  );
}

function EscalateConfirmation({ action }: { action: FollowupAction }) {
  return (
    <div className="flex flex-col gap-1 rounded-[10px] bg-warning-tint px-3.5 py-2.5">
      <p className="m-0 flex items-center gap-2 text-[13px] font-medium text-fg">
        <ShieldAlert aria-hidden="true" className="h-3.5 w-3.5 shrink-0 text-warning" />
        {withTime("Escalated to supervisor", action.created_at_utc)}
      </p>
      {action.note ? (
        <p className="m-0 text-[12px] break-words text-fg-muted">“{action.note}”</p>
      ) : null}
    </div>
  );
}

export function FollowupActions({ recordId }: { recordId: string }) {
  const [actions, setActions] = useState<FollowupAction[]>([]);
  const [chainOk, setChainOk] = useState(true);
  const [posting, setPosting] = useState<FollowupKind | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [escalating, setEscalating] = useState(false);
  const [note, setNote] = useState("");
  const escalateRef = useRef<HTMLButtonElement>(null);
  const noteRef = useRef<HTMLTextAreaElement>(null);
  const noteId = useId();
  const countId = useId();

  // Actions already logged against this record (a revisit, a reload).
  useEffect(() => {
    const ctrl = new AbortController();
    fetchActions(recordId, ctrl.signal).then(
      (log) => {
        setActions(log.actions);
        setChainOk(log.chain_ok || log.actions.length === 0);
      },
      () => undefined, // no log yet / backend without follow-ups: buttons still work
    );
    return () => ctrl.abort();
  }, [recordId]);

  // Note box opens: focus it. Closes (confirmed or cancelled): focus
  // goes back to the Escalate button instead of falling to the page.
  const wasEscalating = useRef(false);
  useEffect(() => {
    if (escalating) noteRef.current?.focus();
    else if (wasEscalating.current) escalateRef.current?.focus();
    wasEscalating.current = escalating;
  }, [escalating]);

  const post = async (kind: FollowupKind, text?: string) => {
    setPosting(kind);
    setError(null);
    try {
      const action = await postAction(recordId, kind, text);
      setActions((prev) => [...prev, action]);
      if (kind === "escalate") {
        setEscalating(false);
        setNote("");
      }
    } catch (err) {
      setError(
        `${kind === "escalate" ? "Escalation" : "Supplier notice"} failed: ${
          err instanceof Error ? err.message : "unexpected error"
        }`,
      );
    } finally {
      setPosting(null);
    }
  };

  const cancelEscalate = () => {
    setEscalating(false);
    setNote("");
  };

  const onNoteKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Escape") {
      e.preventDefault();
      cancelEscalate();
    } else if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      if (!posting) void post("escalate", note);
    }
  };

  const notified = lastOf(actions, "notify_supplier");
  const escalated = lastOf(actions, "escalate");
  const busy = posting !== null;

  return (
    <div className="flex w-full min-w-0 flex-col gap-3">
      <div className="flex gap-2">
        <Button
          type="button"
          variant="primary"
          className="min-w-0 flex-1"
          disabled={busy}
          onClick={() => void post("notify_supplier")}
        >
          <Send aria-hidden="true" className="h-3.5 w-3.5" />
          {posting === "notify_supplier"
            ? "Notifying…"
            : notified
              ? "Notify again"
              : "Notify supplier"}
        </Button>
        <Button
          ref={escalateRef}
          type="button"
          className="shrink-0"
          disabled={busy}
          aria-expanded={escalating}
          aria-controls={escalating ? noteId : undefined}
          onClick={() => {
            setError(null);
            setEscalating(true);
          }}
        >
          <UserRound aria-hidden="true" className="h-3.5 w-3.5" />
          Escalate
        </Button>
      </div>

      {escalating ? (
        <div className="flex flex-col gap-2 rounded-[10px] border border-line-strong bg-surface-subtle p-3">
          <label htmlFor={noteId} className="text-[12px] font-medium text-fg-muted">
            Note for the supervisor (optional)
          </label>
          <textarea
            id={noteId}
            ref={noteRef}
            rows={2}
            maxLength={FOLLOWUP_NOTE_MAX}
            value={note}
            onChange={(e) => setNote(e.target.value)}
            onKeyDown={onNoteKey}
            disabled={busy}
            aria-describedby={countId}
            placeholder="What should the supervisor look at?"
            className="w-full resize-y rounded-[8px] border border-line-strong bg-surface px-3 py-2 text-[13px] text-fg placeholder:text-fg-faint focus-visible:border-brand focus-visible:outline-none disabled:opacity-50"
          />
          <div className="flex items-center justify-between gap-2">
            <span id={countId} className="text-[11px] text-fg-subtle">
              <span className="figure">
                {note.length}/{FOLLOWUP_NOTE_MAX}
              </span>{" "}
              · Enter to escalate, Esc to cancel
            </span>
            <div className="flex shrink-0 gap-1.5">
              <Button type="button" variant="ghost" size="sm" onClick={cancelEscalate} disabled={busy}>
                Cancel
              </Button>
              <Button
                type="button"
                variant="primary"
                size="sm"
                onClick={() => void post("escalate", note)}
                disabled={busy}
              >
                {posting === "escalate" ? "Escalating…" : "Escalate"}
              </Button>
            </div>
          </div>
        </div>
      ) : null}

      {error ? (
        <p
          role="alert"
          className="m-0 rounded-[8px] border border-danger/25 bg-danger-tint px-3 py-2 text-[12.5px] text-danger"
        >
          {error}
        </p>
      ) : null}

      <div role="status" aria-live="polite" className="flex flex-col gap-2 empty:hidden">
        {notified ? <NoticeConfirmation action={notified} /> : null}
        {escalated ? <EscalateConfirmation action={escalated} /> : null}
        {!chainOk ? (
          <p className="m-0 text-[12px] text-warning">
            The follow-up log for this record failed its integrity check.
          </p>
        ) : null}
      </div>
    </div>
  );
}
