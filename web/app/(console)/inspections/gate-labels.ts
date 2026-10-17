/** Gate display names and order, shared by the ledger rows and the record
    checklist (backend audit.GATE_NAMES + OPTIONAL_GATE_NAMES). */
export const GATE_ORDER = [
  "vlm_confidence",
  "ocr_confidence",
  "manifest_crosscheck",
  "gas_plausibility",
  "weight_plausibility",
  "detector_second_opinion",
] as const;

export const GATE_LABEL: Record<string, string> = {
  vlm_confidence: "VLM confidence",
  ocr_confidence: "Manifest confidence",
  manifest_crosscheck: "Manifest cross-check",
  gas_plausibility: "Gas plausibility",
  weight_plausibility: "Weight plausibility",
  detector_second_opinion: "Detector second opinion",
};

/** Entries in the canonical gate order; unknown gates follow, as sent. */
export function orderedGates<T>(gates: Record<string, T>): [string, T][] {
  const rank = (name: string) => {
    const i = (GATE_ORDER as readonly string[]).indexOf(name);
    return i === -1 ? GATE_ORDER.length : i;
  };
  return Object.entries(gates).sort(([a], [b]) => rank(a) - rank(b));
}
