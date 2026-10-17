import { ScanEye } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * LogoMark — the Lynceus mark: the watchman's eye (lucide scan-eye) on a
 * brand-blue tile, 8px radius at 30px. Sized by `size` (tile edge in px).
 */
export function LogoMark({ size = 30, className }: { size?: number; className?: string }) {
  return (
    <span
      aria-hidden="true"
      className={cn("inline-flex shrink-0 items-center justify-center bg-brand text-white", className)}
      style={{ width: size, height: size, borderRadius: Math.round(size * 0.27) }}
    >
      <ScanEye size={Math.round(size * 0.63)} strokeWidth={2} />
    </span>
  );
}
