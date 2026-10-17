/**
 * Gate units for international readers: "16,340 kg", "+7.2 %", "28 %".
 * Money keeps the Indonesian rupiah formatters in lib/format.
 */

const KG = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });

/** 16340 → "16,340 kg" (or "16,340" with unit=false); null → "—". */
export function formatKg(kg: number | null | undefined, unit = true): string {
  if (typeof kg !== "number" || !Number.isFinite(kg)) return "—";
  return unit ? `${KG.format(kg)} kg` : KG.format(kg);
}

/** 0.072 → "+7.2 %"; null → "—". */
export function formatPct(fraction: number | null | undefined): string {
  if (typeof fraction !== "number" || !Number.isFinite(fraction)) return "—";
  const v = fraction * 100;
  const sign = v > 0.05 ? "+" : v < -0.05 ? "−" : "±";
  return `${sign}${Math.abs(v).toFixed(1)} %`;
}

/** 28 → "28 %"; 0.55 (a fraction) is NOT accepted here: pass percent. */
export function formatPercent(pct: number | null | undefined): string {
  if (typeof pct !== "number" || !Number.isFinite(pct)) return "—";
  return `${Number.isInteger(pct) ? pct : pct.toFixed(1)} %`;
}

/** Seconds with one decimal: 12.34 → "12.3 s". */
export function formatSecs(s: number | null | undefined): string {
  if (typeof s !== "number" || !Number.isFinite(s) || s < 0) return "—";
  return `${s.toFixed(1)} s`;
}
