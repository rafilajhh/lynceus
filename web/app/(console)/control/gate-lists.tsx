import Link from "next/link";
import type { GateCard } from "@/lib/control-api";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Panel, PanelHead } from "@/components/ui/panel";
import { num, utcClock } from "@/components/ops/format";

/**
 * The gate's latest decisions and the held-loads worklist. Each row opens
 * the sealed record in the audit trail (/inspections?record=…), where the
 * supervisor decides a hold.
 */

/** Matches control.py HOLD_ALERT_MIN: a hold older than this is an alarm. */
const HOLD_ALERT_MIN = 20;

const VERDICT = {
  accept: { variant: "accept", label: "Accept" },
  escalate_human: { variant: "escalate", label: "Hold" },
  reject: { variant: "reject", label: "Reject" },
  refuse_insufficient_input: { variant: "refuse", label: "Refused" },
} as const;

const RESOLUTION: Record<string, string> = {
  accept: "Supervisor accepted",
  sort_then_accept: "Sorted, then accepted",
  reject: "Supervisor rejected",
  retake: "Photo retaken",
};

function VerdictBadge({ decision }: { decision: string }) {
  const v = VERDICT[decision as keyof typeof VERDICT];
  return <Badge variant={v?.variant ?? "default"}>{v?.label ?? decision.replace(/_/g, " ")}</Badge>;
}

const recordHref = (id: string) => `/inspections?record=${encodeURIComponent(id)}`;

function Marks({ card }: { card: GateCard }) {
  const marks = [
    card.resolution ? (RESOLUTION[card.resolution] ?? "Reviewed") : card.followups.reviewed ? "Reviewed" : null,
    card.followups.lab ? "Lab" : null,
    card.followups.notice ? "Notice" : null,
  ].filter((m): m is string => m !== null);
  if (marks.length === 0) return null;
  return (
    <span className="flex flex-wrap gap-1.5">
      {marks.map((m) => (
        <span
          key={m}
          className="rounded-full border border-seam-strong px-2 py-px text-[11px] font-semibold text-muted"
        >
          {m}
        </span>
      ))}
    </span>
  );
}

function CardRow({ card, held = false }: { card: GateCard; held?: boolean }) {
  const late = held && card.age_min != null && card.age_min > HOLD_ALERT_MIN;
  return (
    <li className="border-b border-seam last:border-b-0">
      <Link
        href={recordHref(card.record_id)}
        className="group flex flex-col gap-1.5 px-5 py-3 transition-colors duration-150 hover:bg-raised focus-visible:bg-raised"
      >
        <span className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
          <VerdictBadge decision={card.decision} />
          <span className="figure text-[13.5px] font-semibold text-ink">{card.truck_id ?? card.record_id}</span>
          <span className="min-w-0 truncate text-[13px] text-muted">{card.supplier}</span>
          <span className="ml-auto flex items-baseline gap-2 text-[12px]">
            {held && card.age_min != null ? (
              <span className={cn("figure font-semibold", late ? "text-verdict-amber" : "text-muted")}>
                waiting {num(card.age_min, 0)} min
              </span>
            ) : card.decision_s != null ? (
              <span className="figure text-faint">{num(card.decision_s)} s</span>
            ) : null}
            <span className="figure text-faint">{utcClock(card.at_utc)}</span>
          </span>
        </span>
        {card.why ? <span className="text-[13px] leading-snug text-ink/90">{card.why}</span> : null}
        <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <Marks card={card} />
          <span className="figure text-[11.5px] text-faint group-hover:text-muted">{card.record_id}</span>
        </span>
      </Link>
    </li>
  );
}

const unavailable = (
  <p className="m-0 px-5 py-6 text-[13px] text-muted">
    Needs <span className="figure">/control/summary</span>, which this backend does not serve. The{" "}
    <Link href="/inspections" className="text-amber underline underline-offset-2">
      audit trail
    </Link>{" "}
    lists every decision.
  </p>
);

export function GateQueue({
  cards: all,
  limit,
  className,
}: {
  cards: GateCard[] | null;
  limit?: number;
  className?: string;
}) {
  const cards = all && limit ? all.slice(0, limit) : all;
  return (
    <Panel className={className} aria-labelledby="queue-head">
      <PanelHead title="Gate" meta={cards ? `latest ${cards.length} decisions` : undefined} />
      <h2 id="queue-head" className="sr-only">
        Latest gate decisions
      </h2>
      {cards === null ? (
        unavailable
      ) : cards.length === 0 ? (
        <p className="m-0 px-5 py-6 text-[13px] text-muted">
          No decisions yet this shift. Run a truck in the{" "}
          <Link href="/app" className="text-amber underline underline-offset-2">
            Inspection console
          </Link>
          .
        </p>
      ) : (
        <>
          <ul className="m-0 flex list-none flex-col p-0">
            {cards.map((card) => (
              <CardRow key={card.record_id} card={card} />
            ))}
          </ul>
          <p className="m-0 border-t border-seam px-5 py-2.5 text-[13px]">
            <Link href="/inspections" className="text-amber underline underline-offset-2">
              Every decision in the audit trail
            </Link>
          </p>
        </>
      )}
    </Panel>
  );
}

export function HeldWorklist({ cards, className }: { cards: GateCard[] | null; className?: string }) {
  return (
    <Panel className={className} aria-labelledby="held-head">
      <PanelHead title="Waiting for a supervisor" meta={cards ? `${cards.length} held` : undefined} />
      <h2 id="held-head" className="sr-only">
        Held loads waiting for a supervisor
      </h2>
      {cards === null ? (
        unavailable
      ) : cards.length === 0 ? (
        <p className="m-0 px-5 py-5 text-[13px] leading-relaxed text-muted">
          No load is waiting. A hold the supervisor has not decided appears here; after {HOLD_ALERT_MIN} min it
          also raises an alarm.
        </p>
      ) : (
        <ul className="m-0 flex list-none flex-col p-0">
          {cards.map((card) => (
            <CardRow key={card.record_id} card={card} held />
          ))}
        </ul>
      )}
    </Panel>
  );
}
