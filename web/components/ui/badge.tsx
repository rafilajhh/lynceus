import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

/**
 * Badge: verdict pill (pen.dev redesign). Tinted surface + colored dot
 * + colored text; color is meaning-only (accept / escalate / reject).
 */

const badgeVariants = cva(
  "inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[12px] font-medium whitespace-nowrap",
  {
    variants: {
      variant: {
        default: "bg-surface-subtle text-fg-muted",
        accept: "bg-success-tint text-success",
        escalate: "bg-warning-tint text-warning",
        reject: "bg-danger-tint text-danger",
        refuse: "bg-surface-subtle text-fg-muted",
      },
    },
    defaultVariants: { variant: "default" },
  },
);

export function Badge({
  className,
  variant,
  dot = true,
  children,
  ...props
}: React.ComponentProps<"span"> & VariantProps<typeof badgeVariants> & { dot?: boolean }) {
  return (
    <span className={cn(badgeVariants({ variant }), className)} {...props}>
      {dot ? <span aria-hidden="true" className="h-1.5 w-1.5 shrink-0 rounded-full bg-current" /> : null}
      {children}
    </span>
  );
}

export { badgeVariants };
