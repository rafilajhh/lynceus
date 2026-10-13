"use client";

/**
 * AuditModal: "View audit record" detail dialog showing the full
 * inspection JSON. Real <dialog>-style overlay with protected focus
 * (focus moves into the modal, Escape closes, focus returns to the
 * trigger). Kept dependency-free per the vanilla-free-but-lean rule:
 * a small hand-rolled accessible modal.
 */

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export function AuditModal({
  recordId,
  data,
  className,
}: {
  recordId: string;
  data: unknown;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const dialogRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("keydown", onKey);
    // Move focus into the modal on open.
    dialogRef.current?.focus();
    return () => {
      document.removeEventListener("keydown", onKey);
      // Return focus to the trigger on close (protected focus).
      triggerRef.current?.focus();
    };
  }, [open]);

  return (
    <>
      <Button
        ref={triggerRef}
        variant="ghost"
        size="sm"
        className={cn("underline-offset-2 hover:underline", className)}
        onClick={() => setOpen(true)}
      >
        View audit record
      </Button>
      {open ? (
        <div
          className="fixed inset-0 z-[100] flex items-center justify-center bg-[rgba(10,12,16,0.78)] p-4 backdrop-blur-sm"
          onClick={(e) => {
            if (e.target === e.currentTarget) setOpen(false);
          }}
        >
          <div
            ref={dialogRef}
            role="dialog"
            aria-modal="true"
            aria-label={`Audit record ${recordId}`}
            tabIndex={-1}
            className="panel flex max-h-[82vh] w-full max-w-[820px] flex-col focus:outline-none"
          >
            <div className="panel-head">
              <span>Audit record · {recordId}</span>
              <Button
                variant="ghost"
                size="sm"
                aria-label="Close audit record"
                onClick={() => setOpen(false)}
              >
                ✕ Close
              </Button>
            </div>
            <pre className="figure m-0 flex-1 overflow-auto bg-ground px-4 py-3 text-[13px] leading-relaxed text-muted">
              {JSON.stringify(data, null, 2)}
            </pre>
          </div>
        </div>
      ) : null}
    </>
  );
}
