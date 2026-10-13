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
#: Optional bearer key for the vLLM endpoints (empty = no auth header).
VLLM_API_KEY_ENV = "VLLM_API_KEY"
#: Endpoint / model for the Pythia assistant role (default: the LLM's).
ASSIST_URL_ENV = "ASSIST_URL"
ASSIST_MODEL_ENV = "ASSIST_MODEL"
#: Hazard localisation style: "box" (normalised boxes) or "zone" (text zone).
LOCALISATION_MODE_ENV = "LOCALISATION_MODE"
#: When false, a live-AI failure returns HTTP 503 instead of a stub fallback.
LYNCEUS_ALLOW_STUB_FALLBACK_ENV = "LYNCEUS_ALLOW_STUB_FALLBACK"
#: Directory where run artefacts are persisted.
LYNCEUS_STORAGE_DIR_ENV = "LYNCEUS_STORAGE_DIR"
#: Version tag stamped onto audit records.
AUDIT_FORMAT_VERSION_ENV = "AUDIT_FORMAT_VERSION"

_DEFAULT_VLLM_VLM_URL = "http://localhost:8000/v1"
_DEFAULT_VLLM_LLM_URL = "http://localhost:8001/v1"
_DEFAULT_VLM_MODEL = "Qwen/Qwen2.5-VL-7B-Instruct"
_DEFAULT_LLM_MODEL = "Qwen/Qwen2.5-7B-Instruct"
_DEFAULT_LOCALISATION_MODE = "box"
_DEFAULT_STORAGE_DIR = "./runs"
_DEFAULT_VLLM_API_KEY = ""
_DEFAULT_ALLOW_STUB_FALLBACK = True
_DEFAULT_AUDIT_FORMAT_VERSION = 1

@dataclass(frozen=True)
class Settings:
    """A snapshot of the environment-driven configuration."""

    vllm_vlm_url: str
    vllm_llm_url: str
    vlm_model: str
    llm_model: str
    assist_url: str
    assist_model: str
    localisation_mode: str
    vllm_api_key: str
    allow_stub_fallback: bool
    storage_dir: str
    audit_format_version: int
    version: str

def provider_for_url(url: str) -> str:
    """Name the provider behind an endpoint URL, for audit provenance.

    ``"amd-token-factory"`` when the host is ``amd.com`` / ``amd.com.cn`` (or a
    subdomain of either); anything else is a generic ``"openai-compatible"``
    server (e.g. self-hosted vLLM).
    """
    host = (urlparse(url).hostname or "").lower()
    for domain in ("amd.com.cn", "amd.com"):
        if host == domain or host.endswith("." + domain):
            return "amd-token-factory"
    return "openai-compatible"


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
    llm_model = os.environ.get(LLM_MODEL_ENV, _DEFAULT_LLM_MODEL)
    localisation_mode = (
        os.environ.get(LOCALISATION_MODE_ENV, _DEFAULT_LOCALISATION_MODE)
        .strip()
        .lower()
    )
    if localisation_mode not in ("box", "zone"):
        localisation_mode = _DEFAULT_LOCALISATION_MODE

    return Settings(
        vllm_vlm_url=os.environ.get(VLLM_VLM_URL_ENV, _DEFAULT_VLLM_VLM_URL),
        vllm_llm_url=vllm_llm_url,
        vlm_model=os.environ.get(VLM_MODEL_ENV, _DEFAULT_VLM_MODEL),
        llm_model=llm_model,
        assist_url=os.environ.get(ASSIST_URL_ENV) or vllm_llm_url,
        assist_model=os.environ.get(ASSIST_MODEL_ENV) or llm_model,
        localisation_mode=localisation_mode,
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
    )
