"use client";

/**
 * WorkspaceClient: route /app (Operate). The whole demo stage:
 *
 * LEFT  "Incoming Load": demo-case buttons, photo hero (rounded 16px,
 *       mono caption), intake form.
 * BELOW "Inspection Verdict": banner + provenance, headline, gate
 *       strip, photo evidence with outlined contaminants beside the
 *       SOP-cited next steps, impact counter, reasons, caveats, Pythia,
 *       audit modal.
 *
 * Logic ported from legacy web/app.js: same API contract
 * (POST /inspect), same demo-case data, same race-guarded photo
 * base64 fetching.
 */

import { cn } from "@/lib/utils";
import { useCallback, useMemo, useRef, useState } from "react";
import { Panel, PanelHead } from "@/components/ui/panel";
import {
  IntakeForm,
  type IntakeValues,
  type UploadSlot,
} from "./intake-form";
import { VerdictPanel, type ResultError, type RunMode } from "./verdict-panel";
import { normalizeGates, type GateDisplay, type GatePhase } from "./gate-strip";
import {
  inspectLoad,
  blobToBase64,
  InspectError,
  type InspectResponse,
} from "@/lib/inspect-api";

/** Long edge (px) of the load photo sent to the VLM. Image tokens, and so
 * VLM latency, grow with pixel count; a 12 MP phone photo has ~10x the pixels
 * of a 1280x960 one. 1280 is still >2x the 524 px image the Token Factory
 * probe localised at IoU >= 0.888 (docs/research/token-factory-probe.md). */
const MAX_PHOTO_EDGE_PX = 1280;
const PHOTO_JPEG_QUALITY = 0.85;

/** The load photo re-encoded as a JPEG with its long edge at
 * MAX_PHOTO_EDGE_PX, or null when it is already that small or the browser
 * cannot decode or re-encode it (the original bytes are sent instead).
 * Aspect ratio is kept, so normalised (0..1) boxes map onto either image;
 * the canvas applies EXIF orientation, so the model sees what the
 * preview shows. */
async function downscaledJpeg(file: File): Promise<Blob | null> {
  const url = URL.createObjectURL(file);
  try {
    const img = new Image();
    img.src = url;
    await img.decode();
    const longEdge = Math.max(img.naturalWidth, img.naturalHeight);
    if (longEdge <= MAX_PHOTO_EDGE_PX) return null;
    const scale = MAX_PHOTO_EDGE_PX / longEdge;
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(img.naturalWidth * scale));
    canvas.height = Math.max(1, Math.round(img.naturalHeight * scale));
    const ctx = canvas.getContext("2d");
    if (!ctx) return null;
    // A transparent PNG would turn black in a JPEG; flatten onto white.
    ctx.fillStyle = "#fff";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
    return await new Promise<Blob | null>((resolve) =>
      canvas.toBlob(resolve, "image/jpeg", PHOTO_JPEG_QUALITY),
    );
  } catch {
    return null;
  } finally {
    URL.revokeObjectURL(url);
  }
}

/** Base64 + MIME of the bytes actually sent for the load photo, and whether
 * they were re-encoded to JPEG here. Original bytes keep the file's own MIME,
 * empty when the browser does not know it (e.g. HEIC): the backend reads the
 * image type from the bytes, never from a name or MIME. */
async function encodeLoadPhoto(
  file: File,
): Promise<{ base64: string; mime: string; reencoded: boolean }> {
  const small = await downscaledJpeg(file);
  return small
    ? { base64: await blobToBase64(small), mime: "image/jpeg", reencoded: true }
    : { base64: await blobToBase64(file), mime: file.type, reencoded: false };
}

/** The audit names the bytes it stores: only a photo re-encoded here becomes
 * a .jpg; original bytes keep their original name. */
function sentFilename(name: string | null, reencoded: boolean): string | null {
  if (!name || !reencoded || /\.jpe?g$/i.test(name)) return name;
  return `${name.replace(/\.[^./\\]+$/, "")}.jpg`;
}

const EMPTY_FORM: IntakeValues = {
  truck_id: "",
  supplier: "",
  manifest_text: "",
  weight_kg: "",
  stream: "mixed-msw",
  moisture_pct: "",
  age_h: "",
};

export function WorkspaceClient() {
  const [values, setValues] = useState<IntakeValues>(EMPTY_FORM);
  const [formError, setFormError] = useState<string | null>(null);
  const [resultError, setResultError] = useState<ResultError | null>(null);
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState<InspectResponse | null>(null);
  const [phase, setPhase] = useState<GatePhase>("idle");
  const [bannerLit, setBannerLit] = useState(false);
  const [impactRunKey, setImpactRunKey] = useState(0);
  const verdictRef = useRef<HTMLDivElement | null>(null);

  // ---- Uploads: an uploaded load photo is the evidence; an uploaded
  // waybill photo rides along as extra evidence bytes (backend accepts
  // extra fields; the audit record digests every input). -------------
  const EMPTY_SLOT: UploadSlot = { previewUrl: null, filename: null };
  const [loadUpload, setLoadUpload] = useState<UploadSlot>(EMPTY_SLOT);
  const [waybillUpload, setWaybillUpload] = useState<UploadSlot>(EMPTY_SLOT);
  const loadBase64 = useRef<string | null>(null);
  const loadSent = useRef({ mime: "image/jpeg", reencoded: false });
  const waybillBase64 = useRef<string | null>(null);

  // The photo the current verdict is about, frozen at submit: the intake
  // side may change (new upload, next demo case) while the verdict and
  // its outlined contaminants are still on screen.
  const [evidence, setEvidence] = useState<{ src: string | null; alt: string }>({
    src: null,
    alt: "Load photo",
  });
  const [runMode, setRunMode] = useState<RunMode>("other");

  // Encodes in flight, per slot: submit awaits them, and only the latest
  // pick may store its bytes (a slow older encode must not overwrite it).
  const encoding = useRef(new Map<object, Promise<void>>());

  const pickFile = useCallback(
    (
      file: File | null,
      setSlot: (s: UploadSlot) => void,
      base64Ref: { current: string | null },
      previous: UploadSlot,
      encode: (file: File) => Promise<{ base64: string; mime: string; reencoded?: boolean }>,
      sentRef?: { current: { mime: string; reencoded: boolean } },
    ) => {
      if (previous.previewUrl) URL.revokeObjectURL(previous.previewUrl);
      base64Ref.current = null;
      if (!file) {
        setSlot(EMPTY_SLOT);
        encoding.current.delete(base64Ref);
        return;
      }
      setSlot({ previewUrl: URL.createObjectURL(file), filename: file.name });
      const job: Promise<void> = encode(file).then(
        ({ base64, mime, reencoded }) => {
          if (encoding.current.get(base64Ref) !== job) return;
          base64Ref.current = base64;
          if (sentRef) sentRef.current = { mime, reencoded: reencoded ?? false };
        },
        () => undefined, // unreadable file: no bytes are stored
      );
      encoding.current.set(base64Ref, job);
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );

  const onLoadPhoto = useCallback(
    (file: File | null) =>
      pickFile(file, setLoadUpload, loadBase64, loadUpload, encodeLoadPhoto, loadSent),
    [pickFile, loadUpload],
  );

  // The waybill photo is evidence bytes, not a VLM input: sent unchanged.
  const onWaybillPhoto = useCallback(
    (file: File | null) =>
      pickFile(file, setWaybillUpload, waybillBase64, waybillUpload, async (f) => ({
        base64: await blobToBase64(f),
        mime: f.type,
      })),
    [pickFile, waybillUpload],
  );

  // Memoised: GateStrip restarts its lighting stagger whenever the array
  // identity changes, so a fresh array per render (typing in the form, say)
  // would replay the interlock.
  const gates: GateDisplay[] = useMemo(
    () => normalizeGates(data?.gates),
    [data?.gates],
  );
  const decision = data?.verdict?.decision ?? data?.decision;
  const impact = data?.impact;

  const onChange = useCallback((patch: Partial<IntakeValues>) => {
    setValues((v) => ({ ...v, ...patch }));
  }, []);

  // ---- Submit -------------------------------------------------------
  const runInspection = useCallback(async () => {
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

    // A photo picked just now may still be downscaling: wait for its bytes.
    // Loading is set first so a second click cannot start a parallel run.
    setLoading(true);
    await Promise.all(encoding.current.values());

    // Freeze the evidence photo for this inspection. Uploaded bytes become
    // a data: URL so a later upload revoking its object URL cannot blank
    // the verdict's photo.
    const uploadSrc = loadBase64.current
      ? `data:${loadSent.current.mime || "application/octet-stream"};base64,${loadBase64.current}`
      : loadUpload.previewUrl;
    setEvidence({
      src: uploadSrc ?? null,
      alt: loadUpload.filename
        ? `Uploaded load photo ${loadUpload.filename}`
        : "Load photo",
    });
    // Wait copy only: whether a live model actually ran is stated by the
    // result's provenance badge, never assumed here.
    setRunMode("live");

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
        supplier: values.supplier.trim() || null,
        photo_base64: loadBase64.current,
        photo_filename: sentFilename(loadUpload.filename, loadSent.current.reencoded),
        demo_case: null,
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
      // "network": the backend was never reached. "http": it answered
      // with an error and said why: show that message, not "unreachable".
      setPhase("idle");
      setData(null);
      setResultError(
        err instanceof InspectError
          ? { kind: err.kind, message: err.message }
          : {
              kind: "http",
              message: err instanceof Error ? err.message : "Unexpected error.",
            },
      );
    } finally {
      setLoading(false);
    }
  }, [values, loadUpload]);

  const onSubmit = useCallback(() => runInspection(), [runInspection]);

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
    encoding.current.clear(); // an encode still in flight must not refill them
  }, []);

  const hasPhoto = Boolean(loadUpload.previewUrl);

  const photoSlot = (
    <figure className="m-0 flex h-full flex-col px-4 py-4">
      {/* eslint-disable-next-line @next/next/no-img-element -- runtime base64/local demo assets; static export has no image optimizer */}
      {/* Click-to-upload (user direction): the photo itself is the upload
          target — hover reveals a hint, picking a file replaces the image.
          aspect-[4/3] crop kills the dead space under the caption. */}
      <input
        id="load-photo-upload"
        type="file"
        accept="image/jpeg,image/png"
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
              src={loadUpload.previewUrl!}
              alt={loadUpload.filename ?? "Load photo"}
              className="aspect-[4/3] w-full object-cover transition-opacity duration-150 group-hover:opacity-60"
            />
            {/* Hover veil: the only affordance for click-to-upload */}
            <span
              aria-hidden="true"
              className="absolute inset-0 flex items-center justify-center text-[13px] font-semibold tracking-[0.6px] text-ink uppercase opacity-0 transition-opacity duration-150 group-hover:opacity-100"
            >
              Replace photo
            </span>
          </>
        ) : (
          /* Empty stage: no truck at the gate until a photo is uploaded. */
          <span className="flex aspect-[4/3] w-full flex-col items-center justify-center gap-2 text-muted transition-colors duration-100 group-hover:text-ink">
            <span className="text-[22px] leading-none" aria-hidden="true">
              ◉
            </span>
            <span className="text-[13px] font-semibold tracking-[0.6px] uppercase">
              Upload load photo
            </span>
            <span className="text-[12px]">JPEG or PNG from the gate camera</span>
          </span>
        )}
      </label>
      {loadUpload.filename ? (
        <figcaption className="figure mt-2 text-[11px] leading-relaxed break-words text-muted">
          {`Uploaded photo · ${loadUpload.filename}`}
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
            onSubmit={onSubmit}
            onReset={onReset}
            onWaybillPhoto={onWaybillPhoto}
            waybillPhoto={waybillUpload}
            loading={loading}
            formError={formError}
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
        evidence={evidence}
        runMode={runMode}
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
