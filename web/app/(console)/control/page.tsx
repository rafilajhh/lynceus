import type { Metadata } from "next";
import { ControlView } from "./control-view";

export const metadata: Metadata = {
  title: "Control Room",
  description:
    "The RDF reception gate at a glance: chlorine load against the shift budget, alternative-fuel energy, alarms, the latest gate decisions, loads waiting for a supervisor, supplier risk, lab trend, carbon and inference on AMD.",
};

/**
 * Route: /control: the AF quality supervisor's live view of the gate. One
 * call (GET /control/summary) refreshed every 20 s while the tab is visible.
 */
export default function ControlPage() {
  return <ControlView />;
}
