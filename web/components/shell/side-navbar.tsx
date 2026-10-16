"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { fetchSession, logout } from "@/lib/auth-api";
import { LogoMark } from "@/components/ui/logo-mark";
import {
  IconAuditTrail,
  IconCollapse,
  IconInspection,
  IconShift,
  IconValidation,
} from "@/components/ui/nav-icons";
import { cn } from "@/lib/utils";

const NAV_ITEMS = [
  { href: "/app", label: "Inspection", Icon: IconInspection },
  { href: "/inspections", label: "Audit Trail", Icon: IconAuditTrail },
  { href: "/shift", label: "Shift", Icon: IconShift },
  { href: "/validation", label: "Validation", Icon: IconValidation },
] as const;

/**
 * SideNavbar — persistent left navigation for the console dashboard.
 * 240px expanded, 64px icon-only collapsed. Amber left border for active route.
 * Collapses to bottom bar on mobile (md breakpoint).
 */
export function SideNavbar({ onCollapseChange }: { onCollapseChange?: (collapsed: boolean) => void }) {
  const pathname = usePathname();
  const router = useRouter();
  const [collapsed, setCollapsed] = useState(false);
  const [authOn, setAuthOn] = useState(false);

  // The sign-out control only exists when the backend actually enforces
  // auth; in demo mode (no admin credentials) it would be a dead button.
  useEffect(() => {
    const controller = new AbortController();
    fetchSession(controller.signal)
      .then((s) => setAuthOn(s.user != null))
      .catch(() => {});
    return () => controller.abort();
  }, []);

  const toggle = () => {
    const next = !collapsed;
    setCollapsed(next);
    onCollapseChange?.(next);
  };

  const signOut = async () => {
    await logout();
    router.replace("/login");
  };

  return (
    <>
      {/* Desktop: side navbar */}
      <nav
        aria-label="Primary"
        className={cn(
          "fixed left-0 top-0 z-40 hidden h-screen flex-col border-r border-seam bg-panel transition-[width] duration-200 md:flex",
          collapsed ? "w-16" : "w-60"
        )}
      >
        {/* Brand: wordmark with amber glyph, links to landing. No hover
            treatment: it is identity, not an interactive control. */}
        <Link href="/" className="flex h-14 items-center gap-3 border-b border-seam px-4">
          <LogoMark size={22} className="shrink-0" />
          {!collapsed && (
            <div className="flex flex-col">
              <span className="text-[15px] font-bold tracking-[2px] text-ink">LYNCEUS</span>
              <span className="text-[10px] font-semibold tracking-[1px] text-muted uppercase">AI Gate Inspector</span>
            </div>
          )}
          {collapsed && (
            <span className="sr-only">Lynceus home</span>
          )}
        </Link>

        {/* Nav items: decision-focused, no filler. Active state uses amber left border
            as the single deliberate accent (core Part 3). */}
        <div className="flex flex-1 flex-col gap-1 p-3">
          {NAV_ITEMS.map((item) => {
            const isActive = pathname === item.href;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  "flex items-center gap-3 rounded-[6px] px-3 py-2.5 text-[13px] font-semibold transition-colors duration-100",
                  isActive
                    ? "border-l-2 border-amber bg-raised text-ink"
                    : "text-muted hover:bg-seam hover:text-ink"
                )}
                aria-current={isActive ? "page" : undefined}
                title={collapsed ? item.label : undefined}
              >
                <item.Icon size={18} />
                {!collapsed && <span>{item.label}</span>}
              </Link>
            );
          })}
        </div>

        {/* Sign out (only when auth is enforced) + collapse toggle */}
        {authOn ? (
          <button
            type="button"
            onClick={() => void signOut()}
            className="flex h-11 items-center justify-center gap-2 border-t border-seam text-[12px] font-semibold tracking-[0.6px] text-muted uppercase transition-colors duration-100 hover:bg-seam hover:text-ink"
          >
            Sign out
          </button>
        ) : null}
        <button
          type="button"
          onClick={toggle}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          className="flex h-12 items-center justify-center border-t border-seam text-muted hover:bg-seam hover:text-ink transition-colors duration-100"
        >
          <IconCollapse collapsed={collapsed} size={18} />
        </button>
      </nav>

      {/* Mobile: bottom bar */}
      <nav
        aria-label="Primary mobile"
        className="fixed bottom-0 left-0 right-0 z-40 flex border-t border-seam bg-panel md:hidden"
      >
        {NAV_ITEMS.map((item) => {
          const isActive = pathname === item.href;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "flex flex-1 flex-col items-center gap-1 py-3 text-[11px] font-semibold",
                isActive ? "text-amber" : "text-muted"
              )}
              aria-current={isActive ? "page" : undefined}
            >
              <item.Icon size={20} />
              <span>{item.label}</span>
            </Link>
          );
        })}
      </nav>
    </>
  );
}
