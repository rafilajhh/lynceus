/**
 * Pythia client: POST /assist → a cited answer from the plant documents
 * (reference gate SOP, regulation notes) and, optionally, one audit record.
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

const assistResponseSchema = z.object({
  answer: z.string().catch(""),
  citations: z.array(z.string()).catch([]),
  grounded: z.boolean().catch(false),
  provenance: assistProvenanceSchema,
});

export type AssistResponse = z.infer<typeof assistResponseSchema>;

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
  const parsed = assistResponseSchema.safeParse(await resp.json().catch(() => null));
  if (!parsed.success) {
    throw new AssistError("Pythia returned an unreadable response.");
  }
  return parsed.data;
}
