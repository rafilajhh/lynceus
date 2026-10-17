import type { Metadata } from "next";
import { ShiftView } from "./shift-view";

export const metadata: Metadata = {
  title: "Shift Report",
  description:
    "What the RDF reception gate changed this shift: trucks cleared without a hand check, hazardous loads stopped, lab and contract recoveries, and each supplier's scorecard.",
};

/**
 * Route: /shift: the AF quality supervisor's view. Leads with the shift's
 * measured improvement, then the supplier scorecard (tier, risk-based
 * sampling, lab averages vs contract spec, deductions), then the value model.
 */
export default function ShiftPage() {
  return <ShiftView />;
}
