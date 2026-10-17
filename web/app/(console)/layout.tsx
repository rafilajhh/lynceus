"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { fetchSession } from "@/lib/auth-api";
import { SideNavbar } from "@/components/shell/side-navbar";

/**
 * Console route group layout: session guard + side navbar + content.
 * Applies to /app, /inspections, /shift, /validation. When the backend
 * runs with admin credentials, an unauthenticated visitor is sent to
 * /login; in demo mode (no credentials configured) the guard passes
 * through. Pages render <PageHeader> + <PageBody> themselves.
 */
export default function ConsoleLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  const router = useRouter();
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
          className="h-6 w-6 animate-spin rounded-full border-2 border-line-strong border-t-brand"
        />
        <span className="sr-only">Checking your session</span>
      </div>
    );
  }

  return (
    <>
      <SideNavbar />
      {/* md:ml-[248px] follows the fixed side rail; pb-20 on mobile clears the bottom nav. */}
      <div className="flex flex-1 flex-col md:ml-[248px] print:ml-0">
        <main className="w-full flex-1 pb-20 md:pb-0">{children}</main>
      </div>
    </>
  );
}
