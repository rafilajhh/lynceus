import { cn } from "@/lib/utils";

/** Foundation container: white card, line-strong border, 14px radius. */
export function Panel({
  className,
  children,
  ...props
}: React.ComponentProps<"section">) {
  return (
    <section className={cn("panel", className)} {...props}>
      {children}
    </section>
  );
}

/**
 * Card title row (15px medium) with optional mono meta on the right.
 * Usage: <Panel><PanelHead title="Workspace" meta="route: /app" />…</Panel>
 */
export function PanelHead({
  title,
  meta,
  className,
  children,
}: {
  title: string;
  meta?: string;
  className?: string;
  children?: React.ReactNode;
}) {
  return (
    <div className={cn("panel-head", className)}>
      <span>{title}</span>
      <span className="flex items-center gap-3">
        {meta ? (
          <span className="figure text-muted" style={{ letterSpacing: 0 }}>
            {meta}
          </span>
        ) : null}
        {children}
      </span>
    </div>
  );
}

