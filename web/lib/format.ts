/**
 * Presentation formatters: mono figures for money, honest relative time.
 */

/** "Rp 1.234.567": Indonesian grouping, no decimals. */
export function formatRupiah(idr: number): string {
  if (!Number.isFinite(idr) || idr <= 0) return "Rp 0";
  return `Rp ${new Intl.NumberFormat("id-ID", {
    maximumFractionDigits: 0,
  }).format(idr)}`;
}

/** "5.200 kg" / "5,2 t": weighbridge register. */
export function formatWeight(kg: number): string {
  if (!Number.isFinite(kg) || kg <= 0) return "—";
  if (kg >= 1000) {
    return `${new Intl.NumberFormat("id-ID", {
      maximumFractionDigits: 1,
    }).format(kg / 1000)} t`;
  }
  return `${new Intl.NumberFormat("id-ID", {
    maximumFractionDigits: 0,
  }).format(kg)} kg`;
}

/** Relative time: "just now", "4m ago", "3h ago", "2d ago", then a date. */
export function relativeTime(
  isoUtc: string,
  now: number = Date.now(),
): string {
  const t = Date.parse(isoUtc);
  if (Number.isNaN(t)) return isoUtc || "—";
  const seconds = Math.round((now - t) / 1000);
  const abs = Math.abs(seconds);
  if (abs < 45) return "just now";
  if (abs < 3_600) return `${Math.round(abs / 60)}m ago`;
  if (abs < 86_400) return `${Math.round(abs / 3_600)}h ago`;
  if (abs < 30 * 86_400) return `${Math.round(abs / 86_400)}d ago`;
  return new Date(t).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

const PROVIDER_NAMES: Record<string, string> = {
  "amd-token-factory": "AMD Token Factory",
  "openai-compatible": "OpenAI-compatible endpoint",
};

/** Latency in seconds, one decimal: 14523 → "14.5 s". */
export function formatSeconds(ms: number | null | undefined): string | null {
  if (typeof ms !== "number" || !Number.isFinite(ms) || ms < 0) return null;
  return `${(ms / 1000).toFixed(1)} s`;
}

/**
 * "Live · AMD Token Factory · {model} · 14.5 s": the provenance line for
 * output a live model produced. Missing parts are left out, never guessed.
 */
export function liveProvenance(
  provider: string,
  model: string | null | undefined,
  latencyMs: number | null | undefined,
): string {
  return [
    "Live",
    PROVIDER_NAMES[provider] ?? provider,
    model || null,
    formatSeconds(latencyMs),
  ]
    .filter(Boolean)
    .join(" · ");
}

/** Short SHA: "9e8ed093…" for inline display; full digest elsewhere. */
export function shortSha(shaField: string | undefined, len = 10): string {
  const hex = (shaField ?? "").replace(/^sha256:/, "");
  if (!hex) return "—";
  return `${hex.slice(0, len)}…`;
}
