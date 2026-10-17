"use client";

/**
 * Segmented: the pill segmented control from the redesign (Metal / Clean /
 * Wet presets, Annotated / Original evidence view). Each option is a real
 * button with aria-pressed, so keyboard and screen readers get plain
 * toggle-button semantics.
 */

import { cn } from "@/lib/utils";

export function Segmented<T extends string>({
  label,
  options,
  value,
  onSelect,
  disabled = false,
  busy = null,
  className,
}: {
  /** Accessible name of the group. */
  label: string;
  options: { value: T; label: string; title?: string }[];
  /** The pressed option; null = none pressed. */
  value: T | null;
  onSelect: (value: T) => void;
  disabled?: boolean;
  /** Option whose action is in flight (shows an ellipsis). */
  busy?: T | null;
  className?: string;
}) {
  return (
    <div
      role="group"
      aria-label={label}
      className={cn("inline-flex items-center gap-0.5 rounded-full bg-surface-subtle p-[3px]", className)}
    >
      {options.map((o) => {
        const pressed = value === o.value;
        return (
          <button
            key={o.value}
            type="button"
            aria-pressed={pressed}
            title={o.title}
            disabled={disabled}
            onClick={() => onSelect(o.value)}
            className={cn(
              "cursor-pointer rounded-full px-3 py-[5px] text-[13px] font-medium whitespace-nowrap transition-colors duration-100 select-none disabled:pointer-events-none disabled:opacity-50",
              pressed ? "bg-fg text-white" : "text-fg-muted hover:text-fg",
            )}
          >
            {busy === o.value ? "…" : o.label}
          </button>
        );
      })}
    </div>
  );
}
