import type { AmdLive, AmdMeasured } from "@/lib/control-api";
import { cn } from "@/lib/utils";
import { Panel, PanelHead } from "@/components/ui/panel";
import { MONTHS, num, plainWords, utcParts } from "./format";

/**
 * AmdPanel: what one measured run on AMD Token Factory gave
 * (backend/benchmark amd_throughput): time per inspection with its 3 reads
 * in parallel, the speed-up over reading them one after another, tokens,
 * read agreement, and the metal detector on the benchmark laptop's AMD CPU.
 * Measured numbers only, each with its window and sample size.
 */

const PROVIDER: Record<string, string> = { "amd-token-factory": "AMD Token Factory" };

/**
 * The benchmark machine, verified: "AMD64 Family 25 Model 117" is the Ryzen 5
 * 8645HS laptop CPU. Any other AMD CPU stays generic; anything else as given.
 */
function cpuName(cpu: string | null | undefined): string {
  if (!cpu) return "CPU";
  if (/family 25 model 117\b/i.test(cpu)) return "AMD Ryzen 5 8645HS (laptop CPU)";
  return /authenticamd/i.test(cpu) ? "AMD CPU" : cpu;
}

const seconds = (ms: number | null | undefined) =>
  ms === null || ms === undefined ? null : `${num(ms / 1000, ms >= 10_000 ? 0 : 1)} s`;

/** "17 Oct 2026, 16:01–16:22 UTC" from the run's start and end. */
function runWindow(start: string | null | undefined, end: string | null | undefined): string | null {
  const a = utcParts(start);
  const b = utcParts(end);
  const year = /^(\d{4})/.exec(start ?? "")?.[1];
  if (!a) return null;
  const day = `${a.day}${year ? ` ${year}` : ""}`;
  if (!b) return `${day}, ${a.time} UTC`;
  return a.day === b.day ? `${day}, ${a.time}–${b.time} UTC` : `${day} ${a.time} – ${b.day} ${b.time} UTC`;
}

/** "2026-10-17" → "17 Oct 2026". */
function runDay(iso: string | null | undefined): string | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso ?? "");
  return m ? `${Number(m[3])} ${MONTHS[Number(m[2]) - 1] ?? m[2]} ${m[1]}` : null;
}

interface Cell {
  key: string;
  label: string;
  value: string | null;
  source: string;
}

export function AmdPanel({
  measured,
  live,
  compact = false,
  className,
}: {
  measured: AmdMeasured | null;
  live?: AmdLive | null;
  /** Two columns (beside another panel) instead of three. */
  compact?: boolean;
  className?: string;
}) {
  if (!measured) {
    return (
      <Panel className={className}>
        <PanelHead title="Inference on AMD" />
        <p className="m-0 px-5 py-6 text-[13px] text-muted">
          No AMD benchmark run is stored on this backend
          (<span className="figure">backend/benchmark/amd_throughput.py</span> writes one).
        </p>
      </Panel>
    );
  }

  const h = measured.headline;
  const latency = h?.inspection_latency_ms;
  const agreement = h?.read_agreement;
  const unanimous = agreement?.["3/3"];
  const detector = measured.detector_cpu;
  const provider =
    measured.provider_label ?? PROVIDER[measured.provider ?? ""] ?? measured.provider ?? "AMD Token Factory";
  const window = runWindow(measured.started_at_utc, measured.finished_at_utc);

  const cells: Cell[] = [
    {
      key: "latency",
      label: "Time per inspection, 3 reads in parallel",
      value:
        latency?.p50 != null
          ? `${seconds(latency.p50)}${latency.p95 != null ? ` · p95 ${seconds(latency.p95)}` : ""}`
          : null,
      source: `median and 95th percentile${latency?.n != null ? ` · n ${latency.n} inspections` : ""}`,
    },
    {
      key: "speedup",
      label: "Parallel speed-up",
      value: h?.parallel_speedup != null ? `×${num(h.parallel_speedup, 2)}` : null,
      source: "the 3 reads at once vs one after another, median time per inspection",
    },
    {
      key: "tokens",
      label: "Tokens per inspection",
      value: h?.tokens_per_inspection?.p50 != null ? num(h.tokens_per_inspection.p50, 0) : null,
      source:
        h?.tokens_per_inspection?.p95 != null
          ? `median · p95 ${num(h.tokens_per_inspection.p95, 0)} · prompt + answer, 3 reads`
          : "median, 3 reads",
    },
    {
      key: "agreement",
      label: "Read agreement, 3 of 3",
      value: unanimous?.share != null ? `${num(unanimous.share * 100, 0)} %` : null,
      source:
        unanimous?.count != null && agreement?.n != null
          ? `${unanimous.count} of ${agreement.n} inspections: all 3 reads named the same hard items`
          : "all 3 reads agreed",
    },
    {
      key: "detector",
      label: "Metal detector on CPU",
      value: detector?.inference_ms?.p50 != null ? `${num(detector.inference_ms.p50, 0)} ms` : null,
      source: [
        "median",
        detector?.inference_ms?.p95 != null ? `p95 ${num(detector.inference_ms.p95, 0)} ms` : null,
        `${detector?.runtime ?? "onnxruntime"} on ${cpuName(detector?.cpu)}`,
      ]
        .filter(Boolean)
        .join(" · "),
    },
    {
      key: "run",
      label: "Calls measured",
      value: h?.calls != null ? num(h.calls, 0) : null,
      source: [
        window ?? runDay(measured.run_date),
        h?.retries != null ? `${num(h.retries, 0)} retries` : null,
        h?.errors != null ? `${num(h.errors, 0)} errors` : null,
      ]
        .filter(Boolean)
        .join(" · "),
    },
  ];
  const shown = cells.filter((c) => c.value !== null);
  const liveP50 = live && (live.count ?? 0) > 0 ? live.vlm_latency_ms?.p50 : null;

  return (
    <Panel className={className} aria-labelledby="amd-head">
      <PanelHead title="Inference on AMD" meta={runDay(measured.run_date ?? measured.started_at_utc) ?? undefined} />
      <div className="px-5 pt-4 pb-4">
        <h2 id="amd-head" className="m-0 text-[15px] leading-snug font-semibold text-ink">
          {measured.model ?? "The vision model"} on {provider}, measured
        </h2>
        <p className="m-0 mt-1 text-[12.5px] leading-relaxed text-muted">
          One run{window ? ` on ${window}` : ""}
          {h?.calls != null ? `, ${num(h.calls, 0)} calls` : ""}. Each inspection is a vote of 3 reads of the same
          photo.
        </p>
      </div>

      {shown.length > 0 ? (
        <dl
          className={cn(
            "m-0 grid grid-cols-1 gap-px border-t border-seam bg-seam sm:grid-cols-2",
            compact ? null : "lg:grid-cols-3",
          )}
        >
          {shown.map((cell) => (
            <div key={cell.key} className="flex min-w-0 flex-col gap-1 bg-panel px-5 py-3.5">
              <dt className="text-[12.5px] font-semibold text-muted">{cell.label}</dt>
              <dd className="figure m-0 text-[22px] leading-tight font-semibold text-ink">{cell.value}</dd>
              <dd className="m-0 text-[12px] leading-snug text-faint">{cell.source}</dd>
            </div>
          ))}
        </dl>
      ) : null}

      {liveP50 != null || measured.cost?.token_factory?.note ? (
        <div className="flex flex-col gap-1 border-t border-seam px-5 py-3 text-[12px] leading-relaxed text-faint">
          {liveP50 != null ? (
            <p className="m-0">
              Live gate: vision vote median <span className="figure text-muted">{seconds(liveP50)}</span>{" "}
              over the last {live?.count} inspections.
            </p>
          ) : null}
          {measured.cost?.token_factory?.note ? <p className="m-0">{measured.cost.token_factory.note}</p> : null}
        </div>
      ) : null}

      {measured.caveats.length > 0 ? (
        <details className="group border-t border-seam px-5 py-2.5">
          <summary className="cursor-pointer text-[12.5px] font-semibold text-muted hover:text-ink">
            How it was measured ({measured.caveats.length} caveats)
          </summary>
          <ul className="m-0 mt-2 mb-1 flex list-disc flex-col gap-1.5 pl-5 text-[12.5px] leading-relaxed text-muted">
            {measured.caveats.map((c) => (
              <li key={c}>{plainWords(c)}</li>
            ))}
          </ul>
        </details>
      ) : null}
    </Panel>
  );
}
