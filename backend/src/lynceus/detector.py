"""CPU object-detector second opinion (fine-tuned YOLO26s, ONNX).

One photo in, contaminant boxes out, in ~150 ms on a laptop CPU, with no
network: the detector keeps working when the shared AMD endpoint does not.
It is a *second opinion* next to the vision-language model, never a verdict
of its own (see :func:`lynceus.decision.decide`).

Runtime: onnxruntime + numpy + Pillow, no torch / Ultralytics.  The decoder
is a port of ``ml/onnx_infer.py`` for the NMS-free end-to-end export (output
``(1, K, 6)``: x0, y0, x1, y1, conf, cls in letterboxed pixels).  The
execution provider is ``DETECTOR_PROVIDERS`` (default CPU; e.g. DirectML on
an AMD Radeon); a GPU provider that is missing or fails to load falls back to
the CPU, and ``runtime`` in every result names the provider actually used.

Classes (from the ONNX metadata): metal, glass, organic, paper, plastic,
textile.  ``metal`` maps to the hard contaminant ``metal``; ``glass`` and
``organic`` (→ ``organic_residue``) are light contaminants; paper, plastic and
textile are RDF feedstock and never flag a load.

Missing dependencies, no configured model, or a model that fails to load all
mean "detector disabled": :func:`detect` returns ``None`` and the gate runs
on without it.  A photo the detector cannot read (or one over
:data:`MAX_PIXELS`) raises; the pipeline turns that into ``None`` plus a log
line.  At most :data:`MAX_CONCURRENT_RUNS` photos are decoded and run at once.
"""

from __future__ import annotations

import ast
import contextlib
import hashlib
import io
import logging
import threading
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from lynceus.config import Settings, get_settings

__all__ = [
    "MODEL_NAME",
    "RUNTIME",
    "CPU_PROVIDER",
    "HARD_LABELS",
    "LIGHT_LABELS",
    "MAX_PIXELS",
    "DetectorImageError",
    "detect",
    "enabled",
    "model_name",
    "runtime_name",
    "summarize",
    "flagged",
    "warm",
]

_log = logging.getLogger(__name__)

MODEL_NAME = "yolo26s-realwaste"
#: The runtime of the CPU provider (the default, and the fallback).
RUNTIME = "onnxruntime-cpu"
CPU_PROVIDER = "CPUExecutionProvider"
#: onnxruntime provider → reported runtime; others: ``onnxruntime-<name>``.
_RUNTIME_NAMES = {
    CPU_PROVIDER: RUNTIME,
    "DmlExecutionProvider": "onnxruntime-directml",
    "ROCMExecutionProvider": "onnxruntime-rocm",
    "MIGraphXExecutionProvider": "onnxruntime-migraphx",
}
#: GPU providers that take a ``device_id`` provider option.
_DEVICE_ID_PROVIDERS = frozenset(
    {"DmlExecutionProvider", "ROCMExecutionProvider", "MIGraphXExecutionProvider"}
)
#: Detector class → gate contaminant name (decision.HARD_CONTAMINANTS).
HARD_LABELS = {"metal": "metal"}
#: Detector class → gate contaminant name (decision.LIGHT_CONTAMINANTS).
LIGHT_LABELS = {"glass": "glass", "organic": "organic_residue"}
#: Letterbox padding grey, as Ultralytics trains with.
_PAD_GREY = (114, 114, 114)
#: Photos above this many pixels are refused before any decode (a 40 MP
#: photo is already far above any gate camera; the model sees 640 px).
MAX_PIXELS = 40_000_000
#: JPEGs are decoded at a reduced DCT scale no smaller than this.
_DRAFT_SIZE = (1280, 1280)
#: Detector runs (decode + inference) allowed at once.
MAX_CONCURRENT_RUNS = 2
#: How long a run waits for a free slot before giving up (seconds).
_SLOT_WAIT_S = 30.0
_RUN_SLOTS = threading.BoundedSemaphore(MAX_CONCURRENT_RUNS)


class DetectorImageError(ValueError):
    """The photo is too large or unsafe to decode."""


def model_name(path: str) -> str:
    """The reported model name: the ONNX file stem without the ``lynceus-``
    prefix (``yolo26s-realwaste`` for the bundled file)."""
    stem = Path(path).stem
    return stem.removeprefix("lynceus-") or stem


def runtime_name(provider: str) -> str:
    """The reported runtime for an onnxruntime provider name
    (``DmlExecutionProvider`` → ``onnxruntime-directml``)."""
    if provider in _RUNTIME_NAMES:
        return _RUNTIME_NAMES[provider]
    return "onnxruntime-" + provider.removesuffix("ExecutionProvider").lower()


def _file_sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


class _Model:
    """One loaded ONNX session plus what the decoder needs from its metadata.

    ``providers`` are tried in order among those this onnxruntime build has,
    always ending with the CPU; ``provider`` / ``runtime`` name the one the
    session actually uses.
    """

    def __init__(
        self,
        path: str,
        threads: int = 2,
        providers: Sequence[str] = (CPU_PROVIDER,),
        device_id: int = 0,
    ) -> None:
        import onnxruntime as ort  # noqa: PLC0415 — optional dependency, loaded lazily

        # Hashed once at load: every result names the exact weights it came from.
        self.sha256 = _file_sha256(path)
        self.name = model_name(path)
        available = set(ort.get_available_providers())
        wanted = [p for p in dict.fromkeys(providers) if p != CPU_PROVIDER]
        missing = [p for p in wanted if p not in available]
        if missing:
            _log.warning("detector: provider(s) %s not in this onnxruntime build (has %s)",
                         ", ".join(missing), ", ".join(sorted(available)))
        gpu = [p for p in wanted if p in available]
        self.session = None
        if gpu:
            try:
                self.session = _session(ort, path, threads, gpu + [CPU_PROVIDER], device_id)
            except Exception as exc:  # noqa: BLE001 — the CPU still runs the detector
                _log.warning("detector: %s session failed (%s: %s); using %s",
                             ", ".join(gpu), type(exc).__name__, exc, CPU_PROVIDER)
        if self.session is None:
            self.session = _session(ort, path, threads, [CPU_PROVIDER], device_id)
        self.provider = self.session.get_providers()[0]
        self.runtime = runtime_name(self.provider)
        # A GPU (DirectML) session is not safe for concurrent Run calls.
        self.run_lock: Any = (
            contextlib.nullcontext() if self.provider == CPU_PROVIDER else threading.Lock()
        )
        inp = self.session.get_inputs()[0]
        self.input_name = inp.name
        self.size = int(inp.shape[2]) if isinstance(inp.shape[2], int) else 640
        meta = self.session.get_modelmeta().custom_metadata_map
        names = ast.literal_eval(meta["names"]) if "names" in meta else {}
        self.names = {int(k): str(v) for k, v in names.items()}
        shape = self.session.get_outputs()[0].shape
        # (1, K, 6) has K rows > 6 columns; the classic head is (1, 4 + nc, 8400).
        if not (len(shape) == 3 and isinstance(shape[2], int) and shape[2] == 6):
            raise ValueError(f"expected an NMS-free (1, K, 6) output, got {shape}")

    def __call__(self, image: Any, min_conf: float) -> List[Dict[str, Any]]:
        import numpy as np  # noqa: PLC0415
        from PIL import Image  # noqa: PLC0415

        w, h = image.size
        r = min(self.size / h, self.size / w)
        nw, nh = round(w * r), round(h * r)
        left, top = round((self.size - nw) / 2 - 0.1), round((self.size - nh) / 2 - 0.1)
        if (nw, nh) != (w, h):
            image = image.resize((nw, nh), Image.BILINEAR)
        canvas = Image.new("RGB", (self.size, self.size), _PAD_GREY)
        canvas.paste(image, (left, top))
        x = np.asarray(canvas, dtype=np.float32).transpose(2, 0, 1)[None] / 255.0
        with self.run_lock:
            out = self.session.run(None, {self.input_name: np.ascontiguousarray(x)})[0][0]
        boxes, scores, classes = out[:, :4], out[:, 4], out[:, 5].astype(int)
        keep = scores >= min_conf
        boxes, scores, classes = boxes[keep], scores[keep], classes[keep]
        boxes = (boxes - np.array([left, top, left, top], dtype=np.float32)) / r
        boxes = np.clip(boxes / np.array([w, h, w, h], dtype=np.float32), 0.0, 1.0)
        found = []
        for i in np.argsort(-scores):
            x0, y0, x1, y1 = (round(float(v), 4) for v in boxes[i])
            if not (x0 < x1 and y0 < y1):
                continue  # degenerate after clipping: a box in no place is no evidence
            label = self.names.get(int(classes[i]), str(int(classes[i])))
            found.append(
                {"label": label, "confidence": round(float(scores[i]), 4), "box": [x0, y0, x1, y1]}
            )
        return found


def _session(ort: Any, path: str, threads: int, providers: List[str], device_id: int) -> Any:
    """An InferenceSession on ``providers`` (the last one is the CPU)."""
    options = ort.SessionOptions()
    options.intra_op_num_threads = max(1, int(threads))
    if providers != [CPU_PROVIDER]:
        # DirectML requires both; harmless for the other GPU providers.
        options.enable_mem_pattern = False
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    chain = [
        (p, {"device_id": int(device_id)}) if p in _DEVICE_ID_PROVIDERS else p for p in providers
    ]
    return ort.InferenceSession(path, sess_options=options, providers=chain)


_LOCK = threading.Lock()
#: (path, providers, device_id) → loaded model, or None when loading failed
#: (not retried per request).
_MODELS: Dict[Tuple[str, Tuple[str, ...], int], Optional[_Model]] = {}


def _model(
    path: str,
    threads: int = 2,
    providers: Sequence[str] = (CPU_PROVIDER,),
    device_id: int = 0,
) -> Optional[_Model]:
    """The cached model for ``path`` on ``providers``; loads once, thread-safe."""
    key = (path, tuple(providers), int(device_id))
    with _LOCK:
        if key not in _MODELS:
            try:
                _MODELS[key] = _Model(path, threads, providers, device_id)
            except Exception as exc:  # noqa: BLE001 — any load failure disables the stage
                _log.warning("detector disabled: cannot load %s (%s: %s)",
                             path, type(exc).__name__, exc)
                _MODELS[key] = None
        return _MODELS[key]


def _settings_model(settings: Settings) -> Optional[_Model]:
    return _model(settings.detector_model_path, settings.detector_threads,
                  settings.detector_providers, settings.detector_device_id)


def _deps_available() -> bool:
    try:
        import numpy  # noqa: F401, PLC0415
        import onnxruntime  # noqa: F401, PLC0415
        import PIL  # noqa: F401, PLC0415
    except ImportError:
        return False
    return True


def enabled(settings: Optional[Settings] = None) -> bool:
    """True when a model is configured, on disk, and its runtime is installed."""
    settings = settings or get_settings()
    path = settings.detector_model_path
    return bool(path) and Path(path).is_file() and _deps_available()


def flagged(
    result: Optional[Dict[str, Any]], hard_conf: float, light_conf: float
) -> Tuple[Dict[str, float], Dict[str, float]]:
    """``(hard, light)``: gate contaminant name → best confidence at/above its
    threshold.  Feedstock classes (paper/plastic/textile) never appear."""
    hard: Dict[str, float] = {}
    light: Dict[str, float] = {}
    for box in (result or {}).get("boxes") or []:
        label = box.get("label")
        conf = box.get("confidence")
        if not isinstance(conf, (int, float)) or isinstance(conf, bool):
            continue
        if label in HARD_LABELS and conf >= hard_conf:
            name = HARD_LABELS[label]
            hard[name] = max(hard.get(name, 0.0), float(conf))
        elif label in LIGHT_LABELS and conf >= light_conf:
            name = LIGHT_LABELS[label]
            light[name] = max(light.get(name, 0.0), float(conf))
    return hard, light


def summarize(
    boxes: Iterable[Dict[str, Any]],
    latency_ms: Optional[float],
    hard_conf: float,
    light_conf: float,
    *,
    escalate_light: bool = True,
    model: str = MODEL_NAME,
    model_sha256: Optional[str] = None,
    runtime: str = RUNTIME,
) -> Dict[str, Any]:
    """The detector result block for a list of ``{label, confidence, box}``.

    ``thresholds`` records the gate settings the block was judged with,
    ``model_sha256`` (when known) the exact weights, and ``runtime`` the
    onnxruntime provider that ran them, for the audit record.
    """
    result: Dict[str, Any] = {
        "model": model,
        "runtime": runtime,
        "latency_ms": None if latency_ms is None else round(float(latency_ms), 1),
        "boxes": list(boxes),
    }
    if model_sha256:
        result["model_sha256"] = model_sha256
    result["thresholds"] = {
        "hard": float(hard_conf),
        "light": float(light_conf),
        "escalate_light": bool(escalate_light),
    }
    hard, light = flagged(result, hard_conf, light_conf)
    result["hard_contaminants"] = sorted(hard)
    result["light_contaminants"] = sorted(light)
    return result


def _decode(photo_bytes: bytes) -> Any:
    """The photo as an upright RGB image, refused before decoding when it is
    over :data:`MAX_PIXELS` (below Pillow's own bomb-warning limit, so the
    header check fires first); Pillow's hard bomb error is refused too."""
    from PIL import Image, ImageOps  # noqa: PLC0415

    try:
        raw = Image.open(io.BytesIO(photo_bytes))
    except Image.DecompressionBombError as exc:
        raise DetectorImageError(f"image refused: {exc}") from exc
    with raw:
        width, height = raw.size
        if width * height > MAX_PIXELS:
            raise DetectorImageError(
                f"image refused: {width}x{height} is over {MAX_PIXELS:,} pixels"
            )
        if raw.format == "JPEG":
            raw.draft("RGB", _DRAFT_SIZE)  # decode at a reduced scale
        # EXIF orientation applied: boxes land on the photo as browsers show it.
        return ImageOps.exif_transpose(raw).convert("RGB")


def warm(settings: Optional[Settings] = None) -> bool:
    """Load the model now (app startup) instead of on the first photo.

    Returns whether the detector is ready; logs once why it is not.
    """
    global _DISABLED_LOGGED
    settings = settings or get_settings()
    if enabled(settings):
        model = _settings_model(settings)
        if model is not None:
            _log.info("detector ready: %s on %s (%s)",
                      settings.detector_model_path, model.provider, model.runtime)
        return model is not None  # a load failure was already logged by _model
    if not _DISABLED_LOGGED:
        _DISABLED_LOGGED = True
        if not settings.detector_model_path:
            why = "no model configured (DETECTOR_MODEL_PATH empty or no bundled file)"
        elif not Path(settings.detector_model_path).is_file():
            why = f"model file not found: {settings.detector_model_path}"
        else:
            why = "onnxruntime, numpy or Pillow is not installed"
        _log.warning("detector disabled: %s", why)
    return False


_DISABLED_LOGGED = False


def detect(
    photo_bytes: bytes,
    settings: Optional[Settings] = None,
    min_conf: Optional[float] = None,
) -> Optional[Dict[str, Any]]:
    """Run the detector on one JPEG/PNG; ``None`` when the stage is disabled.

    ``boxes`` keep every detection at/above ``min_conf`` (default: the lower
    of the two gate thresholds, so the boxes are exactly what the gate can
    act on); ``hard_contaminants`` / ``light_contaminants`` apply the
    configured thresholds.  Raises when the bytes are not a readable image,
    when the image is over :data:`MAX_PIXELS`, or when no run slot frees up
    within 30 s.
    """
    settings = settings or get_settings()
    if not photo_bytes or not enabled(settings):
        return None
    model = _settings_model(settings)
    if model is None:
        return None

    floor = (
        min(settings.detector_hard_conf, settings.detector_light_conf)
        if min_conf is None
        else min_conf
    )
    if not _RUN_SLOTS.acquire(timeout=_SLOT_WAIT_S):
        raise RuntimeError(f"detector busy: no free run slot within {_SLOT_WAIT_S:g} s")
    try:
        started = time.perf_counter()
        boxes = model(_decode(photo_bytes), floor)
        latency_ms = (time.perf_counter() - started) * 1000.0
    finally:
        _RUN_SLOTS.release()
    return summarize(
        boxes,
        latency_ms,
        settings.detector_hard_conf,
        settings.detector_light_conf,
        escalate_light=settings.detector_escalate_light,
        model=model.name,
        model_sha256=model.sha256,
        runtime=model.runtime,
    )
