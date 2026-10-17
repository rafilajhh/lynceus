import type { Metadata } from "next";
import { WorkspaceClient } from "@/components/workspace/workspace-client";

export const metadata: Metadata = {
  title: "Inspection Workspace",
  description:
    "Inspect an incoming load: load photo, waybill and register, six-gate interlock, verdict with reasons and audit record.",
};

/**
 * Route: /app: the inspection workspace (Operate). WorkspaceClient renders
 * the page header and both views: "New inspection" (incoming load,
 * waybill & register, verdict pipeline) and "Inspection result".
 */
export default function WorkspacePage() {
  return <WorkspaceClient />;
}
