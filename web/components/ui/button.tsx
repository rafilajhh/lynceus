import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

/**
 * Button: the base interactive control (pen.dev redesign).
 * 8px radius, 36px tall; primary = ink-black, default = white outline
 * with a 1-3px lift, ghost = text only.
 */
const buttonVariants = cva(
  "inline-flex h-9 items-center justify-center gap-1.5 rounded-[8px] px-3.5 text-[14px] font-medium whitespace-nowrap transition-colors duration-100 cursor-pointer select-none disabled:pointer-events-none disabled:opacity-50 [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        default:
          "border border-line-strong bg-surface text-fg shadow-control hover:bg-surface-subtle",
        primary:
          "border border-fg bg-fg text-white shadow-control hover:bg-[#2a2b2e]",
        brand:
          "border border-brand bg-brand text-white shadow-control hover:bg-brand-deep",
        ghost:
          "border border-transparent bg-transparent text-fg-muted hover:bg-surface-subtle hover:text-fg",
      },
      size: {
        default: "",
        sm: "h-8 px-3 text-[13px]",
        lg: "h-11 px-5 text-[15px]",
        icon: "w-9 px-0",
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
