import type { Metadata } from "next";
import { ShiftView } from "./shift-view";

export const metadata: Metadata = {
  title: "Shift Report",
  description:
    "What the gate caught this shift, what it saved, and which suppliers keep sending bad loads.",
};

/**
 * Route: /shift: the shift supervisor's view. Headline figures for the
 * shift, then supplier risk with a grounded explanation per flagged supplier.
 */
export default function ShiftPage() {
  return <ShiftView />;
}
