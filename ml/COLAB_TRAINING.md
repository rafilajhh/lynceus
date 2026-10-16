# Detector training run on Colab (brief for the training agent)

You are training the Lynceus detector. It runs next to the vision-language model at a cement-plant
gate as a "second opinion". From one photo of a waste load it flags:
- **metal**, the hard contaminant;
- **glass** and **organic**, the light contaminants.

In production the detector can only hold a truck for a human. It never accepts or rejects on its
own. The number that matters most is how many metal loads it catches (**metal recall**), with very
few false metal flags on clean loads.

## Data (the script downloads all of it)

- **RealWaste** (UCI): one item per photo on a concrete floor.
  - 4,177 photos are pseudo-labelled with YOLOE-26l. The class comes from the folder; the box comes
    from YOLOE.
  - The 80 photos of the Lynceus benchmark are held out and never trained on.
  - Every 10th photo per class goes to val.
- **TACO** (github.com/pedropro/TACO, CC BY 4.0): cluttered real-world litter scenes with several
  objects and **human-drawn boxes**. These are closer to a mixed truck load.
  - It has about 550 metal boxes: cans, foil, caps, pop tabs and scrap.
  - Split by image id: `id % 10 == 8` goes to val, `== 9` to **test**, the rest to train.
  - The TACO test split is the **out-of-domain test set**.

## What to run

1. Open a Colab notebook with a **GPU runtime**, in this order of preference: A100, L4, T4. Choose
   High-RAM if it is offered.
2. Upload `lynceus_colab_bundle.zip` to `/content`, then run:

   ```bash
   cd /content && unzip -q -o lynceus_colab_bundle.zip -d lynceus && cd lynceus
   bash ml/colab_train.sh 2.5 "yolo26s yolo26m yolo26l"
   ```

   - The first argument is the wall-clock cap per model, in hours.
   - The second argument lists the models to train.
   - On a T4, run `2.0 "yolo26s yolo26m"` instead. A T4 is too slow for `yolo26l` to be worth it.
   - The script picks batch size, workers and cache from the GPU and RAM it finds.
3. Keep the runtime alive until the script prints `selection.json`.
   - On an A100, data download and labelling take about 1 h, then each model takes up to 2.5 h.
   - If Colab disconnects but `/content/lynceus` survives, re-run with only the unfinished models,
     e.g. `bash ml/colab_train.sh 2.5 "yolo26l"`.
   - Models already in `ml/runs/<model>_e26l` that have their `val_*.json` still take part in
     selection and export.
   - If the runtime was reset, start over.

## What the script does, in order (do not change the order)

1. Installs `ultralytics==8.4.177`, onnx, onnxslim and onnxruntime.
2. Downloads RealWaste (about 690 MB) and rebuilds the 80 benchmark images.
   `common.benchmark_zip_names` aborts the run if they do not match `manifest.csv`.
3. Downloads TACO. About a third of the images have no 640-px copy, so their originals are fetched
   and shrunk.
4. Pseudo-labels RealWaste with YOLOE-26l, then merges TACO's train and val splits. The TACO test
   split is never merged.
5. Runs `check_leakage.py`, a near-duplicate check:
   - the benchmark against RealWaste training data;
   - the TACO test split against TACO train and val.
6. Scores the **current production model** on the same val split. This is the bar to beat (tag
   `prod_yolo26s`).
7. For each model:
   - fine-tune with up to 150 epochs, early-stop patience 25, cosine LR and the hours cap;
   - run `eval_val.py`, which scores val at image level per source (RealWaste, TACO) and picks the
     thresholds **on val**.
8. `select_model.py` ranks every model, including production, on **val only** and writes
   `ml/results/selection.json`.
9. Exports each model to ONNX (NMS-free head, output `(1, 300, 6)`).
10. Scores each model **once** on both test sets, at that model's own val thresholds:
    - the 80 RealWaste benchmark images (`finetuned_*`);
    - the TACO test split (`val_*_tacotest.json`).
11. Zips everything into `/content/lynceus/lynceus_train_results.zip`.

## Rules (they keep the numbers honest)

- Do **not** tune thresholds, epochs or model choice by looking at test results (`finetuned_*.json`
  or `*_tacotest.json`). Selection happens on val before the test step runs. If you change
  anything, change it for every model and re-run from step 7.
- Do **not** add `backend/benchmark/images` or TACO test images to training.
- Licences:
  - The weights derive from Ultralytics YOLO26 (AGPL-3.0).
  - RealWaste is CC BY-NC-SA 4.0. TACO is CC BY 4.0.
  - Do not publish the zip, the weights or the data publicly. Share them with the team only.

## What to send back

1. `lynceus_train_results.zip`. Put it in Google Drive (shared with the team only) or on the
   server, and send the user a link or path. It contains:
   - `ml/results/`:
     - `val_*.json` and `selection.json`;
     - `finetuned_*` and `*_tacotest`;
     - `pseudo_label_stats.json`, `taco_stats.json` and `leakage_check.json`;
   - for each model: `best.pt`, `results.csv`, `args.yaml` and the `.onnx` file.
2. A short note:
   - the GPU type;
   - the epochs actually run per model;
   - the printed `selection.json`;
   - any line containing `FAILED` or `SKIPPED`;
   - the `taco_stats.json` counts.

The final model choice, CPU and AMD Radeon latency, and the hybrid replay are all re-checked on the
dev laptop with the production decoder (`backend/src/lynceus/detector.py`) before anything ships.
