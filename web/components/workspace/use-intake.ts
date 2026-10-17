"use client";

/**
 * useIntake: everything the gate knows about the truck before it inspects:
 * the load photos (main + up to 2 angles), the waybill photo and its AI-read
 * fields (editable, edits tracked), and the weighbridge reading.
 *
 * Every async step is generation-guarded: a newer preset, upload or reset
 * makes a slower older response land nowhere. State is mirrored in refs that
 * update in the same call as the state, so a chained flow (Run the demo
 * truck) reads the intake as it is now, not as of its last render.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  EMPTY_WAYBILL,
  IntakeError,
  WAYBILL_FIELDS,
  parseFieldNumber,
  readToValues,
  readWaybill,
  readWeighbridge,
  type ScaleReading,
  type WaybillFieldKey,
  type WaybillRead,
  type WaybillValues,
} from "@/lib/waybill-api";
import { encodeLoadPhoto, encodeRaw, type EncodedPhoto } from "./photo-encode";

export const MAX_PHOTOS = 3;
/** One field lands every REVEAL_MS while a fresh read fills the form. */
const REVEAL_MS = 70;

export interface PhotoSlot {
  id: number;
  previewUrl: string;
  filename: string;
}

export type WaybillStatus = "empty" | "reading" | "read" | "typed" | "offline";

export interface WaybillState {
  photo: PhotoSlot | null;
  status: WaybillStatus;
  /** Why the fields are typed rather than read, or a read warning. */
  message: string | null;
  read: WaybillRead | null;
  /** Values exactly as read: edits are measured against these. */
  readValues: WaybillValues | null;
  confidence: Partial<Record<WaybillFieldKey, number>>;
  values: WaybillValues;
  /** Fields shown so far while a fresh read fills the form. */
  revealed: number;
  startedAt: number | null;
}

export type ScaleStatus = "idle" | "reading" | "live" | "manual";

export interface ScaleState {
  status: ScaleStatus;
  reading: ScaleReading | null;
  manualNet: string;
  message: string | null;
}

const EMPTY_WAYBILL_STATE: WaybillState = {
  photo: null,
  status: "empty",
  message: null,
  read: null,
  readValues: null,
  confidence: {},
  values: EMPTY_WAYBILL,
  revealed: WAYBILL_FIELDS.length,
  startedAt: null,
};

const EMPTY_SCALE: ScaleState = { status: "idle", reading: null, manualNet: "", message: null };
const NO_PHOTOS: (PhotoSlot | null)[] = [null, null, null];

export function prefersReducedMotion(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** Fields the operator changed after the AI read them. */
function editedOf(w: WaybillState): WaybillFieldKey[] {
  const read = w.readValues;
  if (!read) return [];
  return WAYBILL_FIELDS.map((f) => f.key).filter((k) => w.values[k].trim() !== read[k].trim());
}

/** The net weight the gate will use: the captured reading or the typed one. */
function scaleNetOf(s: ScaleState): number | null {
  if (s.status === "live" && s.reading) return s.reading.net_kg;
  if (s.status === "manual") return parseFieldNumber(s.manualNet);
  return null;
}

function errorText(err: unknown): string {
  return err instanceof Error && err.message ? err.message : "no answer";
}

/** State plus a ref that always holds the newest value. */
function useMirrored<T>(initial: T) {
  const [state, setState] = useState<T>(initial);
  const ref = useRef<T>(initial);
  const update = useCallback((next: T | ((prev: T) => T)) => {
    ref.current = typeof next === "function" ? (next as (prev: T) => T)(ref.current) : next;
    setState(ref.current);
  }, []);
  return [state, update, ref] as const;
}

export function useIntake() {
  const [photos, setPhotos, photosRef] = useMirrored<(PhotoSlot | null)[]>(NO_PHOTOS);
  const [waybill, setWaybill, waybillRef] = useMirrored<WaybillState>(EMPTY_WAYBILL_STATE);
  const [scale, setScale, scaleRef] = useMirrored<ScaleState>(EMPTY_SCALE);

  const nextId = useRef(1);
  /** Encodes in flight or done, per slot id. */
  const jobs = useRef(new Map<number, Promise<EncodedPhoto | null>>());
  const waybillJob = useRef<Promise<EncodedPhoto | null> | null>(null);
  /** Bumped by every new waybill, scale request or reset. */
  const waybillGen = useRef(0);
  const scaleGen = useRef(0);
  /** The plate the truck registered under at the weighbridge, when it is
      not the waybill's (the "Wrong truck" preset); "" = use the waybill's. */
  const registeredPlate = useRef("");
  const urls = useRef(new Set<string>());

  const track = useCallback((file: File): PhotoSlot => {
    const previewUrl = URL.createObjectURL(file);
    urls.current.add(previewUrl);
    return { id: nextId.current++, previewUrl, filename: file.name };
  }, []);

  const release = useCallback((slot: PhotoSlot | null) => {
    if (!slot) return;
    URL.revokeObjectURL(slot.previewUrl);
    urls.current.delete(slot.previewUrl);
    jobs.current.delete(slot.id);
  }, []);

  useEffect(() => {
    const all = urls.current;
    return () => all.forEach((u) => URL.revokeObjectURL(u));
  }, []);

  // ---- Load photos -------------------------------------------------------

  const setPhoto = useCallback(
    (index: number, file: File | null) => {
      const next = [...photosRef.current];
      release(next[index]);
      if (file) {
        const slot = track(file);
        jobs.current.set(slot.id, encodeLoadPhoto(file).catch(() => null));
        next[index] = slot;
      } else {
        next[index] = null;
      }
      // Angles close up behind a removed photo: no gaps in the frame list.
      const kept = next.filter((p): p is PhotoSlot => p !== null);
      setPhotos([...kept, ...Array<null>(MAX_PHOTOS - kept.length).fill(null)]);
    },
    [photosRef, release, setPhotos, track],
  );

  /** Encoded bytes of the photos on stage, in frame order. */
  const encodedPhotos = useCallback(async () => {
    const slots = photosRef.current.filter((p): p is PhotoSlot => p !== null);
    const encoded = await Promise.all(slots.map((s) => jobs.current.get(s.id) ?? null));
    return slots.flatMap((slot, i) => {
      const photo = encoded[i];
      return photo ? [{ slot, photo }] : [];
    });
  }, [photosRef]);

  // ---- Weighbridge -------------------------------------------------------

  const captureScale = useCallback(
    async (waybillPlate: string, declaredNet: number | null) => {
      const gen = ++scaleGen.current;
      const plate = registeredPlate.current || waybillPlate;
      if (!plate.trim()) {
        setScale((s) => ({
          ...s,
          status: "manual",
          message: "No plate yet: read the waybill, or type the net weight from the indicator.",
        }));
        return;
      }
      setScale((s) => ({ ...s, status: "reading", message: null }));
      try {
        const reading = await readWeighbridge(plate.trim(), declaredNet);
        if (gen !== scaleGen.current) return;
        setScale((s) => ({ ...s, status: "live", reading, message: null }));
      } catch (err) {
        if (gen !== scaleGen.current) return;
        const message =
          err instanceof IntakeError && err.kind === "unavailable"
            ? "No weighbridge feed on this backend: type the net weight from the indicator."
            : `The weighbridge did not answer (${errorText(err)}): type the net weight.`;
        setScale((s) => ({ ...s, status: "manual", reading: null, message }));
      }
    },
    [setScale],
  );

  const setManualNet = useCallback(
    (manualNet: string) => {
      scaleGen.current++;
      setScale((s) => ({ ...s, status: "manual", manualNet }));
    },
    [setScale],
  );

  const switchToManualScale = useCallback(() => {
    scaleGen.current++;
    setScale((s) => ({
      ...s,
      status: "manual",
      manualNet: s.manualNet || (s.reading ? String(s.reading.net_kg) : ""),
      message: null,
    }));
  }, [setScale]);

  // ---- Waybill -------------------------------------------------------------

  /**
   * Show a waybill photo and read it. `fallback` (the bundled sample's
   * printed values) is used only when this backend has no reader at all,
   * and is then labelled as typed. Resolves once the fields are on screen
   * and the weighbridge was asked for its reading. `truckPlate` registers
   * the truck at the scale under a plate other than the waybill's.
   */
  const setWaybillPhoto = useCallback(
    async (file: File | null, fallback?: WaybillValues, truckPlate?: string) => {
      const gen = ++waybillGen.current;
      registeredPlate.current = truckPlate?.trim() ?? "";
      release(waybillRef.current.photo);
      if (!file) {
        waybillJob.current = null;
        setWaybill(EMPTY_WAYBILL_STATE);
        return;
      }
      const slot = track(file);
      const job = encodeRaw(file).catch(() => null);
      waybillJob.current = job;
      setWaybill({ ...EMPTY_WAYBILL_STATE, photo: slot, status: "reading", startedAt: performance.now() });

      const encoded = await job;
      if (gen !== waybillGen.current) return;
      if (!encoded) {
        setWaybill((w) => ({
          ...w,
          status: "typed",
          message: "The browser could not open this photo: type the fields.",
        }));
        return;
      }

      let values: WaybillValues;
      try {
        const read = await readWaybill(encoded.base64, encoded.filename);
        if (gen !== waybillGen.current) return;
        const parsed = readToValues(read);
        values = parsed.values;
        const reduce = prefersReducedMotion();
        setWaybill((w) => ({
          ...w,
          status: "read",
          read,
          readValues: parsed.values,
          confidence: parsed.confidence,
          values: parsed.values,
          message: read.warnings.length > 0 ? read.warnings.join(" ") : null,
          revealed: reduce ? WAYBILL_FIELDS.length : 0,
        }));
        if (!reduce) await sleep(REVEAL_MS * (WAYBILL_FIELDS.length + 2));
      } catch (err) {
        if (gen !== waybillGen.current) return;
        const unavailable = err instanceof IntakeError && err.kind === "unavailable";
        const offline = err instanceof IntakeError && err.kind === "offline";
        values = unavailable && fallback ? fallback : EMPTY_WAYBILL;
        setWaybill((w) => ({
          ...w,
          status: offline ? "offline" : "typed",
          values,
          message: unavailable
            ? fallback
              ? "This backend has no waybill reader: the fields were typed from the sample waybill. Check them against the photo."
              : "This backend has no waybill reader: type the fields from the photo."
            : offline
              ? errorText(err)
              : `The waybill could not be read (${errorText(err)}): type the fields.`,
        }));
      }
      if (gen !== waybillGen.current) return;
      await captureScale(values.plate, parseFieldNumber(values.net_kg));
    },
    [captureScale, release, setWaybill, track, waybillRef],
  );

  // Field-by-field fill after a fresh read.
  useEffect(() => {
    if (waybill.status !== "read" || waybill.revealed >= WAYBILL_FIELDS.length) return;
    const t = setTimeout(() => setWaybill((w) => ({ ...w, revealed: w.revealed + 1 })), REVEAL_MS);
    return () => clearTimeout(t);
  }, [waybill.status, waybill.revealed, setWaybill]);

  const editField = useCallback(
    (key: WaybillFieldKey, value: string) => {
      setWaybill((w) => ({
        ...w,
        status: w.status === "empty" ? "typed" : w.status,
        revealed: WAYBILL_FIELDS.length,
        values: { ...w.values, [key]: value },
      }));
    },
    [setWaybill],
  );

  const editedFields = useMemo(() => editedOf(waybill), [waybill]);

  const encodedWaybill = useCallback(
    async () => (waybillJob.current ? await waybillJob.current : null),
    [],
  );

  // ---- Whole gate ----------------------------------------------------------

  const reset = useCallback(() => {
    waybillGen.current++;
    scaleGen.current++;
    registeredPlate.current = "";
    waybillJob.current = null;
    photosRef.current.forEach(release);
    release(waybillRef.current.photo);
    setPhotos(NO_PHOTOS);
    setWaybill(EMPTY_WAYBILL_STATE);
    setScale(EMPTY_SCALE);
  }, [photosRef, release, setPhotos, setScale, setWaybill, waybillRef]);

  /** The intake as it is right now, for a flow that continues after awaits. */
  const latest = useCallback(
    () => ({
      waybill: waybillRef.current,
      editedFields: editedOf(waybillRef.current),
      scale: scaleRef.current,
      scaleNetKg: scaleNetOf(scaleRef.current),
    }),
    [scaleRef, waybillRef],
  );

  return {
    photos,
    setPhoto,
    encodedPhotos,
    waybill,
    setWaybillPhoto,
    editField,
    editedFields,
    encodedWaybill,
    scale,
    scaleNetKg: scaleNetOf(scale),
    captureScale,
    setManualNet,
    switchToManualScale,
    reset,
    latest,
  };
}

export type Intake = ReturnType<typeof useIntake>;
