/**
 * Nav icon set — authored inline SVGs, one stroke weight (1.8), 24px grid,
 * currentColor so they follow the link's text color in every state.
 * Replaces unicode glyphs (▶ ≡ ◷ ✓ ◂ ▸) which render at inconsistent
 * sizes and weights across platforms.
 */

function Svg({ children, size = 18 }: { children: React.ReactNode; size?: number }) {
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {children}
    </svg>
  );
}

/** Inspection: the gate's eye over a scan line. */
export function IconInspection({ size }: { size?: number }) {
  return (
    <Svg size={size}>
      <path d="M3 12c3.2-4.6 6.4-6 9-6s5.8 1.4 9 6c-3.2 4.6-6.4 6-9 6s-5.8-1.4-9-6z" />
      <rect x="10" y="10" width="4" height="4" />
    </Svg>
  );
}

/** Audit Trail: ledger rows with a hash tick. */
export function IconAuditTrail({ size }: { size?: number }) {
  return (
    <Svg size={size}>
      <path d="M4 5.5h16" />
      <path d="M4 10.5h16" />
      <path d="M4 15.5h10" />
      <path d="m15.5 18.5 1.8 1.8 3.2-3.6" />
    </Svg>
  );
}

/** Control room: a dial with its needle over a baseline. */
export function IconControl({ size }: { size?: number }) {
  return (
    <Svg size={size}>
      <path d="M4 16a8 8 0 0 1 16 0" />
      <path d="m12 16 3.6-4.4" />
      <path d="M4 19.5h16" />
    </Svg>
  );
}

/** Shift: a clock over a baseline. */
export function IconShift({ size }: { size?: number }) {
  return (
    <Svg size={size}>
      <circle cx="12" cy="12" r="8.2" />
      <path d="M12 7.5V12l3 2.2" />
    </Svg>
  );
}

/** Validation: badge with a check. */
export function IconValidation({ size }: { size?: number }) {
  return (
    <Svg size={size}>
      <path d="M12 3.6 18.5 6v5.2c0 4.3-2.8 7.4-6.5 9.2-3.7-1.8-6.5-4.9-6.5-9.2V6z" />
      <path d="m9.2 11.8 2 2 3.8-4.2" />
    </Svg>
  );
}

/** Collapse/expand: chevrons pointing inward/outward. */
export function IconCollapse({ collapsed, size }: { collapsed: boolean; size?: number }) {
  return (
    <Svg size={size}>
      {collapsed ? (
        <path d="m9 6 6 6-6 6" />
      ) : (
        <path d="m15 6-6 6 6 6" />
      )}
    </Svg>
  );
}
