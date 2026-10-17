"use client";

/**
 * ShiftBriefing: the shift handover, drafted by Pythia from the sealed
 * records. The facts are collected by code; the assist model only words them,
 * and every number it writes is checked against those facts. A draft that
 * fails the check (or no live model) gives the template briefing, labelled
 * as such. The supervisor can copy it as text or seal it (stored with a
 * digest, traceable to the facts it was written from).
 */

import { useEffect, useId, useRef, useState } from "react";
import { GroundedBadge, SourceChip } from "@/components/assist/pythia-panel";
import { Button } from "@/components/ui/button";
import {
  AssistError,
  briefingText,
  draftBriefing,
  sealBriefing,
  type BriefingDraft,
  type BriefingWindow,
  type SealedBriefing,
} from "@/lib/assist-api";
import { liveProvenance } from "@/lib/format";
import { useElapsedSeconds } from "@/lib/use-elapsed";
import { cn } from "@/lib/utils";

type State =
  | { status: "idle" }
  | { status: "drafting" }
  | { status: "ready"; draft: BriefingDraft }
  | { status: "error"; message: string };

const WINDOW_LABEL: Record<BriefingWindow, string> = {
  shift: "last 8 h",
  day: "last 24 h",
  all: "whole ledger",
};

function hhmm(ts: string | null | undefined): string {
  return ts && ts.length >= 16 ? ts.slice(11, 16) : "–";
}

function Drafting() {
  const seconds = useElapsedSeconds(true);
  return (
    <p className="m-0 flex items-center gap-2 px-4 py-3 text-[13px] text-muted">
      <span
        aria-hidden="true"
        className="h-2 w-2 shrink-0 animate-[gate-pulse_1.1s_ease-in-out_infinite] rounded-full bg-amber"
      />
      Collecting the shift&apos;s records and drafting the handover…
      <span className="figure text-[12px] text-faint" aria-hidden="true">
        {seconds} s
      </span>
    </p>
  );
}

export function ShiftBriefing({
  window = "shift",
  className,
}: {
  /** Which records the handover covers: the last 8 h (default), 24 h, or all. */
  window?: BriefingWindow;
  className?: string;
}) {
  const [state, setState] = useState<State>({ status: "idle" });
  const [sealed, setSealed] = useState<SealedBriefing | null>(null);
  const [sealError, setSealError] = useState<string | null>(null);
  const [sealing, setSealing] = useState(false);
  const [copied, setCopied] = useState(false);
  const inflight = useRef<AbortController | null>(null);
  const headingId = useId();

  useEffect(() => () => inflight.current?.abort(), []);

  const draft = async () => {
    if (state.status === "drafting") return;
    const controller = new AbortController();
    inflight.current?.abort();
    inflight.current = controller;
    setState({ status: "drafting" });
    setSealed(null);
    setSealError(null);
    setCopied(false);
    try {
      const result = await draftBriefing(window, controller.signal);
      setState({ status: "ready", draft: result });
    } catch (err) {
      if (controller.signal.aborted) return;
      setState({
        status: "error",
        message: err instanceof AssistError ? err.message : "The handover could not be drafted.",
      });
    }
  };

  const copy = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  };

  const seal = async (d: BriefingDraft) => {
    if (sealing || sealed) return;
    setSealing(true);
    setSealError(null);
    try {
      setSealed(await sealBriefing(d));
    } catch (err) {
      setSealError(err instanceof AssistError ? err.message : "The handover could not be sealed.");
    } finally {
      setSealing(false);
    }
  };

  const b = state.status === "ready" ? state.draft.briefing : null;

  return (
    <section aria-labelledby={headingId} className={cn("flex flex-col rounded-[10px] border border-seam", className)}>
      <header className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-b border-seam px-4 py-3">
        <div className="flex flex-col gap-0.5">
          <h3 id={headingId} className="smallcaps m-0">
            Shift handover
          </h3>
          <span className="text-[12px] text-muted">
            Pythia drafts it from the sealed records ({WINDOW_LABEL[window]}); every number is checked against them.
          </span>
        </div>
        <Button
          type="button"
          variant={b ? "default" : "primary"}
          size="sm"
          aria-disabled={state.status === "drafting"}
          onClick={() => void draft()}
          className="aria-disabled:cursor-not-allowed aria-disabled:opacity-50"
        >
          {b ? "Redraft" : "Draft handover"}
        </Button>
      </header>

      <div aria-live="polite">
        {state.status === "drafting" ? <Drafting /> : null}
        {state.status === "error" ? (
          <p role="alert" className="m-0 px-4 py-3 text-[13px] text-verdict-red">
            {state.message}
          </p>
        ) : null}
      </div>

      {b ? (
        <div className="flex flex-col">
          <div className="flex flex-wrap items-center gap-2 border-b border-seam px-4 py-2 text-[12px] text-muted">
            <GroundedBadge grounded={b.grounded} />
            <span className="figure rounded-[4px] border border-seam-strong px-1.5 py-0.5 text-[11px] text-ink">
              {b.mode === "live" ? "Live draft" : "Template"}
            </span>
            <span className="figure text-[11px] text-faint">
              {b.mode === "live"
                ? liveProvenance(b.provider ?? "unknown", b.model, b.latency_ms)
                : (b.note ?? "Template briefing built from the records")}
            </span>
            <span className="figure text-[11px] text-faint">
              {hhmm(b.window.since)}–{hhmm(b.window.until)} UTC
            </span>
          </div>

          {b.sections.map((s) => (
            <div key={s.title} className="flex flex-col gap-1.5 border-b border-seam px-4 py-3">
              <h4 className="m-0 text-[12.5px] font-semibold tracking-[0.2px] text-muted">{s.title}</h4>
              {s.items.length === 0 ? (
                <p className="m-0 text-[13px] text-faint">Nothing to report.</p>
              ) : (
                <ul className="m-0 flex list-none flex-col gap-1.5 p-0">
                  {s.items.map((item, i) => (
                    <li key={i} className="flex flex-col gap-1">
                      <span className="text-[13.5px] leading-relaxed text-ink">{item.text}</span>
                      {item.citations.length > 0 ? (
                        <span className="flex flex-wrap gap-1.5">
                          {item.citations.map((c) => (
                            <SourceChip key={`${c.kind}:${c.id}`} source={c} />
                          ))}
                        </span>
                      ) : null}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ))}

          <div className="flex flex-wrap items-center gap-2 px-4 py-3">
            <Button type="button" size="sm" onClick={() => void copy(briefingText(b))}>
              {copied ? "Copied" : "Copy as text"}
            </Button>
            <Button
              type="button"
              size="sm"
              aria-disabled={sealing || sealed !== null}
              onClick={() => state.status === "ready" && void seal(state.draft)}
              className="aria-disabled:cursor-not-allowed aria-disabled:opacity-50"
            >
              {sealed ? "Sealed" : sealing ? "Sealing…" : "Sign off and seal"}
            </Button>
            <span className="figure text-[11px] text-faint" title="sha256 of the facts this briefing was written from">
              Facts {b.facts_digest.slice(0, 19)}…
            </span>
            {sealed ? (
              <span className="figure text-[11px] text-verdict-green">
                {sealed.briefing_id} sealed by {sealed.actor} · {sealed.digest.slice(0, 19)}…
              </span>
            ) : null}
            {sealError ? (
              <span role="alert" className="text-[12px] text-verdict-red">
                {sealError}
              </span>
            ) : null}
          </div>
        </div>
      ) : null}
    </section>
  );
}
