"""Live smoke tests against a real OpenAI-compatible endpoint.

These tests NEVER run by default.  They only execute when:

* the environment flag ``LYNCEUS_LIVE_TESTS=1`` is set, AND
* the configured vLLM endpoint is actually reachable (5s probe).

Run them explicitly against a live/testing endpoint::

    LYNCEUS_LIVE_TESTS=1 \\
    VLLM_VLM_URL=https://your-endpoint.example/v1 \\
    VLLM_LLM_URL=https://your-endpoint.example/v1 \\
    VLM_MODEL=your-model LLM_MODEL=your-model \\
    [VLLM_API_KEY=your-key] \\
    pytest backend/tests/test_live_smoke.py -m live
"""

from __future__ import annotations

import base64
import json
import os
import struct
import zlib

import httpx
import pytest

from lynceus.config import get_settings

pytestmark = pytest.mark.live

_LIVE_FLAG = "LYNCEUS_LIVE_TESTS"


def _endpoint_reachable(url: str, api_key: str) -> bool:
    """5-second liveness probe of the endpoint (``GET /models``)."""
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    try:
        response = httpx.get(
            f"{url.rstrip('/')}/models", headers=headers, timeout=5.0
        )
        return response.status_code < 500
    except httpx.HTTPError:
        return False


pytest.importorskip(
    "httpx",
    reason="httpx is required for live smoke tests",
)

if os.environ.get(_LIVE_FLAG) != "1":
    pytest.skip(
        f"live tests disabled: set {_LIVE_FLAG}=1 to enable",
        allow_module_level=True,
    )

_SETTINGS = get_settings()

if not _endpoint_reachable(_SETTINGS.vllm_vlm_url, _SETTINGS.vllm_api_key):
    pytest.skip(
        f"vLLM endpoint unreachable: {_SETTINGS.vllm_vlm_url}",
        allow_module_level=True,
    )


def _png_1x1_base64() -> str:
    """Build a 1x1 white PNG entirely in-memory (struct + zlib, no files)."""
    width = height = 1
    # IHDR: width, height, bit depth 8, colour type 2 (truecolour RGB).
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    # One scanline: filter byte 0 + one RGB pixel (white).
    raw_scanline = b"\x00" + b"\xff\xff\xff"

    def _chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    png = (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"IDAT", zlib.compress(raw_scanline))
        + _chunk(b"IEND", b"")
    )
    return base64.b64encode(png).decode("ascii")


def _chat(client_url: str, model: str, messages: list) -> str:
    """Direct chat-completions call with SSE-aware reading."""
    settings = get_settings()
    headers = (
        {"Authorization": f"Bearer {settings.vllm_api_key}"}
        if settings.vllm_api_key
        else {}
    )
    with httpx.stream(
        "POST",
        f"{client_url.rstrip('/')}/chat/completions",
        json={"model": model, "messages": messages, "max_tokens": 512},
        headers=headers,
        timeout=90.0,
    ) as response:
        response.raise_for_status()
        content_type = response.headers.get("content-type", "")
        if "text/event-stream" in content_type:
            parts = []
            for line in response.iter_lines():
                line = line.strip()
                if not line.startswith("data:"):
                    continue
                data = line[len("data:") :].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                    delta = chunk["choices"][0]["delta"].get("content")
                    if delta:
                        parts.append(delta)
                except (
                    json.JSONDecodeError,
                    KeyError,
                    IndexError,
                    TypeError,
                    AttributeError,
                ):
                    continue
            return "".join(parts)
        payload = json.loads(response.read().decode("utf-8"))
        return str(payload["choices"][0]["message"]["content"])


def test_live_chat_ping_pong() -> None:
    """Plain text completion: ask for PONG and get it back."""
    settings = get_settings()
    reply = _chat(
        settings.vllm_llm_url,
        settings.llm_model,
        [{"role": "user", "content": "Reply PONG"}],
    )
    assert "PONG" in reply.upper()


def test_live_vision_png_1x1() -> None:
    """Vision round trip: model must accept a base64 1x1 PNG data URI."""
    settings = get_settings()
    data_uri = f"data:image/png;base64,{_png_1x1_base64()}"
    reply = _chat(
        settings.vllm_vlm_url,
        settings.vlm_model,
        [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "Describe this image in one short sentence.",
                    },
                    {"type": "image_url", "image_url": {"url": data_uri}},
                ],
            }
        ],
    )
    assert len(reply.strip()) > 0
