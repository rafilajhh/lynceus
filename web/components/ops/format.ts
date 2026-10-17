/**
 * Ops-surface formatters (/shift, /control, /validation): en-US numbers,
 * Rupiah through lib/format (one locale for the whole app), UTC clock parts.
 * One home so the pages read the same.
 */

import { formatRupiah, formatRupiahCompact, formatUsd } from "@/lib/format";

export const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** en-US number, at most `digits` decimals. */
export function num(n: number, digits = 1): string {
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: digits }).format(n);
}

/** "Rp 4.2M": the contract's currency, compact; the full value goes in the title. */
export const rp = formatRupiahCompact;

/** "Rp 4,200,000 (≈ US$263)": the full value, for titles. */
export function rpFull(idr: number): string {
  return `${formatRupiah(idr)} (≈ ${formatUsd(idr)})`;
}

/** "2026-10-13T09:53:07Z" → { day: "13 Oct", time: "09:53" } (UTC, no locale drift). */
export function utcParts(iso: string | null | undefined): { day: string; time: string } | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(iso ?? "");
  if (!m) return null;
  return { day: `${Number(m[3])} ${MONTHS[Number(m[2]) - 1] ?? m[2]}`, time: `${m[4]}:${m[5]}` };
}

/** "09:53 UTC", or "13 Oct 09:53 UTC" when `withDay`. */
export function utcClock(iso: string | null | undefined, withDay = false): string {
  const p = utcParts(iso);
  if (!p) return "—";
  return withDay ? `${p.day} ${p.time} UTC` : `${p.time} UTC`;
}

/** Minutes since `iso` (never negative); null when unparseable. */
export function minutesSince(iso: string | null | undefined, now = Date.now()): number | null {
  const t = Date.parse(iso ?? "");
  if (Number.isNaN(t)) return null;
  return Math.max(0, Math.round((now - t) / 60_000));
}

/** Backend prose may name a field ("read_latency_ms"): never show a raw key. */
export function plainWords(text: string): string {
  return text.replace(/\b[a-z]+(?:_[a-z0-9]+)+\b/g, (key) => key.replace(/_/g, " "));
}

export const plural =(n: number, one: string, many: string) => (n === 1 ? one : many);
