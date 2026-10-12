"""Environment-driven configuration for the Lynceus backend.

Every knob comes from an environment variable so the service can be pointed at
a different vLLM deployment, model, or storage location without a code change.
Reads are cheap (``os.environ`` lookups), so Settings is fetched per-request
via :func:`get_settings`; nothing heavy happens at module import time.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from lynceus import __version__

#: vLLM OpenAI-compatible endpoint for the vision-language model.
VLLM_VLM_URL_ENV = "VLLM_VLM_URL"
#: vLLM OpenAI-compatible endpoint for the text-only LLM.
VLLM_LLM_URL_ENV = "VLLM_LLM_URL"
#: Model names served by the two vLLM instances.
VLM_MODEL_ENV = "VLM_MODEL"
LLM_MODEL_ENV = "LLM_MODEL"
#: Directory where run artefacts are persisted.
LYNCEUS_STORAGE_DIR_ENV = "LYNCEUS_STORAGE_DIR"
#: Version tag stamped onto audit records.
AUDIT_FORMAT_VERSION_ENV = "AUDIT_FORMAT_VERSION"

_DEFAULT_VLLM_VLM_URL = "http://localhost:8000/v1"
_DEFAULT_VLLM_LLM_URL = "http://localhost:8001/v1"
_DEFAULT_VLM_MODEL = "Qwen/Qwen2.5-VL-7B-Instruct"
_DEFAULT_LLM_MODEL = "Qwen/Qwen2.5-7B-Instruct"
_DEFAULT_STORAGE_DIR = "./runs"
_DEFAULT_AUDIT_FORMAT_VERSION = 1


@dataclass(frozen=True)
class Settings:
    """A snapshot of the environment-driven configuration."""

    vllm_vlm_url: str
    vllm_llm_url: str
    vlm_model: str
    llm_model: str
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
        audit_format_version=audit_format_version,
        version=__version__,
    )
