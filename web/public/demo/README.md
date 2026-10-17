# Demo images

Every image in this folder was **generated with an image model for the demo**
(October 2026). They show no real truck, load, company or person, and they are
not RealWaste photos (the RealWaste benchmark images live in
`backend/benchmark/images/`, with their own attribution).

| File | Scenario | Contents |
|---|---|---|
| `t-metal-1.jpg` | REJECT | shredded RDF with a rusted steel pipe elbow and aluminium foil |
| `t-metal-2.jpg` | REJECT | shredded paper and plastic film over rusted rebar and a chain with a lifting hook |
| `t-clean-1.jpg`, `t-clean-2.jpg` | ACCEPT | clean dry shredded feedstock (paper, cardboard, plastic film, textile) |
| `t-ambiguous-1.jpg`, `t-ambiguous-2.jpg` | ESCALATE | damp mixed waste with wet organic residue clumps |
| `waybill-1.jpg` | waybill evidence | a fictitious Indonesian RDF waybill (*surat jalan*) |

Set 1 shows a truck-bed framing; set 2 fills the frame with the waste only.

The waybill is fiction: the names, plate, reference numbers, signatures and
stamps were invented by the image model. Place names (TPST Bantargebang,
PLTSa Rorotan) are public landmarks used for realism; the stamps are not
theirs and the document was not issued by them. The phone number was
pixelated in case it matches a real line, and the waybill reader is told never
to read it.

The gate reads this image with the vision model on AMD Token Factory
(`POST /waybill/read`): plate, carrier, origin, destination, gross, tare and
net weight, load type and declared moisture. The operator confirms or edits
the fields, and the confirmed fields (with any edits flagged) are what the
rules compare against the load photo and the weighbridge. Offline, the reader
returns the stored fields of this one sample image (matched by its SHA-256)
and labels them as an offline read; any other image needs the live model or
typed fields. The image itself is archived and digested in the audit record.
