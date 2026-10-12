"""Uvicorn entry point: ``python -m lynceus.main``."""

from __future__ import annotations

import uvicorn


def main() -> None:
    uvicorn.run(
        "lynceus.api:app",
        host="0.0.0.0",
        port=8020,
        reload=False,
    )


if __name__ == "__main__":
    main()
