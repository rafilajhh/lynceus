import Image from "next/image";
import Link from "next/link";
import {
  ArrowRight,
  Building2,
  Camera,
  ClipboardList,
  Cpu,
  HardHat,
  ScanLine,
  ScanSearch,
  ShieldCheck,
  Stamp,
  Timer,
} from "lucide-react";
import { CountUpFigure } from "@/components/landing/count-up-figure";
import { buttonVariants } from "@/components/ui/button";
import { LIVE_LATENCY_COPY } from "@/lib/format";
import { cn } from "@/lib/utils";

export const metadata = { title: "One hidden metal chunk can stop a cement kiln" };

/**
 * Route: /: landing (pen.dev redesign, frame TM27Q).
 *
 * Every number on screen answers "from where?" with a source line:
 * figures come from docs/research/realcase-indonesia.md. The hero verdict
 * card is an illustration of the console's output, not a live record.
 */

const CONTAINER = "mx-auto w-full max-w-[1440px] px-4 sm:px-8 lg:px-12";
const SECTION_LABEL = "font-mono text-[12px] tracking-[1px] text-brand-deep uppercase";
const SECTION_HEADING =
  "m-0 font-display text-[30px] leading-[1.15] font-medium tracking-[-0.6px] text-fg sm:text-[40px] sm:leading-[45px]";

const PROOF_FIGURES = [
  {
    target: 350,
    prefix: "Rp ",
    suffix: " jt",
    decimals: 0,
    pill: "≈ US$22k",
    label: "One industrial shredder destroyed by a single metal contaminant",
    source: "RDI 2024, Lampiran 2A · Banyumas RDF plant unit cost",
  },
  {
    target: 28,
    prefix: "US$",
    suffix: "k/hr",
    decimals: 0,
    pill: "≈ Rp 450 jt",
    label: "Cement kiln unplanned downtime, per hour of lost clinker",
    source: "oxmaint US cement benchmark @ Rp 16,000/USD",
  },
  {
    target: 5.2,
    prefix: "",
    suffix: " t/trip",
    decimals: 1,
    pill: "TPA Benowo weighbridge",
    label: "Typical arm-roll load that must be inspected before tipping",
    source: "ITATS Surabaya · 14 m³ × 372.71 kg/m³",
  },
] as const;

const STEPS = [
  {
    no: "01",
    title: "Capture",
    Icon: Camera,
    iconBg: "bg-fg",
    text: "At the weighbridge the operator photographs the load and the paper waybill. AI reads the waybill into the register (plate, supplier, net weight): the same fields a PUPR gate form already records.",
    gate: "gate · intake complete",
  },
  {
    no: "02",
    title: "Analyze",
    Icon: ScanSearch,
    iconBg: "bg-fg",
    text: "A vision-language model on AMD Token Factory reads the load for contaminants and moisture, a language model cross-checks the waybill, and a physics digital twin simulates gate gas readings.",
    gate: "gate · VLM + twin resolved",
  },
  {
    no: "03",
    title: "Decide",
    Icon: Stamp,
    iconBg: "bg-brand",
    text: "Fusion issues ACCEPT / ESCALATE / REJECT with reasons and confidence, sealed into a tamper-evident SHA-256 audit record per truck.",
    gate: "gate · verdict sealed",
  },
] as const;

const PERSONAS = [
  {
    role: "Gate inspectors",
    Icon: HardHat,
    text: "Accept or reject in seconds, not minutes. One photo, one verdict, one sealed record.",
    href: "/app",
    link: "Inspection console",
  },
  {
    role: "Shift supervisors",
    Icon: ClipboardList,
    text: "Supplier risk trends at a glance. Flag problematic haulers before the next delivery.",
    href: "/shift",
    link: "Shift report",
  },
  {
    role: "Plant managers",
    Icon: Building2,
    text: "Audit-ready compliance trail. Every decision documented, every figure sourced.",
    href: "/inspections",
    link: "Audit trail",
  },
] as const;

const VERDICTS = [
  { label: "ACCEPT", tone: "bg-success/20 text-success", dot: "bg-success", title: "Clean load.", note: "Tip it into the line." },
  { label: "ESCALATE", tone: "bg-warning/20 text-warning", dot: "bg-warning", title: "Doubt remains.", note: "A human decides." },
  { label: "REJECT", tone: "bg-danger/20 text-danger", dot: "bg-danger", title: "Contaminant found.", note: "Turn it away." },
] as const;

const SAMPLE_ROWS = [
  { key: "Contaminant", value: "Metal · bolt cluster", tone: "font-sans text-danger" },
  { key: "Confidence", value: "0.94", tone: "font-mono text-fg" },
  { key: "Waybill check", value: "Weight mismatch +6%", tone: "font-sans text-warning" },
  { key: "Audit seal", value: "sha256 · 7f3a…c21e", tone: "font-mono text-fg-muted" },
] as const;

export default function LandingPage() {
  return (
    <>
      {/* ============ HERO ============ */}
      <section
        aria-labelledby="hero-headline"
        style={{
          backgroundImage:
            "radial-gradient(ellipse 55% 70% at 75% 10%, #2563EB24 0%, #FCFCFC00 100%)",
        }}
      >
        <div
          className={cn(
            CONTAINER,
            "flex flex-col gap-14 pt-14 pb-16 sm:pt-[88px] sm:pb-24 xl:flex-row xl:items-center xl:gap-16",
          )}
        >
          <div className="flex flex-col items-start gap-7 xl:w-[600px] xl:shrink-0">
            <span className="inline-flex max-w-full items-center gap-2 rounded-full border border-line-strong bg-surface py-[5px] pr-3 pl-1.5">
              <span className="rounded-full bg-fg px-2 py-0.5 font-mono text-[11px] text-white">
                AI
              </span>
              <span className="truncate font-mono text-[12px] text-fg-muted">
                Gate inspector for refuse-derived fuel
              </span>
            </span>
            <h1
              id="hero-headline"
              className="m-0 font-display text-[40px] leading-[44px] font-medium tracking-[-1.5px] text-fg sm:text-[52px] sm:leading-[56px] lg:text-[64px] lg:leading-[67px]"
            >
              One hidden metal chunk can stop a cement kiln.
            </h1>
            <p className="m-0 max-w-[540px] text-[16px] leading-[26px] text-fg-muted sm:text-[18px] sm:leading-[28px]">
              Lynceus inspects every RDF truck at the gate, before tipping: visual contaminant
              detection, waybill cross-check, and a route verdict in under a minute, sealed to a
              tamper-evident audit record.
            </p>
            <div className="flex w-full flex-col gap-2.5 sm:w-auto sm:flex-row sm:items-center">
              <Link href="/app" className={buttonVariants({ variant: "primary", size: "lg" })}>
                <ScanLine size={14} aria-hidden="true" />
                Open Inspection Console
              </Link>
              <Link href="#how" className={buttonVariants({ variant: "default", size: "lg" })}>
                See how it works
              </Link>
            </div>
            <ul className="m-0 flex list-none flex-wrap items-center gap-x-6 gap-y-2 p-0 pt-2 text-[13px] text-fg-muted">
              <li className="flex items-center gap-1.5">
                <Timer size={15} aria-hidden="true" />~20 s per verdict
              </li>
              <li className="flex items-center gap-1.5">
                <ShieldCheck size={15} aria-hidden="true" />
                SHA-256 sealed
              </li>
              <li className="flex items-center gap-1.5">
                <Cpu size={15} aria-hidden="true" />
                AMD Token Factory
              </li>
            </ul>
          </div>

          {/* Load photo + an example of the verdict card the console produces */}
          <figure className="relative m-0 w-full max-w-[680px] sm:pr-10 sm:pb-[70px] xl:flex-1">
            <div className="relative aspect-[640/470] w-full overflow-hidden rounded-[20px] border border-line-strong">
              <Image
                src="/demo/t-metal-1.jpg"
                alt="Truck load at the weighbridge with a rusted steel pipe and foil, the kind of metal contaminant that destroys an RDF shredder"
                fill
                sizes="(min-width: 1280px) 640px, 100vw"
                className="object-cover"
                priority
              />
              <span className="absolute top-5 left-5 inline-flex items-center gap-2 rounded-full bg-fg/70 px-3 py-1.5 font-mono text-[11px] tracking-[0.6px] text-white backdrop-blur-[6px]">
                <span aria-hidden="true" className="h-[7px] w-[7px] rounded-full bg-brand" />
                WEIGHBRIDGE GATE A · CAM 02
              </span>
            </div>
            <figcaption
              aria-label="Example verdict card"
              className="relative mt-4 w-full overflow-hidden rounded-[20px] border border-line-strong bg-surface [filter:drop-shadow(0px_24px_24px_#18191B14)_drop-shadow(0px_2px_3px_#18191B0F)] sm:absolute sm:right-0 sm:bottom-0 sm:mt-0 sm:w-[420px] sm:max-w-[90%]"
            >
              <div className="flex items-center justify-between border-b border-line px-5 py-4">
                <div className="flex flex-col gap-0.5">
                  <span className="font-mono text-[12px] text-fg-subtle">inspection-000052</span>
                  <span className="font-display text-[20px] font-medium text-fg">B 9174 KT</span>
                </div>
                <span className="inline-flex items-center gap-1.5 rounded-full bg-danger-tint px-3 py-[5px] font-mono text-[12px] font-medium tracking-[0.6px] text-danger">
                  <span aria-hidden="true" className="h-1.5 w-1.5 rounded-full bg-danger" />
                  REJECT
                </span>
              </div>
              <dl className="m-0 flex flex-col gap-3 px-5 pt-4 pb-5 text-[13px]">
                {SAMPLE_ROWS.map((row) => (
                  <div key={row.key} className="flex items-center justify-between gap-4">
                    <dt className="text-fg-muted">{row.key}</dt>
                    <dd className={cn("m-0 text-right font-medium whitespace-nowrap", row.tone)}>
                      {row.value}
                    </dd>
                  </div>
                ))}
              </dl>
            </figcaption>
          </figure>
        </div>
      </section>

      {/* ============ COST OF A MISS: real numbers, sourced ============ */}
      <section aria-labelledby="proof-heading" className="border-t border-line">
        <div className={cn(CONTAINER, "flex flex-col gap-14 py-16 sm:py-24")}>
          <div className="flex flex-col justify-between gap-6 lg:flex-row lg:items-end">
            <div className="flex max-w-[640px] flex-col gap-4">
              <p className={cn("m-0", SECTION_LABEL)}>What one missed truck costs</p>
              <h2 id="proof-heading" className={SECTION_HEADING}>
                The gate is the cheapest place to catch it.
              </h2>
            </div>
            <p className="m-0 max-w-[320px] text-[14px] leading-[21px] text-fg-muted">
              Every figure on this page is sourced. The footnotes show the math.
            </p>
          </div>
          <div className="grid border-y border-line-strong lg:grid-cols-3">
            {PROOF_FIGURES.map((f, i) => (
              <div
                key={f.label}
                className={cn(
                  "flex flex-col items-start gap-3.5 py-9",
                  i > 0 && "border-t border-line-strong lg:border-t-0 lg:border-l lg:px-9",
                  i === 0 && "lg:pr-9",
                )}
              >
                <CountUpFigure
                  target={f.target}
                  prefix={f.prefix}
                  suffix={f.suffix}
                  decimals={f.decimals}
                  className="figure text-[38px] leading-none font-light tracking-[-1px] whitespace-nowrap text-fg sm:text-[48px]"
                />
                <span className="rounded-full bg-surface-subtle px-2.5 py-[3px] font-mono text-[12px] text-fg-muted">
                  {f.pill}
                </span>
                <p className="m-0 text-[16px] leading-6 text-fg">{f.label}</p>
                <p className="m-0 text-[12px] text-fg-subtle">↳ {f.source}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ============ HOW IT WORKS: three process gates ============ */}
      <section id="how" aria-labelledby="how-heading" className="scroll-mt-16 bg-surface-subtle">
        <div className={cn(CONTAINER, "flex flex-col gap-14 py-16 sm:py-24")}>
          <div className="flex flex-col items-center gap-4 text-center">
            <p className={cn("m-0", SECTION_LABEL)}>How a truck is cleared</p>
            <h2 id="how-heading" className={SECTION_HEADING}>
              Three gates. Under a minute. One sealed record.
            </h2>
          </div>
          <ol className="m-0 grid list-none gap-4 p-0 md:grid-cols-3">
            {STEPS.map(({ no, title, Icon, iconBg, text, gate }) => (
              <li
                key={no}
                className="flex flex-col gap-5 rounded-[14px] border border-line-strong bg-surface p-7 shadow-[0px_1px_3px_#18191B0D]"
              >
                <div className="flex items-center justify-between">
                  <span
                    aria-hidden="true"
                    className={cn(
                      "flex h-10 w-10 items-center justify-center rounded-[10px] text-white",
                      iconBg,
                    )}
                  >
                    <Icon size={18} />
                  </span>
                  <span className="font-mono text-[12px] text-fg-subtle">{no} / 03</span>
                </div>
                <div className="flex flex-1 flex-col gap-2">
                  <h3 className="m-0 font-display text-[24px] font-medium text-fg">{title}</h3>
                  <p className="m-0 text-[15px] leading-[23px] text-fg-muted">{text}</p>
                </div>
                <div className="flex items-center gap-2 border-t border-line pt-3.5">
                  <span aria-hidden="true" className="h-1.5 w-1.5 rounded-full bg-success" />
                  <span className="font-mono text-[12px] text-fg-muted">{gate}</span>
                </div>
              </li>
            ))}
          </ol>
        </div>
      </section>

      {/* ============ WHO IT'S FOR ============ */}
      <section id="who" aria-labelledby="who-heading" className="scroll-mt-16">
        <div className={cn(CONTAINER, "flex flex-col gap-10 py-16 sm:py-24 lg:flex-row lg:gap-20")}>
          <div className="flex flex-col gap-4 lg:w-[380px] lg:shrink-0">
            <p className={cn("m-0", SECTION_LABEL)}>For the people who run the gate</p>
            <h2 id="who-heading" className={SECTION_HEADING}>
              Built for the shift, not the slide deck.
            </h2>
          </div>
          <ul className="m-0 flex flex-1 list-none flex-col p-0">
            {PERSONAS.map(({ role, Icon, text, href, link }) => (
              <li
                key={role}
                className="flex flex-wrap items-center gap-x-6 gap-y-3 border-b border-line-strong py-7"
              >
                <span
                  aria-hidden="true"
                  className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-surface-muted text-fg"
                >
                  <Icon size={20} />
                </span>
                <div className="flex min-w-0 flex-1 basis-[240px] flex-col gap-1">
                  <h3 className="m-0 font-display text-[22px] font-medium text-fg">{role}</h3>
                  <p className="m-0 text-[15px] leading-[23px] text-fg-muted">{text}</p>
                </div>
                <Link
                  href={href}
                  className="inline-flex shrink-0 items-center gap-1 text-[14px] font-medium whitespace-nowrap text-fg hover:text-brand"
                >
                  {link}
                  <ArrowRight size={14} aria-hidden="true" />
                </Link>
              </li>
            ))}
          </ul>
        </div>
      </section>

      {/* ============ CTA: the ask, with the three outcomes beside it ============ */}
      <section id="verdicts" aria-labelledby="cta-heading" className="scroll-mt-16">
        <div className={cn(CONTAINER, "pb-16 sm:pb-24")}>
          <div
            className="flex flex-col gap-12 overflow-hidden rounded-[24px] bg-fg p-8 sm:p-12 lg:flex-row lg:items-center lg:gap-16 lg:p-16"
            style={{
              backgroundImage:
                "radial-gradient(ellipse 60% 80% at 10% 100%, #2563EB40 0%, #2563EB00 100%)",
            }}
          >
            <div className="flex flex-1 flex-col items-start gap-6">
              <p className="m-0 font-mono text-[12px] tracking-[1px] text-brand-soft uppercase">
                Try it on a real load
              </p>
              <h2
                id="cta-heading"
                className="m-0 font-display text-[32px] leading-[1.1] font-medium tracking-[-0.8px] text-white sm:text-[44px] sm:leading-[48px]"
              >
                Watch it reject the truck that would have stopped the kiln.
              </h2>
              <p className="m-0 text-[16px] leading-[25px] text-white/[0.68]">
                Upload a load photo and the waybill details. Lynceus returns a verdict in{" "}
                {LIVE_LATENCY_COPY} — sealed, auditable, and ready for your gate log.
              </p>
              <div className="flex flex-wrap items-center gap-x-2.5 gap-y-3 pt-2">
                <Link href="/app" className={buttonVariants({ variant: "brand", size: "lg" })}>
                  <ScanLine size={14} aria-hidden="true" />
                  Open Inspection Console
                </Link>
                <span className="text-[13px] text-white/[0.68]">Demo access available</span>
              </div>
            </div>
            <div className="flex w-full flex-col gap-1.5 rounded-[20px] border border-white/[0.12] bg-white/5 p-2 lg:w-[480px] lg:shrink-0">
              <div className="flex items-start justify-between px-4 py-3 font-mono text-[11px] tracking-[1px] text-white/[0.68]">
                <span>POSSIBLE VERDICTS</span>
                <span>PER TRUCK</span>
              </div>
              <ul className="m-0 flex list-none flex-col gap-1.5 p-0">
                {VERDICTS.map((v) => (
                  <li
                    key={v.label}
                    className="flex items-center gap-4 rounded-[14px] bg-white/[0.03] p-4"
                  >
                    <span className="w-[110px] shrink-0">
                      <span
                        className={cn(
                          "inline-flex items-center gap-1.5 rounded-full px-2.5 py-[3px] font-mono text-[12px] font-medium tracking-[0.6px]",
                          v.tone,
                        )}
                      >
                        <span aria-hidden="true" className={cn("h-1.5 w-1.5 rounded-full", v.dot)} />
                        {v.label}
                      </span>
                    </span>
                    <span className="flex min-w-0 flex-col gap-0.5">
                      <span className="text-[15px] font-medium text-white">{v.title}</span>
                      <span className="text-[13px] text-white/[0.68]">{v.note}</span>
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </div>
      </section>
    </>
  );
}
