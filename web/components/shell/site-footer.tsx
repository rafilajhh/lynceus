import Link from "next/link";
import { LogoMark } from "@/components/ui/logo-mark";

const LINKS = [
  { href: "/app", label: "Inspection console" },
  { href: "/inspections", label: "Audit trail" },
  { href: "/validation", label: "Validation" },
  { href: "/login", label: "Sign in" },
] as const;

/** Landing footer (pen.dev redesign): logo + links, then credits + standards. */
export function SiteFooter() {
  return (
    <footer className="border-t border-line">
      <div className="mx-auto flex w-full max-w-[1440px] flex-col gap-6 px-4 py-10 sm:px-8 lg:px-12">
        <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-4">
          <Link href="/" className="flex items-center gap-2.5" aria-label="Lynceus home">
            <LogoMark size={24} />
            <span className="font-display text-[17px] font-medium text-fg">Lynceus</span>
          </Link>
          <nav aria-label="Footer" className="flex flex-wrap gap-x-6 gap-y-2">
            {LINKS.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                className="text-[13px] whitespace-nowrap text-fg-muted transition-colors duration-100 hover:text-fg"
              >
                {item.label}
              </Link>
            ))}
          </nav>
        </div>
        <div className="flex flex-col justify-between gap-x-12 gap-y-3 border-t border-line pt-5 md:flex-row md:items-start">
          <p className="m-0 max-w-[640px] text-[12px] leading-[18px] text-fg-subtle">
            Built for the AMD Developer Hackathon (ACT III), Intelligent Industry track. Figures
            sourced from RDI 2024, US cement benchmarks, and ITATS Surabaya weighbridge data.
          </p>
          <p className="m-0 font-mono text-[12px] whitespace-nowrap text-fg-subtle">
            ISO 21640:2021 · EN 15359:2011
          </p>
        </div>
      </div>
    </footer>
  );
}
