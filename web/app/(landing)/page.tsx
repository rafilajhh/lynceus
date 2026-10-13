import Image from "next/image";
import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { buttonVariants } from "@/components/ui/button";
import { CountUpFigure } from "@/components/landing/count-up-figure";

export const metadata = { title: "One hidden metal chunk can stop a cement kiln" };

/**
 * Route: /: landing (Persuade for judges).
 *
 * Direction contract (.impeccable/surface-briefs/web-app.md):
 * graphite-dark ground, hairline seams, IBM Plex, one amber accent,
 * mono figures. Every number on screen answers "from where?" with a
 * source line (PRODUCT.md principle #1): figures come from
 * docs/research/realcase-indonesia.md.
 *
 * No kicker/eyebrow, no hero-metric grid: the first viewport states
 * the problem, not the product name.
 */

const PROOF_FIGURES = [
  {
    target: 350,
    prefix: "Rp ",
    suffix: " jt",
    decimals: 0,
    label: "One industrial shredder destroyed by a single metal contaminant",
    labelSuffix: "≈ US$22k",
    source: "RDI 2024, Lampiran 2A, Banyumas RDF plant unit cost",
    grow: "lg:w-[1.25fr]",
  },
  {
    target: 28,
    prefix: "US$",
    suffix: "k/hr",
    decimals: 0,
    label: "Cement kiln unplanned downtime, per hour of lost clinker",
    labelSuffix: "≈ Rp 450 jt",
    source: "oxmaint US cement benchmark @ Rp 16,000/USD",
    grow: "lg:w-[1fr]",
  },
  {
    target: 5.2,
    prefix: "",
    suffix: " t/trip",
    decimals: 1,
    label: "Typical arm-roll load that must be inspected before tipping",
    labelSuffix: "TPA Benowo weighbridge",
    source: "ITATS Surabaya, 14 m³ × 372.71 kg/m³",
    grow: "lg:w-[0.85fr]",
  },
] as const;

const STEPS = [
  {
    no: "01",
    title: "Capture",
    text: "At the weighbridge the operator submits the load photo, the waybill text, and the net weight: the same fields a PUPR gate form already records.",
    gate: "gate · intake complete",
  },
  {
    no: "02",
    title: "Analyze",
    text: "A vision-language model on AMD Instinct MI300X reads the load for contaminants and moisture, cross-checks the waybill claim, and a physics digital twin tests gas and weight plausibility.",
    gate: "gate · VLM + twin resolved",
  },
  {
    no: "03",
    title: "Decide",
    text: "Fusion issues ACCEPT / ESCALATE / REJECT with reasons and confidence, sealed into a tamper-evident SHA-256 audit record per truck.",
    gate: "gate · verdict sealed",
  },
] as const;

export default function LandingPage() {
  return (
    <div className="flex flex-col gap-0 pb-6">
      {/* ============ HERO: the problem, not the product ============ */}
      <section
        aria-labelledby="hero-headline"
        className="grid items-center gap-10 border-b border-seam py-10 lg:grid-cols-[1.15fr_0.85fr] lg:gap-14 lg:py-16"
      >
        <div className="flex flex-col items-start">
          <h1
            id="hero-headline"
            className="max-w-[16ch] text-[clamp(28px,4.4vw,46px)] leading-[1.08] font-bold tracking-[-0.015em] text-ink"
          >
            One hidden metal chunk can stop a cement kiln.
          </h1>
          <p className="mt-5 max-w-[56ch] text-[15px] leading-[1.65] text-muted sm:text-[17px]">
            Lynceus inspects every RDF truck at the gate, before tipping:
            visual contaminant detection, waybill cross-check, and a route
            verdict in seconds, sealed to a tamper-evident audit record.
          </p>
          <div className="mt-8 flex w-full flex-col gap-3 sm:w-auto sm:flex-row">
            <Link
              href="/app"
              className={buttonVariants({ variant: "primary", size: "lg" })}
            >
              Open Inspection Console
            </Link>
            <Link href="/inspections" className={buttonVariants({ size: "lg" })}>
              View Audit Trail
            </Link>
          </div>
        </div>

        {/* Proof photo panel: the contaminant, framed like the AI sees it */}
        <figure className="panel m-0 flex flex-col self-start">
          <div className="relative">
            <Image
              src="/demo/red-2.jpg"
              alt="Rusted industrial steel bolt, the kind of metal contaminant that destroys an RDF shredder"
              width={524}
              height={524}
              className="block h-auto max-h-[340px] w-full object-cover lg:max-h-[420px]"
              priority
            />
            {/* AI-detection frame: the product's gaze on the evidence */}
            <span
              aria-hidden="true"
              className="pointer-events-none absolute inset-[18%] border-2 border-dashed border-verdict-red/70"
            />
            <span
              aria-hidden="true"
              className="figure absolute top-[12%] left-[12%] rounded-[4px] bg-red-dim px-2 py-0.5 text-[11px] font-semibold tracking-[0.5px] text-verdict-red uppercase"
            >
              metal · reject
            </span>
          </div>
          <figcaption className="flex flex-col gap-1 border-t border-seam px-4 py-3">
            <span className="figure text-xs text-muted">
              Metal contaminant, REJECT case: one bolt can kill a shredder
            </span>
            <span className="figure text-[11px] text-muted">
              Real waste-stream photo (RealWaste, CC BY 4.0)
            </span>
          </figcaption>
        </figure>
      </section>

      {/* ============ PROOF STRIP: real numbers, sourced ============ */}
      <section
        aria-labelledby="proof-label"
        className="border-b border-seam py-12 lg:py-16"
      >
        <h2 id="proof-label" className="smallcaps mb-8">
          What one missed truck costs
        </h2>
        {/* Composition, not cards: unequal columns split by hairline seams.
            items-start + mt-auto on the source line keep the three hairline
            dividers on one baseline despite unequal copy lengths. */}
        <div className="flex flex-col gap-8 lg:flex-row lg:items-stretch lg:gap-0">
          {PROOF_FIGURES.map((f, i) => (
            <div
              key={f.label}
              className={[
                "flex flex-col gap-2",
                f.grow,
                i > 0 ? "lg:border-l lg:border-seam lg:pl-10" : "lg:pr-10",
              ].join(" ")}
            >
              <CountUpFigure
                target={f.target}
                prefix={f.prefix}
                suffix={f.suffix}
                decimals={f.decimals}
                className="figure text-[clamp(34px,4.5vw,56px)] leading-none font-semibold tracking-[-0.01em] text-ink"
              />
              <p className="max-w-[26ch] text-[14px] leading-snug text-muted">
                {f.label}
                {f.labelSuffix ? (
                  <span className="figure mt-0.5 block text-[12px] text-faint">
                    {f.labelSuffix}
                  </span>
                ) : null}
              </p>
              <p className="figure mt-auto max-w-[42ch] border-t border-seam pt-2 text-[11px] leading-[1.5] text-muted">
                {f.source}
              </p>
            </div>
          ))}
        </div>
      </section>

      {/* ============ HOW IT WORKS: three process gates ============ */}
      <section aria-labelledby="how-label" className="py-12 lg:py-16">
        <h2 id="how-label" className="smallcaps mb-8">
          How a truck is cleared, gate by gate
        </h2>
        <ol className="m-0 grid list-none items-stretch gap-8 p-0 md:grid-cols-3 md:gap-8">
          {STEPS.map((s) => (
            <li key={s.no} className="flex items-stretch gap-4">
              <span
                aria-hidden="true"
                className="figure shrink-0 text-[clamp(20px,2vw,26px)] leading-none font-semibold tracking-[0.04em] text-faint"
              >
                {s.no}
              </span>
              {/* mt-auto on the chip: the three gate pills share one baseline
                  even though step copy lengths differ (02 runs longest) */}
              <div className="flex flex-1 flex-col items-start gap-2">
                <h3 className="m-0 text-[17px] font-semibold text-ink">
                  {s.title}
                </h3>
                <p className="m-0 text-[14px] leading-[1.6] text-muted">
                  {s.text}
                </p>
                <span className="figure mt-auto inline-flex items-center gap-2 rounded-[6px] border border-seam bg-raised px-3 py-1.5 text-[12px] tracking-[0.04em] text-muted">
                  <span
                    aria-hidden="true"
                    className="h-[6px] w-[6px] rounded-full bg-dot-ok"
                  />
                  {s.gate}
                </span>
              </div>
            </li>
          ))}
        </ol>
      </section>

      {/* ============ CLOSING: the ask, with the proof beside it ============ */}
      <section
        aria-labelledby="closing-label"
        className="grid items-center gap-10 border-t border-seam py-12 lg:grid-cols-[1.1fr_0.9fr] lg:gap-14 lg:py-16"
      >
        <div>
          <h2
            id="closing-label"
            className="max-w-[24ch] text-[clamp(22px,3vw,32px)] leading-[1.15] font-bold tracking-[-0.01em] text-ink"
          >
            Watch it reject the truck that would have stopped the kiln.
          </h2>
          <p className="mt-4 max-w-[56ch] text-[14.5px] leading-[1.65] text-muted">
            Three seeded cases (clean, suspicious, contaminated) run live
            through the same gate pipeline, from photo to sealed audit record.
          </p>
          <div className="mt-7 flex w-full max-w-[420px] flex-col gap-3 sm:max-w-none sm:flex-row">
            <Link
              href="/app"
              className={buttonVariants({ variant: "primary", size: "lg" })}
            >
              Open Inspection Console
            </Link>
            <Link href="/inspections" className={buttonVariants({ size: "lg" })}>
              View Audit Trail
            </Link>
          </div>
        </div>

        {/* The three outcomes, stated plainly: what the pipeline can say */}
        <div className="panel flex flex-col">
          <div className="panel-head">
            <span>Possible verdicts</span>
            <span className="figure text-muted" style={{ letterSpacing: 0 }}>
              per truck
            </span>
          </div>
          <ul className="m-0 flex list-none flex-col p-0">
            {[
              ["accept", "ACCEPT", "Clean load. Tip it into the line."],
              ["escalate", "ESCALATE", "Doubt remains. A human decides."],
              ["reject", "REJECT", "Contaminant found. Turn it away."],
            ].map(([variant, label, note]) => (
              <li
                key={label}
                className="flex items-center gap-3 border-b border-seam px-4 py-3 last:border-b-0"
              >
                <Badge variant={variant as "accept" | "escalate" | "reject"}>
                  <span
                    aria-hidden="true"
                    className="h-1.5 w-1.5 rounded-full bg-current"
                  />
                  {label}
                </Badge>
                <span className="text-[13px] text-muted">{note}</span>
              </li>
            ))}
          </ul>
        </div>
      </section>

      {/* ============ COLOPHON: one honest line, no stacked fine print ============ */}
      <footer className="border-t border-seam pt-6 pb-2">
        <p className="m-0 max-w-[90ch] text-[12.5px] leading-[1.7] text-muted">
          Built during the AMD Developer Hackathon (ACT III). Demo figures are
          sourced estimates, not validated measurements · photos: RealWaste,
          CC BY 4.0.
        </p>
      </footer>
    </div>
  );
}
