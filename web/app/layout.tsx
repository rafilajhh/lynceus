import type { Metadata, Viewport } from "next";
import { IBM_Plex_Sans, IBM_Plex_Mono } from "next/font/google";
import "./globals.css";
import { TopBar } from "@/components/shell/top-bar";
import { SiteFooter } from "@/components/shell/site-footer";

const plexSans = IBM_Plex_Sans({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-plex-sans",
  display: "swap",
});

const plexMono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-plex-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: {
    default: "Lynceus · AI Gate Inspector",
    template: "%s · Lynceus",
  },
  description:
    "Enterprise-grade AI gate inspection for Indonesian waste-to-energy plants. Verdicts with reasons, audit records, and honest degradation.",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  colorScheme: "dark",
  themeColor: "#0a0c10",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={`${plexSans.variable} ${plexMono.variable}`}>
      <body className="flex min-h-screen flex-col bg-ground font-sans text-ink">
        <TopBar />
        <main className="mx-auto w-full max-w-[1320px] flex-1 px-6 py-6 pb-14">
          {children}
        </main>
        <SiteFooter />
      </body>
    </html>
  );
}
