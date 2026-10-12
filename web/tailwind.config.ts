import type { Config } from "tailwindcss";

/**
 * Tailwind v4 is CSS-first — the real theme lives in app/globals.css
 * under @theme. This file exists only for tooling that still expects
 * an explicit config entry point; keep custom design tokens in
 * globals.css, not here.
 */
const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  darkMode: ["class", "&:where(.dark, .dark *)"],
};

export default config;
