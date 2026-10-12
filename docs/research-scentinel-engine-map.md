# Riset: Pemetaan Engine Scentinel untuk Lynceus

Path sumber: `D:/project lock in/amd act 3/scentinel/src/scentinel/core/`. Semua module **pure Python (frozen dataclass, stdlib-only), tanpa Qt/CFD/solver/IO** — `pipeline.py:7-9` menyatakan chain linear & pure eksplisit. Import graph:

```
composition  (leaf, stdlib saja)
 ├── generation   (→ composition)
 ├── massbalance  (→ composition)
 └── suitability  (→ composition)
recommend (→ massbalance, suitability, composition)
pipeline  (→ generation, massbalance, recommend, suitability, composition)
gas_data  (→ gas_defaults; jalur terpisah)
assessment (→ gas_defaults)
virtual_sensor (leaf, stdlib math saja)
```

## 1. composition.py (322 ln)
| API | Signature | Peran |
|---|---|---|
| `preset` | `(name) -> tuple[WasteComposition, float]` (L318) | Komposisi + moisture preset (`PRESETS` L301: mixed-msw, co-disposal, organic-rich, green-waste, rdf-feedstock, dry-recyclables) |
| `phase_for` / `interpret_phase` | `(age_h, model) -> str / PhaseInterpretation` (L148/L162) | Fase dekomposisi I–IV + batas model + uncertainty |
| `decay_rate` | `(material, moisture) -> float` (L183) | Interpolasi k_low→k_high via moisture (DRY 0.15 / WET 0.65) |
| `WasteComposition` | frozen dataclass; fields: food, garden, paper, wood, textile, diaper, sludge, inert | Fraksi massa wet-basis, jumlah = 1 |

Asumsi kunci: Table HH-1 EPA (MCF=1.0, DOCF=0.5, F=0.5); ceiling CH4 0.55; boundary fase dari narasi AP-42.
**Lynceus**: basis domain model; `preset()` → dropdown stream.

## 2. generation.py (277 ln)
| API | Signature | Peran |
|---|---|---|
| `generate` | `(composition, tonnage_t, age_h, moisture, k_override=None) -> Generation` (L182) | Gas batch: ch4/co2 cumulative kg & m3, rate kg/h, methane_fraction, phase_interpretation |
| `ultimate_methane_yield` | `(composition) -> tuple[kg/t, m3/t]` (L107) | Yield CH4 ultimate stoikiometrik |
| `decay_fraction` | `(k_per_year, age_h) -> float` (L135) | 1−exp(−k·t) orde pertama |

Asumsi: rasio stoikiometrik 16/12; CO2 via 44.009/12.011 & share (1−F).
**Lynceus**: inti kalkulasi emisi batch — dipakai pipeline.

## 3. massbalance.py (188 ln)
| API | Signature | Peran |
|---|---|---|
| `balance` | `(composition, tonnage_t, moisture, routing=DEFAULT_ROUTING) -> BatchResult` (L108) | Massa kering per stream (rdf/recyclable/organic/compost/residue/moisture) + `fraction(stream)` |

Asumsi: `DEFAULT_ROUTING` adalah asumsi UI yang bisa diedit; provenance CITED vs USER_ASSUMPTION.
**Lynceus**: endpoint "material flow" / sankey; routing = parameter per-facility.

## 4. suitability.py (284 ln)
| API | Signature | Peran |
|---|---|---|
| `assess` | `(composition, moisture, quality=None) -> Suitability` (L229) | Skor 5 rute + `best` |
| `score_rdf` / `score_recycling` / `score_composting` / `score_anaerobic_digestion` / `score_landfill` | `(composition, moisture) -> RouteScore` (L107-217) | Heuristik eksplisit; rule string di output |
| `fuel_grade` | `(quality) -> tuple[str|None, str]` (L263) | Kelas EN 15359-style dari NCV/Cl/ash, atau alasan ditahan |

Asumsi: skor clamp [0,1]; input lab hilang → INSUFFICIENT (ditahan, tidak ditebak).
**Lynceus**: scoring engine verdict; `RouteScore.rule` + `inputs` → panel explainability frontend.

## 5. recommend.py (174 ln)
| API | Signature | Peran |
|---|---|---|
| `recommend` | `(composition, tonnage_t, moisture, balance, suitability, age_h) -> Recommendation` (L57) | Satu keputusan + reasons/caveats/inputs/alternative/missing; `actionable` |

Asumsi: `MINIMUM_SCORE=0.45`; `DRYING_THRESHOLD=0.45` moisture → drying jadi prerequisite.
**Lynceus**: headline verdict user-facing; caveats wajib tampil di UI.

## 6. pipeline.py (113 ln)
| API | Signature | Peran |
|---|---|---|
| `assess_batch` | `(composition, *, tonnage_t, moisture, age_h, quality=None, screening=True) -> BatchAssessment` (L70) | **Entry point end-to-end**: composition→phase→generation→balance→suitability→recommend |
| `BatchAssessment.summary_lines()` | `-> list[str]` (L37) | Digest terbaca manusia |

**Lynceus**: inti endpoint verdict backend (`POST /assess`); serialize via asdict.

## 7. virtual_sensor.py (80 ln)
| API | Signature | Peran |
|---|---|---|
| `step_response` | `(config, *, ground_truth_ppm, previous_ppm, elapsed_s, step_s, ...) -> VirtualReading` (L47) | Lag exponential, drift, noise deterministik, saturasi, detection limit |
| `VirtualSensorConfig` | frozen dataclass; 5 family: PID/MOX/Electrochemical/NDIR/Pellistor | Kalibrasi virtual hardware |

**Lynceus**: simulator digital-twin sensor untuk demo tanpa hardware; noise deterministik → reproducible.

## 8. gas_data.py (397 ln) + assessment.py (316 ln, ringkas)
| API | Signature | Peran |
|---|---|---|
| `get_gas` / `offered_gases` / `applicability` / `default_sources` | (gas_data L317/L191/L165/L380) | Katalog AP-42 terkutip per gas + fase umur |
| `evaluate` | `(readings, moisture_fraction=None) -> RdfAssessment` (assessment L291) | Gas readings vs threshold paparan; halogen load mg/Nm³; verdict |

**Lynceus**: referensi gas + evaluasi sensor (endpoint "gas screening report"); `citation()` → tooltip provenance.

## Contoh pemakaian terverifikasi (dijalankan)
```python
from scentinel.core.composition import preset
from scentinel.core.pipeline import assess_batch
comp, _ = preset('mixed-msw')
a = assess_batch(comp, tonnage_t=12.0, moisture=0.45, age_h=72.0)
```
Output aktual: fase II; CH₄ kumulatif **0.471 kg** (0.657 m³); CO₂ 1.295 kg; skor composting 0.51 > rdf 0.46 → rekomendasi **'composting'** (moisture 0.45 + putrescible 0.38 memenangkan aturan composting); caveat NCV/ash/Cl-butuh-lab muncul sesuai harapan.

## Nasib module untuk Lynceus
- **Langsung adopsi tanpa modifikasi** (9): composition, generation, massbalance, suitability, recommend, pipeline, virtual_sensor, gas_data, assessment — pure & stdlib-only. `gas_defaults.py` (780 ln generated) ikut sebagai data.
- **Ubah**: string Inggris hardcode di `recommend` → i18n key; caveat "mesh independence" (flag `screening=True`) → ganti redaksi untuk web; backend serialize asdict, frontend memformat.
- **Buang**: `casegen.py`, `container.py`, `geometry.py`, `mesh.py`, `runner.py`, `post.py`, `scenario.py`, `project.py`, `history.py` (konsep audit-nya diadopsi ulang, lihat research-scentinel-audit-provenance.md; kode IO/Qt tidak dibawa).
