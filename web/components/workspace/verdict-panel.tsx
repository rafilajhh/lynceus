"use client";

/**
 * VerdictPanel: one truck's decision, top to bottom in the order the gate
 * acts on it:
 *
 * 1. Banner (ACCEPT / HOLD FOR REVIEW / REJECT · DO NOT TIP), the one
 *    sentence why, what ran, and the checks strip. These fit one viewport.
 * 2. Evidence (photos with marked regions, frame tabs) beside the
 *    declared-vs-observed table and the SOP next steps.
 * 3. What the decision was worth (time, money with its basis).
 * 4. Closing the loop: supervisor decision, supplier notice, lab sample,
 *    each sealed onto the record.
 * 5. The sealed record itself, the rule notes, and Pythia.
 */

import { forwardRef, useCallback, useMemo, useState, type ReactNode } from "react";
import { PythiaPanel, pythiaSuggestions } from "@/components/assist/pythia-panel";
import { Button } from "@/components/ui/button";
import { Panel, PanelHead } from "@/components/ui/panel";
import { ChecksStrip } from "@/components/checks/checks-strip";
import { DecisionReceipt } from "./decision-receipt";
import { DeclaredObserved } from "./declared-observed";
import { EngineNotes, ProvenanceNote } from "./engine-notes";
import { EvidenceFrames } from "./evidence-frames";
import { LabSample } from "./lab-sample";
import { NextSteps } from "./next-steps";
import { SealedRecord } from "./sealed-record";
import { SensorsRow } from "./sensors-row";
import { SupervisorActions } from "./supervisor-actions";
import { SupplierNotice } from "./supplier-notice";
import { cn } from "@/lib/utils";
import type { RunState } from "./use-inspection";
import { ValueStrip } from "./value-strip";
import { VerdictBanner, verdictTone } from "./verdict-banner";
import { checksOf, voteAgreement, type VoteAgreement } from "./vision-findings";

const THIRD_READ: Record<string, string> = {
  arrived: "the third arrived in time",
  late: "the third did not return in time",
  failed: "the third failed",
};

/** "Vision reads 3/3 agree" or the split, and early-majority honesty. */
function VoteLine({ votes }: { votes: VoteAgreement | null }) {
  if (!votes) return null;
  return (
    <p className="m-0 flex flex-wrap items-baseline gap-x-2 text-[13px]">
      <span className="font-semibold text-muted">Vision</span>
      <span className={cn("font-semibold", votes.split ? "text-amber" : "text-ink")}>{votes.label}</span>
      {votes.split ? <span className="text-muted">A split vote is never a reject on its own: a person checks.</span> : null}
      {votes.early && votes.early.thirdRead !== "arrived" ? (
        <span className="text-muted">
          Decided on {votes.early.votesUsed} agreeing reads
          {votes.early.thirdRead ? `; ${THIRD_READ[votes.early.thirdRead] ?? votes.early.thirdRead}` : ""}.
        </span>
      ) : null}
    </p>
  );
}

function Section({ title, aside, children }: { title: string; aside?: ReactNode; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-3 border-t border-seam px-4 py-4" aria-label={title}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="smallcaps m-0">{title}</h3>
        {aside}
      </div>
      {children}
    </section>
  );
}

export const VerdictPanel = forwardRef<HTMLElement, { run: RunState; onNextTruck: () => void }>(
  function VerdictPanel({ run, onNextTruck }, ref) {
    const data = run.result!;
    const snapshot = run.snapshot!;
    const decision = data.verdict?.decision ?? data.decision;
    const tone = verdictTone(decision);
    const checks = useMemo(() => checksOf(data), [data]);
    const votes = useMemo(() => voteAgreement(data), [data]);
    // Lit per run id, not reset by an effect: the strip resolves inside its
    // own effect (at once under reduced motion), which runs before ours.
    const [litRun, setLitRun] = useState<RunState["runId"] | null>(null);
    const lit = litRun === run.runId;
    const runId = run.runId;
    const onAllLit = useCallback(() => setLitRun(runId), [runId]);

    const recordId = data.record_id ?? null;
    const declarationConflict = checks.some((c) => c.key === "declaration" && c.status === "fail");
    const wantsNotice = Boolean(recordId) && (tone === "reject" || declarationConflict);

    return (
      // Unlit, the panel holds a viewport of room so the scroll that brings
      // it in can reach the top before its content has expanded.
      <Panel
        ref={ref}
        aria-labelledby="verdict-title"
        className={cn("scroll-mt-3", !lit && "min-h-[calc(100dvh-110px)]")}
      >
        <PanelHead title="Verdict">
          <Button type="button" size="sm" variant="ghost" onClick={onNextTruck} className="-my-1">
            Next truck
          </Button>
        </PanelHead>
        <h2 id="verdict-title" className="sr-only">
          Inspection verdict
        </h2>

        <div className="flex flex-col gap-4 px-4 py-4">
          <VerdictBanner tone={tone} data={data} lit={lit} recordId={recordId} elapsedMs={run.elapsedMs} />
          <ProvenanceNote data={data} />
          <ChecksStrip
            checks={checks}
            showDetail
            label="Gate checks"
            runKey={run.runId}
            onAllResolved={onAllLit}
            emptyText="This backend returned no checks for the verdict."
          />
          <VoteLine votes={votes} />
        </div>

        {lit ? (
          <>
            <div className="grid grid-cols-1 gap-5 border-t border-seam px-4 py-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
              <EvidenceFrames
                frames={snapshot.frames}
                data={data}
                sourceNote={
                  data.provenance === "stub"
                    ? "Scripted sample"
                    : data.provenance === "stub_fallback_live_error"
                      ? "Scripted fallback"
                      : null
                }
              />
              <div className="flex min-w-0 flex-col gap-5">
                <DeclaredObserved data={data} snapshot={snapshot} />
                <NextSteps steps={data.actions} emptyText="The backend returned no next steps." />
              </div>
            </div>

            {data.receipt.length > 0 ? (
              <div className="border-t border-seam px-4 py-4">
                <DecisionReceipt receipt={data.receipt} />
              </div>
            ) : null}

            <div className="border-t border-seam px-4 py-4">
              <SensorsRow observations={data.observations} />
            </div>

            <Section title="What this decision was worth">
              <ValueStrip tone={tone} elapsedMs={run.elapsedMs} impact={data.impact} runKey={run.runId} />
            </Section>

            {recordId ? (
              <>
                <Section title="Supervisor decision">
                  <SupervisorActions key={recordId} recordId={recordId} tone={tone} />
                </Section>
                {wantsNotice ? (
                  <Section
                    title="Supplier notice"
                    aside={
                      <span className="text-[12px] text-faint">
                        {declarationConflict ? "Declaration conflict" : "Load refused"}: drafted automatically
                      </span>
                    }
                  >
                    <SupplierNotice key={recordId} recordId={recordId} />
                  </Section>
                ) : null}
                <Section title="Lab sample">
                  <LabSample key={recordId} recordId={recordId} sampling={data.sampling} />
                </Section>
              </>
            ) : null}

            <Section title="Sealed record">
              <SealedRecord data={data} />
              <EngineNotes data={data} />
            </Section>

            <div className="border-t border-seam px-4 py-4">
              <PythiaPanel
                key={recordId ?? "no-record"}
                recordId={recordId ?? undefined}
                suggestions={pythiaSuggestions(decision)}
              />
            </div>

            <div className="flex justify-end border-t border-seam px-4 py-3">
              <Button type="button" onClick={onNextTruck}>
                Clear the gate for the next truck
              </Button>
            </div>
          </>
        ) : null}
      </Panel>
    );
  },
);
