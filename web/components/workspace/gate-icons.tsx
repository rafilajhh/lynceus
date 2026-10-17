/**
 * Gate icon set: authored inline SVGs on the nav icons' grid (24px, stroke
 * 1.8, currentColor), so a status glyph follows its text colour.
 */

function Svg({ children, size = 16 }: { children: React.ReactNode; size?: number }) {
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
      className="shrink-0"
    >
      {children}
    </svg>
  );
}

type IconProps = { size?: number };

export function IconCheck({ size }: IconProps) {
  return (
    <Svg size={size}>
      <path d="m5 12.5 4.2 4.2L19 7" />
    </Svg>
  );
}

export function IconCross({ size }: IconProps) {
  return (
    <Svg size={size}>
      <path d="M6.5 6.5 17.5 17.5M17.5 6.5 6.5 17.5" />
    </Svg>
  );
}

export function IconWarn({ size }: IconProps) {
  return (
    <Svg size={size}>
      <path d="M12 4 21 19.5H3z" />
      <path d="M12 10v4.2" />
      <path d="M12 17.2h.01" />
    </Svg>
  );
}

export function IconInfo({ size }: IconProps) {
  return (
    <Svg size={size}>
      <circle cx="12" cy="12" r="8.2" />
      <path d="M12 11v5" />
      <path d="M12 7.8h.01" />
    </Svg>
  );
}

export function IconDash({ size }: IconProps) {
  return (
    <Svg size={size}>
      <path d="M7 12h10" />
    </Svg>
  );
}

export function IconCamera({ size }: IconProps) {
  return (
    <Svg size={size}>
      <path d="M4 8h3l1.6-2.2h6.8L17 8h3v11H4z" />
      <circle cx="12" cy="13.2" r="3.4" />
    </Svg>
  );
}

export function IconDocument({ size }: IconProps) {
  return (
    <Svg size={size}>
      <path d="M6.5 3.5h7.5l4 4v13h-11.5z" />
      <path d="M14 3.5v4h4" />
      <path d="M9.5 12h5M9.5 15.5h5" />
    </Svg>
  );
}

export function IconScale({ size }: IconProps) {
  return (
    <Svg size={size}>
      <path d="M3 18.5h18" />
      <path d="M5 18.5v-4h14v4" />
      <path d="M9 14.5V9h6v5.5" />
      <path d="M12 9V5.5" />
    </Svg>
  );
}

export function IconCopy({ size }: IconProps) {
  return (
    <Svg size={size}>
      <rect x="8.5" y="8.5" width="11" height="11" rx="1.5" />
      <path d="M15.5 8.5v-3a1.5 1.5 0 0 0-1.5-1.5H6A1.5 1.5 0 0 0 4.5 5.5V14A1.5 1.5 0 0 0 6 15.5h2.5" />
    </Svg>
  );
}

export function IconSeal({ size }: IconProps) {
  return (
    <Svg size={size}>
      <path d="M12 3.6 18.5 6v5.2c0 4.3-2.8 7.4-6.5 9.2-3.7-1.8-6.5-4.9-6.5-9.2V6z" />
      <path d="M9.6 11.6h4.8v3.6H9.6zM10.6 11.6V10a1.4 1.4 0 0 1 2.8 0v1.6" />
    </Svg>
  );
}

export function IconPlay({ size }: IconProps) {
  return (
    <Svg size={size}>
      <path d="M8 5.5v13l10.5-6.5z" />
    </Svg>
  );
}

export function IconPlus({ size }: IconProps) {
  return (
    <Svg size={size}>
      <path d="M12 5.5v13M5.5 12h13" />
    </Svg>
  );
}
