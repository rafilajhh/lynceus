import { cn } from "@/lib/utils";

/** Foundation container: graphite panel with hairline seam + card radius. */
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
 * Small-caps panel header band — the industrial register.
 * Usage: <Panel><PanelHead title="Workspace" meta="route: /app" />…</Panel>
 */
export function PanelHead({
  title,
  meta,
  className,
}: {
  title: string;
  meta?: string;
  className?: string;
}) {
  return (
    <div className={cn("panel-head", className)}>
      <span>{title}</span>
      {meta ? (
        <span className="figure text-muted" style={{ letterSpacing: 0 }}>
          {meta}
        </span>
      ) : null}
    </div>
  );
}

