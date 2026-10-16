"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { fetchSession } from "@/lib/auth-api";
import { SideNavbar } from "@/components/shell/side-navbar";
import { TopBar } from "@/components/shell/top-bar";

/**
 * Console route group layout: session guard + side navbar + top bar
 * (status only) + content. Applies to /app, /inspections, /shift,
 * /validation. When the backend runs with admin credentials, an
 * unauthenticated visitor is sent to /login; in demo mode (no
 * credentials configured) the guard passes through.
 */
export default function ConsoleLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  const router = useRouter();
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [allowed, setAllowed] = useState<boolean | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    fetchSession(controller.signal)
      .then((s) => {
        if (s.authenticated) {
          setAllowed(true);
        } else {
          router.replace("/login");
        }
      })
      .catch((err) => {
        if (err instanceof DOMException && err.name === "AbortError") return;
        router.replace("/login");
      });
    return () => controller.abort();
  }, [router]);

  if (allowed !== true) {
    return (
      <div className="flex min-h-[50vh] items-center justify-center" role="status">
        <span
          aria-hidden="true"
          className="h-6 w-6 animate-spin rounded-full border-2 border-seam border-t-amber"
        />
        <span className="sr-only">Checking your session</span>
      </div>
    );
  }

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
      </div>
    </>
  );
}
