# Third-party notices

All Lynceus source code in this repository — the backend (`backend/src/`),
the web console (`web/`), the deployment files (`deploy/`, `Dockerfile`) and
the training scripts (`ml/`) — is released under the MIT licence (`LICENSE`).

The repository also carries the third-party materials below. They keep their
own licences, are kept in their own directories, and are optional: Lynceus
builds and runs without them.

| Material | Where | Licence | Used for | Without it |
|---|---|---|---|---|
| Detector weights (YOLO26m, YOLO26s), fine-tuned from Ultralytics YOLO26 | `backend/models/*.onnx` | AGPL-3.0 (Ultralytics), trained on RealWaste and TACO — see `backend/models/NOTICE` | Optional CPU second opinion on the load photo | Set `DETECTOR_MODEL_PATH=` (empty); verdicts come from the AMD-hosted vision model and the rule engine alone |
| RealWaste benchmark images | `backend/benchmark/images/` | CC BY 4.0 (UCI) / CC BY-NC-SA 4.0 (dataset README); the stricter terms are treated as binding — see `ATTRIBUTION.md` there | Reproducing the committed benchmark | Not needed to run Lynceus; not included in the Docker image |
| Ultralytics library | installed by `ml/setup_env.py`, not vendored | AGPL-3.0 | Training and exporting the detector weights only | Not a runtime dependency: the backend decodes the ONNX output itself (`lynceus.detector`, onnxruntime, MIT) |

Corresponding source for the detector weights, as AGPL-3.0 section 13
requires for a network service, is the `ml/` directory of this repository.
For commercial use, retrain on data you hold the rights to and either obtain an
Ultralytics Enterprise licence or point `DETECTOR_MODEL_PATH` at a permissively
licensed detector.
