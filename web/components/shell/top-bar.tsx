import Link from "next/link";
import { buttonVariants } from "@/components/ui/button";
import { LogoMark } from "@/components/ui/logo-mark";
import { cn } from "@/lib/utils";

const NAV = [
  { href: "/#how", label: "How it works" },
  { href: "/#who", label: "Who it's for" },
  { href: "/#verdicts", label: "Verdicts" },
] as const;

/**
 * Landing navbar (pen.dev redesign): logo + section links on the left,
 * Sign in / Open console on the right. 64px tall, white, hairline bottom.
 * Section links collapse below md; the two actions always stay visible.
 */
export function TopBar() {
  return (
    <header className="sticky top-0 z-50 border-b border-line bg-surface">
      <div className="mx-auto flex h-16 w-full max-w-[1440px] items-center justify-between gap-4 px-4 sm:px-8 lg:px-12">
        <div className="flex items-center gap-10">
          <Link href="/" className="flex shrink-0 items-center gap-2.5" aria-label="Lynceus home">
            <LogoMark size={28} />
            <span className="font-display text-[19px] font-medium text-fg">Lynceus</span>
          </Link>
          <nav aria-label="Primary" className="hidden items-center gap-7 md:flex">
            {NAV.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                className="text-[14px] font-medium whitespace-nowrap text-fg-muted transition-colors duration-100 hover:text-fg"
              >
                {item.label}
              </Link>
            ))}
          </nav>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <Link
            href="/login"
            className={cn(buttonVariants({ variant: "ghost" }), "h-[34px] text-fg")}
          >
            Sign in
          </Link>
          <Link
            href="/app"
            className={cn(buttonVariants({ variant: "primary" }), "h-[34px]")}
          >
            Open console
          </Link>
        </div>
      </div>
    </header>
  );
}
