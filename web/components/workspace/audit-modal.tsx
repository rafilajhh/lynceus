"use client";

/**
 * AuditModal: "View audit record" detail dialog showing the full
 * inspection JSON. Real <dialog>-style overlay with protected focus
 * (focus moves into the modal, Escape closes, focus returns to the
 * trigger). Kept dependency-free: a small hand-rolled accessible modal.
 */

import { createPortal } from "react-dom";
import { useEffect, useRef, useState } from "react";
import { ScrollText, X } from "lucide-react";
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
        type="button"
        variant="default"
        className={cn(className)}
        onClick={() => setOpen(true)}
      >
        <ScrollText aria-hidden="true" className="h-3.5 w-3.5" />
        View audit record
      </Button>
      {/* Portalled to <body>: the sticky page header uses backdrop-blur,
          which makes it the containing block of any fixed descendant. */}
      {open
        ? createPortal(
            <div
              className="fixed inset-0 z-[100] flex items-center justify-center bg-fg/40 p-4 backdrop-blur-sm"
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
                className="card flex max-h-[82vh] w-full max-w-[820px] flex-col focus:outline-none"
              >
                <div className="flex items-center justify-between gap-3 border-b border-line px-5 py-4">
                  <div className="flex min-w-0 flex-col gap-0.5">
                    <span className="font-display text-[17px] font-medium text-fg">Audit record</span>
                    <span className="truncate font-mono text-[12px] text-fg-muted">{recordId}</span>
                  </div>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    aria-label="Close audit record"
                    onClick={() => setOpen(false)}
                  >
                    <X aria-hidden="true" className="h-4 w-4" />
                  </Button>
                </div>
                <pre className="figure m-0 flex-1 overflow-auto bg-surface-subtle px-5 py-4 text-[12.5px] leading-relaxed text-fg-muted">
                  {JSON.stringify(data, null, 2)}
                </pre>
              </div>
            </div>,
            document.body,
          )
        : null}
    </>
  );
}
