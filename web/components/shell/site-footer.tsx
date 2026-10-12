export function SiteFooter() {
  return (
    <footer className="border-t border-seam bg-panel px-6 py-5 text-center text-[13px] text-muted">
      <p className="mx-auto max-w-[70ch]">
        Lynceus · AI on AMD GPU track · Verdicts are{" "}
        <code className="figure text-muted">screening_estimate</code> for triage,
        not validated measurements. ISO 21640:2021 / EN 15359:2011 reference
        classes.
      </p>
    </footer>
  );
}
