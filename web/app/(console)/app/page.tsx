import type { Metadata } from "next";
import { WorkspaceClient } from "@/components/workspace/workspace-client";

export const metadata: Metadata = {
  title: "Inspection Workspace",
  description:
    "Inspect an incoming RDF truck: AI-read waybill, load photos, weighbridge, live inspection stages, and a sealed verdict with SOP steps.",
};

/**
 * Route: /app: the gate (Operate). One truck is the whole stage: what the
 * gate does and the one-click demo truck, the intake (photos, waybill,
 * weighbridge), the live stages, then the verdict and its follow-ups.
 */
export default function WorkspacePage() {
  return <WorkspaceClient />;
}
