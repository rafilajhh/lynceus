import type { Metadata } from "next";
import { ValidationView } from "./validation-view";

export const metadata: Metadata = {
  title: "Validation",
  description:
    "How reliably the live vision gate catches metal, measured on public RealWaste images.",
};

/** Route: /validation: the benchmark behind the headline number, with its limits stated. */
export default function ValidationPage() {
  return <ValidationView />;
}
