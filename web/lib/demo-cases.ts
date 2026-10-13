/**
 * Demo cases: ported from legacy web/app.js (research-backed data).
 *
 * Every field carries its research source in comments
 * (docs/research-realcase-indonesia.md). photo paths point at
 * public/demo/*.jpg (RealWaste photos: see public/demo/ATTRIBUTION.md).
 */

export interface DemoCase {
  key: "green" | "amber" | "red";
  label: string;
  truck_id: string;
  photo: string;
  photo_caption: string;
  manifest_text: string;
  weight_kg: number;
  stream: string;
  moisture_pct: number;
  age_h: number;
}

export const DEMO_CASES: Record<DemoCase["key"], DemoCase> = {
  green: {
    key: "green",
    label: "Dry RDF / Bantargebang",
    // Arm-roll truck on the Bantargebang RDF corridor. B = DKI/Jakarta
    // plate area (Bantargebang); offtakers are the cement co-processing
    // lines (SBI Narogong is one of the three RDF plants: Narogong,
    // Cilacap, Tuban). Numbers: arm roll 14 m³ × 372.71 kg/m³ ≈ 5.2 t/trip
    // (ITATS Surabaya, TPA Benowo weighbridge); RDF gate price
    // Rp 300,000/t (SWITCH-Asia §5d). Plate 'B' = DKI per TNKB codes.
    truck_id: "B 9174 KT",
    photo: "/demo/green-1.jpg",
    photo_caption:
      "Arm-roll B 9174 KT · RDF feedstock, dry & baled · Bantargebang to SBI Narogong line",
    manifest_text:
      "WAYBILL / WEIGHBRIDGE TICKET (RDF-MSW): No. SJ: SJ/RDF/2026/10/0001\n" +
      "Plate No.  : B 9174 KT        Date: 2026-10-13   Entry time: 01:20\n" +
      "Driver     : Sukarno          Origin: TPST Bantargebang RDF plant (waste source: TPS district 4)\n" +
      "Destination: SBI Narogong cement plant (RDF co-processing line)\n" +
      "Gross (kg) : 10,000           Tare (kg): 4,800\n" +
      "Net (kg)   : 5,200            Weighbridge operator: Gate A\n" +
      "Load type  : RDF fluff, pre-sorted, baled\n" +
      "Declared weight: 5,200 kg\n" +
      "Moisture declared: 10% (dry, stored under cover)\n" +
      "Checks     : non-hazardous, non-medical, moisture/calorific value (RDF)",
    weight_kg: 5200,
    stream: "rdf-feedstock",
    moisture_pct: 9.5,
    age_h: 5,
  },
  amber: {
    key: "amber",
    label: "Wet Organics / District 4",
    // Wet organics rejected at RDF intake: Indonesian MSW runs 55-60%
    // moisture (SBI Cilacap study) and ~40.77% food waste nationally
    // (SIPSN 2025): exactly why MBT pre-processing is mandatory before
    // kiln feeding. Plate "B" = Bantargebang/Jakarta corridor.
    truck_id: "B 9282 AP",
    photo: "/demo/amber-1.jpg",
    photo_caption:
      "Compactor B 9282 AP · wet organics from TPST · 57% moisture measured",
    manifest_text:
      "WAYBILL / WEIGHBRIDGE TICKET (RDF-MSW): No. SJ: SJ/RDF/2026/10/0002\n" +
      "Plate No.  : B 9282 AP        Date: 2026-10-13   Entry time: 04:05\n" +
      "Driver     : Rustam           Origin: TPST Bantargebang (waste source: TPS district 4)\n" +
      "Destination: RDF processing plant -> cement plant co-processing\n" +
      "Gross (kg) : 12,250           Tare (kg): 4,850\n" +
      "Net (kg)   : 7,400            Weighbridge operator: Gate A\n" +
      "Load type  : organic-rich, source-separated biowaste\n" +
      "Declared weight: 7,400 kg\n" +
      "Moisture declared: 30%\n" +
      "Checks     : non-hazardous, non-medical, moisture/calorific value (RDF)",
    weight_kg: 7400,
    stream: "organic-rich",
    moisture_pct: 57.0,
    age_h: 76,
  },
  red: {
    key: "red",
    label: "Hidden Metal / Bogor",
    // Scrap metal smuggled in under a 'clean RDF' claim with a weight
    // mismatch: the kiln-killer scenario: metal in the feed damages the
    // kiln/refractory; unplanned downtime ≈ Rp 450 million/hour
    // (oxmaint US benchmark @ Rp 16,000/USD, §5a). Metal is also 3.11% of
    // national MSW composition (SIPSN 2025): the exact fraction screening
    // must catch at the gate. Plate "F" = Bogor (SBI Narogong corridor).
    truck_id: "F 7702 TS",
    photo: "/demo/red-1.jpg",
    photo_caption:
      "Compactor F 7702 TS · scrap metal found under the bales · weight mismatch",
    manifest_text:
      "WAYBILL / WEIGHBRIDGE TICKET (RDF-MSW): No. SJ: SJ/RDF/2026/10/0003\n" +
      "Plate No.  : F 7702 TS        Date: 2026-10-13   Entry time: 00:45\n" +
      "Driver     : Hendra           Origin: RDF supplier CV, Bogor (waste source: industrial park skip)\n" +
      "Destination: cement plant co-processing line\n" +
      "Gross (kg) : 24,800           Tare (kg): 9,300\n" +
      "Net (kg)   : 15,500           Weighbridge operator: Gate A\n" +
      "Load type  : clean RDF fluff, dry, no contamination\n" +
      "Declared weight: 15,500 kg\n" +
      "Moisture declared: 12%\n" +
      "NOTE (driver): drum of scrap metal and concrete rubble loaded on " +
      "top of the bales at the last minute.\n" +
      "Checks     : non-hazardous, non-medical, moisture/calorific value (RDF)",
    // Weighbridge far above declared 15,500 kg: the crosscheck trigger.
    weight_kg: 19300,
    stream: "mixed-msw",
    moisture_pct: 14.0,
    age_h: 8,
  },
};

/** Lynceus engine composition presets (lynceus_engine core composition.py). */
export const WASTE_STREAMS = [
  { value: "mixed-msw", label: "mixed-msw" },
  { value: "co-disposal", label: "co-disposal" },
  { value: "organic-rich", label: "organic-rich" },
  { value: "green-waste", label: "green-waste" },
  { value: "rdf-feedstock", label: "rdf-feedstock" },
  { value: "dry-recyclables", label: "dry-recyclables" },
] as const;

/** The five interlock gates (audit.GATE_NAMES order). */
export const GATE_ORDER = [
  { key: "vlm_confidence", label: "VLM" },
  { key: "ocr_confidence", label: "OCR" },
  { key: "manifest_crosscheck", label: "XCHECK" },
  { key: "gas_plausibility", label: "GAS" },
  { key: "weight_plausibility", label: "WEIGHT" },
] as const;
