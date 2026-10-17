import { TopBar } from "@/components/shell/top-bar";
import { SiteFooter } from "@/components/shell/site-footer";

/**
 * Landing route group layout: navbar + full-bleed sections + footer.
 * Applies to / (landing) and 404. Console routes use (console)/layout.tsx.
 * Sections own their own 1440px container so backgrounds can run edge to edge.
 */
export default function LandingLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <>
      <TopBar />
      <main className="flex w-full flex-1 flex-col">{children}</main>
      <SiteFooter />
    </>
  );
}
