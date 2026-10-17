"""Environment-driven configuration for the Lynceus backend.

Every knob comes from an environment variable so the service can be pointed at
a different vLLM deployment, model, or storage location without a code change.
Reads are cheap (``os.environ`` lookups), so Settings is fetched per-request
via :func:`get_settings`; nothing heavy happens at module import time.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Tuple
from urllib.parse import urlparse

from lynceus import __version__


def _load_dotenv(path: str = ".env") -> None:
    """Load ``KEY=VALUE`` lines from ``path`` into ``os.environ`` (no overwrite).

    A dependency-free ``.env`` loader so the backend can be pointed at a
    different AI endpoint without exporting shell variables first. Missing
    file, blank lines, and ``#`` comments are skipped; values may be quoted.
    Real environment variables always win over the file.
    """
    env_file = Path(path)
    if not env_file.is_file():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv()

#: vLLM OpenAI-compatible endpoint for the vision-language model.
VLLM_VLM_URL_ENV = "VLLM_VLM_URL"
#: vLLM OpenAI-compatible endpoint for the text-only LLM.
VLLM_LLM_URL_ENV = "VLLM_LLM_URL"
#: Model names served by the two vLLM instances.
VLM_MODEL_ENV = "VLM_MODEL"
LLM_MODEL_ENV = "LLM_MODEL"
#: Comma-separated vision models tried in order on the VLM endpoint when
#: ``VLM_MODEL`` fails with an HTTP error status or an unparseable reply
#: (an unreachable endpoint or a spent budget ends the chain). Empty = none.
VLM_FALLBACK_MODELS_ENV = "VLM_FALLBACK_MODELS"
#: Comma-separated vision models with a benchmark run behind them.  A
#: fallback model outside this list may hold a load, never accept or reject it.
VLM_BENCHMARKED_MODELS_ENV = "VLM_BENCHMARKED_MODELS"
#: VLM reads per inspection, merged by majority vote (1..3; malformed = 3).
VLM_VOTES_ENV = "VLM_VOTES"
#: Optional bearer key for the vLLM endpoints (empty = no auth header).
VLLM_API_KEY_ENV = "VLLM_API_KEY"
#: Endpoint / model for the Pythia assistant role (default: the LLM's).
ASSIST_URL_ENV = "ASSIST_URL"
ASSIST_MODEL_ENV = "ASSIST_MODEL"
#: Endpoint / model for shift-report supplier explanations (default: assist's).
EXPLAIN_URL_ENV = "EXPLAIN_URL"
EXPLAIN_MODEL_ENV = "EXPLAIN_MODEL"
#: Hazard localisation style: "box" (normalised boxes) or "zone" (text zone).
LOCALISATION_MODE_ENV = "LOCALISATION_MODE"
#: When false, a live-AI failure returns HTTP 503 instead of a stub fallback.
LYNCEUS_ALLOW_STUB_FALLBACK_ENV = "LYNCEUS_ALLOW_STUB_FALLBACK"
#: Directory where run artefacts are persisted.
LYNCEUS_STORAGE_DIR_ENV = "LYNCEUS_STORAGE_DIR"
#: Version tag stamped onto audit records.
AUDIT_FORMAT_VERSION_ENV = "AUDIT_FORMAT_VERSION"
#: ONNX file of the CPU detector second opinion (set but empty = detector off).
DETECTOR_MODEL_PATH_ENV = "DETECTOR_MODEL_PATH"
#: Detector confidence at/above which a hard (metal) box holds the truck.
DETECTOR_HARD_CONF_ENV = "DETECTOR_HARD_CONF"
#: Detector confidence at/above which a light (glass/organic) box counts.
DETECTOR_LIGHT_CONF_ENV = "DETECTOR_LIGHT_CONF"
#: When false, light detector findings the VLM did not confirm never escalate.
DETECTOR_ESCALATE_LIGHT_ENV = "DETECTOR_ESCALATE_LIGHT"
#: onnxruntime intra-op threads per detector run (positive integer).
DETECTOR_THREADS_ENV = "DETECTOR_THREADS"
#: onnxruntime execution providers for the detector, comma-separated. The
#: detector runs on the CPU: the only valid provider is CPUExecutionProvider.
DETECTOR_PROVIDERS_ENV = "DETECTOR_PROVIDERS"
#: Optional https webhook that receives supplier notices (empty = logged only).
SUPPLIER_NOTIFY_WEBHOOK_ENV = "SUPPLIER_NOTIFY_WEBHOOK"

_DEFAULT_VLLM_VLM_URL = "http://localhost:8000/v1"
_DEFAULT_VLLM_LLM_URL = "http://localhost:8001/v1"
_DEFAULT_VLM_MODEL = "Qwen/Qwen2.5-VL-7B-Instruct"
_DEFAULT_LLM_MODEL = "Qwen/Qwen2.5-7B-Instruct"
_DEFAULT_LOCALISATION_MODE = "box"
_DEFAULT_STORAGE_DIR = "./runs"
_DEFAULT_VLLM_API_KEY = ""
_DEFAULT_ALLOW_STUB_FALLBACK = True
_DEFAULT_AUDIT_FORMAT_VERSION = 1
#: The detector bundled with a source checkout (backend/models/).  A
#: site-packages install cannot see it; the container sets
#: ``DETECTOR_MODEL_PATH`` instead.
BUNDLED_DETECTOR_MODEL = (
    Path(__file__).resolve().parents[2] / "models" / "lynceus-yolo26m-realwaste-taco.onnx"
)
#: The detector defaults (decision.py uses these too).  Picked on the val split
#: (RealWaste val + TACO val: not trained on, but used for checkpoint selection)
#: by the rule in ml/eval_val.py: the lowest threshold whose false-metal rate is
#: <= 2% (RealWaste) and <= 5% (TACO); light likewise with false escalations on
#: clean images <= 5% / 10%.  ml/results/val_yolo26m_e26l.json.
DEFAULT_DETECTOR_HARD_CONF = 0.35
DEFAULT_DETECTOR_LIGHT_CONF = 0.05
_DEFAULT_DETECTOR_THREADS = 2
_DEFAULT_DETECTOR_PROVIDERS: Tuple[str, ...] = ("CPUExecutionProvider",)
#: VLM reads per inspection, merged by majority vote (pipeline._vote_majority).
_DEFAULT_VLM_VOTES = 3
#: The reads run concurrently on pipeline._VLM_READ_SLOTS (3), which leaves
#: one of the four outbound slots for the waybill / assist calls.
_MAX_VLM_VOTES = 3
#: The vision model of the committed live benchmark run (2026-10-13).
_DEFAULT_VLM_BENCHMARKED_MODELS: Tuple[str, ...] = ("MiniCPM-V-4.7-35B-A3B",)

@dataclass(frozen=True)
class Settings:
    """A snapshot of the environment-driven configuration."""

    vllm_vlm_url: str
    vllm_llm_url: str
    vlm_model: str
    llm_model: str
    assist_url: str
    assist_model: str
    explain_url: str
    explain_model: str
    localisation_mode: str
    vllm_api_key: str
    allow_stub_fallback: bool
    storage_dir: str
    audit_format_version: int
    version: str
    vlm_fallback_models: Tuple[str, ...] = ()
    detector_model_path: str = ""
    detector_hard_conf: float = DEFAULT_DETECTOR_HARD_CONF
    detector_light_conf: float = DEFAULT_DETECTOR_LIGHT_CONF
    detector_escalate_light: bool = True
    vlm_benchmarked_models: Tuple[str, ...] = _DEFAULT_VLM_BENCHMARKED_MODELS
    detector_threads: int = _DEFAULT_DETECTOR_THREADS
    detector_providers: Tuple[str, ...] = _DEFAULT_DETECTOR_PROVIDERS
    vlm_votes: int = _DEFAULT_VLM_VOTES
    supplier_notify_webhook: str = ""

def provider_for_url(url: str) -> str:
    """Name the provider behind an endpoint URL, for audit provenance.

    ``"amd-token-factory"`` when the host is ``amd.com`` / ``amd.com.cn`` (or a
    subdomain of either); anything else is a generic ``"openai-compatible"``
    server.
    """
    host = (urlparse(url).hostname or "").lower()
    for domain in ("amd.com.cn", "amd.com"):
        if host == domain or host.endswith("." + domain):
            return "amd-token-factory"
    return "openai-compatible"


def _env_conf(name: str, default: float) -> float:
    """A 0..1 confidence threshold from ``name``; malformed values keep ``default``."""
    try:
        value = float(os.environ.get(name, default))
    except ValueError:
        return default
    return value if 0.0 <= value <= 1.0 else default


def _env_models(name: str) -> Tuple[str, ...]:
    """Comma-separated model names from ``name``: stripped, de-duplicated, in order."""
    return tuple(
        m for m in dict.fromkeys(p.strip() for p in os.environ.get(name, "").split(",")) if m
    )


def _env_votes() -> int:
    """``VLM_VOTES`` clamped to 1.._MAX_VLM_VOTES; malformed values keep the default."""
    try:
        value = int(os.environ.get(VLM_VOTES_ENV, _DEFAULT_VLM_VOTES))
    except ValueError:
        return _DEFAULT_VLM_VOTES
    return min(max(value, 1), _MAX_VLM_VOTES)


def _env_threads() -> int:
    """``DETECTOR_THREADS`` as a positive int; malformed values keep the default."""
    try:
        value = int(os.environ.get(DETECTOR_THREADS_ENV, _DEFAULT_DETECTOR_THREADS))
    except ValueError:
        return _DEFAULT_DETECTOR_THREADS
    return value if value >= 1 else _DEFAULT_DETECTOR_THREADS


def _env_providers() -> Tuple[str, ...]:
    """``DETECTOR_PROVIDERS``; unset, empty or anything else = CPU only."""
    return _env_models(DETECTOR_PROVIDERS_ENV) or _DEFAULT_DETECTOR_PROVIDERS


def _detector_model_path() -> str:
    """``DETECTOR_MODEL_PATH`` when set (empty disables the detector), else
    the bundled model when the file exists, else ``""`` (detector off)."""
    if DETECTOR_MODEL_PATH_ENV in os.environ:
        return os.environ[DETECTOR_MODEL_PATH_ENV].strip()
    return str(BUNDLED_DETECTOR_MODEL) if BUNDLED_DETECTOR_MODEL.is_file() else ""


def get_settings() -> Settings:
    """Build a :class:`Settings` from the current environment.

    Kept as a function (not a module-level singleton) so tests can flip
    environment variables and immediately see the effect, and so importing
    this module never performs work beyond defining names.
    """
    raw_audit_version = os.environ.get(
        AUDIT_FORMAT_VERSION_ENV, str(_DEFAULT_AUDIT_FORMAT_VERSION)
    )
    try:
        audit_format_version = int(raw_audit_version)
    except ValueError:
        audit_format_version = _DEFAULT_AUDIT_FORMAT_VERSION

    vllm_llm_url = os.environ.get(VLLM_LLM_URL_ENV, _DEFAULT_VLLM_LLM_URL)
    vlm_model = os.environ.get(VLM_MODEL_ENV, _DEFAULT_VLM_MODEL)
    llm_model = os.environ.get(LLM_MODEL_ENV, _DEFAULT_LLM_MODEL)
    localisation_mode = (
        os.environ.get(LOCALISATION_MODE_ENV, _DEFAULT_LOCALISATION_MODE)
        .strip()
        .lower()
    )
    if localisation_mode not in ("box", "zone"):
        localisation_mode = _DEFAULT_LOCALISATION_MODE

    assist_url = os.environ.get(ASSIST_URL_ENV) or vllm_llm_url
    assist_model = os.environ.get(ASSIST_MODEL_ENV) or llm_model

    return Settings(
        vllm_vlm_url=os.environ.get(VLLM_VLM_URL_ENV, _DEFAULT_VLLM_VLM_URL),
        vllm_llm_url=vllm_llm_url,
        vlm_model=vlm_model,
        vlm_fallback_models=tuple(
            m for m in _env_models(VLM_FALLBACK_MODELS_ENV) if m != vlm_model
        ),
        # Set but empty = no model is benchmarked: no fallback answer decides.
        vlm_benchmarked_models=_env_models(VLM_BENCHMARKED_MODELS_ENV)
        if VLM_BENCHMARKED_MODELS_ENV in os.environ
        else _DEFAULT_VLM_BENCHMARKED_MODELS,
        llm_model=llm_model,
        assist_url=assist_url,
        assist_model=assist_model,
        explain_url=os.environ.get(EXPLAIN_URL_ENV) or assist_url,
        explain_model=os.environ.get(EXPLAIN_MODEL_ENV) or assist_model,
        localisation_mode=localisation_mode,
        vlm_votes=_env_votes(),
        storage_dir=os.environ.get(LYNCEUS_STORAGE_DIR_ENV, _DEFAULT_STORAGE_DIR),
        vllm_api_key=os.environ.get(VLLM_API_KEY_ENV, _DEFAULT_VLLM_API_KEY),
        allow_stub_fallback=os.environ.get(
            LYNCEUS_ALLOW_STUB_FALLBACK_ENV, ""
        ).strip().lower()
        not in ("0", "false", "no")
        if LYNCEUS_ALLOW_STUB_FALLBACK_ENV in os.environ
        else _DEFAULT_ALLOW_STUB_FALLBACK,
        audit_format_version=audit_format_version,
        version=__version__,
        detector_model_path=_detector_model_path(),
        detector_hard_conf=_env_conf(DETECTOR_HARD_CONF_ENV, DEFAULT_DETECTOR_HARD_CONF),
        detector_light_conf=_env_conf(DETECTOR_LIGHT_CONF_ENV, DEFAULT_DETECTOR_LIGHT_CONF),
        detector_escalate_light=os.environ.get(DETECTOR_ESCALATE_LIGHT_ENV, "1")
        .strip()
        .lower()
        not in ("0", "false", "no"),
        detector_threads=_env_threads(),
        detector_providers=_env_providers(),
        supplier_notify_webhook=os.environ.get(SUPPLIER_NOTIFY_WEBHOOK_ENV, "").strip(),
    )
