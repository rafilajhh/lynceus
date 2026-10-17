"use client";

import { useEffect, useState } from "react";
import {
  OpsError,
  chainFailed,
  fetchFollowups,
  knownAmount,
  type Followup,
  type FollowupsResponse,
} from "@/lib/ops-api";
import { formatRupiah } from "@/lib/format";
import { plainWords } from "@/components/ops/format";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";

/**
 * The human loop after a verdict, as sealed: supervisor decision, lab
 * result, supplier notice. Each follow-up is its own SHA-256 record chained
 * to the inspection record and to the follow-up before it; the backend
 * re-verifies the chain on every read and the state is shown as it says.
 */

type ChainLoad =
  | { kind: "loading" }
  | { kind: "absent" }
  | { kind: "error"; message: string }
  | { kind: "ready"; data: FollowupsResponse };

const KIND_LABEL: Record<Followup["kind"], string> = {
  resolution: "Supervisor decision",
  lab_result: "Lab result",
  notice: "Supplier notice",
};

const DECISION_LABEL: Record<string, string> = {
  accept: "Accept",
  sort_then_accept: "Sort, then accept",
  reject: "Reject",
  retake: "Retake the photo",
};

const AI_LABEL: Record<string, string> = {
  accept: "ACCEPT",
  reject: "REJECT",
  escalate_human: "HOLD",
  refuse_insufficient_input: "REFUSED",
};

function short(digest: string | null | undefined): string {
  const clean = (digest ?? "").replace(/^sha256:/, "");
  return clean.length > 12 ? `${clean.slice(0, 12)}…` : clean || "—";
}

/** "2026-10-17T09:14:03Z" → "17 Oct 09:14 UTC". */
function when(iso: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(iso);
  if (!m) return iso;
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  return `${Number(m[3])} ${months[Number(m[2]) - 1] ?? m[2]} ${m[4]}:${m[5]} UTC`;
}

const rp = formatRupiah;

/** Example settlement tiers (GET /contract settlement_tiers). */
const SETTLEMENT_NAME: Record<string, string> = { A: "Premium", B: "Base", C: "Deductions" };

export function FollowupChain({ recordId }: { recordId: string }) {
  const [state, setState] = useState<ChainLoad>({ kind: "loading" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setState({ kind: "loading" });
    fetchFollowups(recordId)
      .then((data) => {
        if (!cancelled) setState({ kind: "ready", data });
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        // The record itself loaded, so a 404 here means this backend has
        // no follow-up service: the section stays out of the way.
        if (err instanceof OpsError && err.status === 404) setState({ kind: "absent" });
        else setState({ kind: "error", message: err instanceof Error ? err.message : "Unexpected error." });
      });
    return () => {
      cancelled = true;
    };
  }, [recordId, attempt]);

  if (state.kind === "absent") return null;

  const followups = state.kind === "ready" ? state.data.followups : [];
  const chain = state.kind === "ready" ? state.data.chain : null;
  const failed = chain ? chainFailed(chain) : false;
  const truncated = chain ? chain.problems.some((p) => /truncat/i.test(p)) : false;
  const sealed = `${followups.length} sealed ${followups.length === 1 ? "record" : "records"}`;

  return (
    <section aria-labelledby={`chain-${recordId}`}>
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h3 id={`chain-${recordId}`} className="smallcaps m-0">
          After the verdict
        </h3>
        {chain && followups.length > 0 ? (
          <span
            className={cn(
              "inline-flex items-center gap-1.5 text-[12px] font-semibold",
              failed ? "text-verdict-red" : "text-muted",
            )}
          >
            <span
              aria-hidden="true"
              className={cn("h-1.5 w-1.5 rounded-full", failed ? "bg-dot-down" : "bg-dot-ok")}
            />
            {failed
              ? truncated
                ? "Chain truncated: sealed follow-ups are missing from the end"
                : "Chain broken: a follow-up was altered or removed"
              : `${chain.anchored ? "Chain anchored" : "Chain verified"} · ${sealed}`}
          </span>
        ) : null}
      </div>
      {chain && followups.length > 0 && chain.notes.length > 0 ? (
        <ul className="m-0 mb-2 flex list-none flex-col gap-0.5 p-0 text-[12px] text-faint">
          {chain.notes.map((note) => (
            <li key={note}>{plainWords(note)}</li>
          ))}
        </ul>
      ) : null}

      {state.kind === "loading" ? (
        <div role="status" className="rounded-[8px] border border-seam bg-ground px-3.5 py-3">
          <span className="sr-only">Loading follow-ups</span>
          <div
            aria-hidden="true"
            className="h-4 w-[55%] animate-[gate-pulse_1.1s_ease-in-out_infinite] rounded-[4px] bg-raised"
          />
        </div>
      ) : state.kind === "error" ? (
        <div role="alert" className="flex flex-wrap items-center justify-between gap-3 rounded-[8px] border border-seam bg-ground px-3.5 py-3">
          <p className="m-0 text-[13px] text-muted">Follow-ups could not be loaded. {state.message}</p>
          <Button size="sm" onClick={() => setAttempt((n) => n + 1)}>
            Retry
          </Button>
        </div>
      ) : followups.length === 0 ? (
        <p className="m-0 rounded-[8px] border border-seam bg-ground px-3.5 py-3 text-[13px] leading-relaxed text-muted">
          Nothing sealed after the verdict yet. A supervisor decision, a lab result or a supplier
          notice recorded in the Inspection console is chained to this record and listed here.
        </p>
      ) : (
        <>
          {chain && failed && chain.problems.length > 0 ? (
            <ul className="m-0 mb-2 list-disc pl-5 text-[12.5px] text-verdict-red">
              {chain.problems.map((p) => (
                <li key={p}>{p}</li>
              ))}
            </ul>
          ) : null}
          <ol className="m-0 flex list-none flex-col p-0">
            {followups.map((f, i) => (
              <li key={f.digest || `${f.kind}-${f.seq}`} className="relative flex gap-3 pb-3 last:pb-0">
                {/* the chain: a hairline from each sealed step to the next */}
                <span aria-hidden="true" className="relative flex w-3 shrink-0 justify-center">
                  <span className="mt-[7px] h-2 w-2 rounded-full border border-seam-strong bg-raised" />
                  {i < followups.length - 1 ? (
                    <span className="absolute top-[17px] bottom-[-5px] w-px bg-seam-strong" />
                  ) : null}
                </span>
                <div className="flex min-w-0 flex-1 flex-col gap-1 rounded-[8px] border border-seam bg-ground px-3.5 py-2.5">
                  <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-0.5">
                    <span className="text-[13px] font-semibold text-ink">{KIND_LABEL[f.kind] ?? f.kind}</span>
                    <span className="figure text-[11.5px] text-faint">
                      {f.actor} · {when(f.created_at_utc)}
                    </span>
                  </div>
                  <FollowupBody followup={f} />
                  <span className="figure text-[11.5px] text-faint" title={f.digest}>
                    sha256 {short(f.digest)}
                    {f.previous_digest ? ` · after ${short(f.previous_digest)}` : ` · after record ${short(f.parent_record_digest)}`}
                  </span>
                </div>
              </li>
            ))}
          </ol>
        </>
      )}
    </section>
  );
}

function FollowupBody({ followup }: { followup: Followup }) {
  if (followup.kind === "resolution") {
    const b = followup.body;
    const ai = AI_LABEL[String(b.ai_decision)] ?? String(b.ai_decision).toUpperCase();
    const stance =
      b.agrees_with_ai === null
        ? `AI held the truck (${ai}); a person made the call`
        : b.agrees_with_ai
          ? `Confirms the AI verdict (${ai})`
          : `Overrides the AI verdict (${ai})`;
    return (
      <div className="flex flex-col gap-0.5 text-[13px] text-muted">
        <span>
          <span className="font-semibold text-ink">{DECISION_LABEL[b.decision] ?? b.decision}</span> · {stance}
          {typeof b.hand_check_minutes === "number" ? ` · ${b.hand_check_minutes} min hand check` : ""}
        </span>
        {b.note ? <span className="text-[12.5px]">“{b.note}”</span> : null}
      </div>
    );
  }
  if (followup.kind === "lab_result") {
    const b = followup.body;
    const ev = b.contract_eval;
    // A "warning" breach (chlorine near the limit) has no price effect: it is
    // listed as a warning, never as a breach.
    const penalties = ev ? ev.breaches.filter((br) => br.severity !== "warning") : [];
    const warnings = ev ? ev.breaches.filter((br) => br.severity === "warning") : [];
    const isoCode = ev?.iso21640?.code ?? null;
    const isoLabel = ev?.iso21640?.label ?? null;
    const tier = ev?.tier ? (SETTLEMENT_NAME[ev.tier] ? `${ev.tier} · ${SETTLEMENT_NAME[ev.tier]}` : ev.tier) : null;
    // No weighbridge ticket: money is null, never shown as Rp 0 or NaN.
    const settles = knownAmount(ev?.settlement_idr);
    const payable = knownAmount(ev?.payable_idr);
    const deducted = knownAmount(ev?.deduction_idr);
    const unweighed =
      ev && (ev.weight_measured === false || payable === null)
        ? (ev.settlement_note ?? "Weight not measured: settlement needs the weighbridge ticket.")
        : null;
    return (
      <div className="flex flex-col gap-1 text-[13px] text-muted">
        <span className="figure text-[12.5px] text-ink">
          Moisture {b.moisture_pct} % · NCV {b.ncv_mj_kg} MJ/kg · Chlorine {b.chlorine_pct} %
          {typeof b.ash_pct === "number" ? ` · Ash ${b.ash_pct} %` : ""}
        </span>
        {isoCode ? (
          <span className="text-[12.5px]">
            ISO 21640 class <span className="figure text-ink">{isoCode}</span>
            {isoLabel ? <span className="text-faint">: {isoLabel}</span> : null}
          </span>
        ) : null}
        {tier ? (
          <span className="text-[12.5px]">
            Settlement tier <span className="font-semibold text-ink">{tier}</span>
            {settles !== null ? (
              <>
                {" "}· settles at <span className="figure text-ink">{rp(settles)}</span>
              </>
            ) : null}
            {ev?.tier_reason ? <span className="block text-faint">{ev.tier_reason}</span> : null}
          </span>
        ) : null}
        {ev ? (
          ev.refused === true ? (
            <span className="font-semibold text-verdict-red">Refused under the contract.</span>
          ) : penalties.length === 0 ? (
            <span>Within contract spec: paid at {rp(ev.base_price_idr_per_t)}/t.</span>
          ) : (
            <>
              <ul className="m-0 list-disc pl-5 text-[12.5px]">
                {penalties.map((br) => (
                  <li key={br.param}>{br.effect}</li>
                ))}
              </ul>
              <span>
                Price {rp(ev.adjusted_price_idr_per_t)}/t ({ev.adjustment_pct > 0 ? "+" : ""}
                {ev.adjustment_pct} %)
                {payable !== null ? (
                  <>
                    {" "}· payable <span className="figure text-ink">{rp(payable)}</span>
                  </>
                ) : null}
                {deducted !== null && deducted > 0 ? (
                  <>
                    {" "}· deducted <span className="figure font-semibold text-ink">{rp(deducted)}</span>
                  </>
                ) : null}
              </span>
            </>
          )
        ) : null}
        {unweighed ? <span className="text-[12.5px] text-muted">{unweighed}</span> : null}
        {warnings.map((br) => (
          <span key={`warn-${br.param}`} className="text-[12.5px] text-verdict-amber">
            {br.effect}
          </span>
        ))}
        <span className="figure text-[11.5px] text-faint">
          {[b.sample_id, b.lab].filter(Boolean).join(" · ")}
        </span>
      </div>
    );
  }
  const b = followup.body;
  return (
    <div className="flex flex-col gap-1 text-[13px] text-muted">
      <span>
        To <span className="text-ink">{b.to}</span>: <span className="text-ink">{b.subject}</span>
      </span>
      <details className="group">
        <summary className="cursor-pointer text-[12.5px] font-semibold text-ink transition-colors duration-100 select-none hover:text-amber">
          Read the notice
        </summary>
        <p className="m-0 mt-1.5 max-w-[80ch] text-[12.5px] leading-relaxed whitespace-pre-line">{b.text}</p>
      </details>
      <span className="figure text-[11.5px] text-faint">
        {b.provenance === "live"
          ? `Drafted live · ${[b.model, b.provider === "amd-token-factory" ? "AMD Token Factory" : b.provider].filter(Boolean).join(" · ")}`
          : "Template · built from the sealed record's facts"}
      </span>
    </div>
  );
}
