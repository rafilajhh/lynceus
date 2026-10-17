import type { EvalCard as EvalData } from "@/lib/control-api";
import { cn } from "@/lib/utils";
import { Panel, PanelHead } from "@/components/ui/panel";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { plainWords } from "./format";

/**
 * EvalCard: the shipped gate (vision model + CPU detector) against the vision
 * model alone on the same held-out RealWaste photos, then every fusion
 * variant the backend graded. Counts out of n, never a bare percentage. The
 * framing and the disclosure are the backend's own words, shown in full.
 */

type Count = { count?: number | null; n?: number | null } | null | undefined;

const ROWS: { key: string; label: string; question: string }[] = [
  { key: "metal_let_through", label: "Metal let through", question: "metal photos accepted with no human check" },
  { key: "clean_passed", label: "Clean loads passed", question: "clean-load photos accepted" },
  { key: "held_for_human", label: "Held for a human", question: "photos of any class held for review" },
];

const LIFT_COLUMNS = ["metal_let_through", "metal_rejected", "clean_passed", "held_for_human"] as const;

const LIFT_LABEL: Record<(typeof LIFT_COLUMNS)[number], string> = {
  metal_let_through: "Metal let through",
  metal_rejected: "Metal rejected",
  clean_passed: "Clean passed",
  held_for_human: "Held",
};

const CLASS_LABEL: Record<string, string> = { metal: "metal", glass_organic: "glass/organic", clean: "clean" };

function of(c: Count): string {
  return c && c.count != null && c.n != null ? `${c.count} of ${c.n}` : "—";
}

function Bar({ c, strong }: { c: Count; strong?: boolean }) {
  const share = c && c.count != null && c.n ? Math.min(1, c.count / c.n) : 0;
  return (
    <span aria-hidden="true" className="block h-1.5 w-full max-w-[160px] rounded-full bg-raised">
      <span
        className={cn("block h-full rounded-full", strong ? "bg-ink" : "bg-faint")}
        style={{ width: `${share * 100}%` }}
      />
    </span>
  );
}

function sentence(text: string): string {
  const t = text.trim();
  const head = plainWords(t.charAt(0).toUpperCase() + t.slice(1));
  return /[.!?]$/.test(head) ? head : `${head}.`;
}

/** The card's one claim, read off the counts so it can never outrun them. */
function evalHeadline(data: EvalData): string {
  const metal = data.card.metal_let_through;
  const held = data.card.held_for_human;
  const s = metal?.shipped?.count;
  const v = metal?.vlm_only?.count;
  const n = metal?.shipped?.n;
  if (s == null || v == null || n == null) return "The shipped gate against the vision model alone.";
  const moreHolds =
    held?.shipped?.count != null && held.vlm_only?.count != null && held.shipped.count > held.vlm_only.count
      ? `, at the cost of ${held.shipped.count - held.vlm_only.count} more holds for a human`
      : "";
  if (s < v) return `The shipped gate let ${s} of ${n} metal photos through where the vision model alone let ${v}${moreHolds}.`;
  return `The shipped gate let ${s} of ${n} metal photos through; the vision model alone let ${v}.`;
}

export function EvalCard({
  data,
  showFraming = true,
  className,
}: {
  data: EvalData | null;
  /** Off where the page already states the framing (/validation leads with it). */
  showFraming?: boolean;
  className?: string;
}) {
  if (!data) return null;
  const rows = ROWS.filter((r) => data.card[r.key]);
  const shippedVariant = data.fusion_lift.find((v) => v.variant.startsWith("hybrid"));

  return (
    <Panel className={className} aria-labelledby="eval-head">
      <PanelHead title="Shipped gate vs the vision model alone" meta="same held-out photos" />
      <div className="px-5 pt-4 pb-3">
        <h2 id="eval-head" className="m-0 text-[15px] leading-snug font-semibold text-ink">
          {evalHeadline(data)}
        </h2>
        {showFraming && data.framing ? (
          <p className="m-0 mt-1 text-[12.5px] text-muted">{sentence(data.framing)}</p>
        ) : null}
      </div>

      {rows.length > 0 ? (
        <dl className="m-0 grid grid-cols-1 gap-px border-y border-seam bg-seam md:grid-cols-3">
          {rows.map((row) => {
            const cell = data.card[row.key];
            return (
              <div key={row.key} className="flex min-w-0 flex-col gap-2.5 bg-panel px-5 py-4">
                <dt className="flex flex-col gap-0.5">
                  <span className="text-[13.5px] font-semibold text-ink">{row.label}</span>
                  <span className="text-[12px] text-faint">
                    {data.definitions[row.key] ? plainWords(data.definitions[row.key]) : row.question}
                  </span>
                </dt>
                <dd className="m-0 flex flex-col gap-1">
                  <span className="flex items-baseline justify-between gap-3">
                    <span className="text-[12.5px] font-semibold text-muted">Shipped gate</span>
                    <span className="figure text-[20px] leading-tight font-semibold text-ink">{of(cell?.shipped)}</span>
                  </span>
                  <Bar c={cell?.shipped} strong />
                </dd>
                <dd className="m-0 flex flex-col gap-1">
                  <span className="flex items-baseline justify-between gap-3">
                    <span className="text-[12.5px] text-muted">Vision model alone</span>
                    <span className="figure text-[15px] text-muted">{of(cell?.vlm_only)}</span>
                  </span>
                  <Bar c={cell?.vlm_only} />
                </dd>
              </div>
            );
          })}
        </dl>
      ) : null}

      {shippedVariant && Object.keys(shippedVariant.held_by_class).length > 0 ? (
        <p className="m-0 px-5 py-3 text-[12.5px] leading-relaxed text-muted">
          The shipped gate&apos;s holds by class:{" "}
          {Object.entries(shippedVariant.held_by_class)
            .map(([k, c]) => `${of(c)} ${CLASS_LABEL[k] ?? k.replace(/_/g, " ")}`)
            .join(", ")}
          . A hold on glass or organics is the intended outcome; a hold on a clean load is a false alarm.
        </p>
      ) : null}

      {data.fusion_lift.length > 0 ? (
        <details className="group border-t border-seam">
          <summary className="cursor-pointer px-5 py-2.5 text-[12.5px] font-semibold text-muted hover:text-ink">
            Every variant graded ({data.fusion_lift.length})
          </summary>
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Variant</TableHead>
                  {LIFT_COLUMNS.map((c) => (
                    <TableHead key={c} className="text-right whitespace-nowrap">
                      {LIFT_LABEL[c]}
                    </TableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.fusion_lift.map((v) => (
                  <TableRow key={v.variant}>
                    <TableCell className="min-w-[220px] align-top">
                      <span className="block text-[13px] font-semibold text-ink">{v.label || v.variant}</span>
                      {v.note ? <span className="block text-[12px] leading-snug text-faint">{v.note}</span> : null}
                    </TableCell>
                    {LIFT_COLUMNS.map((c) => (
                      <TableCell key={c} className="figure text-right align-top whitespace-nowrap">
                        {of(v[c])}
                      </TableCell>
                    ))}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </details>
      ) : null}

      {data.disclosure ? (
        <details className="group border-t border-seam px-5 py-2.5">
          <summary className="cursor-pointer text-[12.5px] font-semibold text-muted hover:text-ink">
            Disclosure: in-domain and optimistic
          </summary>
          <p className="m-0 mt-2 mb-1 text-[12.5px] leading-relaxed text-muted">{plainWords(data.disclosure)}</p>
          {data.definitions.classes ? (
            <p className="m-0 mb-1 text-[12.5px] leading-relaxed text-faint">{plainWords(data.definitions.classes)}</p>
          ) : null}
        </details>
      ) : null}
    </Panel>
  );
}
