"use client";

/**
 * WorkspaceClient: route /app (Operate), one truck at the gate.
 *
 * Header: what this gate does, the one-click demo truck, presets.
 * Incoming truck: load photos · waybill (AI-read, editable) · weighbridge.
 * Inspecting: the live stage panel (NDJSON stream from /inspect/stream).
 * Verdict: banner, why, checks, evidence, declared vs observed, SOP steps,
 *   value, supervisor decision, supplier notice, lab sample, sealed record.
 *
 * The page scrolls to the stage panel when a run starts and to the verdict
 * when it lands; an inspect attempt with a missing input focuses that field.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Panel, PanelHead } from "@/components/ui/panel";
import { DEMO_TRUCK, PRESETS, SAMPLE_WAYBILL, SAMPLE_WAYBILL_PRINTED, demoFile, type PresetKey } from "@/lib/demo-cases";
import type { InspectPayload } from "@/lib/inspect-api";
import { cn } from "@/lib/utils";
import {
  WAYBILL_FIELDS,
  parseFieldNumber,
  streamFromDeclaration,
  toWaybillFields,
  transcriptOf,
  warmUp,
} from "@/lib/waybill-api";
import { GateHeader } from "./gate-header";
import { IconCheck, IconDash } from "./gate-icons";
import { LoadPhotos } from "./load-photos";
import { dataUrl } from "./photo-encode";
import { StagePanel } from "./stage-panel";
import { prefersReducedMotion, useIntake, type Intake } from "./use-intake";
import { useInspection, type RunSnapshot, type RunState } from "./use-inspection";
import { formatKg } from "./units";
import { VerdictPanel } from "./verdict-panel";
import { WaybillBlock, waybillFieldId } from "./waybill-block";
import { WeighbridgeBlock } from "./weighbridge-block";

type InvalidField = "photo" | "plate" | "scale" | null;

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

function scrollToPanel(el: HTMLElement | null) {
  el?.scrollIntoView({ behavior: prefersReducedMotion() ? "auto" : "smooth", block: "start" });
}

/** After a state change renders the field, focus it. */
function focusLater(id: string) {
  requestAnimationFrame(() => document.getElementById(id)?.focus());
}

export function WorkspaceClient() {
  const intake = useIntake();
  const { run, start, clear } = useInspection();
  const [preset, setPreset] = useState<PresetKey | null>(null);
  const [loadingPreset, setLoadingPreset] = useState<PresetKey | null>(null);
  const [autoRun, setAutoRun] = useState(false);
  const [formError, setFormError] = useState<{ message: string; field: InvalidField } | null>(null);
  const stageRef = useRef<HTMLElement>(null);
  const verdictRef = useRef<HTMLElement>(null);
  /** Bumped by every preset load and clear: an older flow stops at its next await. */
  const flow = useRef(0);

  // Wake the vision model while the visitor reads the page.
  useEffect(() => {
    void warmUp();
  }, []);

  // Follow the run: to the stages when it starts, to the verdict when it lands.
  useEffect(() => {
    if (run.phase === "running") scrollToPanel(stageRef.current);
    if (run.phase === "error") scrollToPanel(stageRef.current);
  }, [run.phase, run.runId]);
  useEffect(() => {
    if (run.phase === "done") requestAnimationFrame(() => scrollToPanel(verdictRef.current));
  }, [run.phase, run.runId]);

  const inspect = useCallback(async () => {
    setFormError(null);
    const fail = (message: string, field: InvalidField, focusId?: string) => {
      setFormError({ message, field });
      if (focusId) focusLater(focusId);
    };
    const now = intake.latest();
    const w = now.waybill;
    if (w.status === "reading") return fail("The waybill is still being read: inspect once its fields are in.", null);

    const photos = await intake.encodedPhotos();
    if (photos.length === 0) return fail("Add a load photo: it is what the AI inspects.", "photo", "load-photo-0");
    if (!w.values.plate.trim()) {
      return fail("The plate is empty: read the waybill photo or type the plate.", "plate", waybillFieldId("plate"));
    }
    if (now.scaleNetKg === null || now.scaleNetKg <= 0) {
      intake.switchToManualScale();
      return fail("No net weight yet: capture the weighbridge or type the net weight.", "scale", "scale-net");
    }

    const values = w.values;
    const hasFields = WAYBILL_FIELDS.some((f) => values[f.key].trim());
    const read = w.status === "read" ? w.read : null;
    const waybillPhoto = await intake.encodedWaybill();
    const declaredNet = parseFieldNumber(values.net_kg);
    const scale = now.scale;
    const weightSource =
      scale.status === "live" && scale.reading
        ? scale.reading.source === "simulated"
          ? "weighbridge_simulated"
          : "weighbridge"
        : "manual_entry";

    const payload: InspectPayload = {
      truck_id: values.plate.trim(),
      supplier: values.carrier.trim() || null,
      photo_base64: photos[0].photo.base64,
      photo_filename: photos[0].photo.filename,
      extra_photos_base64: photos.slice(1).map((p) => p.photo.base64),
      extra_photo_filenames: photos.slice(1).map((p) => p.photo.filename),
      demo_case: null,
      // The confirmed fields as text: the read transcript when nothing was
      // edited, else rebuilt from the fields. Nothing is synthesized.
      manifest_text: hasFields
        ? (read?.transcript && now.editedFields.length === 0 ? read.transcript : transcriptOf(values))
        : null,
      waybill_image_base64: waybillPhoto?.base64 ?? null,
      waybill_photo_filename: waybillPhoto?.filename ?? null,
      waybill_fields: hasFields ? toWaybillFields(values) : undefined,
      waybill_read: read
        ? {
            confidence: read.confidence ?? 0,
            model: read.model ?? "unknown",
            provenance: read.provenance ?? "live",
            latency_ms: read.latency_ms ?? null,
            edited_fields: now.editedFields,
          }
        : undefined,
      weight_kg: now.scaleNetKg,
      declared_weight_kg: declaredNet,
      weight_source: weightSource,
      stream: streamFromDeclaration(values),
      moisture_pct: parseFieldNumber(values.moisture_pct),
    };
    const snapshot: RunSnapshot = {
      frames: photos.map((p) => ({ src: dataUrl(p.photo), filename: p.photo.filename })),
      waybill: { values, status: w.status, read, editedFields: now.editedFields },
      scale: { netKg: now.scaleNetKg, declaredNetKg: declaredNet, source: weightSource, reading: scale.reading },
    };
    await start(payload, snapshot);
  }, [intake, start]);

  const loadPreset = useCallback(
    async (key: PresetKey, thenInspect: boolean) => {
      const p = PRESETS.find((x) => x.key === key);
      if (!p) return;
      const mine = ++flow.current;
      clear();
      setFormError(null);
      setPreset(key);
      setLoadingPreset(key);
      setAutoRun(thenInspect);
      intake.reset();
      try {
        const [photo, waybill] = await Promise.all([demoFile(p.photo), demoFile(SAMPLE_WAYBILL)]);
        if (mine !== flow.current) return;
        intake.setPhoto(0, photo);
        await intake.setWaybillPhoto(waybill, SAMPLE_WAYBILL_PRINTED);
        if (mine !== flow.current) return;
        setLoadingPreset(null);
        if (thenInspect) {
          await sleep(prefersReducedMotion() ? 0 : 450); // a beat to see the filled intake
          if (mine !== flow.current) return;
          await inspect();
        }
      } catch (err) {
        if (mine === flow.current) {
          setFormError({ message: err instanceof Error ? err.message : "The preset could not load.", field: null });
        }
      } finally {
        if (mine === flow.current) {
          setLoadingPreset(null);
          setAutoRun(false);
        }
      }
    },
    [clear, inspect, intake],
  );

  const clearGate = useCallback(() => {
    flow.current++;
    clear();
    intake.reset();
    setPreset(null);
    setLoadingPreset(null);
    setAutoRun(false);
    setFormError(null);
    requestAnimationFrame(() => window.scrollTo({ top: 0, behavior: prefersReducedMotion() ? "auto" : "smooth" }));
  }, [clear, intake]);

  const running = run.phase === "running";
  const busy = running || loadingPreset !== null;
  const busyLabel = autoRun
    ? intake.waybill.status === "reading"
      ? "Reading the waybill…"
      : intake.scale.status === "reading"
        ? "Weighing…"
        : running
          ? "Inspecting…"
          : "Loading the truck…"
    : running
      ? "Inspecting…"
      : null;

  return (
    <div className="flex flex-col gap-5">
      <GateHeader
        busyLabel={busyLabel}
        activePreset={preset}
        disabled={busy}
        onRunDemo={() => void loadPreset(DEMO_TRUCK, true)}
        onPreset={(k) => void loadPreset(k, false)}
        onClear={clearGate}
      />

      <Panel aria-labelledby="intake-title">
        <PanelHead title="Incoming truck" meta="weighbridge gate A" />
        <h2 id="intake-title" className="sr-only">
          Incoming truck
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-[minmax(0,0.95fr)_minmax(0,1.55fr)_minmax(0,0.9fr)]">
          <div className="border-b border-seam md:border-r xl:border-b-0">
            <LoadPhotos
              photos={intake.photos}
              disabled={busy}
              invalid={formError?.field === "photo"}
              onPick={(i, f) => {
                setPreset(null);
                intake.setPhoto(i, f);
              }}
            />
          </div>
          <div className="border-b border-seam md:order-3 md:col-span-2 md:border-b-0 xl:order-none xl:col-span-1 xl:border-r">
            <WaybillBlock
              waybill={intake.waybill}
              editedFields={intake.editedFields}
              disabled={busy}
              invalidField={formError?.field === "plate" ? "plate" : null}
              onPhoto={(f) => {
                setPreset(null);
                void intake.setWaybillPhoto(f);
              }}
              onEdit={intake.editField}
            />
          </div>
          <div className="border-seam md:border-b xl:border-b-0">
            <WeighbridgeBlock
              scale={intake.scale}
              netKg={intake.scaleNetKg}
              declaredNetKg={parseFieldNumber(intake.waybill.values.net_kg)}
              plate={intake.waybill.values.plate}
              disabled={busy}
              invalid={formError?.field === "scale"}
              onCapture={() =>
                void intake.captureScale(intake.waybill.values.plate, parseFieldNumber(intake.waybill.values.net_kg))
              }
              onManual={intake.switchToManualScale}
              onManualNet={intake.setManualNet}
            />
          </div>
        </div>
        <IntakeBar intake={intake} busy={busy} error={formError?.message ?? null} onInspect={() => void inspect()} />
      </Panel>

      {run.phase !== "idle" ? <StagePanel ref={stageRef} run={run} /> : null}
      {run.phase === "error" && run.error ? <RunError error={run.error} onRetry={() => void inspect()} /> : null}
      {run.phase === "done" && run.result && run.snapshot ? (
        <VerdictPanel ref={verdictRef} run={run} onNextTruck={clearGate} />
      ) : null}
    </div>
  );
}

/** Readiness at a glance, then the one action. */
function IntakeBar({
  intake,
  busy,
  error,
  onInspect,
}: {
  intake: Intake;
  busy: boolean;
  error: string | null;
  onInspect: () => void;
}) {
  const photos = intake.photos.filter(Boolean).length;
  const w = intake.waybill;
  const fields = WAYBILL_FIELDS.filter((f) => w.values[f.key].trim()).length;
  const items: { ok: boolean; text: string }[] = [
    { ok: photos > 0, text: photos > 0 ? `${photos} photo${photos > 1 ? "s" : ""}` : "No load photo" },
    {
      ok: fields > 0 && w.status !== "reading",
      text:
        w.status === "reading"
          ? "Reading the waybill"
          : w.status === "read"
            ? `Waybill read · ${fields} fields${intake.editedFields.length ? `, ${intake.editedFields.length} edited` : ""}`
            : fields > 0
              ? `Waybill typed · ${fields} fields`
              : "No waybill: the inspection will refuse",
    },
    {
      ok: intake.scaleNetKg !== null,
      text: intake.scaleNetKg !== null ? `Net ${formatKg(intake.scaleNetKg)}` : "No net weight",
    },
  ];
  return (
    <div className="flex flex-col gap-3 border-t border-seam px-4 py-3 md:flex-row md:items-center md:justify-between">
      <ul className="m-0 flex list-none flex-wrap gap-x-4 gap-y-1 p-0 text-[12.5px]" aria-label="Ready to inspect">
        {items.map((it) => (
          <li key={it.text} className={cn("inline-flex items-center gap-1.5", it.ok ? "text-ink" : "text-muted")}>
            <span className={it.ok ? "text-muted" : "text-faint"}>{it.ok ? <IconCheck size={13} /> : <IconDash size={13} />}</span>
            {it.text}
          </li>
        ))}
      </ul>
      <div className="flex flex-col gap-2 md:items-end">
        {error ? (
          <p role="alert" className="m-0 text-[13px] text-verdict-red md:text-right">
            {error}
          </p>
        ) : null}
        <Button
          type="button"
          variant="primary"
          size="lg"
          onClick={onInspect}
          disabled={busy || w.status === "reading"}
          className="w-full md:w-auto md:min-w-[180px]"
        >
          Inspect load
        </Button>
      </div>
    </div>
  );
}

/** A run that stopped before a verdict: what happened and what to do. */
function RunError({ error, onRetry }: { error: NonNullable<RunState["error"]>; onRetry: () => void }) {
  const title =
    error.kind === "network"
      ? "The backend could not be reached"
      : error.status === 503
        ? "The live AI pipeline is busy or unavailable"
        : error.status === 429
          ? "Rate limit reached on the AI endpoint"
          : "The inspection could not run";
  const recovery =
    error.kind === "network"
      ? "Start the Lynceus backend (it serves this console), then inspect again."
      : error.status === 503 || error.status === 429
        ? "Wait a few seconds, then inspect again. Nothing was decided for this truck."
        : "Fix the input above if needed, then inspect again.";
  return (
    <div role="alert" className="flex flex-col gap-2 rounded-[14px] border border-verdict-red/60 bg-red-dim px-4 py-3">
      <p className="m-0 text-[14px] font-semibold text-verdict-red">{title}</p>
      <p className="figure m-0 text-[12.5px] leading-relaxed break-words text-muted">{error.message}</p>
      <div className="flex flex-wrap items-center gap-3">
        <p className="m-0 text-[13px] text-ink">{recovery}</p>
        <Button type="button" size="sm" onClick={onRetry}>
          Inspect again
        </Button>
      </div>
    </div>
  );
}
