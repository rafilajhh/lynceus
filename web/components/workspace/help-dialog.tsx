"use client";

/**
 * HelpDialog: the (?) button in the New inspection header and the short
 * "How inspection works" walkthrough it opens. Accessible modal: focus
 * moves in on open and is trapped (Tab / Shift+Tab cycle), Escape or the
 * backdrop closes, focus returns to the trigger.
 */

import { createPortal } from "react-dom";
import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import { CircleHelp, X } from "lucide-react";
import { Button } from "@/components/ui/button";

const STEPS: { title: string; body: React.ReactNode }[] = [
  {
    title: "Capture",
    body: "Add the load photo from the gate camera and a photo of the paper waybill.",
  },
  {
    title: "Check the register",
    body:
      "The waybill is read automatically: truck ID, supplier, weight and stream fill in. " +
      "Check them, correct anything wrong, and add moisture and age. Fields you type are never overwritten.",
  },
  {
    title: "Inspect",
    body:
      "Press Inspect load. Six checks run: visual contaminants, waybill text, waybill against " +
      "the observed load, gas sensors, weighbridge against declared weight, and a second-opinion detector.",
  },
  {
    title: "Read the verdict",
    body: (
      <dl className="m-0 mt-1.5 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
        <dt className="font-mono text-[11px] font-medium tracking-[1px] text-success">ACCEPT</dt>
        <dd className="m-0">Admit the load to processing.</dd>
        <dt className="font-mono text-[11px] font-medium tracking-[1px] text-warning">ESCALATE</dt>
        <dd className="m-0">Hold the truck until a supervisor reviews it.</dd>
        <dt className="font-mono text-[11px] font-medium tracking-[1px] text-danger">REJECT</dt>
        <dd className="m-0">Do not admit; follow the next steps.</dd>
        <dt className="font-mono text-[11px] font-medium tracking-[1px] text-fg-muted">REFUSED</dt>
        <dd className="m-0">Not enough usable input to judge; supply it and inspect again.</dd>
      </dl>
    ),
  },
  {
    title: "Follow up",
    body:
      "Every verdict is sealed in a tamper-evident audit record. From the result you can notify " +
      "the supplier or escalate to a supervisor; each action is logged next to the record.",
  },
];

const FOCUSABLE =
  'a[href], button:not([disabled]), textarea, input, select, [tabindex]:not([tabindex="-1"])';

export function HelpDialog() {
  const [open, setOpen] = useState(false);
  const dialogRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const titleId = useId();

  useEffect(() => {
    if (!open) return;
    dialogRef.current?.focus();
    const trigger = triggerRef.current;
    return () => trigger?.focus();
  }, [open]);

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === "Escape") {
      e.stopPropagation();
      setOpen(false);
      return;
    }
    if (e.key !== "Tab" || !dialogRef.current) return;
    const items = Array.from(dialogRef.current.querySelectorAll<HTMLElement>(FOCUSABLE));
    if (items.length === 0) {
      e.preventDefault();
      return;
    }
    const first = items[0];
    const last = items[items.length - 1];
    const active = document.activeElement;
    if (e.shiftKey && (active === first || active === dialogRef.current)) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && active === last) {
      e.preventDefault();
      first.focus();
    }
  };

  return (
    <>
      <Button
        ref={triggerRef}
        type="button"
        size="icon"
        aria-label="How inspection works"
        title="How inspection works"
        aria-haspopup="dialog"
        onClick={() => setOpen(true)}
        className="shadow-none"
      >
        <CircleHelp aria-hidden="true" className="h-4 w-4" />
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
                aria-labelledby={titleId}
                tabIndex={-1}
                onKeyDown={onKeyDown}
                className="card flex max-h-[86vh] w-full max-w-[520px] flex-col focus:outline-none"
              >
                <div className="flex items-center justify-between gap-3 border-b border-line px-5 py-4">
                  <h2 id={titleId} className="m-0 font-display text-[17px] font-medium text-fg">
                    How inspection works
                  </h2>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    aria-label="Close"
                    onClick={() => setOpen(false)}
                  >
                    <X aria-hidden="true" className="h-4 w-4" />
                  </Button>
                </div>
                <ol className="m-0 flex list-none flex-col gap-4 overflow-auto px-5 py-5">
                  {STEPS.map((step, i) => (
                    <li key={step.title} className="flex items-start gap-3">
                      <span
                        aria-hidden="true"
                        className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-surface-muted font-mono text-[12px] text-fg"
                      >
                        {i + 1}
                      </span>
                      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                        <h3 className="m-0 text-[14px] font-medium text-fg">{step.title}</h3>
                        <div className="text-[13px] leading-5 text-fg-muted">{step.body}</div>
                      </div>
                    </li>
                  ))}
                </ol>
              </div>
            </div>,
            document.body,
          )
        : null}
    </>
  );
}
