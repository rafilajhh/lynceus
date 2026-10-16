/**
 * LogoMark — the Lynceus eye: the watchman's eye whose pupil is a CV
 * detection box in the brand's single amber. Inline SVG so it inherits
 * layout size; strokes/fills follow the design tokens, not text color.
 * Replaces the former ◉ unicode glyph in the top bar and side navbar.
 */
export function LogoMark({ size = 20, className }: { size?: number; className?: string }) {
  return (
    <svg
      viewBox="0 0 256 256"
      width={size}
      height={size}
      className={className}
      aria-hidden="true"
      focusable="false"
    >
      <path
        fill="none"
        stroke="var(--color-ink)"
        strokeWidth="20"
        strokeLinecap="round"
        d="M36 128C68 82 100 66 128 66s60 16 92 62c-32 46-60 62-92 62s-60-16-92-62z"
      />
      <rect x="104" y="104" width="48" height="48" fill="var(--color-amber)" />
    </svg>
  );
}
