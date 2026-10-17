/**
 * Pythia client: POST /assist → an answer from the plant's own records.
 *
 * Pythia is a tool-using agent: it looks things up in the inspection ledger,
 * the supplier scorecard, the example contract, kiln intake and the gate SOP,
 * and every number in a grounded answer appears in one of those lookups.
 * The response carries the lookups (`steps`), the records cited (`sources`)
 * and whether the answer passed the grounding check.
 *
 * The response is untrusted JSON, parsed once here with zod; malformed
 * fields degrade (an answer without valid citations is shown as
 * ungrounded) instead of throwing.
 */

import { z } from "zod";

export const QUESTION_MAX_CHARS = 500;

const assistProvenanceSchema = z
  .object({
    provider: z.string().catch("unknown"),
    model: z.string().nullish().catch(null),
    latency_ms: z.number().nullish().catch(null),
  })
  .catch({ provider: "unknown", model: null, latency_ms: null });

export const CITATION_KINDS = ["record", "supplier", "sop", "contract", "kiln"] as const;
export type CitationKind = (typeof CITATION_KINDS)[number];

const sourceSchema = z.object({
  kind: z.enum(CITATION_KINDS),
  id: z.string().min(1),
  label: z.string().catch(""),
});

const stepSchema = z.object({
  tool: z.string().catch("tool"),
  args: z.record(z.string(), z.unknown()).catch({}),
  summary: z.string().catch(""),
  ms: z.number().nullish().catch(null),
});

/** Keep the well-formed items of a list; drop the rest. */
function listOf<T extends z.ZodTypeAny>(item: T) {
  return z
    .array(z.unknown())
    .catch([])
    .transform((items) =>
      items.flatMap((raw) => {
        const parsed = item.safeParse(raw);
        return parsed.success ? [parsed.data as z.infer<T>] : [];
      }),
    );
}

const assistResponseSchema = z.object({
  answer: z.string().catch(""),
  citations: z.array(z.string()).catch([]),
  sources: listOf(sourceSchema),
  steps: listOf(stepSchema),
  grounded: z.boolean().catch(false),
  provenance: assistProvenanceSchema,
  mode: z.enum(["live", "stub"]).nullish().catch(null),
  latency_ms: z.number().nullish().catch(null),
  note: z.string().nullish().catch(null),
});

export type AssistResponse = z.infer<typeof assistResponseSchema>;
export type AssistSource = z.infer<typeof sourceSchema>;
export type AssistStep = z.infer<typeof stepSchema>;

/** Where a citation opens in the console, or null when it has no page. */
export function sourceHref(source: AssistSource): string | null {
  if (source.kind === "record") return `/inspections?record=${encodeURIComponent(source.id)}`;
  if (source.kind === "supplier") return `/inspections?supplier=${encodeURIComponent(source.id)}`;
  return null;
}

/** Backend 4xx/5xx or network failure, in operator language. */
export class AssistError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "AssistError";
  }
}

export async function askPythia(
  question: string,
  recordId?: string,
  signal?: AbortSignal,
): Promise<AssistResponse> {
  const body: { question: string; record_id?: string } = {
    question: question.trim().slice(0, QUESTION_MAX_CHARS),
  };
  if (recordId) body.record_id = recordId;

  let resp: Response;
  try {
    resp = await fetch("/assist", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(body),
      signal,
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    throw new AssistError("Backend unreachable: is the Lynceus API running?");
  }
  if (resp.status === 404) {
    throw new AssistError(
      recordId ? `Record ${recordId} was not found.` : "Pythia endpoint not found.",
    );
  }
  if (resp.status === 422) {
    throw new AssistError(
      `The question must be 1–${QUESTION_MAX_CHARS} characters` +
        (recordId ? " and the record id valid." : "."),
    );
  }
  if (!resp.ok) {
    throw new AssistError(`Pythia is unavailable (HTTP ${resp.status}).`);
  }
  return parseResponse(await resp.json().catch(() => null));
}

function parseResponse(raw: unknown): AssistResponse {
  const parsed = assistResponseSchema.safeParse(raw);
  if (!parsed.success) {
    throw new AssistError("Pythia returned an unreadable response.");
  }
  return parsed.data;
}

/** What Pythia is doing while the answer is on its way. */
export type PythiaProgress =
  | { kind: "thinking"; turn: number }
  | { kind: "step"; step: AssistStep };

/** One NDJSON line → a progress callback, the final response, or nothing. */
function handleLine(line: string, onProgress: (p: PythiaProgress) => void): AssistResponse | null {
  const trimmed = line.trim();
  if (!trimmed) return null;
  let raw: Record<string, unknown>;
  try {
    raw = JSON.parse(trimmed) as Record<string, unknown>;
  } catch {
    return null; // a torn or non-JSON line carries no state
  }
  if (raw.event === "thinking" && typeof raw.turn === "number") {
    onProgress({ kind: "thinking", turn: raw.turn });
  } else if (raw.event === "step") {
    const step = stepSchema.safeParse(raw);
    if (step.success) onProgress({ kind: "step", step: step.data });
  } else if (raw.event === "result") {
    return parseResponse(raw.data);
  } else if (raw.event === "error") {
    throw new AssistError(
      typeof raw.message === "string" ? raw.message : "Pythia could not answer right now.",
    );
  }
  return null;
}

/**
 * POST /assist/stream: the same answer as {@link askPythia}, with each lookup
 * and model turn reported through `onProgress` as it happens. Any failure of
 * the stream itself (old backend, dropped connection, error line, no result)
 * falls back to one plain POST /assist, whose errors are the operator-facing
 * ones.
 */
export async function askPythiaStreaming(
  question: string,
  recordId: string | undefined,
  onProgress: (p: PythiaProgress) => void,
  signal?: AbortSignal,
): Promise<AssistResponse> {
  const body: { question: string; record_id?: string } = {
    question: question.trim().slice(0, QUESTION_MAX_CHARS),
  };
  if (recordId) body.record_id = recordId;
  const fallback = () => askPythia(question, recordId, signal);

  let resp: Response;
  try {
    resp = await fetch("/assist/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/x-ndjson" },
      body: JSON.stringify(body),
      signal,
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    return fallback();
  }
  if (!resp.ok || !resp.body) return fallback();

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let result: AssistResponse | null = null;
  try {
    for (;;) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      let nl = buffer.indexOf("\n");
      while (nl >= 0) {
        result = handleLine(buffer.slice(0, nl), onProgress) ?? result;
        buffer = buffer.slice(nl + 1);
        nl = buffer.indexOf("\n");
      }
      if (done) break;
    }
    result = handleLine(buffer, onProgress) ?? result;
  } catch (err) {
    if (signal?.aborted) throw err;
    return fallback();
  }
  return result ?? fallback();
}

// ---------------------------------------------------------------------------
// Shift handover briefing (POST /shift/briefing, /shift/briefing/seal)
// ---------------------------------------------------------------------------

export type BriefingWindow = "shift" | "day" | "all";

const briefingItemSchema = z.object({
  text: z.string(),
  citations: listOf(sourceSchema),
});

const briefingSchema = z.object({
  sections: z.array(z.object({ title: z.string(), items: listOf(briefingItemSchema) })),
  generated_at_utc: z.string().catch(""),
  window: z
    .object({
      name: z.string().catch("shift"),
      hours: z.number().nullish().catch(null),
      since: z.string().nullish().catch(null),
      until: z.string().nullish().catch(null),
    })
    .catch({ name: "shift", hours: null, since: null, until: null }),
  model: z.string().nullish().catch(null),
  provider: z.string().nullish().catch(null),
  mode: z.enum(["live", "template"]).catch("template"),
  grounded: z.boolean().catch(false),
  latency_ms: z.number().nullish().catch(null),
  note: z.string().nullish().catch(null),
  facts_digest: z.string().catch(""),
});

export type Briefing = z.infer<typeof briefingSchema>;

/** The parsed briefing plus the response exactly as sent: sealing posts the raw one back. */
export interface BriefingDraft {
  briefing: Briefing;
  raw: unknown;
}

async function postJson(path: string, body: unknown, what: string, signal?: AbortSignal): Promise<unknown> {
  let resp: Response;
  try {
    resp = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(body),
      signal,
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    throw new AssistError("Backend unreachable: is the Lynceus API running?");
  }
  if (!resp.ok) throw new AssistError(`${what} failed (HTTP ${resp.status}).`);
  return resp.json().catch(() => null);
}

export async function draftBriefing(
  window: BriefingWindow = "shift",
  signal?: AbortSignal,
): Promise<BriefingDraft> {
  const raw = await postJson("/shift/briefing", { window }, "Drafting the handover", signal);
  const parsed = briefingSchema.safeParse(raw);
  if (!parsed.success) throw new AssistError("The handover came back unreadable.");
  return { briefing: parsed.data, raw };
}

export interface SealedBriefing {
  briefing_id: string;
  sealed_at_utc: string;
  actor: string;
  digest: string;
}

export async function sealBriefing(draft: BriefingDraft): Promise<SealedBriefing> {
  const raw = (await postJson("/shift/briefing/seal", { briefing: draft.raw }, "Sealing the handover")) as
    | Partial<SealedBriefing>
    | null;
  if (!raw || typeof raw.briefing_id !== "string" || typeof raw.digest !== "string") {
    throw new AssistError("The sealed handover came back unreadable.");
  }
  return {
    briefing_id: raw.briefing_id,
    sealed_at_utc: String(raw.sealed_at_utc ?? ""),
    actor: String(raw.actor ?? ""),
    digest: raw.digest,
  };
}

/** Plain text of a briefing, for the clipboard (mirrors briefing.as_text on the backend). */
export function briefingText(b: Briefing): string {
  const lines = [`Shift handover · ${b.window.since ?? "start"} to ${b.window.until ?? ""} UTC`];
  for (const s of b.sections) {
    lines.push("", s.title);
    if (s.items.length === 0) lines.push("- Nothing to report.");
    for (const i of s.items) lines.push(`- ${i.text}`);
  }
  lines.push(
    "",
    `${b.mode === "live" ? `Drafted by ${b.model ?? "the assist model"}` : "Template briefing"} · facts ${b.facts_digest}`,
  );
  return lines.join("\n");
}
