import Link from "next/link";
import { StatusChip } from "./status-chip";

const NAV = [
  { href: "/app", label: "Demo" },
  { href: "/inspections", label: "Inspections" },
] as const;

/**
 * Persistent top bar: LYNCEUS wordmark + subtitle, nav links, live
 * status chip. Sticky with a hairline seam — no shadow.
 */
export function TopBar() {
  return (
    <header className="sticky top-0 z-50 flex flex-wrap items-center gap-x-5 gap-y-2 border-b border-seam bg-panel px-6 py-3 backdrop-blur">
      <div className="flex shrink-0 items-baseline gap-3">
        <Link href="/" className="line-through-none">
          <h1 className="m-0 inline text-[22px] leading-none font-bold tracking-[3px] text-ink">
            <span className="mr-0.5 text-amber" aria-hidden="true">
              ◉
            </span>
            LYNCEUS
          </h1>
        </Link>
        <span className="text-[12px] font-semibold tracking-[1px] text-muted uppercase">
          AI Gate Inspector
        </span>
      </div>

      <nav aria-label="Primary" className="ml-auto flex items-center gap-1">
        {NAV.map((item) => (
          <Link
            key={item.href}
            href={item.href}
            className="rounded-[6px] px-3 py-2 text-[13px] font-semibold tracking-[0.6px] text-muted uppercase transition-colors duration-100 hover:bg-seam hover:text-ink"
          >
            {item.label}
          </Link>
        ))}
      </nav>

      <StatusChip />
    </header>
  );
}
