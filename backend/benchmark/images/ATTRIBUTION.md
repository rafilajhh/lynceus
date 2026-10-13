# Image attribution

The 80 images in this folder are a subset of **RealWaste**:

- Dataset: *RealWaste*, UCI Machine Learning Repository, dataset id 908.
  https://archive.ics.uci.edu/dataset/908/realwaste (DOI 10.24432/C5SS4G)
- Authors: Sam Single, Saeid Iranmanesh, Raad Raad (University of Wollongong).
- Paper: "RealWaste: A Novel Real-Life Data Set for Landfill Waste Classification
  Using Deep Learning", *Information* 14(12):633, 2023.
  https://www.mdpi.com/2078-2489/14/12/633
- Photographed at the Whyte's Gully Waste and Resource Recovery facility,
  Wollongong NSW, Australia.

## Licence

- The UCI dataset page states **CC BY 4.0** (https://creativecommons.org/licenses/by/4.0/).
- The README bundled in the dataset's zip (`realwaste-main/README.md`, same
  download) instead says **CC BY-NC-SA 4.0**.
- The two statements disagree. Until the authors clarify, treat the more
  restrictive terms as binding: attribution, non-commercial use, share-alike.
  These images are used only to validate the gate, not shipped in the product.

## Selection rule

Fixed quotas per RealWaste class: Metal 20, Glass 7, Food Organics 7,
Vegetation 6, Paper 10, Cardboard 10, Plastic 10, Textile Trash 10 (80 total).
Within each class the files are sorted by their trailing number and every
k-th one is taken from the first, with k = floor(class size / quota).
`Miscellaneous Trash` is not used. The script is `backend/benchmark/prepare_images.py`;
the source zip's SHA-256 is
`1ede08b32358ee62065bcc1c8cb47a2ece04e8dff5b1fb53342bb8750895b2f3`.

## Modifications

Images are 524 x 524 px, the same size as the source. 74 files are byte-for-byte
copies; 6 were larger than 200 KB and were re-encoded as JPEG at a lower quality
(same pixel size) to stay under 200 KB. File names were lower-cased
(`Metal_40.jpg` -> `metal_40.jpg`).
