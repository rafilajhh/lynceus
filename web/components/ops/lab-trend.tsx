import type { LabPoint, LabTrend } from "@/lib/control-api";
import { cn } from "@/lib/utils";
import { Panel, PanelHead } from "@/components/ui/panel";
import { num, utcClock } from "./format";

/**
 * LabTrend: the last lab results as three small multiples (moisture, NCV,
 * chlorine), one dot per sampled truck in time order, against the contract
 * spec the backend sends. The out-of-spec side of each limit is shaded; a dot
 * past the limit is amber, a chlorine dot in the warning band is an amber
 * ring (a warning carries no price effect). Inline SVG, no chart library.
 */

type ParamKey = "moisture_pct" | "ncv_mj_kg" | "chlorine_pct";

interface Param {
  key: ParamKey;
  label: string;
  unit: string;
  digits: number;
}

const PARAMS: Param[] = [
  { key: "moisture_pct", label: "Moisture", unit: "%", digits: 1 },
  { key: "ncv_mj_kg", label: "NCV", unit: "MJ/kg", digits: 1 },
  { key: "chlorine_pct", label: "Chlorine (dry)", unit: "%", digits: 2 },
];

interface Spec {
  limit: number | null;
  /** "max": higher is worse; "min": lower is worse. */
  dir: "max" | "min";
  warn: number | null;
}

/** Spec keys are "<param>_max", "<param>_min" and "<param>_warn". */
function specFor(spec: Record<string, number>, key: ParamKey): Spec {
  const max = spec[`${key}_max`];
  const min = spec[`${key}_min`];
  const warn = spec[`${key}_warn`];
  if (typeof max === "number") return { limit: max, dir: "max", warn: typeof warn === "number" ? warn : null };
  if (typeof min === "number") return { limit: min, dir: "min", warn: typeof warn === "number" ? warn : null };
  return { limit: null, dir: "max", warn: null };
}

type Zone = "ok" | "warn" | "out";

function zoneOf(v: number, s: Spec): Zone {
  if (s.limit !== null && (s.dir === "max" ? v > s.limit : v < s.limit)) return "out";
  if (s.warn !== null && (s.dir === "max" ? v > s.warn : v < s.warn)) return "warn";
  return "ok";
}

const W = 300;
const H = 104;
const PAD_X = 8;
const PAD_Y = 10;

function Multiple({ param, points, spec }: { param: Param; points: LabPoint[]; spec: Spec }) {
  const values = points
    .map((p, i) => ({ p, i, v: p[param.key] }))
    .filter((d): d is { p: LabPoint; i: number; v: number } => typeof d.v === "number");
  const fmt = (v: number) => `${num(v, param.digits)} ${param.unit}`;
  const sign = spec.dir === "max" ? "≤" : "≥";
  const out = values.filter((d) => zoneOf(d.v, spec) === "out").length;
  const latest = values.at(-1);

  if (values.length === 0) {
    return (
      <figure className="m-0 flex flex-col gap-2 bg-panel px-4 py-3.5">
        <figcaption className="text-[13px] font-semibold text-ink">{param.label}</figcaption>
        <p className="m-0 text-[12.5px] text-faint">No lab results yet.</p>
      </figure>
    );
  }

  const domain = [...values.map((d) => d.v), spec.limit, spec.warn].filter(
    (v): v is number => typeof v === "number",
  );
  let lo = Math.min(...domain);
  let hi = Math.max(...domain);
  const span = hi - lo || Math.abs(hi) || 1;
  lo -= span * 0.15;
  hi += span * 0.15;
  const n = points.length;
  const x = (i: number) => (n <= 1 ? W / 2 : PAD_X + (i / (n - 1)) * (W - PAD_X * 2));
  const y = (v: number) => PAD_Y + (1 - (v - lo) / (hi - lo)) * (H - PAD_Y * 2);
  const path = values.map((d, k) => `${k === 0 ? "M" : "L"}${x(d.i).toFixed(1)} ${y(d.v).toFixed(1)}`).join(" ");
  const limitY = spec.limit !== null ? y(spec.limit) : null;
  const warnY = spec.warn !== null ? y(spec.warn) : null;

  const summary = `${param.label}, last ${values.length} lab results: latest ${latest ? fmt(latest.v) : "none"}${
    spec.limit !== null ? `, spec ${sign} ${fmt(spec.limit)}, ${out} out of spec` : ", no spec stated"
  }.`;

  return (
    <figure className="m-0 flex min-w-0 flex-col gap-2 bg-panel px-4 pt-3.5 pb-3">
      <figcaption className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5">
        <span className="text-[13px] font-semibold text-ink">{param.label}</span>
        <span className="text-[12px] text-faint">
          {spec.limit !== null ? (
            <>
              spec <span className="figure text-muted">{sign} {fmt(spec.limit)}</span>
            </>
          ) : (
            "no spec in the contract"
          )}
        </span>
      </figcaption>
      <p className="m-0 flex items-baseline gap-2">
        <span
          className={cn(
            "figure text-[22px] leading-none font-semibold",
            latest && zoneOf(latest.v, spec) !== "ok" ? "text-verdict-amber" : "text-ink",
          )}
        >
          {latest ? num(latest.v, param.digits) : "—"}
        </span>
        <span className="figure text-[12px] text-faint">{param.unit} latest</span>
        <span className="ml-auto text-[12px] text-muted">
          <span className="figure">{out}</span> of <span className="figure">{values.length}</span> out
        </span>
      </p>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="block h-auto w-full overflow-visible"
        role="img"
        aria-label={summary}
      >
        {limitY !== null ? (
          <rect
            x={0}
            width={W}
            y={spec.dir === "max" ? 0 : limitY}
            height={spec.dir === "max" ? limitY : H - limitY}
            className="fill-[color-mix(in_srgb,var(--color-amber)_7%,transparent)]"
          />
        ) : null}
        <line x1={0} x2={W} y1={H - 0.5} y2={H - 0.5} className="stroke-seam" strokeWidth={1} />
        {warnY !== null ? (
          <line
            x1={0}
            x2={W}
            y1={warnY}
            y2={warnY}
            className="stroke-faint"
            strokeWidth={1}
            strokeDasharray="2 3"
            vectorEffect="non-scaling-stroke"
          />
        ) : null}
        {limitY !== null ? (
          <line
            x1={0}
            x2={W}
            y1={limitY}
            y2={limitY}
            className="stroke-amber"
            strokeOpacity={0.7}
            strokeWidth={1}
            strokeDasharray="5 3"
            vectorEffect="non-scaling-stroke"
          />
        ) : null}
        <path d={path} fill="none" className="stroke-seam-strong" strokeWidth={1.25} vectorEffect="non-scaling-stroke" />
        {values.map((d, k) => {
          const zone = zoneOf(d.v, spec);
          const last = k === values.length - 1;
          return (
            <circle
              key={`${d.p.record_id}-${k}`}
              cx={x(d.i)}
              cy={y(d.v)}
              r={last ? 4 : 3}
              strokeWidth={1.5}
              className={cn(
                zone === "out" && "fill-verdict-amber stroke-verdict-amber",
                zone === "warn" && "fill-panel stroke-verdict-amber",
                zone === "ok" && (last ? "fill-ink stroke-ink" : "fill-muted stroke-muted"),
              )}
            >
              <title>
                {`${fmt(d.v)} · ${d.p.supplier} · ${d.p.record_id} · ${utcClock(d.p.at_utc, true)}${
                  d.p.tier ? ` · settlement tier ${d.p.tier}` : ""
                }`}
              </title>
            </circle>
          );
        })}
      </svg>
    </figure>
  );
}

export function LabTrendPanel({ trend, className }: { trend: LabTrend | null; className?: string }) {
  const points = trend?.points ?? [];
  return (
    <Panel className={className} aria-labelledby="lab-trend-head">
      <PanelHead title="Lab trend" meta={points.length > 0 ? `last ${points.length} results` : undefined} />
      <h2 id="lab-trend-head" className="sr-only">
        Lab trend against the contract spec
      </h2>
      {trend === null ? (
        <p className="m-0 px-5 py-6 text-[13px] text-muted">
          The lab trend needs <span className="figure">/control/summary</span>, which this backend does not
          serve.
        </p>
      ) : points.length === 0 ? (
        <p className="m-0 px-5 py-6 text-[13px] text-muted">
          No lab results yet. A sampled truck&apos;s result appears here once the lab posts it.
        </p>
      ) : (
        <>
          <div className="grid grid-cols-1 gap-px bg-seam sm:grid-cols-3">
            {PARAMS.map((param) => (
              <Multiple key={param.key} param={param} points={points} spec={specFor(trend.spec, param.key)} />
            ))}
          </div>
          <p className="m-0 flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-seam px-5 py-2.5 text-[12px] text-faint">
            <span className="inline-flex items-center gap-1.5">
              <svg width="10" height="10" aria-hidden="true">
                <circle cx="5" cy="5" r="3.5" className="fill-verdict-amber" />
              </svg>
              out of spec
            </span>
            {PARAMS.some((p) => specFor(trend.spec, p.key).warn !== null) ? (
              <span className="inline-flex items-center gap-1.5">
                <svg width="10" height="10" aria-hidden="true">
                  <circle cx="5" cy="5" r="3.5" strokeWidth="1.5" className="fill-panel stroke-verdict-amber" />
                </svg>
                warning band (no price effect)
              </span>
            ) : null}
            <span>One dot per sampled truck, oldest left. Spec from the contract.</span>
          </p>
        </>
      )}
    </Panel>
  );
}
