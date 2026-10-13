import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Settings",
  description: "Console configuration and system preferences.",
};

export default function SettingsPage() {
  return (
    <div className="flex flex-col gap-6">
      <div className="panel">
        <div className="panel-head">
          <span>Settings</span>
        </div>
        <div className="px-4 py-6">
          <p className="text-[14px] text-muted">
            Console configuration and system preferences will be available here.
          </p>
          <div className="mt-4 rounded-[8px] border border-seam bg-raised px-4 py-3">
            <p className="text-[13px] text-muted">
              <span className="font-semibold text-ink">Current configuration:</span> Default
            </p>
            <ul className="mt-2 space-y-1 text-[13px] text-muted">
              <li>• AI Provider: vLLM (stub mode)</li>
              <li>• Storage: ./runs</li>
              <li>• Audit Format: v1</li>
              <li>• Theme: Graphite Dark</li>
            </ul>
          </div>
        </div>
      </div>
    </div>
  );
}
