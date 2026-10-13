"use client";

import { useEffect, useState } from "react";

/**
 * Whole seconds since `active` became true; 0 while inactive. Drives the
 * honest "n s elapsed" readout on long live-model waits (the vision model
 * takes ~15 s on the shared endpoint): a real clock, not a fake progress
 * bar.
 */
export function useElapsedSeconds(active: boolean): number {
  const [seconds, setSeconds] = useState(0);

  useEffect(() => {
    setSeconds(0);
    if (!active) return;
    const started = Date.now();
    const timer = window.setInterval(() => {
      setSeconds(Math.floor((Date.now() - started) / 1000));
    }, 250);
    return () => window.clearInterval(timer);
  }, [active]);

  return seconds;
}
