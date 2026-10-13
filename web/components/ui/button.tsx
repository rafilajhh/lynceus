import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

/**
 * .btn: the base interactive control.
 * 6px radius (machine-control feel), raised surface, amber accents.
 * Other agents compose these variants; do not invent new ad-hoc buttons.
 */
const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 rounded-[6px] px-4 py-2 text-[13px] font-semibold tracking-[0.2px] transition-colors duration-100 cursor-pointer select-none disabled:pointer-events-none disabled:opacity-50 active:translate-y-px",
  {
    variants: {
      variant: {
        default:
          "bg-raised border border-seam-strong text-ink hover:bg-seam hover:border-amber-line",
        primary:
          "bg-amber border border-amber text-ground hover:bg-[#ffb53a] hover:border-[#ffb53a]",
        ghost:
          "bg-transparent border border-transparent text-muted hover:text-ink hover:bg-seam",
      },
      size: {
        default: "px-4 py-2",
        sm: "px-3 py-1.5 text-xs",
        lg: "px-6 py-2.5 text-sm",
      },
    },
    defaultVariants: { variant: "default", size: "default" },
  },
);

export function Button({
  className,
  variant,
  size,
  ...props
}: React.ComponentProps<"button"> & VariantProps<typeof buttonVariants>) {
  return (
    <button className={cn(buttonVariants({ variant, size }), className)} {...props} />
  );
}

export { buttonVariants };
