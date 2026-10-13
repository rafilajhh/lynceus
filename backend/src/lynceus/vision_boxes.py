"""Contaminant localisation: strict validation of VLM-proposed regions.

The VLM returns a ``locations`` list (boxes and/or coarse zones) that the
console draws on the truck-load photo.  Model output is untrusted, so
anything malformed is *dropped*, never repaired or clamped: a box that
points at the wrong place is worse than no box.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

__all__ = ["ZONES", "parse_locations"]

#: Third-grid cells, ``(x0, y0, x1, y1)`` normalised from the top-left.
ZONES: Dict[str, Tuple[float, float, float, float]] = {
    name: (cx / 3, cy / 3, (cx + 1) / 3, (cy + 1) / 3)
    for name, cx, cy in (
        ("top-left", 0, 0),
        ("top", 1, 0),
        ("top-right", 2, 0),
        ("left", 0, 1),
        ("center", 1, 1),
        ("right", 2, 1),
        ("bottom-left", 0, 2),
        ("bottom", 1, 2),
        ("bottom-right", 2, 2),
    )
}


def _number(value: Any) -> Optional[float]:
    """A finite real number (bools and strings are not coordinates)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except OverflowError:  # int literal beyond float range
        return None
    return number if math.isfinite(number) else None


#: Returned by :func:`_valid_box` for a well-formed but oversize (full-frame)
#: box: the whole entry is dropped, with no zone fallback.
_OVERSIZE = object()


def _valid_box(box: Any, min_area: float, max_area: float) -> Any:
    """``(x0,y0,x1,y1)``, ``None`` when unusable (try zone), or ``_OVERSIZE``."""
    if not isinstance(box, (list, tuple)) or len(box) != 4:
        return None
    nums = [_number(v) for v in box]
    if any(n is None for n in nums):
        return None
    x0, y0, x1, y1 = nums  # type: ignore[misc]
    if not (0.0 <= x0 < x1 <= 1.0 and 0.0 <= y0 < y1 <= 1.0):
        return None
    area = (x1 - x0) * (y1 - y0)
    if area > max_area:
        return _OVERSIZE
    if area < min_area:
        return None
    return x0, y0, x1, y1


def parse_locations(
    raw: Any,
    mode: str,
    max_boxes: int = 8,
    min_area: float = 0.0025,
    max_area: float = 0.9,
) -> List[Dict[str, Any]]:
    """Validate a VLM ``locations`` value into ``{label,x0,y0,x1,y1}`` dicts.

    * ``mode == "zone"``: only each entry's ``zone`` (mapped via
      :data:`ZONES`) is used.  Any other mode is ``"box"``: the entry's
      ``box`` is used, falling back to its ``zone`` when the box is missing
      or malformed (an oversize box drops the entry, no fallback).
    * Dropped: non-list input, non-dict entries, non-string or blank labels
      (kept labels are stripped and lowercased), boxes that are not four
      finite numbers with ``0 <= x0 < x1 <= 1`` and ``0 <= y0 < y1 <= 1``,
      boxes with area below ``min_area`` (specks) or above ``max_area``
      (full-frame boxes -- MiniCPM-V-4.7 returned ``[0,0,1,1]`` on a clean
      load in 3/3 probe runs, which says nothing about *where*).
    * At most ``max_boxes`` entries are kept, in model order.
    """
    if not isinstance(raw, list):
        return []
    use_box = mode != "zone"
    out: List[Dict[str, Any]] = []
    for entry in raw:
        if len(out) >= max_boxes:
            break
        if not isinstance(entry, dict):
            continue
        label = entry.get("label")
        if not isinstance(label, str) or not label.strip():
            continue
        coords = _valid_box(entry.get("box"), min_area, max_area) if use_box else None
        if coords is _OVERSIZE:
            # A full-frame box says nothing about *where*; a zone on the same
            # entry would re-introduce the false outline, so drop the entry.
            continue
        if coords is None:
            zone = entry.get("zone")
            if isinstance(zone, str) and zone in ZONES:
                coords = ZONES[zone]
        if coords is None:
            continue
        x0, y0, x1, y1 = coords
        out.append(
            {"label": label.strip().lower(), "x0": x0, "y0": y0, "x1": x1, "y1": y1}
        )
    return out
