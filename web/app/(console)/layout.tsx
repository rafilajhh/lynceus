"use client";

import { useState } from "react";
import { SideNavbar } from "@/components/shell/side-navbar";
import { TopBar } from "@/components/shell/top-bar";
import { SiteFooter } from "@/components/shell/site-footer";

/**
 * Console route group layout: side navbar + top bar (status only, no wordmark/nav) + content.
 * Applies to /app, /inspections, /settings. Landing page (/) uses (landing)/layout.tsx.
 */
export default function ConsoleLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);

  return (
    <>
      <SideNavbar onCollapseChange={setSidebarCollapsed} />
      {/* md:ml-60 expanded (240px), md:ml-16 collapsed (64px) — follows side navbar width */}
      <div className={`flex flex-1 flex-col transition-[margin] duration-200 ${sidebarCollapsed ? "md:ml-16" : "md:ml-60"}`}>
        <TopBar showNav={false} showWordmark={false} />
        {/* pb-20 on mobile: clears the fixed bottom nav (h-16 = 64px + breathing room) */}
        <main className="mx-auto w-full max-w-[1320px] flex-1 px-6 py-6 pb-20 md:pb-14">
          {children}
        </main>
        <SiteFooter />
      </div>
      {/* Mobile bottom bar spacer */}
      <div className="h-16 md:hidden" aria-hidden="true" />
    </>
  );
}
