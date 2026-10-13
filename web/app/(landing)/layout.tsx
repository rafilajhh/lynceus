import { TopBar } from "@/components/shell/top-bar";
import { SiteFooter } from "@/components/shell/site-footer";

/**
 * Landing route group layout: top bar + centered content.
 * Applies to / (landing) and 404. Console routes use (console)/layout.tsx.
 */
export default function LandingLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <>
      <TopBar showStatus={false} />
      <main className="mx-auto w-full max-w-[1320px] flex-1 px-6 py-6 pb-14">
        {children}
      </main>
      <SiteFooter />
    </>
  );
}
