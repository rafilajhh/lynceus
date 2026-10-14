# Operator validation kit

A 15-minute interview to learn, from the people at an RDF gate, how often bad loads arrive, what they cost, and whether a plant would pay for Lynceus. The numbers it produces are the ones `docs/BUSINESS.md` says we do not have yet.

Who to interview:
- **Gate side:** weighbridge operator, gate checker, shift supervisor at a cement plant that receives RDF/SRF, or at an RDF producer (TPST, CSS plant).
- **Manager side:** alternative-fuels (AF) or co-processing manager, maintenance lead for the shredder line.

Interview gate and manager staff separately. They give different answers, and both answers are useful.

## Rules

1. **No personal contact data in this repository.** Do not write a name, phone number, e-mail or photo of a person into any file here. Record only: role, plant type, country and province or region, date, interviewer initials.
2. **Read the consent line first.** If the person says no, thank them and stop. Write nothing down.
3. **Ask about the past, not the future.** "When did this last happen?" gives facts. "Would you use...?" gives politeness. Keep the questions on what happened.
4. **Do not demo Lynceus before section D.** Describe the problem, not the product, until the price question.
5. **Write their words, not your summary.** Put direct quotes in quotation marks. Mark your own notes as `[note]`.

## Consent line (read aloud)

**English.** "I am part of a small team building a tool that checks RDF trucks at the weighbridge. I would like to ask you about 15 minutes of questions about your gate. It is voluntary, you can skip any question or stop at any time. I will not write down your name or contact details. I may quote what you say in a presentation, described only by your role and the type of plant, for example 'weighbridge operator, cement plant, Central Java', and only if you agree. Is that all right? May I quote you in that way?"

**Bahasa Indonesia.** "Saya sedang mengembangkan alat untuk memeriksa truk RDF di jembatan timbang. Saya ingin bertanya sekitar 15 menit tentang pekerjaan di gerbang Anda. Ini sukarela; Anda boleh melewati pertanyaan atau berhenti kapan saja. Saya tidak akan mencatat nama atau kontak Anda. Jawaban Anda mungkin saya kutip dalam presentasi, hanya dengan menyebut jabatan dan jenis pabrik, misalnya 'operator jembatan timbang, pabrik semen, Jawa Tengah', dan hanya jika Anda setuju. Apakah boleh? Bolehkah saya mengutip Anda dengan cara itu?"

**Italiano.** "Sto sviluppando uno strumento che controlla i camion di CSS/RDF alla pesa. Vorrei farle domande per circa 15 minuti sul suo lavoro all'ingresso. La partecipazione è volontaria: può saltare una domanda o fermarsi quando vuole. Non annoterò il suo nome né i suoi contatti. Potrei citare le sue parole in una presentazione, indicando solo il ruolo e il tipo di impianto, per esempio 'addetto pesa, cementeria, Nord Italia', e solo se è d'accordo. Va bene? Posso citarla in questo modo?"

Record two answers: consent to interview (yes/no) and consent to quote (yes/no).

## Script (15 minutes)

### A. Context (2 min)

| # | Question | Bahasa Indonesia |
|---|---|---|
| A1 | What is your role at the gate, and how long have you done it? | Apa tugas Anda di gerbang, dan sudah berapa lama? |
| A2 | On a normal day, how many trucks of RDF come through your gate? How many suppliers? | Di hari biasa, berapa truk RDF yang masuk? Dari berapa pemasok? |

### B. What happens now (4 min)

| # | Question | Bahasa Indonesia |
|---|---|---|
| B1 | Walk me through what happens from when a truck reaches the scale until it tips. Who looks at the load, and how? | Ceritakan prosesnya dari truk naik timbangan sampai bongkar. Siapa yang memeriksa muatan, dan bagaimana caranya? |
| B2 | How long does one truck spend at the gate, from arrival to leaving the scale? | Berapa lama satu truk di gerbang, dari datang sampai turun timbangan? |
| B3 | What do you write down for each truck, and where (paper, weighbridge software, photos)? | Apa yang dicatat untuk setiap truk, dan di mana (kertas, software timbangan, foto)? |
| B4 | What checks happen after tipping (magnet, picking, shredder stop)? | Pemeriksaan apa yang ada setelah bongkar (magnet, pemilahan manual, shredder berhenti)? |

### C. Bad loads and their cost (6 min)

| # | Question | Bahasa Indonesia |
|---|---|---|
| C1 | Tell me about the last time a load had something in it that should not be there. When was it? What was it? | Ceritakan terakhir kali ada muatan berisi benda yang tidak seharusnya. Kapan? Benda apa? |
| C2 | How was it found: at the gate, on the tipping floor, at the shredder, or later? | Ditemukan di mana: di gerbang, di lantai bongkar, di shredder, atau setelahnya? |
| C3 | What happened next? Did a machine stop? For how long? Who had to fix it? | Lalu apa yang terjadi? Apakah mesin berhenti? Berapa lama? Siapa yang memperbaiki? |
| C4 | Roughly how often does that happen: per week, per month, per year? | Kira-kira seberapa sering: per minggu, per bulan, per tahun? |
| C5 | Which items cause the most trouble: metal, stone, concrete, tyres, electronics, wet loads, something else? | Benda apa yang paling merepotkan: logam, batu, beton, ban, elektronik, muatan basah, lainnya? |
| C6 | Has a waybill (surat jalan) ever not matched what was in the truck? What happened? | Pernah surat jalan tidak sesuai dengan isi truk? Lalu bagaimana? |
| C7 | When a load is refused or argued about, how long does it take to settle, and who decides? What does it cost you (time, a penalty, a returned load)? | Kalau muatan ditolak atau diperdebatkan, berapa lama selesainya dan siapa yang memutuskan? Berapa biayanya (waktu, denda, muatan dikembalikan)? |

If the person gives a cost figure, ask: "Is that a number you saw on a document, or an estimate?" Record which.

### D. Value and price (2 min)

Now describe Lynceus in two sentences: "A camera and software at the weighbridge check the load and the waybill before tipping. They give accept, escalate or reject, with a record and the next step from your SOP."

| # | Question | Bahasa Indonesia |
|---|---|---|
| D1 | Would this have changed what happened in the case you told me about? How? | Apakah ini akan mengubah kejadian yang tadi Anda ceritakan? Bagaimana? |
| D2 | Who at the plant would decide to buy something like this, and from which budget? | Siapa di pabrik yang memutuskan membeli alat seperti ini, dan dari anggaran apa? |
| D3 | What would make you not trust it? | Apa yang membuat Anda tidak percaya pada alat ini? |
| D4 | We are thinking of Rp 6 juta per gate per month (Italy: €500). Too expensive, about right, or cheap? Why? | Kami memikirkan Rp 6 juta per gerbang per bulan. Terlalu mahal, wajar, atau murah? Kenapa? |
| D5 | Would your plant run a free 60-day trial at one gate? Who would have to agree? | Apakah pabrik Anda mau uji coba gratis 60 hari di satu gerbang? Siapa yang harus setuju? |

### E. Close (1 min)

- "Is there anything I should have asked and did not?"
- Re-confirm the quote consent. Thank them.

## Quote-capture template

Copy one block per interview into a private notes folder outside this repository. Only the anonymised summary goes into the pitch.

```yaml
interview_id: IDN-001            # country code + number, never a name
date: 2026-10-__
interviewer: __                  # initials
consent_interview: yes
consent_quote: yes               # if no, keep numbers only, no quotes
role: weighbridge operator       # or: shift supervisor / AF manager / maintenance lead
plant_type: cement plant gate    # or: RDF producer (TPST) / CSS producer
region: Central Java             # province or region only
trucks_per_day: __               # A2, as stated
suppliers: __                    # A2
minutes_per_truck_at_gate: __    # B2
checks_now: [visual at gate, magnet after shredder]   # B1, B4
last_incident:
  when: "__"                     # C1
  item: "__"                     # C1
  found_at: gate | tipping floor | shredder | later   # C2
  consequence: "__"              # C3, e.g. shredder stop 2 h
  cost_figure: "__"              # C7, with currency
  cost_basis: document | estimate | unknown
frequency: "__"                  # C4, as stated, e.g. "2-3 per month"
top_items: [__, __]              # C5
waybill_mismatch: "__"           # C6
dispute_time_and_owner: "__"     # C7
buyer_and_budget: "__"           # D2
trust_concerns: "__"             # D3
price_reaction: too expensive | about right | cheap   # D4
price_reason: "__"
pilot_interest: yes | no | needs approval from __     # D5
quotes:
  - "__"                         # verbatim, only if consent_quote: yes
```

## How to cite the results honestly in the pitch

1. **Say how many, who and when.** For example: "6 interviews, October to November 2026: 4 weighbridge operators and 2 AF managers, at 3 cement plants in Java." Never round 6 up to "dozens" or call it a survey.
2. **Report what people said as what people said.** "Operators reported 1 to 3 bad loads a month" is honest. "1 to 3 bad loads a month happen" is not. Mark every number as reported, and say whether it came from a document or an estimate (`cost_basis`).
3. **Give ranges and counts, not invented averages.** With fewer than 10 interviews, show "4 of 6 said..." and the range. Do not compute a market-wide figure from them.
4. **Do not extrapolate one plant to a country.** One plant's incident cost is a case, not a national number.
5. **Keep price reactions apart from commitments.** "About right" is an opinion. A signed pilot or a named approver is a commitment. Say which one you have.
6. **Quote only with consent, and only by role.** Attribute a quote as "weighbridge operator, cement plant, Central Java", never by name or company unless the company has agreed in writing.
7. **Show the bad news too.** If people say bad loads are rare, or that they do not trust a camera, put it on the slide with what we changed because of it.
8. **If no interview is done before the deadline, say so.** The slide then reads "Validation plan: 15-minute operator interviews, script in `docs/operator-validation-kit.md`", with no numbers.

Slide line template:

> "We interviewed **N** people (**roles**) at **K** RDF gates in **region** (**dates**). **X of N** described a bad load in the last **period**; reported consequences ranged from **a** to **b**. **Y of N** called Rp 6 juta per gate per month about right or cheap; **Z** plant(s) agreed to a pilot."
