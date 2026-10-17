import Image from "next/image";
import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { buttonVariants } from "@/components/ui/button";
import { LIVE_LATENCY_COPY, formatRupiahCompact } from "@/lib/format";

export const metadata = {
  title: "Incoming-fuel quality control for RDF reception gates",
  description:
    "Lynceus checks every refuse-derived fuel truck at the weighbridge of cement kilns and waste-to-energy plants: reads the waybill, inspects the load, decides with cited rules and closes the loop with the supervisor, the lab, the contract and the supplier.",
};

/**
 * Route: /: landing (Persuade, for judges and plant buyers).
 *
 * Direction contract (.impeccable/surface-briefs/web-app.md): graphite
 * ground, hairline seams, IBM Plex, one amber accent, mono figures. Every
 * number answers "from where?" with a source line (PRODUCT.md principle
 * #1): figures come from docs/research/realcase-indonesia.md.
 *
 * No kicker or eyebrow, no hero-metric grid: the first viewport states the
 * problem, then who it is for and where, then the one action.
 */

const PROOF_FIGURES = [
  {
    value: formatRupiahCompact(350_000_000),
    label: "One industrial shredder: the asset a single metal contaminant can wreck",
    aside: "≈ US$22k",
    source: "RDI 2024, Lampiran 2A, Banyumas RDF plant unit cost",
  },
  {
    value: "US$28k/h",
    label: "Cement kiln unplanned downtime, per hour of lost clinker",
    aside: `≈ ${formatRupiahCompact(450_000_000)}`,
    source: "oxmaint US cement benchmark at Rp 16,000/USD",
  },
  {
    value: "Rp 360k/t",
    label: "What a plant pays for RDF, so every wet or contaminated load is a commercial dispute",
    aside: "≈ US$24 per tonne",
    source: "Bantargebang RDF selling price, ASI / Kompas 27 Jun 2023",
  },
] as const;

const STEPS = [
  {
    no: "1",
    title: "Read the waybill",
    text: "The operator photographs the supplier's waybill at the weighbridge. A vision model reads plate, supplier, net weight, load type and declared moisture; the weighbridge reading is set beside the declared net.",
    chip: "DeepSeek-V4-Flash-Vision · AMD Token Factory",
  },
  {
    no: "2",
    title: "Inspect the load",
    text: "The same vision model reads the load photo for hard contaminants (metal, stone), glass, organics and wetness, three reads per photo. A CPU detector takes a second look and can hold a truck the model waved through.",
    chip: "Vision model + CPU detector second look",
  },
  {
    no: "3",
    title: "Decide with cited rules",
    text: "Deterministic rules compare what was declared with what is seen and weighed, and return ACCEPT, HOLD or REJECT in one plain sentence, with the plant SOP clause for each next step.",
    chip: "SOP-cited · sealed SHA-256 record",
  },
  {
    no: "4",
    title: "Close the loop",
    text: "A supervisor confirms or overrides a held truck, the lab result adjusts the contract price, the supplier gets a notice drafted from the sealed facts, and the scorecard sets how often each supplier is sampled.",
    chip: "Supervisor · lab · contract · notice",
  },
] as const;

const ROLES = [
  {
    role: "Gate operator",
    text: "One photo of the load, one of the waybill. A verdict in seconds, with the step to take and the clause behind it.",
  },
  {
    role: "Alternative-fuel quality supervisor",
    text: "Held trucks wait for a decision, lab samples go where the risk is, and every call is sealed beside the AI's.",
  },
  {
    role: "Alternative-fuel procurement",
    text: "Lab results become price adjustments under the contract, and each supplier's record is evidence it cannot dispute.",
  },
] as const;

export default function LandingPage() {
  return (
    <div className="flex flex-col gap-0 pb-6">
      {/* ============ HERO: the problem, then who and where ============ */}
      <section
        aria-labelledby="hero-headline"
        className="grid items-center gap-10 border-b border-seam py-10 lg:grid-cols-[1.15fr_0.85fr] lg:gap-14 lg:py-16"
      >
        <div className="flex flex-col items-start">
          <h1
            id="hero-headline"
            className="max-w-[16ch] text-[clamp(30px,4.4vw,48px)] leading-[1.08] font-bold tracking-[-0.015em] text-balance text-ink"
          >
            One hidden metal chunk can stop a cement kiln.
          </h1>
          <p className="mt-5 max-w-[54ch] text-[16px] leading-[1.6] font-semibold text-ink sm:text-[18px]">
            Lynceus is incoming-fuel quality control for RDF reception gates at cement kilns and
            waste-to-energy plants.
          </p>
          <p className="mt-3 max-w-[58ch] text-[15px] leading-[1.65] text-muted sm:text-[16px]">
            RDF, refuse-derived fuel, is municipal waste sorted and shredded so a plant can burn
            it in place of coal. At the weighbridge, Lynceus reads the supplier&apos;s waybill,
            inspects the load and tells the operator to accept, hold or reject it in seconds,
            before anything is tipped.
          </p>
          <div className="mt-8 flex w-full flex-col items-start gap-4 sm:w-auto sm:flex-row sm:items-center">
            <Link href="/app" className={buttonVariants({ variant: "primary", size: "lg" })}>
              Try the live demo
            </Link>
            <Link
              href="/validation"
              className="text-[14px] font-semibold text-muted underline decoration-seam-strong underline-offset-4 transition-colors duration-100 hover:text-ink hover:decoration-amber"
            >
              See how it was measured
            </Link>
          </div>
        </div>

        {/* Proof photo: the contaminant, framed the way the gate reads it */}
        <figure className="panel m-0 flex flex-col self-start">
          <div className="relative">
            <Image
              src="/demo/t-metal-1.jpg"
              alt="AI-generated illustration: shredded RDF with a rusted steel pipe elbow and crumpled aluminium foil, the kind of metal contaminant that can wreck a shredder"
              width={524}
              height={524}
              className="block h-auto max-h-[340px] w-full object-cover lg:max-h-[420px]"
              priority
            />
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
            <span className="text-[13px] text-ink">
              Declared as sorted RDF fluff; the camera sees a steel pipe elbow. Do not tip.
            </span>
            <span className="text-[12px] text-muted">
              AI-generated illustration, not a photo from a plant.
            </span>
          </figcaption>
        </figure>
      </section>

      {/* ============ PROOF STRIP: what one missed truck costs, sourced ============ */}
      <section aria-labelledby="proof-label" className="border-b border-seam py-12 lg:py-16">
        <h2 id="proof-label" className="smallcaps mb-8">
          What one missed truck costs
        </h2>
        {/* Composition, not cards: unequal columns split by hairline seams. */}
        <div className="grid gap-8 lg:grid-cols-[1.2fr_1fr_1fr] lg:gap-0">
          {PROOF_FIGURES.map((f, i) => (
            <div
              key={f.value}
              className={[
                "flex min-w-0 flex-col gap-2",
                i > 0 ? "lg:border-l lg:border-seam lg:pl-8 xl:pl-10" : "lg:pr-8 xl:pr-10",
                i === 1 ? "lg:pr-8 xl:pr-10" : "",
              ].join(" ")}
            >
              <span className="figure text-[clamp(30px,3.4vw,48px)] leading-none font-semibold tracking-[-0.01em] whitespace-nowrap text-ink">
                {f.value}
              </span>
              <p className="m-0 max-w-[30ch] text-[14px] leading-snug text-muted">
                {f.label}
                <span className="figure mt-1 block text-[12px] text-faint">{f.aside}</span>
              </p>
              <p className="figure m-0 mt-auto max-w-[42ch] border-t border-seam pt-2 text-[11.5px] leading-[1.5] text-muted">
                {f.source}
              </p>
            </div>
          ))}
        </div>
      </section>

      {/* ============ HOW IT WORKS: four steps, the last one closes the loop ============ */}
      <section aria-labelledby="how-label" className="border-b border-seam py-12 lg:py-16">
        <h2 id="how-label" className="smallcaps mb-8">
          How a truck is cleared
        </h2>
        <ol className="m-0 grid list-none gap-8 p-0 md:grid-cols-2 xl:grid-cols-4 xl:gap-0">
          {STEPS.map((s, i) => (
            <li
              key={s.no}
              className={[
                "flex min-w-0 flex-col items-start gap-2",
                i > 0 ? "xl:border-l xl:border-seam xl:pl-7" : "",
                i < STEPS.length - 1 ? "xl:pr-7" : "",
              ].join(" ")}
            >
              <span className="flex items-baseline gap-3">
                <span aria-hidden="true" className="figure text-[15px] font-semibold text-faint">
                  {s.no}
                </span>
                <h3 className="m-0 text-[17px] font-semibold text-ink">{s.title}</h3>
              </span>
              <p className="m-0 text-[14px] leading-[1.6] text-muted">{s.text}</p>
              <span className="figure mt-auto inline-flex max-w-full items-center rounded-[6px] border border-seam bg-raised px-2.5 py-1.5 text-[11.5px] leading-snug text-muted">
                {s.chip}
              </span>
            </li>
          ))}
        </ol>

        <dl className="m-0 mt-10 grid gap-x-10 gap-y-3 border-t border-seam pt-6 text-[13.5px] md:grid-cols-[auto_1fr]">
          <dt className="font-semibold text-ink">On AMD</dt>
          <dd className="m-0 max-w-[90ch] leading-relaxed text-muted">
            DeepSeek-V4-Flash-Vision reads the load and the waybill on AMD Token Factory.
            DeepSeek-V4-Flash drafts supplier notices and answers Pythia, the gate assistant
            that quotes the plant SOP. A CPU detector (YOLO, ONNX Runtime) gives the second look.
          </dd>
          <dt className="font-semibold text-ink">Speed</dt>
          <dd className="m-0 max-w-[90ch] leading-relaxed text-muted">
            A full inspection takes {LIVE_LATENCY_COPY}, measured live on 80 photos.
          </dd>
        </dl>
      </section>

      {/* ============ WHO IT'S FOR ============ */}
      <section aria-labelledby="who-label" className="py-12 lg:py-16">
        <h2 id="who-label" className="smallcaps mb-8">
          For the people who run the gate
        </h2>
        <div className="grid gap-8 md:grid-cols-3 md:gap-10">
          {ROLES.map((item) => (
            <div key={item.role} className="flex flex-col gap-2">
              <h3 className="m-0 text-[15px] font-semibold text-ink">{item.role}</h3>
              <p className="m-0 max-w-[44ch] text-[14px] leading-[1.6] text-muted">{item.text}</p>
            </div>
          ))}
        </div>
      </section>

      {/* ============ CLOSING: the ask, with the three outcomes beside it ============ */}
      <section
        aria-labelledby="closing-label"
        className="grid items-center gap-10 border-t border-seam py-12 lg:grid-cols-[1.1fr_0.9fr] lg:gap-14 lg:py-16"
      >
        <div>
          <h2
            id="closing-label"
            className="max-w-[24ch] text-[clamp(22px,3vw,32px)] leading-[1.15] font-bold tracking-[-0.01em] text-balance text-ink"
          >
            Watch it stop the truck that would have stopped the kiln.
          </h2>
          <p className="mt-4 max-w-[56ch] text-[15px] leading-[1.65] text-muted">
            The demo truck carries a waybill that declares sorted RDF fluff and a load with metal
            in it. One click reads the waybill, weighs the truck, inspects the load and seals the
            verdict; then confirm it as the supervisor and send the supplier notice.
          </p>
          <div className="mt-7 flex w-full flex-col gap-3 sm:w-auto sm:flex-row">
            <Link href="/app" className={buttonVariants({ variant: "primary", size: "lg" })}>
              Try the live demo
            </Link>
          </div>
        </div>

        <div className="panel flex flex-col">
          <div className="panel-head">
            <span>Three outcomes</span>
            <span className="figure text-muted" style={{ letterSpacing: 0 }}>
              per truck
            </span>
          </div>
          <ul className="m-0 flex list-none flex-col p-0">
            {(
              [
                ["accept", "Accept", "Clean RDF. Tip it into the line."],
                ["escalate", "Hold", "Doubt remains: a supervisor decides, a lab sample if needed."],
                ["reject", "Reject", "Hard contaminant: do not tip. Notice to the supplier."],
              ] as const
            ).map(([variant, label, note]) => (
              <li
                key={label}
                className="flex items-center gap-3 border-b border-seam px-4 py-3 last:border-b-0"
              >
                <Badge variant={variant} className="min-w-[84px] justify-center">
                  <span aria-hidden="true" className="h-1.5 w-1.5 rounded-full bg-current" />
                  {label}
                </Badge>
                <span className="text-[13.5px] text-muted">{note}</span>
              </li>
            ))}
          </ul>
        </div>
      </section>

      {/* ============ COLOPHON: provenance, one honest paragraph ============ */}
      <footer className="border-t border-seam pt-6 pb-2">
        <p className="m-0 max-w-[90ch] text-[12.5px] leading-[1.7] text-muted">
          Built for the AMD Developer Hackathon (ACT III). The demo truck photos and the sample
          waybill are AI-generated, fictitious illustrations; the weighbridge feed in the demo is
          simulated; contract terms are an example. Cost figures are sourced estimates
          (RDI 2024, a US cement benchmark, ASI), not measurements from a plant.
        </p>
      </footer>
    </div>
  );
}
