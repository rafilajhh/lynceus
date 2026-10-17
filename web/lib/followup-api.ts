/**
 * Follow-up actions on a sealed record: notify the supplier, escalate to a
 * supervisor. The audit record itself is never changed; actions live in an
 * append-only, hash-chained log next to it (GET/POST
 * /inspections/{record_id}/actions).
 */

import { z } from "zod";

export const FOLLOWUP_NOTE_MAX = 500;

export type FollowupKind = "notify_supplier" | "escalate";

const actionSchema = z.object({
  action_id: z.string(),
  record_id: z.string(),
  kind: z.enum(["notify_supplier", "escalate"]),
  created_at_utc: z.string().catch(""),
  actor: z.string().nullish().catch(null),
  note: z.string().nullish().catch(null),
  notice: z
    .object({ to: z.string(), subject: z.string(), body: z.string() })
    .nullish()
    .catch(null),
  delivery: z.enum(["webhook", "logged"]).nullish().catch(null),
  delivery_error: z.string().nullish().catch(null),
  prev_sha256: z.string().catch(""),
  entry_sha256: z.string().catch(""),
});

export type FollowupAction = z.infer<typeof actionSchema>;

const listSchema = z.object({
  actions: z.array(actionSchema).catch([]),
  chain_ok: z.boolean().catch(false),
});

export type FollowupLog = z.infer<typeof listSchema>;

export class FollowupError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "FollowupError";
  }
}

async function errorMessage(resp: Response): Promise<string> {
  try {
    const body = (await resp.json()) as { detail?: { message?: unknown } | string };
    const detail = body?.detail;
    if (typeof detail === "string") return detail;
    if (detail && typeof detail.message === "string") return detail.message;
  } catch {
    // fall through
  }
  return `HTTP ${resp.status}`;
}

const path = (recordId: string) =>
  `/inspections/${encodeURIComponent(recordId)}/actions`;

export async function fetchActions(
  recordId: string,
  signal?: AbortSignal,
): Promise<FollowupLog> {
  let resp: Response;
  try {
    resp = await fetch(path(recordId), {
      headers: { Accept: "application/json" },
      credentials: "same-origin",
      cache: "no-store",
      signal,
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    throw new FollowupError("Backend unreachable.");
  }
  if (!resp.ok) throw new FollowupError(await errorMessage(resp));
  const parsed = listSchema.safeParse(await resp.json().catch(() => null));
  if (!parsed.success) throw new FollowupError("Unreadable follow-up log.");
  return parsed.data;
}

export async function postAction(
  recordId: string,
  kind: FollowupKind,
  note?: string | null,
): Promise<FollowupAction> {
  let resp: Response;
  try {
    resp = await fetch(path(recordId), {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      credentials: "same-origin",
      body: JSON.stringify({
        kind,
        note: note?.trim() ? note.trim().slice(0, FOLLOWUP_NOTE_MAX) : null,
      }),
    });
  } catch {
    throw new FollowupError("Backend unreachable.");
  }
  if (!resp.ok) throw new FollowupError(await errorMessage(resp));
  const parsed = z
    .object({ action: actionSchema })
    .safeParse(await resp.json().catch(() => null));
  if (!parsed.success) throw new FollowupError("Unreadable follow-up response.");
  return parsed.data.action;
}
