/**
 * SealedRecord: the inspection's tamper-evident record: its id, a short
 * SHA-256 digest (full value in the title), the raw record, and the audit
 * trail where every later follow-up is chained to it.
 */

import Link from "next/link";
import type { InspectResponse } from "@/lib/inspect-api";
import { AuditModal } from "./audit-modal";
import { IconSeal } from "./gate-icons";
import { shortDigest } from "./sealed-line";

export function recordDigest(data: InspectResponse): string | null {
  const record = data.audit_record as { digest?: { record_sha256?: unknown } } | undefined;
  const d = record?.digest?.record_sha256;
  return typeof d === "string" && d ? d : null;
}

export function SealedRecord({ data }: { data: InspectResponse }) {
  const recordId = data.record_id ?? null;
  const digest = recordDigest(data);
  if (!recordId) {
    return (
      <p className="m-0 text-[13px] text-muted">
        No record was written for this run, so there is nothing to seal.
      </p>
    );
  }
  return (
    <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
      <p className="figure m-0 flex flex-wrap items-center gap-x-2.5 gap-y-1 text-[12.5px] text-muted">
        <span className="inline-flex items-center gap-1.5 font-semibold text-ink">
          <IconSeal size={15} />
          {recordId}
        </span>
        {digest ? <span title={digest}>sha256 {shortDigest(digest)}</span> : null}
        <span className="font-sans text-faint">every input, model output and rule, sealed</span>
      </p>
      <div className="flex items-center gap-1">
        <AuditModal recordId={recordId} data={data} />
        <Link
          href="/inspections"
          className="rounded-[6px] px-3 py-1.5 text-xs font-semibold text-muted transition-colors duration-100 hover:bg-seam hover:text-ink"
        >
          Open the audit trail
        </Link>
      </div>
    </div>
  );
}
