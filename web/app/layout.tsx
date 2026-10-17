import type { Metadata, Viewport } from "next";
import { IBM_Plex_Sans, IBM_Plex_Mono } from "next/font/google";
import "./globals.css";

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

const SITE_TITLE = "Lynceus · AI Gate Inspector";
const SITE_DESCRIPTION =
  "AI gate inspector for RDF fuel trucks: a vision model on AMD Token Factory plus a CPU detector second opinion returns ACCEPT / ESCALATE / REJECT with reasons and a tamper-evident audit record.";
/** Link-preview card (1200×630), rendered from web/scripts/og.html. */
const OG_IMAGE = {
  url: "/og.png",
  width: 1200,
  height: 630,
  alt: "Lynceus: AI gate inspector for RDF fuel trucks",
};

export const metadata: Metadata = {
  metadataBase: new URL("https://lynceus.web.id"),
  title: {
    default: SITE_TITLE,
    template: "%s · Lynceus",
  },
  description: SITE_DESCRIPTION,
  icons: {
    icon: "/favicon.svg",
  },
  openGraph: {
    type: "website",
    url: "/",
    siteName: "Lynceus",
    title: SITE_TITLE,
    description: SITE_DESCRIPTION,
    images: [OG_IMAGE],
  },
  twitter: {
    card: "summary_large_image",
    title: SITE_TITLE,
    description: SITE_DESCRIPTION,
    images: [OG_IMAGE.url],
  },
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
        {children}
      </body>
    </html>
  );
}
