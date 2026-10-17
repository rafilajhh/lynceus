"use client";

/**
 * useInspection: one truck's run, from Inspect to the sealed verdict. The
 * stage events stream in (POST /inspect/stream); a backend without the
 * stream answers in one piece (POST /inspect). The snapshot freezes what was
 * submitted, so the verdict keeps showing these photos and these declared
 * values while the intake above moves on to the next truck.
 */

import { useCallback, useRef, useState } from "react";
import { InspectError, type InspectPayload, type InspectResponse } from "@/lib/inspect-api";
import { inspectStreaming, type InspectMode, type StageEvent } from "@/lib/inspect-stream";
import type { ScaleReading, WaybillRead, WaybillValues } from "@/lib/waybill-api";
import type { WaybillStatus } from "./use-intake";

export interface RunSnapshot {
  frames: { src: string; filename: string }[];
  waybill: {
    values: WaybillValues;
    status: WaybillStatus;
    read: WaybillRead | null;
    editedFields: string[];
  };
  scale: {
    netKg: number;
    declaredNetKg: number | null;
    source: "weighbridge_simulated" | "weighbridge" | "manual_entry";
    reading: ScaleReading | null;
  };
}

export interface RunError {
  kind: "network" | "http";
  message: string;
  status: number | null;
}

export interface RunState {
  phase: "idle" | "running" | "done" | "error";
  /** Bumped by every start: effects key their scroll and requests on it. */
  runId: number;
  mode: InspectMode | null;
  events: StageEvent[];
  /** performance.now() at submit. */
  startedAt: number | null;
  /** Wall-clock submit → verdict, measured here. */
  elapsedMs: number | null;
  result: InspectResponse | null;
  error: RunError | null;
  snapshot: RunSnapshot | null;
}

const IDLE: RunState = {
  phase: "idle",
  runId: 0,
  mode: null,
  events: [],
  startedAt: null,
  elapsedMs: null,
  result: null,
  error: null,
  snapshot: null,
};

export function useInspection() {
  const [run, setRun] = useState<RunState>(IDLE);
  const current = useRef(0);

  const start = useCallback(async (payload: InspectPayload, snapshot: RunSnapshot) => {
    const runId = ++current.current;
    const startedAt = performance.now();
    setRun({ ...IDLE, phase: "running", runId, startedAt, snapshot });
    const mine = () => runId === current.current;
    try {
      const result = await inspectStreaming(
        payload,
        (e) => mine() && setRun((r) => ({ ...r, events: [...r.events, e] })),
        (mode) => mine() && setRun((r) => ({ ...r, mode })),
      );
      if (!mine()) return;
      setRun((r) => ({ ...r, phase: "done", result, elapsedMs: performance.now() - startedAt }));
    } catch (err) {
      if (!mine()) return;
      const error: RunError =
        err instanceof InspectError
          ? { kind: err.kind, message: err.message, status: err.status }
          : { kind: "http", message: err instanceof Error ? err.message : "Unexpected error.", status: null };
      setRun((r) => ({ ...r, phase: "error", error, elapsedMs: performance.now() - startedAt }));
    }
  }, []);

  /** Forget the run on screen (a request already sent still completes and
      is sealed on the backend; its answer is simply not shown). */
  const clear = useCallback(() => {
    current.current++;
    setRun(IDLE);
  }, []);

  return { run, start, clear };
}
