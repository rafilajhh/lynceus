"use client";

import { useEffect, useId, useState } from "react";
import {
  Check,
  ChevronDown,
  CircleArrowUp,
  Copy,
  Send,
  ShieldCheck,
  TriangleAlert,
} from "lucide-react";
import {
  FOLLOWUP_NOTE_MAX,
  fetchActions,
  postAction,
  type FollowupAction,
  type FollowupKind,
} from "@/lib/followup-api";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";

/**
 * Follow-up on a sealed record: the append-only, hash-chained action log
 * (GET /inspections/{id}/actions) plus the two actions an operator can
 * take. The sealed record itself never changes; each POST appends an entry.
 */

type LogLoad =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ready"; actions: FollowupAction[]; chainOk: boolean };

const KIND_LABEL: Record<FollowupKind, string> = {
  notify_supplier: "Supplier notified",
  escalate: "Escalated",
};

const pad2 = (n: number) => String(n).padStart(2, "0");

/** "2026-10-17 16:40 UTC"; the raw string when it does not parse. */
function formatUtc(iso: string): string {
  const t = Date.parse(iso);
  if (!Number.isFinite(t)) return iso || "time not recorded";
  const d = new Date(t);
  return `${d.getUTCFullYear()}-${pad2(d.getUTCMonth() + 1)}-${pad2(d.getUTCDate())} ${pad2(d.getUTCHours())}:${pad2(d.getUTCMinutes())} UTC`;
}

function errorText(err: unknown, fallback: string): string {
  return err instanceof Error && err.message ? err.message : fallback;
}

export function FollowupCard({
  recordId,
  onLogged,
}: {
  recordId: string;
  /** Called after an action is appended, so the ledger can update its counts. */
  onLogged?: (action: FollowupAction) => void;
}) {
  const [log, setLog] = useState<LogLoad>({ kind: "loading" });
  const [retryCount, setRetryCount] = useState(0);
  const [note, setNote] = useState("");
  const [posting, setPosting] = useState<FollowupKind | null>(null);
  const [postError, setPostError] = useState<string | null>(null);
  const noteId = useId();
  const noteHintId = useId();

  useEffect(() => {
    const controller = new AbortController();
    setLog({ kind: "loading" });
    fetchActions(recordId, controller.signal)
      .then((data) => setLog({ kind: "ready", actions: data.actions, chainOk: data.chain_ok }))
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        setLog({ kind: "error", message: errorText(err, "Could not load the follow-up log.") });
      });
    return () => controller.abort();
  }, [recordId, retryCount]);

  const submit = async (kind: FollowupKind) => {
    if (posting) return;
    setPosting(kind);
    setPostError(null);
    try {
      const action = await postAction(recordId, kind, note);
      setLog((prev) =>
        prev.kind === "ready" ? { ...prev, actions: [...prev.actions, action] } : prev,
      );
      setNote("");
      onLogged?.(action);
    } catch (err) {
      setPostError(
        errorText(
          err,
          kind === "notify_supplier" ? "Could not notify the supplier." : "Could not escalate.",
        ),
      );
    } finally {
      setPosting(null);
    }
  };

  const actions = log.kind === "ready" ? log.actions : [];

  return (
    <section aria-label="Follow-up" className="card flex flex-col gap-3.5 p-5 md:p-6">
      <h2 className="eyebrow m-0">Follow-up</h2>

      {log.kind === "loading" ? (
        <p role="status" className="m-0 text-[13px] text-fg-muted">
          Loading the follow-up log…
        </p>
      ) : log.kind === "error" ? (
        <div role="alert" className="flex flex-col items-start gap-2">
          <p className="m-0 text-[13px] text-danger">{log.message}</p>
          <Button size="sm" onClick={() => setRetryCount((c) => c + 1)}>
            Retry
          </Button>
        </div>
      ) : (
        <>
          {actions.length > 0 ? (
            <ol className="m-0 flex list-none flex-col gap-2 p-0">
              {actions.map((action) => (
                <ActionEntry key={action.action_id || action.entry_sha256} action={action} />
              ))}
            </ol>
          ) : (
            <p className="m-0 text-[13px] text-fg-muted">
              No follow-up logged yet. Actions are appended to a hash-chained log; the sealed
              record is never changed.
            </p>
          )}
          {actions.length > 0 || !log.chainOk ? (
            log.chainOk ? (
              <p className="m-0 flex items-center gap-1.5 text-[12px] text-success">
                <ShieldCheck aria-hidden="true" className="h-3.5 w-3.5 shrink-0" />
                Log chain verified
              </p>
            ) : (
              <p className="m-0 flex items-start gap-1.5 text-[12px] text-warning">
                <TriangleAlert aria-hidden="true" className="mt-px h-3.5 w-3.5 shrink-0" />
                Log chain broken: an entry no longer matches the hash chain.
              </p>
            )
          ) : null}
        </>
      )}

      <div className="flex flex-col gap-1.5">
        <label htmlFor={noteId} className="text-[13px] font-medium text-fg">
          Note <span className="font-normal text-fg-subtle">(optional)</span>
        </label>
        <textarea
          id={noteId}
          value={note}
          onChange={(e) => setNote(e.target.value.slice(0, FOLLOWUP_NOTE_MAX))}
          maxLength={FOLLOWUP_NOTE_MAX}
          rows={3}
          disabled={posting !== null}
          aria-describedby={noteHintId}
          placeholder="Added to the log and to the supplier notice."
          className="w-full resize-y rounded-[8px] border border-line-strong bg-surface px-3 py-2 text-[13px] leading-[19px] text-fg placeholder:text-fg-faint focus:border-brand focus:outline-none disabled:opacity-60"
        />
        <span id={noteHintId} className="figure self-end text-[11px] text-fg-subtle">
          {note.length}/{FOLLOWUP_NOTE_MAX}
        </span>
      </div>

      {postError ? (
        <p role="alert" className="m-0 flex items-start gap-1.5 text-[13px] text-danger">
          <TriangleAlert aria-hidden="true" className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          {postError}
        </p>
      ) : null}

      <div className="flex flex-wrap gap-2">
        <Button
          variant="primary"
          disabled={posting !== null}
          aria-busy={posting === "notify_supplier"}
          onClick={() => void submit("notify_supplier")}
        >
          <Send aria-hidden="true" className="h-3.5 w-3.5" />
          {posting === "notify_supplier" ? "Notifying…" : "Notify supplier"}
        </Button>
        <Button
          variant="default"
          disabled={posting !== null}
          aria-busy={posting === "escalate"}
          onClick={() => void submit("escalate")}
        >
          <CircleArrowUp aria-hidden="true" className="h-3.5 w-3.5" />
          {posting === "escalate" ? "Escalating…" : "Escalate"}
        </Button>
      </div>
    </section>
  );
}

function ActionEntry({ action }: { action: FollowupAction }) {
  const [open, setOpen] = useState(false);
  const noticeId = useId();
  const Icon = action.kind === "notify_supplier" ? Send : CircleArrowUp;
  const delivery =
    action.kind !== "notify_supplier"
      ? null
      : action.delivery === "webhook"
        ? "Sent via webhook"
        : "Logged (not sent)";

  return (
    <li className="flex flex-col gap-1.5 rounded-[8px] bg-surface-subtle px-3 py-2.5">
      <div className="flex items-center gap-2">
        <Icon
          aria-hidden="true"
          className={cn(
            "h-3.5 w-3.5 shrink-0",
            action.kind === "notify_supplier" ? "text-brand" : "text-warning",
          )}
        />
        <span className="min-w-0 flex-1 text-[13px] font-medium text-fg">
          {KIND_LABEL[action.kind]}
        </span>
        <time dateTime={action.created_at_utc} className="figure shrink-0 text-[11px] text-fg-muted">
          {formatUtc(action.created_at_utc)}
        </time>
      </div>
      <p className="m-0 pl-[22px] text-[12px] leading-[17px] text-fg-muted">
        {[action.actor ? `by ${action.actor}` : null, delivery].filter(Boolean).join(" · ") ||
          "Logged"}
      </p>
      {action.delivery_error ? (
        <p className="m-0 pl-[22px] text-[12px] leading-[17px] text-warning">
          Delivery failed: {action.delivery_error}
        </p>
      ) : null}
      {action.note ? (
        <p className="m-0 pl-[22px] text-[13px] leading-[19px] break-words whitespace-pre-wrap text-fg">
          {action.note}
        </p>
      ) : null}
      {action.notice ? (
        <div className="pl-[22px]">
          <button
            type="button"
            aria-expanded={open}
            aria-controls={noticeId}
            onClick={() => setOpen((o) => !o)}
            className="inline-flex cursor-pointer items-center gap-1 text-[12px] font-medium text-brand hover:text-brand-deep"
          >
            <ChevronDown
              aria-hidden="true"
              className={cn("h-3.5 w-3.5 transition-transform duration-100", open && "rotate-180")}
            />
            {open ? "Hide notice" : "Show notice"}
          </button>
          {open ? (
            <div
              id={noticeId}
              className="mt-2 flex flex-col gap-2 rounded-[8px] border border-line-strong bg-surface p-3"
            >
              <dl className="m-0 flex flex-col gap-1 text-[12px]">
                <div className="flex gap-2">
                  <dt className="w-14 shrink-0 text-fg-muted">To</dt>
                  <dd className="m-0 min-w-0 break-words text-fg">{action.notice.to}</dd>
                </div>
                <div className="flex gap-2">
                  <dt className="w-14 shrink-0 text-fg-muted">Subject</dt>
                  <dd className="m-0 min-w-0 break-words text-fg">{action.notice.subject}</dd>
                </div>
              </dl>
              <pre className="m-0 max-h-[280px] overflow-auto font-sans text-[12px] leading-[18px] break-words whitespace-pre-wrap text-fg">
                {action.notice.body}
              </pre>
              <CopyNoticeButton
                text={`To: ${action.notice.to}\nSubject: ${action.notice.subject}\n\n${action.notice.body}`}
              />
            </div>
          ) : null}
        </div>
      ) : null}
    </li>
  );
}

function CopyNoticeButton({ text }: { text: string }) {
  const [status, setStatus] = useState<"idle" | "copied" | "failed">("idle");

  useEffect(() => {
    if (status === "idle") return;
    const timer = window.setTimeout(() => setStatus("idle"), 1600);
    return () => window.clearTimeout(timer);
  }, [status]);

  const copy = () => {
    if (!navigator.clipboard) {
      setStatus("failed");
      return;
    }
    navigator.clipboard.writeText(text).then(
      () => setStatus("copied"),
      () => setStatus("failed"),
    );
  };

  const label = status === "copied" ? "Copied" : status === "failed" ? "Copy failed" : "Copy";
  return (
    <>
      <Button size="sm" variant="default" className="self-start" onClick={copy}>
        {status === "copied" ? (
          <Check aria-hidden="true" className="h-3.5 w-3.5 text-success" />
        ) : (
          <Copy aria-hidden="true" className="h-3.5 w-3.5" />
        )}
        {label}
      </Button>
      <span aria-live="polite" className="sr-only">
        {status === "copied" ? "Notice copied" : status === "failed" ? "Copy failed" : ""}
      </span>
    </>
  );
}
