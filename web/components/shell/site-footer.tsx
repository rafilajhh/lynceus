import { cn } from "@/lib/utils";

const SOURCE_URL = "https://github.com/rafilajhh/lynceus";

/**
 * Site footer, on the landing and console pages. Carries the source offer
 * the detector weights' AGPL-3.0 licence asks of a network service (§13).
 */
export function SiteFooter({ className }: { className?: string }) {
  return (
    <footer className={cn("border-t border-seam bg-panel px-6 py-5 text-[13px] text-muted", className)}>
      <p className="max-w-[70ch]">
        Lynceus · AMD Developer Hackathon, Intelligent Industry track · ISO 21640:2021 / EN 15359:2011
        reference classes.
      </p>
      <p className="mt-1.5 max-w-[70ch] text-[12px] text-faint">
        <a
          href={SOURCE_URL}
          className="text-muted underline underline-offset-2 transition-colors hover:text-amber"
        >
          Source &amp; licences
        </a>
        {" · "}Code MIT · detector weights AGPL-3.0 / CC BY-NC-SA 4.0 (non-commercial)
      </p>
    </footer>
  );
}
