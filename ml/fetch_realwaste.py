"""Download the RealWaste zip from UCI into ml/data/zip/ (never extracted or executed).

    python -I ml/fetch_realwaste.py
"""

from __future__ import annotations

import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _env  # noqa: E402

URL = "https://archive.ics.uci.edu/static/public/908/realwaste.zip"
OUT = _env.DATA / "zip" / "realwaste.zip"


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    if not OUT.exists():
        part = OUT.with_suffix(".part")
        print(f"downloading {URL}", flush=True)
        with urllib.request.urlopen(URL, timeout=60) as resp, part.open("wb") as fh:
            shutil.copyfileobj(resp, fh, length=1 << 20)
        part.replace(OUT)
    with zipfile.ZipFile(OUT) as zf:
        names = zf.namelist()
    print(f"{OUT} {OUT.stat().st_size / 1e6:.1f} MB, {len(names)} entries")
    for n in names[:15]:
        print(" ", n)


if __name__ == "__main__":
    main()
