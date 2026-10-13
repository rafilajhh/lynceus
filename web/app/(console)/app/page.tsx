import type { Metadata } from "next";
import { WorkspaceClient } from "@/components/workspace/workspace-client";

export const metadata: Metadata = {
  title: "Inspection Workspace",
  description:
    "Inspect an incoming load: intake form, five-gate interlock, verdict with reasons and audit record.",
};

/**
 * Route: /app: the workspace (Operate). One inspection is the whole
 * stage: left "Incoming Load" (photo hero + intake form + demo cases),
 * right "Inspection Verdict" (banner, impact counter, gate strip).
 */
export default function WorkspacePage() {
  return <WorkspaceClient />;
}
