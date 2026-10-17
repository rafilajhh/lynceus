"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import {
  ClipboardList,
  FlaskConical,
  LogOut,
  ScanLine,
  ScrollText,
} from "lucide-react";
import { fetchSession, logout } from "@/lib/auth-api";
import { LogoMark } from "@/components/ui/logo-mark";
import { StatusChip } from "@/components/shell/status-chip";
import { cn } from "@/lib/utils";

const NAV_ITEMS = [
  { href: "/app", label: "Inspection", Icon: ScanLine },
  { href: "/inspections", label: "Audit trail", Icon: ScrollText },
  { href: "/shift", label: "Shift report", Icon: ClipboardList },
  { href: "/validation", label: "Validation", Icon: FlaskConical },
] as const;

/**
 * SideNavbar — persistent 248px left rail (pen.dev "Lynceus/Sidebar"):
 * brand, "Console" group, four routes, operator block with sign-out.
 * Collapses to a bottom bar below md.
 */
export function SideNavbar() {
  const pathname = usePathname();
  const router = useRouter();
  const [user, setUser] = useState<string | null>(null);

  // Sign-out only exists when the backend enforces auth; in demo mode
  // (no admin credentials) the session has no user.
  useEffect(() => {
    const controller = new AbortController();
    fetchSession(controller.signal)
      .then((s) => setUser(s.user ?? null))
      .catch(() => {});
    return () => controller.abort();
  }, []);

  const signOut = async () => {
    await logout();
    router.replace("/login");
  };

  const isActive = (href: string) =>
    pathname === href || pathname.startsWith(`${href}/`);

  return (
    <>
      <nav
        aria-label="Primary"
        className="fixed left-0 top-0 z-40 hidden h-screen print:hidden w-[248px] flex-col justify-between border-r border-line bg-surface px-3.5 py-5 md:flex"
      >
        <div className="flex flex-col gap-7">
          <Link href="/" className="flex items-center gap-2.5 px-1.5">
            <LogoMark size={30} />
            <span className="flex flex-col gap-px">
              <span className="font-display text-[17px] leading-tight font-medium text-fg">Lynceus</span>
              <span className="font-mono text-[10px] tracking-[0.8px] text-fg-subtle">AI GATE INSPECTOR</span>
            </span>
          </Link>

          <div className="flex flex-col gap-0.5">
            <span className="px-2.5 pb-2 text-[12px] font-medium text-fg-subtle">Console</span>
            {NAV_ITEMS.map(({ href, label, Icon }) => {
              const active = isActive(href);
              return (
                <Link
                  key={href}
                  href={href}
                  aria-current={active ? "page" : undefined}
                  className={cn(
                    "flex h-9 items-center gap-2.5 rounded-[8px] px-2.5 text-[14px] font-medium transition-colors duration-100",
                    active
                      ? "bg-surface-muted text-fg"
                      : "text-fg-muted hover:bg-surface-subtle hover:text-fg",
                  )}
                >
                  <Icon aria-hidden="true" size={16} strokeWidth={2} />
                  {label}
                </Link>
              );
            })}
          </div>
        </div>

        <div className="flex flex-col gap-3">
          {/* Live /health poll: never a fake green when the engine is down. */}
          <div className="px-1.5">
            <StatusChip />
          </div>
          <div className="flex items-center gap-2.5 border-t border-line px-1.5 pt-2.5">
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-line bg-surface-muted text-[13px] font-medium text-fg">
              OP
            </span>
            <span className="flex min-w-0 flex-1 flex-col gap-px">
              <span className="truncate text-[13px] font-medium text-fg">Gate operator</span>
              <span className="truncate text-[12px] text-fg-subtle">
                {user ? `${user} · Gate A` : "Open access · Gate A"}
              </span>
            </span>
            {user ? (
              <button
                type="button"
                onClick={() => void signOut()}
                aria-label="Sign out"
                title="Sign out"
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-[8px] text-fg-muted transition-colors duration-100 hover:bg-surface-subtle hover:text-fg"
              >
                <LogOut aria-hidden="true" size={16} strokeWidth={2} />
              </button>
            ) : null}
          </div>
        </div>
      </nav>

      {/* Mobile: bottom bar */}
      <nav
        aria-label="Primary mobile"
        className="fixed bottom-0 left-0 right-0 z-40 flex print:hidden border-t border-line bg-surface md:hidden"
      >
        {NAV_ITEMS.map(({ href, label, Icon }) => {
          const active = isActive(href);
          return (
            <Link
              key={href}
              href={href}
              aria-current={active ? "page" : undefined}
              className={cn(
                "flex flex-1 flex-col items-center gap-1 py-2.5 text-[11px] font-medium",
                active ? "text-fg" : "text-fg-subtle",
              )}
            >
              <Icon aria-hidden="true" size={18} strokeWidth={2} />
              <span>{label}</span>
            </Link>
          );
        })}
      </nav>
    </>
  );
}
