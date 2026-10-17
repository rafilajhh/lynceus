import { LedgerView } from "./ledger-view";

export const metadata = { title: "Inspection Ledger" };

/**
 * Route: /inspections: audit ledger (Read).
 * Every inspection record browsable, tamper-evident, provenance intact:
 * filterable by verdict, sortable on Record/When, each row opening the
 * full audit record (?record=<id>) in place of the ledger.
 */
export default function LedgerPage() {
  return <LedgerView />;
}
