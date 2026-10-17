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

/** "Rp 16,0 M" / "Rp 350 jt": compact headline figure. The full grouped value
    stays in the title; compact only ever shortens, never changes the value. */
export function formatRupiahCompact(idr: number): string {
  if (!Number.isFinite(idr) || idr <= 0) return "Rp 0";
  const M = 1_000_000_000; // miliar
  const JT = 1_000_000; // juta
  const oneDecimal = (n: number) =>
    new Intl.NumberFormat("id-ID", { maximumFractionDigits: 1 }).format(n);
  if (idr >= M) return `Rp ${oneDecimal(idr / M)} M`;
  if (idr >= JT) return `Rp ${oneDecimal(idr / JT)} jt`;
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

/** "5,200 kg" / "5.2 t": weighbridge register, in the console's English
    number style (matches the inspection result's "15,500 kg"). */
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
 * the console and landing copy: backend/benchmark/results/2026-10-13.summary.json
 * (80 images, live on AMD Token Factory): full inspection p50 19.5 s, p95 34.4 s;
 * VLM call p50 16.5 s (docs/research/token-factory-probe.md: p50 14.5 s over
 * 9 calls). Shown on the /validation page.
 */
export const LIVE_LATENCY_COPY = "about 20 s typically, 34 s at the 95th percentile of completed runs";

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
