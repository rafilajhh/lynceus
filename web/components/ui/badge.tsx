import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

/**
 * Badge — shadcn/ui badge primitive. On the Lynceus foundation, color is
 * meaning-only: verdict variants map to the decision states; everything
 * else stays graphite.
 */

const badgeVariants = cva(
  "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[12px] font-bold tracking-[0.4px] whitespace-nowrap uppercase",
  {
    variants: {
      variant: {
        default: "border-seam-strong bg-raised text-muted",
        accept: "border-[rgba(46,204,113,0.45)] bg-green-dim text-verdict-green",
        escalate:
          "border-[rgba(245,166,35,0.45)] bg-amber-dim text-verdict-amber",
        reject: "border-[rgba(231,76,60,0.45)] bg-red-dim text-verdict-red",
        refuse: "border-seam-strong bg-raised text-muted",
      },
    },
    defaultVariants: { variant: "default" },
  },
);

export function Badge({
  className,
  variant,
  ...props
}: React.ComponentProps<"span"> & VariantProps<typeof badgeVariants>) {
  return (
    <span className={cn(badgeVariants({ variant }), className)} {...props} />
  );
}

export { badgeVariants };
