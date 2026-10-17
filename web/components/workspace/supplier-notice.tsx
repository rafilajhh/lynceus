"use client";

/**
 * SupplierNotice: the letter to the supplier after a refusal or a
 * declaration conflict, requested automatically when the verdict lands
 * (POST /inspections/{id}/notice). A language model drafts it from facts
 * taken only from the sealed record; if the draft states a number the facts
 * do not contain, the backend falls back to a fixed template. The tag says
 * which one wrote it.
 */

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { formatSeconds, providerName } from "@/lib/format";
import { requestNotice, type Followup, type NoticeBody } from "@/lib/ops-api";
import { useElapsedSeconds } from "@/lib/use-elapsed";
import { SourceTag } from "./block-head";
import { IconCopy } from "./gate-icons";
import { SealedLine, followupError } from "./sealed-line";

type State =
  | { kind: "drafting" }
  | { kind: "ready"; followup: Followup & { body: NoticeBody } }
  | { kind: "error"; message: string };

export function SupplierNotice({ recordId }: { recordId: string }) {
  const [state, setState] = useState<State>({ kind: "drafting" });
  const [copied, setCopied] = useState(false);
  const asked = useRef<string | null>(null);
  const seconds = useElapsedSeconds(state.kind === "drafting");

  const ask = () => {
    setState({ kind: "drafting" });
    requestNotice(recordId).then(
      (f) =>
        f.kind === "notice"
          ? setState({ kind: "ready", followup: f })
          : setState({ kind: "error", message: "The backend answered with a different follow-up kind." }),
      (err) => setState({ kind: "error", message: followupError(err) }),
    );
  };

  useEffect(() => {
    // Once per record, even if the effect runs twice in development.
    if (asked.current === recordId) return;
    asked.current = recordId;
    ask();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [recordId]);

  if (state.kind === "drafting") {
    return (
      <p role="status" className="figure m-0 inline-flex items-center gap-2 text-[12.5px] text-amber">
        <span aria-hidden="true" className="h-1.5 w-1.5 animate-[gate-pulse_1.1s_ease-in-out_infinite] rounded-full bg-amber" />
        Drafting the supplier notice from the sealed record · {seconds} s
      </p>
    );
  }

  if (state.kind === "error") {
    return (
      <div className="flex flex-wrap items-center gap-3">
        <p className="m-0 text-[13px] text-muted">{state.message}</p>
        <Button type="button" size="sm" onClick={ask}>
          Try again
        </Button>
      </div>
    );
  }

  const { body } = state.followup;
  const live = body.provenance === "live";
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(`To: ${body.to}\nSubject: ${body.subject}\n\n${body.text}`);
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch {
      setCopied(false);
    }
  };

  return (
    <div className="flex flex-col gap-2.5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="inline-flex flex-wrap items-center gap-2 text-[12px] text-muted">
          <SourceTag title={live ? "Drafted by a language model; every number checked against the record's facts." : "Fixed template: the model draft was unavailable or failed the number check."}>
            {live ? "AI draft" : "Template"}
          </SourceTag>
          {live ? (
            <span className="figure">
              {[body.model, body.provider ? `on ${providerName(body.provider)}` : null, formatSeconds(body.latency_ms)]
                .filter(Boolean)
                .join(" · ")}
            </span>
          ) : (
            <span>Numbers only from the sealed record</span>
          )}
        </span>
        <Button type="button" size="sm" onClick={() => void copy()} aria-live="polite">
          <IconCopy size={14} />
          {copied ? "Copied" : "Copy notice"}
        </Button>
      </div>
      <div className="rounded-[10px] border border-seam bg-ground px-4 py-3">
        <p className="m-0 text-[12.5px] text-muted">
          To <span className="text-ink">{body.to}</span>
        </p>
        <p className="m-0 mt-0.5 text-[13.5px] font-semibold text-ink">{body.subject}</p>
        <p className="m-0 mt-2 max-w-[75ch] text-[13.5px] leading-relaxed whitespace-pre-wrap text-ink">{body.text}</p>
      </div>
      {body.facts.length > 0 ? (
        <details className="group text-[12.5px] text-muted">
          <summary className="cursor-pointer select-none hover:text-ink">
            Grounded in {body.facts.length} facts from the record
          </summary>
          <ul className="figure m-0 mt-1.5 flex list-none flex-col gap-1 p-0 text-[12px]">
            {body.facts.map((f) => (
              <li key={f}>{f}</li>
            ))}
          </ul>
        </details>
      ) : null}
      <SealedLine followup={state.followup} />
    </div>
  );
}
