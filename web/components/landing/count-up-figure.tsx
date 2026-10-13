"use client";

import { useEffect, useRef, useState } from "react";

/**
 * CountUpFigure: a Plex Mono figure that counts up to its target the
 * first time it enters the viewport (IntersectionObserver, exponential
 * ease-out). The landing's single motion moment: the proof strip.
 *
 * Honesty contract: the end value is the sourced figure; the animation
 * only delays its reveal, never changes it. Respects
 * prefers-reduced-motion by rendering the final value immediately.
 */
export function CountUpFigure({
  target,
  prefix = "",
  suffix = "",
  decimals = 0,
  durationMs = 1400,
  className,
}: {
  target: number;
  prefix?: string;
  suffix?: string;
  decimals?: number;
  durationMs?: number;
  className?: string;
}) {
  const ref = useRef<HTMLSpanElement>(null);
  const [value, setValue] = useState(0);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    const prefersReduced =
      typeof window.matchMedia === "function" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    if (prefersReduced || !("IntersectionObserver" in window)) {
      setValue(target);
      return;
    }

    const easeOutExpo = (t: number) => (t >= 1 ? 1 : 1 - Math.pow(2, -10 * t));

    let raf = 0;
    const start = () => {
      const t0 = performance.now();
      const tick = (now: number) => {
        const t = Math.min((now - t0) / durationMs, 1);
        setValue(target * easeOutExpo(t));
        if (t < 1) raf = requestAnimationFrame(tick);
        else setValue(target);
      };
      raf = requestAnimationFrame(tick);
    };

    const io = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          io.disconnect();
          start();
        }
      },
      { threshold: 0.4 }
    );
    io.observe(el);

    return () => {
      io.disconnect();
      cancelAnimationFrame(raf);
    };
  }, [target, durationMs]);

  const formatted =
    decimals > 0
      ? value.toFixed(decimals)
      : String(Math.round(value)).replace(/\B(?=(\d{3})+(?!\d))/g, ",");

  return (
    <span ref={ref} className={className}>
      {prefix}
      {formatted}
      {suffix}
    </span>
  );
}
