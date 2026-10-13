"use client";

/**
 * WorkspaceClient: route /app (Operate). The whole demo stage:
 *
 * LEFT  "Incoming Load": demo-case buttons, photo hero (rounded 16px,
 *       mono caption), intake form.
 * RIGHT "Inspection Verdict": banner, headline, impact counter,
 *       five-gate interlock strip, reasons, caveats, audit modal.
 *
 * Logic ported from legacy web/app.js: same API contract
 * (POST /inspect, /assess fallback), same demo-case data, same
 * race-guarded photo base64 fetching.
 */

import { cn } from "@/lib/utils";
import { useCallback, useRef, useState } from "react";
import { Panel, PanelHead } from "@/components/ui/panel";
import {
  IntakeForm,
  type IntakeValues,
  type UploadSlot,
} from "./intake-form";
import {
  VerdictPanel,
  verdictTone,
} from "./verdict-panel";
import { normalizeGates, type GateDisplay, type GatePhase } from "./gate-strip";
import { DEMO_CASES } from "@/lib/demo-cases";
import {
  inspectLoad,
  fetchPhotoBase64,
  blobToBase64,
  type InspectResponse,
} from "@/lib/inspect-api";

const EMPTY_FORM: IntakeValues = {
  truck_id: "",
  manifest_text: "",
  weight_kg: "",
  stream: "mixed-msw",
  moisture_pct: "",
  age_h: "",
};

export function WorkspaceClient() {
  const [values, setValues] = useState<IntakeValues>(EMPTY_FORM);
  const [formError, setFormError] = useState<string | null>(null);
  const [resultError, setResultError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState<InspectResponse | null>(null);
  const [phase, setPhase] = useState<GatePhase>("idle");
  const [bannerLit, setBannerLit] = useState(false);
  const [impactRunKey, setImpactRunKey] = useState(0);
  const [activeDemo, setActiveDemo] = useState<string | null>(null);
  const autoSequence = useRef(0);
  const verdictRef = useRef<HTMLDivElement | null>(null);

  // Photo state: nothing is preloaded (user direction): the stage starts
  // empty and a truck arrives only when the operator picks a demo case or
  // uploads a photo. demoPhotoBase64/demoPhotoPath hold the demo bytes.
  const [heroPhoto, setHeroPhoto] = useState<{
    path: string;
    caption: string;
  } | null>(null);
  const demoPhotoBase64 = useRef<string | null>(null);
  const demoPhotoPath = useRef<string | null>(null);

  // ---- Uploads: an uploaded load photo overrides the demo photo; an
  // uploaded waybill photo rides along as extra evidence bytes (backend
  // accepts extra fields; the audit record digests every input). -------
  const EMPTY_SLOT: UploadSlot = { previewUrl: null, filename: null };
  const [loadUpload, setLoadUpload] = useState<UploadSlot>(EMPTY_SLOT);
  const [waybillUpload, setWaybillUpload] = useState<UploadSlot>(EMPTY_SLOT);
  const loadBase64 = useRef<string | null>(null);
  const waybillBase64 = useRef<string | null>(null);

  const pickFile = useCallback(
    (
      file: File | null,
      setSlot: (s: UploadSlot) => void,
      base64Ref: { current: string | null },
      previous: UploadSlot,
    ) => {
      if (previous.previewUrl) URL.revokeObjectURL(previous.previewUrl);
      if (!file) {
        setSlot(EMPTY_SLOT);
        base64Ref.current = null;
        return;
      }
      setSlot({ previewUrl: URL.createObjectURL(file), filename: file.name });
      base64Ref.current = null;
      blobToBase64(file).then((b64) => {
        base64Ref.current = b64;
      });
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );

  const onLoadPhoto = useCallback(
    (file: File | null) => {
      pickFile(file, setLoadUpload, loadBase64, loadUpload);
      // Uploading a photo deselects the demo case: the hero now shows
      // the operator's own evidence, and submit sends its bytes.
      if (file) setActiveDemo(null);
    },
    [pickFile, loadUpload],
  );

  const onWaybillPhoto = useCallback(
    (file: File | null) =>
      pickFile(file, setWaybillUpload, waybillBase64, waybillUpload),
    [pickFile, waybillUpload],
  );

  const gates: GateDisplay[] = normalizeGates(data?.gates);
  const decision = data?.verdict?.decision ?? data?.decision;
  const impact = data?.impact;

  const onChange = useCallback((patch: Partial<IntakeValues>) => {
    setValues((v) => ({ ...v, ...patch }));
  }, []);

  // ---- Demo case loading (race-guarded photo fetch) ----------------
  const onDemo = useCallback((key: "green" | "amber" | "red") => {
    const c = DEMO_CASES[key];
    setFormError(null);
    setResultError(null);
    setValues({
      truck_id: c.truck_id,
      manifest_text: c.manifest_text,
      weight_kg: String(c.weight_kg),
      stream: c.stream,
      moisture_pct: String(c.moisture_pct),
      age_h: String(c.age_h),
    });
    setActiveDemo(key);
    // Picking a demo case clears any uploaded load photo: one source of
    // visual evidence at a time.
    setLoadUpload((prev) => {
      if (prev.previewUrl) URL.revokeObjectURL(prev.previewUrl);
      return { previewUrl: null, filename: null };
    });
    loadBase64.current = null;
    demoPhotoBase64.current = null;
    demoPhotoPath.current = c.photo;
    setHeroPhoto({ path: c.photo, caption: c.photo_caption });
    // Fetch the photo bytes as base64 so submit sends real image data.
    // Race guard: if the user switched cases while this fetch was in
    // flight, drop the stale bytes.
    fetchPhotoBase64(c.photo).then((b64) => {
      if (demoPhotoPath.current === c.photo) demoPhotoBase64.current = b64;
    });
  }, []);

  // ---- Gate camera (auto intake) -------------------------------------
  // Simulates the production trigger: a truck stops at the weighbridge,
  // the gate camera fires, and the load enters the pipeline without the
  // operator touching the form. Cases rotate green -> amber -> red so a
  // run of arrivals tells the full story; manual controls (upload, edit,
  // Inspect) stay untouched for testing the VLM.
  const onTruckArriving = useCallback(() => {
    const order = ["green", "amber", "red"] as const;
    const key = order[autoSequence.current % order.length];
    autoSequence.current += 1;
    onDemo(key);
    // Fire the pipeline after the demo values land; the photo fetch is a
    // fast local asset and the form submit re-reads the latest refs.
    window.setTimeout(() => {
      (document.getElementById("inspect-form") as HTMLFormElement | null)
        ?.requestSubmit();
    }, 350);
  }, [onDemo]);

  // ---- Submit -------------------------------------------------------
  const onSubmit = useCallback(async () => {
    setFormError(null);
    setResultError(null);

    // Client-side validation (legacy contract).
    if (!values.truck_id.trim()) {
      setFormError("Truck ID is required.");
      return;
    }
    const weight = parseFloat(values.weight_kg);
    if (!isFinite(weight) || weight <= 0) {
      setFormError("Weight must be a positive number (kg).");
      return;
    }
    const moisture = parseFloat(values.moisture_pct);
    if (!isFinite(moisture) || moisture < 0 || moisture > 100) {
      setFormError("Moisture must be between 0 and 100 (%).");
      return;
    }
    const age = parseFloat(values.age_h);
    if (!isFinite(age) || age < 0) {
      setFormError("Age must be zero or more hours.");
      return;
    }

    setLoading(true);
    setPhase("evaluating");
    setBannerLit(false);
    // Stale-state fix (review finding 4): clear the previous verdict so
    // the old impact note/gates never sit beneath the pending strip while
    // the new run evaluates.
    setData(null);
    // User direction: pressing Inspect takes the operator straight to the
    // verdict panel (the gate strip is the show while it evaluates).
    // Scroll so the panel sits flush under the sticky topbar (scroll-mt
    // on the wrapper clears the ~60px bar) — the whole verdict, from its
    // head down, is the new viewport.
    verdictRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });

    try {
      const resp = await inspectLoad({
        truck_id: values.truck_id.trim(),
        photo_base64: loadBase64.current ?? demoPhotoBase64.current,
        photo_filename: loadUpload.filename ?? demoPhotoPath.current,
        demo_case: activeDemo,
        manifest_text: values.manifest_text.trim() || null,
        waybill_image_base64: waybillBase64.current,
        weight_kg: weight,
        stream: values.stream,
        moisture_pct: moisture,
        age_h: age,
      });
      setData(resp);
      setImpactRunKey((k) => k + 1);
      setPhase("resolved");
      // Banner lights only after the five gates resolve (GateStrip
      // calls onAllResolved after the last stagger step).
      setBannerLit(false);
    } catch (err) {
      // Network-level failure → inline error with recovery hint.
      setPhase("idle");
      setData(null);
      setResultError(
        err instanceof Error ? err.message : String(err ?? "unknown error"),
      );
    } finally {
      setLoading(false);
    }
  }, [values, activeDemo]);

  const onAllResolved = useCallback(() => {
    setBannerLit(true);
  }, []);

  // Gate flow is truck-by-truck. Reset clears EVERYTHING (user
  // direction): verdict stage, form, demo selection, uploads, photo —
  // the gate stands empty for the next truck.
  const onReset = useCallback(() => {
    setData(null);
    setPhase("idle");
    setBannerLit(false);
    setResultError(null);
    setFormError(null);
    setValues(EMPTY_FORM);
    setActiveDemo(null);
    setHeroPhoto(null);
    setLoadUpload((prev) => {
      if (prev.previewUrl) URL.revokeObjectURL(prev.previewUrl);
      return { previewUrl: null, filename: null };
    });
    setWaybillUpload((prev) => {
      if (prev.previewUrl) URL.revokeObjectURL(prev.previewUrl);
      return { previewUrl: null, filename: null };
    });
    loadBase64.current = null;
    waybillBase64.current = null;
    demoPhotoBase64.current = null;
    demoPhotoPath.current = null;
  }, []);

  const hasPhoto = Boolean(heroPhoto || loadUpload.previewUrl);

  const photoSlot = (
    <figure className="m-0 flex h-full flex-col px-4 py-4">
      {/* eslint-disable-next-line @next/next/no-img-element -- runtime base64/local demo assets; static export has no image optimizer */}
      {/* Click-to-upload (user direction): the photo itself is the upload
          target — hover reveals a hint, picking a file replaces the image.
          aspect-[4/3] crop kills the dead space under the caption. */}
      <input
        id="load-photo-upload"
        type="file"
        accept="image/*"
        className="sr-only"
        disabled={loading}
        onChange={(e) => onLoadPhoto(e.target.files?.[0] ?? null)}
      />
      <label
        htmlFor="load-photo-upload"
        className={cn(
          "group relative block cursor-pointer overflow-hidden rounded-[16px] border transition-colors duration-100",
          hasPhoto
            ? "border-seam hover:border-amber-line"
            : "border-dashed border-seam-strong hover:border-amber-line",
          loading && "pointer-events-none opacity-50",
        )}
        title={loadUpload.filename ? "Replace photo" : "Upload photo"}
      >
        {hasPhoto ? (
          <>
            <img
              src={loadUpload.previewUrl ?? heroPhoto!.path}
              alt={loadUpload.filename ?? heroPhoto!.caption}
              className="aspect-[4/3] w-full object-cover transition-opacity duration-150 group-hover:opacity-60"
            />
            {/* Hover veil: the only affordance for click-to-upload */}
            <span
              aria-hidden="true"
              className="absolute inset-0 flex items-center justify-center text-[13px] font-semibold tracking-[0.6px] text-ink uppercase opacity-0 transition-opacity duration-150 group-hover:opacity-100"
            >
              {loadUpload.filename ? "Replace photo" : "Upload photo"}
            </span>
          </>
        ) : (
          /* Empty stage: no truck at the gate until a demo case or an
              upload arrives (user direction). */
          <span className="flex aspect-[4/3] w-full flex-col items-center justify-center gap-2 text-muted transition-colors duration-100 group-hover:text-ink">
            <span className="text-[22px] leading-none" aria-hidden="true">
              ◉
            </span>
            <span className="text-[13px] font-semibold tracking-[0.6px] uppercase">
              Upload load photo
            </span>
            <span className="text-[12px]">
              or pick a demo case on the right
            </span>
          </span>
        )}
      </label>
      {hasPhoto ? (
        <figcaption className="figure mt-2 text-[11px] leading-relaxed break-words text-muted">
          {loadUpload.filename
            ? `Uploaded photo · ${loadUpload.filename}`
            : heroPhoto!.caption}
        </figcaption>
      ) : null}
      {loadUpload.filename ? (
        <button
          type="button"
          onClick={() => onLoadPhoto(null)}
          disabled={loading}
          className="mt-1 self-start cursor-pointer rounded-[6px] px-2 py-1 text-[12px] font-semibold text-muted transition-colors duration-100 hover:bg-seam hover:text-ink"
        >
          Clear upload
        </button>
      ) : null}
    </figure>
  );

  return (
    /* Vertical gate flow: intake on top, verdict below (user direction,
       2026-10-13). The previous 5/7 split caused a scroll-jump on resolve
       (verdict column outgrew the form) and ~500px of dead space in the
       shorter column; stacking removes both and matches truck-by-truck
       reading order: register first, decision second. */
    <div className="flex flex-col gap-5">
      {/* ============ Incoming Load ============ */}
      <Panel>
        <PanelHead title="Incoming load" meta="weighbridge gate A" />
        <div className="grid grid-cols-1 gap-0 lg:grid-cols-2">
          {/* Photo column: hero + uploads stay beside the register on wide
              screens so the form never stretches full-width unreadably. */}
          <div className="flex flex-col border-b border-seam lg:border-b-0 lg:border-r">
            {photoSlot}
          </div>
          <IntakeForm
            values={values}
            onChange={onChange}
            onDemo={onDemo}
            onTruckArriving={onTruckArriving}
            onSubmit={onSubmit}
            onReset={onReset}
            onWaybillPhoto={onWaybillPhoto}
            waybillPhoto={waybillUpload}
            loading={loading}
            formError={formError}
            activeDemo={activeDemo}
          />
        </div>
      </Panel>

      {/* ============ Inspection Verdict ============ */}
      {/* min-h fills the viewport below the topbar: after Inspect scrolls
          here, the verdict IS the screen (user direction — the incoming
          panel must not peek above it). scroll-mt clears the sticky bar. */}
      <div
        ref={verdictRef}
        className="flex min-h-[calc(100vh-84px)] scroll-mt-[72px] flex-col"
      >
      <VerdictPanel
        phase={phase}
        gates={gates}
        data={data}
        decision={decision}
        preventedLossIdr={impact?.prevented_loss_idr ?? 0}
        preventedLossUsd={impact?.prevented_loss_usd ?? 0}
        impactRunKey={impactRunKey}
        bannerLit={bannerLit}
        onAllResolved={onAllResolved}
        onReset={onReset}
        error={resultError}
      >
        {phase === "resolved" && impact ? (
          <p className="m-0 text-[13px] leading-relaxed text-muted">
            {impact.note}{" "}
            {impact.provenance ? <span>({impact.provenance})</span> : null}
          </p>
        ) : null}
      </VerdictPanel>
      </div>
    </div>
  );
}
