"""Uvicorn entry point: ``python -m lynceus.main``."""

from __future__ import annotations

import os

import uvicorn

#: Listening port when ``PORT`` is not set.
DEFAULT_PORT = 8020


def main() -> None:
    uvicorn.run(
        "lynceus.api:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT") or DEFAULT_PORT),
        reload=False,
    )


if __name__ == "__main__":
    main()
