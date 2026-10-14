# Lynceus: business case

Deck source. Every figure has a numbered source, opened in October 2026. Anything proposed rather than measured is marked **Proposal**. Rupiah to dollars uses Rp 16,000/US$ (convention of `docs/research/realcase-indonesia.md`).

## 1. One line

Lynceus checks a truck of refuse-derived fuel (RDF, called SRF or CSS in Europe) at the weighbridge, before it is tipped. It returns ACCEPT, ESCALATE or REJECT from a rule engine, keeps a tamper-evident record, and tells the operator the next step, with the SOP clause for each step.

## 2. User and buyer

| Role | Who | What they need |
|---|---|---|
| **User** | Weighbridge operator and shift supervisor at the receiving gate | A clear call in the time the truck sits on the scale, and evidence for a refusal that the driver will dispute |
| **Buyer** | Alternative-fuels (AF) manager or plant manager of a cement plant that co-processes RDF | Fewer stoppages at the shredder and kiln feed, steady fuel quality, a record to show the supplier and the regulator |
| **Influencers** | Maintenance (shredders, feeders), quality lab, HSE | Fewer foreign objects, a link from a bad lot to the truck that brought it |
| **Second buyer** | RDF producer (Indonesian TPST, Italian CSS producer) | Proof that what left their gate was clean, which protects the offtake price |

## 3. The problem and what it costs

- **Hard objects reach the line, and most checks act after tipping.** At an RDF plant in Albany, New York, about 10% of incoming trucks were already turned away to landfill because they held too much unshreddable material, so a gate check pays; still, magnets were "less effective in removing very heavy ferrous objects" and visual inspection on the tipping floor was "ineffective in removing all material which might damage the shredders" [17]. The same plant also recorded 23 shredder explosions in four and a half years, which the paper attributes to containers of volatile material, not to hard objects [17]. This is a 1986 US case, the only one we found with measured numbers.
- **Shredders stop on metal.** A current supplier's shredder shuts down when metal enters, and an operator removes it by hand [16]. The line has already stopped.
- **The equipment and the stop are expensive.** One shredder in an Indonesian RDF plant budget costs Rp 350 million (about US$21,900), with a 5-year life [9]. A US maintenance vendor puts unplanned kiln downtime at about US$28,000 per hour [12], a vendor benchmark, not a local measurement.
- **Supply is already short, so every load counts.** Jakarta's Bantargebang plant is designed for about 700 t/day of RDF against 2,500 t/day wanted by its cement offtakers [8], and actually makes about 400 t/day (RDI 2024, Table III.2, in `docs/research/realcase-indonesia.md`). In Italy, CSS-Combustibile use fell 11.5% in 2022, mainly because one plant's supplier could not deliver steadily [3].

**What we do not know yet:** how often a contaminated truck arrives at an RDF gate, and what one escalation costs a plant. No public source gives these numbers. `docs/operator-validation-kit.md` is how we will get them.

## 4. Market

### Indonesia (beachhead)

| Fact | Value | Source |
|---|---|---|
| Integrated cement companies | 15, installed capacity 116 Mt/yr, 45% overcapacity (July 2023) | [7] |
| SIG group alternative fuels, 2023 | 559,625 t; thermal substitution rate (TSR) 7.27% | [8] |
| RDF from municipal waste at three SBI plants (Narogong, Cilacap, Tuban), 2023 | 30,061 t | [8] |
| SBI TSR, 2022 | 11.73% | [8] |
| RDF share of kiln fuel tonnage, national | about 5% | [9] |
| RDF price paid by cement plants | Rp 300,000 to 450,000 per tonne | [8], [9] |
| Named RDF supply plants | Bantargebang, Rorotan (Jakarta), Cilacap, Banyumas, Belahanrejo and Ngipik (Gresik) | [8], [9] |

Indonesian kilns get 7 to 12% of their heat from alternative fuels, RDF is about 5% of fuel tonnage, and supply is the constraint. Each new RDF plant adds a receiving gate at the producer and at the kiln.

### Italy and the EU (expansion)

| Fact | Value | Source |
|---|---|---|
| Full-cycle cement plants of Aitec members (85% of national cement) | 27 (2019) | [1] |
| Share authorised to burn recovered fuels | "only half" of the 27 (2022) | [2] |
| Italian TSR | 20.3% in 2019, against an EU average of 47% | [1] |
| | 22.5%, against a European average of 57.6% (Federbeton 2023 report) | [4] |
| Industry target (Federbeton with KPMG) | 47% by 2030, 80% by 2050 | [2] |
| Benchmarks | Germany 70.4%, Austria 78% | [2] |
| CSS (combustibili solidi secondari) burned in Italian cement plants, 2019 | 282,973 t of 421,686 t of recovered fuels | [1] |
| CSS-Combustibile (end-of-waste product, DM 22/2013) used in 2022 | 64,237 t at 7 plants | [3] |
| CSS exported by Italy, 2020 | over 116,000 t | [2] |

Going from 20.9% (2020 [2]) to the 47% target is a factor of about 2.2: at constant clinker output, recovered fuel arriving at Italian kiln gates would roughly double by 2030. That is our arithmetic, not a forecast in the sources.

### Size of the first market, at the proposed price

**Proposal.** Indonesia: 5 cement gates (SBI Narogong, Cilacap and Tuban; SIG Tuban; the Indocement plant that takes Jakarta RDF) plus 6 named RDF plants gives 11 gates, or Rp 792 million (about US$49,500) a year. Italy: about 14 authorised plants at €6,000 gives about €84,000 a year. The first market is small; it is where we get proof. The larger market is every gate that receives RDF or SRF (kilns, RDF producers, waste-to-energy plants); the next subsection counts the part we could source.

### Market size (bottom-up)

**Proposal.** Section 7 prices, one gate per site (an assumption: a large plant with several weighbridge lanes would add gates). Counts are sites that could buy, not sites that have.

| Segment | Sites | Gates per site | Subscription per gate a year | Total a year | Source |
|---|---|---|---|---|---|
| EU integrated cement plants (clinker kilns; grinding-only sites left out) | about 200 of 250 installations (2026) | 1 | €6,000 | about €1.2 million | [21] |
| of which Italy, full-cycle plants of Aitec members | 27 (2019) | 1 | €6,000 | €162,000 | [1] |
| Indonesia integrated cement plants (16 cement association members) | 23 (April 2024) | 1 | Rp 72 million | Rp 1,656 million (about US$103,500) | [22] |
| Indonesia municipal-waste RDF plants listed by the cement association | 18: 4 completed, 14 ongoing or next (April 2024) | 1 | Rp 72 million | Rp 1,296 million (about US$81,000) | [22] |
| **Serviceable market** (rows above, Italy counted once) | **241** | | | **about €1.2 million plus US$184,500** | |
| Europe waste-to-energy plants (residual waste; EU plus UK, Norway, Switzerland) | 499 (2023) | 1 | €6,000 | about €3.0 million | [24] |
| **Upper bound, not a forecast:** every cement plant tracked worldwide plus European waste-to-energy plants, all at the EU price | 3,884 + 499 = 4,383 (2026, 2023) | 1 | €6,000 | about €26.3 million | [23], [24] |

- The serviceable rows count kilns that can burn RDF, not kilns that do: only half of the Italian plants are authorised [2]. We found no sourced count of EU plants that co-process SRF, so that row is left out rather than estimated.
- 14 of the 18 Indonesian RDF plants are projects, not yet operating.
- Waste-to-energy plants take residual municipal waste rather than RDF. The same gate checks (metal, rock, tyres, weight) apply, but we have not validated them there, so they sit outside the serviceable market.
- The global count includes grinding-only and non-operating plants, which receive no fuel, and prices every plant at the EU fee rather than the Indonesian one. It is a ceiling.

## 5. Competition

| Option | Where it acts | What it catches | What it misses for an RDF gate | Decides before tipping? |
|---|---|---|---|---|
| Overband magnet + eddy-current separator (e.g. Eriez [15]) | Conveyor, after shredding | Ferrous (magnet) and non-ferrous (eddy current) metal | Rock, concrete, tyres, waybill fraud; heavy ferrous slips past magnets [17] | No, the object has already gone through the shredder |
| Shredder metal trip (e.g. WEIMA [16]) | Inside the shredder | Metal, by stopping the machine | Everything that is not metal; the line has already stopped | No |
| Manual visual check (PUPR gate SOP [10]) | Gate and tipping floor | Whatever the person sees | Consistency, records, night shifts; found "ineffective" in [17] | Partly |
| Greyparrot Analyzer [11] | Above conveyors in MRFs and plastics plants | 115 material categories | The page says it does not support collection vehicles; names no gate, RDF or cement use | No |
| TOMRA AUTOSORT RDF [13] | Sorting line | Calorific value, chlorine and moisture; removes PVC and non-combustibles | No gate, weighbridge or waybill check named | No |
| AMCS Weighbridge and Vision AI [14] | Scale-house tickets; cameras on collection vehicles | Weights and tickets; bin contamination and overfill | The weighbridge brochure names no load inspection; vision is on collection trucks | No |
| 3rd Eye [18] | Truck hoppers, scale houses, tipping floors | Bags, film, tyres, batteries, propane tanks | Built for haulers and MRFs; no RDF, cement, waybill check or SOP steps named | Partly |
| MOBA MAWIS.AI VIEW [19] | On the collection vehicle during tipping | Batteries, hazardous items, 30+ fractions | Municipal collection, not plant gates | No |
| **Lynceus** | **Weighbridge, truck still on the scale** | **Metal (measured: 19 of 20 metal-waste photos); the rules also cover rock, concrete, tyres, e-waste, wet loads, waybill and weight mismatch and gate gas, not yet benchmarked** | **No physical sorting; needs a lab for calorific value and chlorine** | **Yes** |

3rd Eye is the closest product: it already watches scale houses and tipping floors. Our answer is the RDF-specific layer (waybill check, rule engine, SOP-cited next steps, audit trail). A vision model on its own is not a moat.

## 6. Why Lynceus is different

1. **It decides before tipping.** The truck is still on the scale, so a refused load never enters the fuel stream.
2. **Rules decide, not the model.** The vision and language models only report what they see. A rule engine with cited thresholds gives the verdict, and an uncertain case goes to ESCALATE for a person to decide.
3. **It keeps a record a supplier cannot easily dispute.** Inputs are digested with SHA-256 and records are tamper-evident: evidence for a refusal, a price penalty or a supplier talk.
4. **It tells the operator what to do.** Each next step cites the gate SOP clause behind it, and the assistant answers only from plant documents. In Italy the knowledge base already holds the CSS-Combustibile rule (DM 22/2013, `REG-IT-CSS`).

## 7. Revenue model (Proposal)

| Item | Indonesia | Italy / EU |
|---|---|---|
| Subscription per gate | Rp 6 million a month (Rp 72 million a year, about US$4,500) | €500 a month (€6,000 a year) |
| Install | Camera, mount, edge box and weighbridge link, at cost, quoted after a site survey | Same |
| Pilot | 60 days free at one gate, in exchange for the right to quote the results | Same |

How we set the prices:
- **Comparable.** Weighbridge software sells to UK public buyers at £4,995 per instance a year [20]. Lynceus is an add-on at the same gate, so the EU price sits in that band.
- **Value.** A Cilacap-scale gate takes about 60 t of RDF a day [8]. At Rp 360,000 per tonne that is about Rp 648 million of fuel a month, so the fee is under 1% of the fuel it protects. The yearly fee is about a fifth of the price of one shredder (Rp 350 million [9]).
- **Break-even.** At the US benchmark of US$28,000 per hour of kiln downtime [12], one avoided hour pays for about six Indonesian gate-years. Plant figures from the validation interviews will replace this.
- **Not yet known.** Production inference cost: the demo runs on AMD Token Factory, free for the hackathon.

## 8. Go-to-market

**Indonesia, first.**
1. Run the 15-minute interview in `docs/operator-validation-kit.md` with gate staff at the SBI and SIG RDF plants (Cilacap, Narogong, Tuban) and at the UPST DKI plants that supply Indocement (Bantargebang, Rorotan) [8].
2. One free 60-day pilot at a gate with several RDF suppliers, so supplier records matter.
3. Sell to the cement group for its other RDF gates, and to RDF producers as proof of quality.

**Italy, second.**
1. Begin with the seven plants that used CSS-Combustibile in 2022: Buzzi (Vernasca, Fanna, Augusta), Colacem (Ghigiano, Caravate) and Italcementi/Italsacci (Matera, Cagnano Amiterno) [3].
2. Reach the cement producers through Federbeton, whose reports cover the Aitec cement companies [1], and the CSS producers' side through AIREC and COREPLA, the bodies the ministry's CSS committee heard in 2022 [3].
3. The message: under DM 22/2013 [6], CSS-Combustibile is a product only within 18 of the 125 CSS classes [5] and only with a declaration of conformity [3]. Lynceus adds evidence from the gate to the plant's own acceptance checks.

## 9. Risks

| Risk | Mitigation |
|---|---|
| No measured accuracy on real truck beds; no public truck-bed dataset fits (see `docs/research/truck-datasets.md`) | Pilot photo collection under consent; ESCALATE when confidence is low |
| A wrong REJECT costs a supplier money | Each REJECT shows the rule and evidence behind it; uncertain loads go to ESCALATE and a supervisor check (SOP-RDF-5.2) |
| Italian permits: only half the plants are authorised, partly because of local opposition [2] | Start with the plants already authorised [3] |
| Indonesian overcapacity squeezes capital budgets [7] | Price as an operating cost, with no hardware margin |
| AMCS or 3rd Eye adds an RDF gate feature | Go deep on RDF: SOP, CSS and EN 15359 knowledge, supplier history |
| Plates and drivers in photos (GDPR in Italy) | Store only the fields the gate SOP needs; masking faces in stored photos is not built yet and is on the roadmap |

## 10. Roadmap

- **Now (hackathon):** the working gate flow, rule engine, audit ledger, SOP next steps, cited assistant and shift report.
- **Next 3 months:** operator interviews in Indonesia; the first labelled truck-bed photo set from a consenting gate; pilot at one gate.
- **3 to 9 months:** links to weighbridge software; supplier scorecards; ticket links to the lab's lot results (for CSS-Combustibile and EN ISO 21640 lots).
- **9 to 18 months:** an Italian pilot at a plant that uses CSS-Combustibile; Italian SOP and user interface; self-hosted inference option on AMD Instinct for plants that do not allow cloud.

## Sources

1. Federbeton, *Rapporto di Sostenibilità 2019*: https://ordingegneri.it/wp-content/uploads/sites/118/2024/07/Rapporto_di_Sostenibilita_Federbeton_2019.pdf
2. Federbeton, contribution to the PNGR consultation, 28 April 2022 (MiTE registry): https://va.mite.gov.it/File/Documento/621772
3. MASE, Comitato di Vigilanza e Controllo, *Rapporto sull'applicazione del DM 22/2013, anno 2022*: https://www.mase.gov.it/sites/default/files/archivio/allegati/CSS/rapp_comitato_CSS_2022.pdf
4. Heidelberg Materials Italia blog, citing the Federbeton 2023 report: https://blog.heidelbergmaterials.it/it/combustibili-alternativi-risorse-indispensabili-per-una-produzione-piu-sostenibile
5. Ministry of Environment letter prot. 0004843 (Lazio Region incoming register 0179645), 28 March 2018 (18 vs 125 classes): https://www.regione.lazio.it/sites/default/files/documentazione/RIF_C_Ministero_Ambiente_Tutela_Territorio_Mare_0179645_28_03_2018.pdf
6. DM 14 February 2013 n. 22 on Normattiva: https://www.normattiva.it/uri-res/N2Ls?urn:nir:ministero.ambiente.e.tutela.territorio.e.mare:decreto:2013-02-14;22
7. IDX Channel, Kemenperin on cement overcapacity, 14 July 2023: https://www.idxchannel.com/economics/kemenperin-ungkap-strategi-atasi-overcapacity-di-industri-semen/all
8. `docs/research/realcase-indonesia.md` sections 2a to 2d (Kompas, SIG, SBI report, ASI/Kompas, SWITCH-Asia, PUPR Cipta Karya URLs listed there)
9. RDI (2024), *Kajian Strategi Pembiayaan dan Analisis Ekonomi Proyek RDF*: https://dashboard.rdiglobal.org/storage/publications/file/OgidnCyQqXihV2iFnsOB2cDOTmjDRVkOZ9cSFMUM.pdf
10. PUPR TPA receiving SOP (Rakernis Adipura 2019): https://bulelengkab.go.id/informasi/download/pengelolaan-tpa-yang-baik-landfill-52.pdf
11. Greyparrot product page: https://www.greyparrot.ai/product
12. oxmaint, cement CMMS guide (US benchmark): https://oxmaint.ai/article/cement-plant-maintenance-cmms-system-guide
13. TOMRA, RDF sorting: https://tomra.com/en/waste-metal-recycling/applications/waste-recycling/refuse-derived-fuel
14. AMCS Weighbridge brochure: https://www.amcsgroup.com/resources/brochures/brochure-amcs-weighbridge/ ; AMCS Vision AI: https://www.amcsgroup.com/solutions/amcs-vision-ai
15. Eriez eddy current separators: https://www.eriez.com/Products/Metals-Recycling/Nonferrous-Recovery/Eddy-Current-Separators
16. WEIMA, Dekasan RDF case: https://weima.com/en/success-stories/hazardous-waste-rdf-production-dekasan/
17. Nollet, Hedlund, Hasselriis, *Test of rotary drum air-classifier at Albany, New York*, 1986 National Waste Processing Conference: https://wtert.org/wp-content/uploads/2020/10/1986-National-Waste-Processing-Conference-37.pdf
18. 3rd Eye, contamination detection: https://www.3rdeyecam.com/solution/contamination-detection
19. MOBA, MAWIS.AI VIEW: https://mobile-automation.eu/?p=20226
20. Pentagull Weighbridge, UK G-Cloud 14 listing: https://www.applytosupply.digitalmarketplace.service.gov.uk/g-cloud-14/services/555028591895331
21. European Commission JRC, *Cement factsheet* (JRC144123), 2026 ("around 200 out of 250 installations"): https://publications.jrc.ec.europa.eu/repository/bitstream/JRC144123/Cement_factsheet_JRC144123.pdf
22. Lilik Unggul Raharjo (Chairman, Indonesia Cement Association), *Cost Leadership and Plant Efficiency Enhancement in Indonesia Cement Industry*, World Cement Association conference, 30 April 2024, p. 2 (23 integrated plants) and p. 16 (RDF projects): https://www.worldcementassociation.org/images/download-selector/2024%20conference/Lilik%20Unggul%20Raharjo%20-%20Cost%20Leadership%20and%20Plant%20Efficiency%20Enhancement%20in%20Indonesia%20Cement%20Industry%20to%20support%20Decarbonization%20Initiatives.pdf
23. Global Energy Monitor, Global Cement and Concrete Tracker, 2026 release (3,884 plants): https://globalenergymonitor.org/article/new-data-insights-global-cement-and-concrete-tracker
24. CEWEP, *Waste-to-Energy in Europe in 2023* map (499 plants, hazardous-waste incinerators excluded): https://www.cewep.eu/wp-content/uploads/2026/02/EU-Map-2023.pdf
