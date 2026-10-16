#!/usr/bin/env bash
# Lynceus detector: full training run on a Colab GPU, one command.
#
#   cd /content/lynceus && bash ml/colab_train.sh [HOURS_PER_MODEL] [MODELS]
#   e.g. bash ml/colab_train.sh 2.5 "yolo26s yolo26m yolo26l"
#
# Run from the repo (or bundle) root. Steps: install deps; download RealWaste and
# TACO; rebuild the 80 held-out benchmark images; pseudo-label RealWaste with
# YOLOE-26l and merge TACO's human-drawn boxes; leakage check; score the current
# production model as a baseline; train each model; score each on the VAL split;
# select on val only (select_model.py); then export ONNX and score every model
# once on the two test sets (80 RealWaste benchmark images, TACO test split).
# Everything lands in lynceus_train_results.zip.
set -euo pipefail
HOURS=${1:-2.5}
MODELS=${2:-"yolo26s yolo26m yolo26l"}
export PYTHONUNBUFFERED=1

nvidia-smi --query-gpu=name,memory.total --format=csv
# Same Ultralytics as the dev laptop, so the NMS-free ONNX export matches backend/src/lynceus/detector.py.
pip install -q "ultralytics==8.4.177" onnx onnxslim onnxruntime

GPU_GB=$(( $(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits | head -1) / 1024 ))
RAM_GB=$(( $(grep MemTotal /proc/meminfo | awk '{print $2}') / 1024 / 1024 ))
WORKERS=$(( $(nproc) > 8 ? 8 : $(nproc) ))
CACHE=disk; [ "$RAM_GB" -ge 24 ] && CACHE=ram
batch_for() {  # model -> batch size for this GPU (imgsz 640, AMP)
  case "$1" in
    yolo26n|yolo26s) [ "$GPU_GB" -ge 35 ] && echo 64 || { [ "$GPU_GB" -ge 20 ] && echo 32 || echo 32; } ;;
    yolo26m)         [ "$GPU_GB" -ge 35 ] && echo 32 || { [ "$GPU_GB" -ge 20 ] && echo 16 || echo 16; } ;;
    *)               [ "$GPU_GB" -ge 35 ] && echo 24 || { [ "$GPU_GB" -ge 20 ] && echo 12 || echo 8; } ;;
  esac
}
echo "GPU ${GPU_GB} GB, RAM ${RAM_GB} GB, workers ${WORKERS}, cache ${CACHE}, ${HOURS} h per model: ${MODELS}"

python ml/fetch_realwaste.py
python -I backend/benchmark/prepare_images.py ml/data/zip/realwaste.zip backend/benchmark/images
python ml/fetch_taco.py --workers 32
python ml/build_dataset.py --model yoloe-26l-seg.pt --with-taco
python ml/check_leakage.py

# The model in production today, scored on the same val split (the bar to beat).
if [ -f ml/baseline/yolo26s_realwaste.pt ]; then
  python ml/eval_val.py --weights ml/baseline/yolo26s_realwaste.pt --tag prod_yolo26s || echo "BASELINE VAL FAILED"
fi

for M in $MODELS; do
  # One failed model must not sink the others: log it and move on.
  python ml/train.py --model "$M.pt" --epochs 150 --batch "$(batch_for "$M")" --hours "$HOURS" \
    --patience 25 --cos-lr --workers "$WORKERS" --cache "$CACHE" --name "${M}_e26l" \
    || echo "TRAIN FAILED: $M"
  if [ -f "ml/runs/${M}_e26l/weights/best.pt" ]; then
    python ml/eval_val.py --weights "ml/runs/${M}_e26l/weights/best.pt" || echo "VAL FAILED: $M"
  else
    echo "SKIPPED (no best.pt): $M"
  fi
done

# Every model trained so far (this run or an earlier, disconnected one) takes part,
# plus the production baseline.
TAGS=""
for D in ml/runs/*_e26l; do
  T=$(basename "$D")
  [ -f "$D/weights/best.pt" ] && [ -f "ml/results/val_$T.json" ] && TAGS="$TAGS $T"
done
[ -n "$TAGS" ] || { echo "no model trained"; exit 1; }
CANDIDATES="$TAGS"
[ -f ml/results/val_prod_yolo26s.json ] && CANDIDATES="$CANDIDATES prod_yolo26s"
echo "candidates:$CANDIDATES"

# Selection uses the val split only; it is written before any test-set score.
python ml/select_model.py $CANDIDATES

# Test sets, each read once per model at that model's own val thresholds.
thr() { python -c "import json;v=json.load(open('ml/results/val_$1.json'));print(v['hard_threshold'],v['light_threshold'])"; }
for T in $TAGS; do
  python ml/export_onnx.py --weights "ml/runs/$T/weights/best.pt" --out "$T.onnx"
  python ml/eval_finetuned.py --weights "ml/runs/$T/weights/best.pt" --nms-free --tag "$T"
  read -r H L < <(thr "$T")
  python ml/eval_val.py --weights "ml/runs/$T/weights/best.pt" --data ml/data/taco/data.yaml --split test \
    --hard "$H" --light "$L" --tag "${T}_tacotest" || echo "TACO TEST FAILED: $T"
done
if [ -f ml/results/val_prod_yolo26s.json ]; then
  read -r H L < <(thr prod_yolo26s)
  python ml/eval_val.py --weights ml/baseline/yolo26s_realwaste.pt --data ml/data/taco/data.yaml --split test \
    --hard "$H" --light "$L" --tag prod_yolo26s_tacotest || echo "TACO TEST FAILED: prod"
fi

ZIP=lynceus_train_results.zip
rm -f "$ZIP"
FILES="ml/results"
for T in $TAGS; do
  FILES="$FILES ml/weights/$T.onnx ml/runs/$T/weights/best.pt ml/runs/$T/results.csv ml/runs/$T/args.yaml"
done
zip -qr "$ZIP" $FILES
ls -lh "$ZIP"
cat ml/results/selection.json
