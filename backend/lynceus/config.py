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
#: Optional bearer key for the vLLM endpoints (empty = no auth header).
VLLM_API_KEY_ENV = "VLLM_API_KEY"
#: AI provider selector; "vllm" and "openai-compatible" share the same logic.
LYNCEUS_AI_PROVIDER_ENV = "LYNCEUS_AI_PROVIDER"
#: Directory where run artefacts are persisted.
LYNCEUS_STORAGE_DIR_ENV = "LYNCEUS_STORAGE_DIR"
#: Version tag stamped onto audit records.
AUDIT_FORMAT_VERSION_ENV = "AUDIT_FORMAT_VERSION"

_DEFAULT_VLLM_VLM_URL = "http://localhost:8000/v1"
_DEFAULT_VLLM_LLM_URL = "http://localhost:8001/v1"
_DEFAULT_VLM_MODEL = "Qwen/Qwen2.5-VL-7B-Instruct"
_DEFAULT_LLM_MODEL = "Qwen/Qwen2.5-7B-Instruct"
_DEFAULT_STORAGE_DIR = "./runs"
_DEFAULT_VLLM_API_KEY = ""
_DEFAULT_AI_PROVIDER = "vllm"
_DEFAULT_AUDIT_FORMAT_VERSION = 1

@dataclass(frozen=True)
class Settings:
    """A snapshot of the environment-driven configuration."""

    vllm_vlm_url: str
    vllm_llm_url: str
    vlm_model: str
    llm_model: str
    vllm_api_key: str
    ai_provider: str
    storage_dir: str
    audit_format_version: int
    version: str

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

    return Settings(
        vllm_vlm_url=os.environ.get(VLLM_VLM_URL_ENV, _DEFAULT_VLLM_VLM_URL),
        vllm_llm_url=os.environ.get(VLLM_LLM_URL_ENV, _DEFAULT_VLLM_LLM_URL),
        vlm_model=os.environ.get(VLM_MODEL_ENV, _DEFAULT_VLM_MODEL),
        llm_model=os.environ.get(LLM_MODEL_ENV, _DEFAULT_LLM_MODEL),
        storage_dir=os.environ.get(LYNCEUS_STORAGE_DIR_ENV, _DEFAULT_STORAGE_DIR),
        vllm_api_key=os.environ.get(VLLM_API_KEY_ENV, _DEFAULT_VLLM_API_KEY),
        ai_provider=os.environ.get(LYNCEUS_AI_PROVIDER_ENV, _DEFAULT_AI_PROVIDER),
        audit_format_version=audit_format_version,
        version=__version__,
    )
