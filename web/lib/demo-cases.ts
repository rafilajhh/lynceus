/**
 * Gate presets: the bundled demo photos (web/public/demo, AI-generated and
 * fictitious; see its README) loaded through the same upload pipeline as a
 * camera photo. Every preset uses the one sample waybill, so the verdict
 * differs only by what the camera sees:
 *
 * - Metal: a steel pipe elbow in a load declared as sorted RDF fluff.
 * - Clean: dry shredded feedstock; matches its declaration.
 * - Wet:   damp mixed waste with organic clumps, declared at 28 % moisture.
 * - Wrong truck: the clean load, but the truck on the scale is B 9406 KXW
 *   while its waybill belongs to B 9723 KXW (the plate camera catches it).
 */

import type { WaybillValues } from "./waybill-api";

export type PresetKey = "metal" | "clean" | "wet" | "wrong_truck";

export interface GatePreset {
  key: PresetKey;
  label: string;
  /** What the photo shows, in operator words (no verdict spoiler). */
  hint: string;
  /** Main load photo (public /demo path name). */
  photo: string;
  /** Plate the truck registers under at the weighbridge, when it is not
      the waybill's. */
  truckPlate?: string;
}

export const PRESETS: readonly GatePreset[] = [
  { key: "metal", label: "Metal", hint: "Pipe elbow in the load", photo: "t-metal-1.jpg" },
  { key: "clean", label: "Clean", hint: "Dry shredded RDF", photo: "t-clean-1.jpg" },
  { key: "wet", label: "Wet", hint: "Damp mixed waste", photo: "t-ambiguous-1.jpg" },
  {
    key: "wrong_truck",
    label: "Wrong truck",
    hint: "Truck B 9406 KXW, another truck's waybill",
    photo: "t-clean-1.jpg",
    truckPlate: "B 9406 KXW",
  },
];

/** The demo truck runs the Metal story: the most expensive miss. */
export const DEMO_TRUCK: PresetKey = "metal";

/** The sample waybill photo every preset hands to the reader. */
export const SAMPLE_WAYBILL = "waybill-1.jpg";

/**
 * What the sample waybill prints. Used ONLY when this backend has no waybill
 * reader (an older build): the console then shows these as fields typed by
 * the operator, labelled as typed, never as an AI read.
 */
export const SAMPLE_WAYBILL_PRINTED: WaybillValues = {
  plate: "B 9723 KXW",
  carrier: "PT. Hijau Lestari Transport",
  load_type: "RDF fluff",
  moisture_pct: "28",
  gross_kg: "32580",
  tare_kg: "16240",
  net_kg: "16340",
  document_no: "007842",
  date: "2025-05-14",
  reference_no: "DO-250514-0198",
  origin: "TPST Bantargebang, Bekasi",
  destination: "PLTSa Rorotan, Jakarta Utara",
  shipper: "TPST Bantargebang",
  driver: "Slamet Riyadi",
  remarks: "Muatan RDF fluff dari hasil proses pemilahan sampah. Pastikan terpal tertutup.",
};

/** Fetch a public /demo asset as a File (browser-cached JPEG bytes). */
export async function demoFile(name: string): Promise<File> {
  const res = await fetch(`/demo/${name}`);
  if (!res.ok) throw new Error(`Cannot read the demo photo ${name}.`);
  return new File([await res.blob()], name, { type: "image/jpeg" });
}
