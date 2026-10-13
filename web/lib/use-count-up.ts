"use client";

/**
 * useCountUp: animated count-up to a target, triggered by a `runKey`
 * change (the workspace fires it when a verdict arrives).
 *
 * Honesty contract (inherited from CountUpFigure): the end value is the
 * real figure; the animation only delays its reveal, never changes it.
 * Respects prefers-reduced-motion by snapping to the final value.
 *
 * Returns [displayValue, isAnimating].
 */

import { useEffect, useRef, useState } from "react";

export function useCountUp(
  target: number,
  runKey: number,
  durationMs = 1400,
): [number, boolean] {
  const [value, setValue] = useState(0);
  const [animating, setAnimating] = useState(false);
  const rafRef = useRef(0);

  useEffect(() => {
    const el = document.documentElement;
    const prefersReduced =
      typeof window.matchMedia === "function" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    if (runKey === 0) {
      setValue(0);
      setAnimating(false);
      return;
    }
    if (prefersReduced) {
      setValue(target);
      setAnimating(false);
      return;
    }

    const easeOutExpo = (t: number) => (t >= 1 ? 1 : 1 - Math.pow(2, -10 * t));
    const t0 = performance.now();
    setAnimating(true);

    const tick = (now: number) => {
      const t = Math.min((now - t0) / durationMs, 1);
      setValue(target * easeOutExpo(t));
      if (t < 1) {
        rafRef.current = requestAnimationFrame(tick);
      } else {
        setValue(target);
        setAnimating(false);
      }
    };
    rafRef.current = requestAnimationFrame(tick);

    return () => {
      cancelAnimationFrame(rafRef.current);
      setAnimating(false);
    };
  }, [target, runKey, durationMs]);

  return [value, animating];
}
