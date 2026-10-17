/**
 * SealedLine: proof that a follow-up (decision, lab result, notice) was
 * sealed onto the truck's record: who, when, and a short digest whose full
 * value sits in the title.
 */

import type { Followup } from "@/lib/ops-api";
import { OpsError } from "@/lib/ops-api";
import { IconSeal } from "./gate-icons";

/** "3f9a1c2b…c2e7b7" for a sha256 hex digest. */
export function shortDigest(hex: string | null | undefined): string {
  if (!hex) return "—";
  const h = hex.replace(/^sha256:/, "");
  return h.length > 16 ? `${h.slice(0, 8)}…${h.slice(-6)}` : h;
}

function clock(iso: string): string {
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return iso;
  return new Date(t).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

const KIND_LABEL: Record<string, string> = {
  resolution: "Decision",
  lab_result: "Lab result",
  notice: "Supplier notice",
};

export function SealedLine({ followup }: { followup: Followup }) {
  return (
    <p className="figure m-0 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11.5px] text-muted">
      <span className="inline-flex items-center gap-1.5 font-semibold text-ink">
        <IconSeal size={14} />
        {KIND_LABEL[followup.kind] ?? followup.kind} sealed
      </span>
      <span>#{followup.seq}</span>
      <span>by {followup.actor}</span>
      <span>{clock(followup.created_at_utc)}</span>
      <span title={followup.digest}>sha256 {shortDigest(followup.digest)}</span>
      <span title="Chained to the inspection record's own digest">
        linked to {shortDigest(followup.parent_record_digest)}
      </span>
    </p>
  );
}

/** Operator wording for a failed follow-up request. */
export function followupError(err: unknown): string {
  if (err instanceof OpsError) {
    if (err.status === 404 || err.status === 405) {
      return "This backend does not record follow-ups yet.";
    }
    if (err.status === 409) return "The inspection record is not complete, so nothing can be added to it.";
    return err.message;
  }
  return err instanceof Error ? err.message : "The request failed.";
}
