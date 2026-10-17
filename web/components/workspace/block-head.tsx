/**
 * BlockHead: the title row of one intake block (Load photos, Waybill,
 * Weighbridge): glyph, small-caps title, and a right-aligned status slot.
 */

import type { ReactNode } from "react";

export function BlockHead({
  id,
  icon,
  title,
  children,
}: {
  id: string;
  icon: ReactNode;
  title: string;
  /** Status on the right: a provenance tag, a reading state. */
  children?: ReactNode;
}) {
  return (
    <div className="flex min-h-[26px] flex-wrap items-center justify-between gap-x-3 gap-y-1">
      <h2 id={id} className="smallcaps m-0 inline-flex items-center gap-2 text-ink">
        <span className="text-muted">{icon}</span>
        {title}
      </h2>
      {children ? <div className="flex items-center gap-2">{children}</div> : null}
    </div>
  );
}

/** Neutral outline tag for provenance labels (SIMULATED FEED, TYPED). */
export function SourceTag({ children, title }: { children: ReactNode; title?: string }) {
  return (
    <span
      title={title}
      className="figure inline-flex items-center rounded-[4px] border border-seam-strong px-1.5 py-0.5 text-[10.5px] font-semibold tracking-[0.8px] whitespace-nowrap text-muted uppercase"
    >
      {children}
    </span>
  );
}
