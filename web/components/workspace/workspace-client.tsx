"use client";

/**
 * WorkspaceClient: route /app (Operate), two views of one gate:
 *
 * IDLE (frame rxd5f) "New inspection": 01 Incoming load (photo presets,
 *       drop/upload zone), 02 Waybill & register (IntakeForm), 03 Verdict
 *       (pipeline placeholder; request errors land here).
 * RESULT (frame HX9C5) "Inspection result": VerdictPanel (banner, gate
 *       checks, evidence, reasons, next steps, submitted load, Pythia);
 *       the header carries the audit record and Next truck.
 *
 * Logic ported from legacy web/app.js: same API contract
 * (POST /inspect), same race-guarded photo base64 encoding.
 */

import { cn } from "@/lib/utils";
import { useCallback, useEffect, useMemo, useRef, useState, type DragEvent } from "react";
import {
  Camera,
  ImageUp,
  Info,
  ScanSearch,
  Sparkles,
  Stamp,
  Truck,
  Upload,
  X,
  type LucideIcon,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { PageBody, PageHeader } from "@/components/shell/page-header";
import {
  IntakeForm,
  type IntakeValues,
  type UploadSlot,
} from "./intake-form";
import {
  VerdictPanel,
  type ResultError,
  type RunMode,
  type SubmittedLoad,
} from "./verdict-panel";
import { AuditModal } from "./audit-modal";
import { Segmented } from "./segmented";
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

/** Quick-pick presets: a site photo asset fetched as a File, so it flows
 * through the exact same upload pipeline (encode, preview, audit filename)
 * as a camera upload. Generic operator copy — no scenario name leaks into
 * the UI text. */
const QUICK_LOADS: { label: string; file: string }[] = [
  { label: "Metal", file: "t-metal-1.jpg" },
  { label: "Clean", file: "t-clean-1.jpg" },
  { label: "Wet", file: "t-ambiguous-1.jpg" },
];
const QUICK_WAYBILL = "waybill-1.jpg";

/** Fetch a public sample asset as a File (browser-cached JPEG bytes). */
async function demoFile(name: string): Promise<File> {
  const res = await fetch(`/demo/${name}`);
  if (!res.ok) throw new Error(`Cannot read ${name}`);
  return new File([await res.blob()], name, { type: "image/jpeg" });
}

const EMPTY_FORM: IntakeValues = {
  truck_id: "",
  supplier: "",
  weight_kg: "",
  stream: "mixed-msw",
  moisture_pct: "",
  age_h: "",
};

/** The gate's manifest gate needs declared waybill text; without it the
    inspection refuses (insufficient input). The operator no longer types
    it — synthesize the declaration from the stream and weighed mass so
    the LLM still has a claim to cross-check. */
function synthesizeWaybill(stream: string, weightKg: number): string {
  const streamLabel = stream.replace(/-/g, " ");
  return `Dry ${streamLabel}, no metal, declared ${weightKg} kg`;
}

export function WorkspaceClient() {
  const [values, setValues] = useState<IntakeValues>(EMPTY_FORM);
  const [formError, setFormError] = useState<string | null>(null);
  const [resultError, setResultError] = useState<ResultError | null>(null);
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState<InspectResponse | null>(null);
  const [phase, setPhase] = useState<GatePhase>("idle");
  const [bannerLit, setBannerLit] = useState(false);
  const resultRef = useRef<HTMLDivElement | null>(null);

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
  // side may change (new upload, next preset) while the verdict and
  // its outlined contaminants are still on screen.
  const [evidence, setEvidence] = useState<{ src: string | null; alt: string }>({
    src: null,
    alt: "Load photo",
  });
  const [runMode, setRunMode] = useState<RunMode>("other");
  // The register as submitted, frozen with the evidence photo.
  const [submitted, setSubmitted] = useState<SubmittedLoad | null>(null);

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

  // Quick-pick: site photo assets piped through the upload handlers above,
  // so a picked preset is indistinguishable from a camera upload.
  const [quickBusy, setQuickBusy] = useState<string | null>(null);
  // The preset whose photo is on the stage (pressed in the segmented
  // control); null once the operator uploads their own photo.
  const [activePreset, setActivePreset] = useState<string | null>(null);
  const pickDemo = useCallback(
    async (name: string, kind: "load" | "waybill") => {
      setQuickBusy(name);
      try {
        const file = await demoFile(name);
        if (kind === "load") {
          onLoadPhoto(file);
          setActivePreset(name);
        } else onWaybillPhoto(file);
      } finally {
        setQuickBusy(null);
      }
    },
    [onLoadPhoto, onWaybillPhoto],
  );

  /** An operator-chosen load photo (file picker or drop), or a clear. */
  const onOwnLoadPhoto = useCallback(
    (file: File | null) => {
      setActivePreset(null);
      onLoadPhoto(file);
    },
    [onLoadPhoto],
  );

  // Header "Load sample": the pressed (else first) photo preset plus the
  // sample waybill, through the same quick-pick loaders.
  const loadSample = useCallback(async () => {
    await pickDemo(activePreset ?? QUICK_LOADS[0].file, "load");
    await pickDemo(QUICK_WAYBILL, "waybill");
  }, [pickDemo, activePreset]);

  // Memoised: GateStrip restarts its lighting stagger whenever the array
  // identity changes, so a fresh array per render (typing in the form, say)
  // would replay the interlock.
  const gates: GateDisplay[] = useMemo(
    () => normalizeGates(data?.gates),
    [data?.gates],
  );
  const decision = data?.verdict?.decision ?? data?.decision;

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
    setSubmitted({
      truck_id: values.truck_id.trim(),
      supplier: values.supplier.trim(),
      weight_kg: weight,
      moisture_pct: moisture,
      age_h: age,
      loadFilename: loadUpload.filename,
      waybillFilename: waybillUpload.filename,
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
    // Pressing Inspect switches to the result view (the gate checks are
    // the show while it evaluates); the effect below scrolls it to top.

    try {
      const resp = await inspectLoad({
        truck_id: values.truck_id.trim(),
        supplier: values.supplier.trim() || null,
        photo_base64: loadBase64.current,
        photo_filename: sentFilename(loadUpload.filename, loadSent.current.reencoded),
        demo_case: null,
        manifest_text: synthesizeWaybill(values.stream, weight),
        waybill_image_base64: waybillBase64.current,
        weight_kg: weight,
        stream: values.stream,
        moisture_pct: moisture,
        age_h: age,
      });
      setData(resp);
      setPhase("resolved");
      // Banner lights only after the six gates resolve (GateStrip
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
  }, [values, loadUpload, waybillUpload.filename]);

  const onSubmit = useCallback(() => runInspection(), [runInspection]);

  const onAllResolved = useCallback(() => {
    setBannerLit(true);
  }, []);

  // Gate flow is truck-by-truck. Reset clears EVERYTHING (user
  // direction): verdict stage, form, preset selection, uploads, photo —
  // the gate stands empty for the next truck.
  const onReset = useCallback(() => {
    setActivePreset(null);
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

  // Back to the intake with the register and photos kept: fix an input,
  // then inspect again.
  const onEdit = useCallback(() => {
    setData(null);
    setPhase("idle");
    setBannerLit(false);
  }, []);

  const showResult = phase !== "idle";

  // Switching views starts at the top. Entering the result also moves
  // focus onto it (the Inspect button that had focus is gone with the
  // intake view). The first render is not a switch.
  const viewMounted = useRef(false);
  const resultErrorRef = useRef(resultError);
  resultErrorRef.current = resultError;
  useEffect(() => {
    if (!viewMounted.current) {
      viewMounted.current = true;
      return;
    }
    // Back to intake because the request failed: the error effect below
    // scrolls to the alert instead of the top.
    if (!showResult && resultErrorRef.current) return;
    window.scrollTo({ top: 0, behavior: "smooth" });
    if (showResult) resultRef.current?.focus({ preventScroll: true });
  }, [showResult]);

  // A failed request drops back to the intake view; its alert lives in the
  // 03 Verdict card, which sits far below the fold on narrow screens.
  // Bring it into view and focus it so the failure is never silent.
  useEffect(() => {
    if (!resultError || showResult) return;
    const id = window.setTimeout(() => {
      const alert = document.getElementById("inspect-error");
      alert?.scrollIntoView({ behavior: "smooth", block: "center" });
      alert?.focus({ preventScroll: true });
    }, 50);
    return () => window.clearTimeout(id);
  }, [resultError, showResult]);

  const hasPhoto = Boolean(loadUpload.previewUrl);
  const [dragOver, setDragOver] = useState(false);

  const onDrop = (e: DragEvent<HTMLLabelElement>) => {
    e.preventDefault();
    setDragOver(false);
    if (loading) return;
    const file = e.dataTransfer.files?.[0];
    if (file && /^image\/(jpeg|png)$/.test(file.type)) onOwnLoadPhoto(file);
  };

  if (showResult && submitted) {
    const recordId = phase === "resolved" ? data?.record_id : undefined;
    return (
      <>
        <PageHeader
          crumb={`Console / Weighbridge Gate A${recordId ? ` / ${recordId}` : ""}`}
          title={phase === "resolved" ? "Inspection result" : "Inspecting load"}
        >
          {phase === "resolved" && data && recordId ? (
            <AuditModal recordId={recordId} data={data} />
          ) : null}
          {phase === "resolved" ? (
            <Button type="button" variant="primary" onClick={onReset}>
              <Truck aria-hidden="true" className="h-3.5 w-3.5" />
              Next truck
            </Button>
          ) : null}
        </PageHeader>
        <PageBody>
          <div ref={resultRef} tabIndex={-1} className="outline-none">
            <VerdictPanel
              phase={phase}
              gates={gates}
              data={data}
              decision={decision}
              bannerLit={bannerLit}
              onAllResolved={onAllResolved}
              onEdit={onEdit}
              evidence={evidence}
              submitted={submitted}
              runMode={runMode}
            />
          </div>
        </PageBody>
      </>
    );
  }

  return (
    <>
      <PageHeader crumb="Console / Weighbridge Gate A" title="New inspection">
        <Button
          type="button"
          onClick={() => void loadSample()}
          disabled={loading || quickBusy !== null}
        >
          <Sparkles aria-hidden="true" className="h-3.5 w-3.5" />
          {quickBusy !== null ? "Loading…" : "Load sample"}
        </Button>
      </PageHeader>

      <PageBody>
        <div className="grid grid-cols-1 items-stretch gap-6 lg:grid-cols-[minmax(0,1fr)_440px]">
          {/* ============ 01 Incoming load ============ */}
          <div className="flex min-w-0 flex-col gap-4">
            <section aria-labelledby="load-title" className="card flex flex-1 flex-col">
              <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-5 py-4">
                <div className="flex items-center gap-2.5">
                  <span className="font-mono text-[12px] text-brand-deep" aria-hidden="true">
                    01
                  </span>
                  <h2 id="load-title" className="m-0 font-display text-[17px] font-medium text-fg">
                    Incoming load
                  </h2>
                </div>
                {/* Quick-pick presets: one tap loads a site photo through the
                    normal upload pipeline — faster than browsing for a file. */}
                <Segmented
                  label="Photo presets"
                  options={QUICK_LOADS.map((p) => ({ value: p.file, label: p.label }))}
                  value={activePreset}
                  onSelect={(file) => void pickDemo(file, "load")}
                  disabled={loading || quickBusy !== null}
                  busy={quickBusy}
                />
              </div>

              <div className="flex flex-1 flex-col gap-3 p-5">
                {/* Click-or-drop upload: the zone is the label of the hidden
                    file input; keyboard users reach the input, and its focus
                    ring is drawn on the zone. */}
                <input
                  id="load-photo-upload"
                  type="file"
                  accept="image/jpeg,image/png"
                  className="peer sr-only"
                  disabled={loading}
                  onChange={(e) => onOwnLoadPhoto(e.target.files?.[0] ?? null)}
                />
                <label
                  htmlFor="load-photo-upload"
                  onDragOver={(e) => {
                    e.preventDefault();
                    if (!loading) setDragOver(true);
                  }}
                  onDragLeave={() => setDragOver(false)}
                  onDrop={onDrop}
                  title={loadUpload.filename ? "Replace photo" : "Upload photo"}
                  className={cn(
                    "group relative flex min-h-[280px] flex-1 cursor-pointer flex-col items-center justify-center gap-3.5 overflow-hidden rounded-[10px] border bg-surface-subtle transition-colors duration-100 peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-brand lg:min-h-[420px]",
                    dragOver ? "border-brand bg-brand/5" : "border-line-strong hover:border-brand-soft",
                    loading && "pointer-events-none opacity-50",
                  )}
                >
                  {hasPhoto ? (
                    <>
                      {/* eslint-disable-next-line @next/next/no-img-element -- local object URL; static export has no image optimizer */}
                      <img
                        src={loadUpload.previewUrl!}
                        alt={loadUpload.filename ?? "Load photo"}
                        className="absolute inset-0 h-full w-full object-contain transition-opacity duration-150 group-hover:opacity-60"
                      />
                      {/* Hover veil: the replace affordance */}
                      <span
                        aria-hidden="true"
                        className="relative inline-flex h-[34px] items-center gap-1.5 rounded-[8px] border border-line-strong bg-surface px-3.5 text-[14px] font-medium text-fg opacity-0 shadow-control transition-opacity duration-150 group-hover:opacity-100"
                      >
                        <Upload className="h-3.5 w-3.5" />
                        Replace photo
                      </span>
                    </>
                  ) : (
                    <>
                      <span
                        aria-hidden="true"
                        className="flex h-[52px] w-[52px] items-center justify-center rounded-[14px] border border-line-strong bg-surface text-fg shadow-[0_2px_6px_#18191B0F]"
                      >
                        <ImageUp className="h-[22px] w-[22px]" />
                      </span>
                      <span className="flex flex-col items-center gap-1 px-4 text-center">
                        <span className="text-[15px] font-medium text-fg">Drop the load photo here</span>
                        <span className="text-[13px] text-fg-muted">JPEG or PNG from the gate camera</span>
                      </span>
                      <span className="inline-flex h-[34px] items-center gap-1.5 rounded-[8px] border border-line-strong bg-surface px-3.5 text-[14px] font-medium text-fg shadow-control group-hover:bg-surface-subtle">
                        <Upload aria-hidden="true" className="h-3.5 w-3.5" />
                        Upload photo
                      </span>
                    </>
                  )}
                </label>
                {loadUpload.filename ? (
                  <div className="flex items-center justify-between gap-3">
                    <span className="min-w-0 truncate text-[12px] text-fg-muted">
                      Uploaded photo · <span className="font-mono">{loadUpload.filename}</span>
                    </span>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={() => onOwnLoadPhoto(null)}
                      disabled={loading}
                    >
                      <X aria-hidden="true" className="h-3.5 w-3.5" />
                      Clear upload
                    </Button>
                  </div>
                ) : null}
              </div>
            </section>

            <p className="m-0 flex items-center gap-2.5 rounded-[10px] bg-brand/7 px-4 py-3 text-[13px] text-fg">
              <Info aria-hidden="true" className="h-4 w-4 shrink-0 text-brand" />
              Upload the load photo and the waybill photo, fill in the register, then press Inspect load.
            </p>
          </div>

          {/* ============ 02 Waybill & register, 03 Verdict ============ */}
          <div className="flex min-w-0 flex-col gap-4">
            <IntakeForm
              values={values}
              onChange={onChange}
              onSubmit={onSubmit}
              onReset={onReset}
              onWaybillPhoto={onWaybillPhoto}
              onQuickWaybill={() => void pickDemo(QUICK_WAYBILL, "waybill")}
              quickWaybillBusy={quickBusy === QUICK_WAYBILL}
              waybillPhoto={waybillUpload}
              loading={loading}
              formError={formError}
            />

            <IdleVerdictCard
              hasPhoto={hasPhoto}
              hasWaybill={Boolean(waybillUpload.filename)}
              error={resultError}
            />
          </div>
        </div>
      </PageBody>
    </>
  );
}

const PIPELINE: { key: string; icon: LucideIcon; title: string; desc: string }[] = [
  { key: "capture", icon: Camera, title: "Capture", desc: "Photo, waybill and weight" },
  { key: "analyze", icon: ScanSearch, title: "Analyze", desc: "VLM + waybill check + digital twin" },
  { key: "seal", icon: Stamp, title: "Decide & seal", desc: "Verdict sealed with SHA-256" },
];

/** "03 Verdict" before a run: the three pipeline stages, idle, with the
    capture stage reflecting what is on the stage. A failed request is
    reported here (the result view only exists while a run is live). */
function IdleVerdictCard({
  hasPhoto,
  hasWaybill,
  error,
}: {
  hasPhoto: boolean;
  hasWaybill: boolean;
  error: ResultError | null;
}) {
  const captureState =
    hasPhoto && hasWaybill ? "ready" : hasPhoto || hasWaybill ? "partial" : "idle";
  return (
    <section aria-labelledby="verdict-title" className="card flex flex-1 flex-col">
      <div className="flex items-center justify-between gap-3 border-b border-line px-5 py-4">
        <div className="flex items-center gap-2.5">
          <span className="font-mono text-[12px] text-brand-deep" aria-hidden="true">
            03
          </span>
          <h2 id="verdict-title" className="m-0 font-display text-[17px] font-medium text-fg">
            Verdict
          </h2>
        </div>
        <span className="rounded-full bg-surface-subtle px-2.5 py-[3px] text-[12px] font-medium text-fg-muted">
          {hasPhoto ? "Ready to inspect" : "Waiting for load"}
        </span>
      </div>

      {error ? (
        <div
          id="inspect-error"
          role="alert"
          tabIndex={-1}
          className="mx-5 mt-4 rounded-[10px] border border-danger/25 bg-danger-tint px-4 py-3 focus-visible:outline-none"
        >
          <p className="m-0 text-[13.5px] font-medium text-danger">
            {error.kind === "network"
              ? "Backend unreachable: is the server running?"
              : "Inspection could not run"}
          </p>
          <p className="figure m-0 mt-1 text-[13px] leading-relaxed break-words text-fg-muted">
            {error.message}
          </p>
          <p className="m-0 mt-1.5 text-[12px] text-fg-muted">
            {error.kind === "network"
              ? "Start the FastAPI backend (it serves this app as static files), then press Inspect load again."
              : "Fix the input above if needed, then press Inspect load again."}
          </p>
        </div>
      ) : null}

      <ol className="m-0 flex flex-1 list-none flex-col justify-center px-5 pt-1 pb-3">
        {PIPELINE.map(({ key, icon: Icon, title, desc }) => (
          <li key={key} className="flex items-center gap-3 py-2">
            <span
              aria-hidden="true"
              className="flex h-[30px] w-[30px] shrink-0 items-center justify-center rounded-full bg-surface-subtle text-fg-muted"
            >
              <Icon className="h-3.5 w-3.5" />
            </span>
            <span className="flex min-w-0 flex-1 flex-col gap-px">
              <span className="text-[13px] font-medium text-fg">{title}</span>
              <span className="text-[12px] text-fg-muted">{desc}</span>
            </span>
            <span
              className={cn(
                "font-mono text-[11px]",
                key === "capture" && captureState === "ready" ? "text-success" : "text-fg-subtle",
              )}
            >
              {key === "capture" ? captureState : "idle"}
            </span>
          </li>
        ))}
      </ol>
    </section>
  );
}
