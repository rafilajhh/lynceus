import Link from "next/link";
import { LogoMark } from "@/components/ui/logo-mark";
import { StatusChip } from "./status-chip";

const NAV = [
  { href: "/app", label: "Console" },
] as const;

/**
 * Persistent top bar: LYNCEUS wordmark + subtitle, nav links, live
 * status chip. Sticky with a hairline seam: no shadow.
 *
 * @param showNav — when false, renders wordmark + status chip only (no nav links).
 * Used by console layout where navigation lives in the side navbar.
 * @param showWordmark — when false, renders status chip only (no brand).
 * Used by console layout where brand lives in the side navbar.
 * @param showStatus — when false, drops the status chip (landing: the demo
 * backend's health is not the visitor's task status — critique finding).
 */
export function TopBar({ showNav = true, showWordmark = true, showStatus = true }: { showNav?: boolean; showWordmark?: boolean; showStatus?: boolean }) {
  return (
    <header className="sticky top-0 z-50 flex flex-wrap items-center gap-x-5 gap-y-2 border-b border-seam bg-panel px-6 py-3 backdrop-blur">
      {showWordmark ? (
        <div className="flex shrink-0 items-baseline gap-3">
          <Link href="/" className="line-through-none">
            <h1 className="m-0 inline-flex items-center gap-2 text-[22px] leading-none font-bold tracking-[3px] text-ink">
              <LogoMark size={22} />
              LYNCEUS
            </h1>
          </Link>
          <span className="text-[12px] font-semibold tracking-[1px] text-muted uppercase">
            AI Gate Inspector
          </span>
        </div>
      ) : null}

      {showNav ? (
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
      ) : null}

      {showStatus ? (
        <div className={showNav ? "" : "ml-auto"}>
          <StatusChip />
        </div>
      ) : null}
    </header>
  );
}
