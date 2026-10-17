import { cn } from "@/lib/utils";

/**
 * PageHeader — the 72px console topbar from the pen.dev redesign:
 * 12px crumb over a 22px display title on the left, actions on the right,
 * hairline underneath. Every console page renders one as its first child,
 * then its body inside <PageBody> (32px padding).
 */
export function PageHeader({
  crumb,
  title,
  children,
  className,
}: {
  crumb: React.ReactNode;
  title: React.ReactNode;
  children?: React.ReactNode;
  className?: string;
}) {
  return (
    <header
      className={cn(
        "sticky top-0 z-30 flex min-h-[72px] flex-wrap items-center justify-between gap-x-6 gap-y-3 border-b border-line bg-background/90 px-5 py-3 backdrop-blur md:px-8",
        className,
      )}
    >
      <div className="flex min-w-0 flex-col gap-0.5">
        <span className="truncate text-[12px] text-fg-subtle">{crumb}</span>
        <h1 className="truncate font-display text-[22px] leading-tight font-medium text-fg">{title}</h1>
      </div>
      {children ? <div className="flex flex-wrap items-center gap-2">{children}</div> : null}
    </header>
  );
}

export function PageBody({ className, children }: { className?: string; children: React.ReactNode }) {
  return <div className={cn("p-5 md:p-8", className)}>{children}</div>;
}
