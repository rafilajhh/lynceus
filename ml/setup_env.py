"""Install the ML dependencies into ml/.venv with every cache kept under ml/.cache.

    ml/.venv/Scripts/python ml/setup_env.py          (Windows)
    ml/.venv/bin/python ml/setup_env.py              (Linux)

Installs CUDA torch (cu124 wheels) then Ultralytics + ONNX tooling.
"""

from __future__ import annotations

import subprocess
import sys

import _env  # noqa: F401  (sets PIP_CACHE_DIR, TMP, ...)

TORCH_INDEX = "https://download.pytorch.org/whl/cu124"


def pip(*args: str) -> None:
    cmd = [sys.executable, "-m", "pip", *args]
    print("+", " ".join(cmd), flush=True)
    subprocess.check_call(cmd)


def main() -> None:
    pip("install", "--upgrade", "pip")
    pip("install", "torch", "torchvision", "--index-url", TORCH_INDEX)
    pip("install", "ultralytics==8.4.177", "onnx", "onnxslim", "onnxruntime", "pillow", "numpy")
    import torch  # noqa: PLC0415

    print("torch", torch.__version__, "cuda", torch.cuda.is_available(), flush=True)


if __name__ == "__main__":
    main()
