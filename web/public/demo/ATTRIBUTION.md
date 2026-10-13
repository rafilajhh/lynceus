# Demo Photo Attribution

## Source

**RealWaste** — An image classification dataset of waste items across 9 major
material types, collected within an authentic landfill environment.

- **Publisher:** UCI Machine Learning Repository (UC Irvine)
- **Dataset URL:** https://archive.ics.uci.edu/dataset/908/realwaste
- **Download:** https://archive.ics.uci.edu/static/public/908/realwaste.zip
- **DOI:** 10.24432/C5SS4G
- **License:** see [Licence](#licence) below. The UCI page states
  [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/), but the README inside
  the dataset zip states CC BY-NC-SA 4.0; the statements disagree.
- **Creators:** Sam Single, Saeid Iranmanesh, Raad Raad
- **Paper:** *RealWaste: A Novel Real-Life Data Set for Landfill Waste
  Classification Using Deep Learning* —
  https://www.mdpi.com/2078-2489/14/12/633

The images in this directory are copies (re-encoded as JPEG, quality 82, no
resizing) of photographs from the RealWaste dataset. The source is credited
here; see Licence for the terms that are assumed.

## Licence

- The UCI dataset page states **CC BY 4.0** (https://creativecommons.org/licenses/by/4.0/).
- The README bundled in the dataset's zip (`realwaste-main/README.md`, same
  download) instead says **CC BY-NC-SA 4.0**.
- The two statements disagree. Until the authors clarify, treat the more
  restrictive terms as binding: attribution, non-commercial use, share-alike.
  These images are used only to illustrate and validate the gate. They are
  excluded from this repository's MIT licence and remain under the dataset's
  own terms.

## Photos

The photos illustrate the three demo risk cases of the Lynceus waste
inspection dashboard:

| File | Original file | Original class | Demo case | Why it fits |
|------|--------------|----------------|-----------|-------------|
| `green-1.jpg` | `Cardboard/Cardboard_212.jpg` | Cardboard | 🟢 Green | Clean, dry, flattened cardboard — dry recyclable stream |
| `green-2.jpg` | `Plastic/Plastic_1.jpg` | Plastic | 🟢 Green | Clean HDPE milk bottle — dry recyclable plastic |
| `green-3.jpg` | `Paper/Paper_445.jpg` | Paper | 🟢 Green | Dry printed paper sheets — clean paper stream |
| `amber-1.jpg` | `Vegetation/Vegetation_111.jpg` | Vegetation | 🟡 Amber | Fresh grass clippings — moist green waste |
| `amber-2.jpg` | `Vegetation/Vegetation_238.jpg` | Vegetation | 🟡 Amber | Damp grass/vegetation pile — elevated moisture |
| `amber-3.jpg` | `Food Organics/Food Organics_233.jpg` | Food Organics | 🟡 Amber | Decaying food waste — wet organic load |
| `red-1.jpg` | `Metal/Metal_333.jpg` | Metal | 🔴 Red | Prominent aluminium trays — visible metal in the load |
| `red-2.jpg` | `Metal/Metal_614.jpg` | Metal | 🔴 Red | Rusty steel bolts/scrap — hazardous metal pieces |
| `red-3.jpg` | `Metal/Metal_626.jpg` | Metal | 🔴 Red | Crushed metal can among waste — clear metal contaminant |

All nine photos are 524×524 px JPEGs (the native RealWaste image size),
totalling well under 1 MB.

## Citation (BibTeX, from UCI)

```bibtex
@misc{misc_realwaste_2023,
  author       = {Sam Single and Saeid Iranmanesh and Raad Raad},
  title        = {{RealWaste}: A Novel Real-Life Data Set for Landfill Waste Classification Using Deep Learning},
  year         = {2023},
  howpublished = {UCI Machine Learning Repository},
  doi          = {10.24432/C5SS4G},
  url          = {https://archive.ics.uci.edu/dataset/908/realwaste}
}
```
