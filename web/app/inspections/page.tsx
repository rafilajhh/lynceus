import { LedgerView } from "./ledger-view";

export const metadata = { title: "Inspection Ledger" };

/**
 * Route: /inspections — audit ledger (Read).
 * Every inspection record browsable, immutable, provenance intact —
 * filterable by verdict, sortable on Record/When, each row opening an
 * inline detail panel with the full audit record.
 */
export default function LedgerPage() {
  return <LedgerView />;
}
