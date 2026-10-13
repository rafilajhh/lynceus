"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { cn } from "@/lib/utils";

const NAV_ITEMS = [
  { href: "/app", label: "Inspection", icon: "▶" },
  { href: "/inspections", label: "Audit Trail", icon: "≡" },
  { href: "/shift", label: "Shift", icon: "◷" },
  { href: "/validation", label: "Validation", icon: "✓" },
] as const;

/**
 * SideNavbar — persistent left navigation for the console dashboard.
 * 240px expanded, 64px icon-only collapsed. Amber left border for active route.
 * Collapses to bottom bar on mobile (md breakpoint).
 */
export function SideNavbar({ onCollapseChange }: { onCollapseChange?: (collapsed: boolean) => void }) {
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState(false);

  const toggle = () => {
    const next = !collapsed;
    setCollapsed(next);
    onCollapseChange?.(next);
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
          <span className="text-amber text-xl" aria-hidden="true">◉</span>
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
              >
                {/* Icon glyphs: functional markers for route identification, not decorative */}
                <span className="text-[16px] w-5 text-center" aria-hidden="true">{item.icon}</span>
                {!collapsed && <span>{item.label}</span>}
              </Link>
            );
          })}
        </div>

        {/* Collapse toggle */}
        <button
          type="button"
          onClick={toggle}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          className="flex h-12 items-center justify-center border-t border-seam text-muted hover:bg-seam hover:text-ink transition-colors duration-100"
        >
          <span aria-hidden="true">{collapsed ? "▸" : "◂"}</span>
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
              <span className="text-[18px]" aria-hidden="true">{item.icon}</span>
              <span>{item.label}</span>
            </Link>
          );
        })}
      </nav>
    </>
  );
}
