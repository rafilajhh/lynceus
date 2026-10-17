/**
 * Presentation formatters: mono figures for money, honest relative time.
 * Every figure uses en-US separators ("Rp 1,234,567", "16,340 kg"), the
 * same as the backend's notices: the readers are international.
 */

/** "Rp 1,234,567": en-US grouping, no decimals. */
export function formatRupiah(idr: number): string {
  if (!Number.isFinite(idr) || idr <= 0) return "Rp 0";
  return `Rp ${new Intl.NumberFormat("en-US", {
    maximumFractionDigits: 0,
  }).format(idr)}`;
}

/** "Rp 16.0B" / "Rp 350M": compact headline figure (English billion /
    million, not the Indonesian "M" = miliar). The full grouped value stays
    in the title; compact only ever shortens, never changes the value. */
export function formatRupiahCompact(idr: number): string {
  if (!Number.isFinite(idr) || idr <= 0) return "Rp 0";
  const B = 1_000_000_000;
  const M = 1_000_000;
  const oneDecimal = (n: number) =>
    new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 }).format(n);
  if (idr >= B) return `Rp ${oneDecimal(idr / B)}B`;
  if (idr >= M) return `Rp ${oneDecimal(idr / M)}M`;
  return formatRupiah(idr);
}

/** Backend conversion rate (backend/src/lynceus/impact.py: USD_IDR_RATE). */
export const USD_IDR_RATE = 16_000;

/** "US$2,793,664": en-US grouping, no decimals. Sign preserved for negatives. */
export function formatUsd(idr: number): string {
  if (!Number.isFinite(idr) || idr === 0) return "US$0";
  const sign = idr < 0 ? "−" : "";
  return `${sign}US$${new Intl.NumberFormat("en-US", {
    maximumFractionDigits: 0,
  }).format(Math.abs(idr) / USD_IDR_RATE)}`;
}

/** "US$2.8M" / "US$34.4K": compact headline figure; full value stays in the title. */
export function formatUsdCompact(idr: number): string {
  if (!Number.isFinite(idr) || idr === 0) return "US$0";
  const sign = idr < 0 ? "−" : "";
  const usd = Math.abs(idr) / USD_IDR_RATE;
  const oneDecimal = (n: number) =>
    new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 }).format(n);
  if (usd >= 1_000_000) return `${sign}US$${oneDecimal(usd / 1_000_000)}M`;
  if (usd >= 10_000) return `${sign}US$${oneDecimal(usd / 1_000)}K`;
  return `${sign}US$${new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(usd)}`;
}

/** "520 kg" / "5.2 t": weighbridge register. */
export function formatWeight(kg: number): string {
  if (!Number.isFinite(kg) || kg <= 0) return "—";
  if (kg >= 1000) {
    return `${new Intl.NumberFormat("en-US", {
      maximumFractionDigits: 1,
    }).format(kg / 1000)} t`;
  }
  return `${new Intl.NumberFormat("en-US", {
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

/** Display name of a backend provider id ("amd-token-factory" → "AMD Token Factory"). */
export function providerName(provider: string): string {
  return PROVIDER_NAMES[provider] ?? provider;
}

/**
 * Measured live-inspection latency, the one source for every latency claim in
 * the console and landing copy: backend/benchmark/results/2026-10-17.deepseek-vision-exp.summary.json
 * (80/80 images, live on AMD Token Factory, vision model DeepSeek-V4-Flash-Vision-Exp,
 * language model DeepSeek-V4-Flash): full inspection p50 12.2 s, p95 27.1 s;
 * VLM call p50 10.5 s, p95 16.0 s. The slowest request, retries included,
 * took 46.7 s. Shown on the /validation page (read there at runtime).
 */
export const LIVE_LATENCY_COPY = "about 12 s typically, 27 s at the 95th percentile of completed runs";

/** Latency in seconds, one decimal: 14523 → "14.5 s". */
export function formatSeconds(ms: number | null | undefined): string | null {
  if (typeof ms !== "number" || !Number.isFinite(ms) || ms < 0) return null;
  return `${(ms / 1000).toFixed(1)} s`;
}

/** Short latency in whole milliseconds: 153.7 → "154 ms". */
export function formatMilliseconds(ms: number | null | undefined): string | null {
  if (typeof ms !== "number" || !Number.isFinite(ms) || ms < 0) return null;
  return `${Math.round(ms)} ms`;
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
