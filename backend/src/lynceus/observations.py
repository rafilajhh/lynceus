"""Gate sensor observations: one record shape for every instrument.

Every sensor reading at the gate — computed here, simulated for the demo, or
sent by a site's own gateway — is one :data:`Observation`::

    {"source": "camera:main", "kind": "image_quality", "value": {...},
     "unit": None, "uncertainty": None, "status": "ok|poor|mismatch|not_installed|unavailable",
     "measured_at_utc": "…Z", "sha256": "sha256:…", "simulated": False,
     "note": "One plain sentence.", "frame": 0}

``sha256`` digests what the reading came from (the frame bytes for image
quality, the canonical JSON of the value otherwise).  The decision rules read
them from ``inputs["observations"]``; the audit keeps them under
``inputs.observations``.

Plug-ins (:data:`PLUGINS`, served by ``GET /sensors``):

* ``image_quality`` — installed: computed on the CPU from every load photo
  (sharpness = variance of the 4-neighbour Laplacian on a 1024 px greyscale
  copy, mean brightness, resolution).  ``poor`` when any threshold in
  :data:`IMAGE_QUALITY_THRESHOLDS` is missed.
* ``weighbridge`` — simulated feed (:mod:`lynceus.weighbridge`); a typed
  weight is recorded as ``operator`` input, not as a scale reading.
* ``plate`` — simulated ANPR camera: it reads the plate the truck was
  registered under at the weighbridge (``truck_id``) and compares it with the
  waybill plate.  Demo truck ``B 9406 KXW`` arrives with the waybill of
  ``B 9723 KXW``.
* ``radiation`` and ``nir_analyzer`` — not installed; listed so the plug-in
  point is visible.
"""

from __future__ import annotations

import hashlib
import io
import json
from typing import Any, Dict, List, Optional, Sequence

from lynceus.weighbridge import SCALE_NAME, SIMULATED_NOTE, normalize_plate

#: Closed set of observation states.
STATUSES = ("ok", "poor", "mismatch", "not_installed", "unavailable")

#: An image is ``poor`` below/above any of these (stated in every note).
#: Checked on the bundled demo photos: they score sharpness 780–1885 and
#: brightness 90–181; a 3 px Gaussian blur of them scores 10–17 and a copy
#: at 20 % brightness 18–36 — both fall clearly on the poor side.
IMAGE_QUALITY_THRESHOLDS = {
    "min_sharpness": 60.0,  # Laplacian variance on the 1024 px greyscale copy
    "min_brightness": 40.0,  # mean grey level, 0..255
    "max_brightness": 225.0,
    "min_short_edge_px": 480,
}
#: Long edge of the greyscale copy the sharpness is measured on, so the
#: number does not depend on the camera's resolution.
_QUALITY_EDGE_PX = 1024

#: Truck scale division (kg): the scale's own resolution.
_SCALE_DIVISION_KG = 10.0

PLUGINS: List[Dict[str, Any]] = [
    {
        "kind": "image_quality",
        "name": "Load photo quality",
        "status": "installed",
        "source": "gate camera photos (computed on the CPU)",
        "unit": None,
        "note": (
            "Sharpness (Laplacian variance), brightness and resolution of every "
            "load photo; a poor photo holds the truck for a retake (SOP-RDF-2.1)."
        ),
    },
    {
        "kind": "weighbridge",
        "name": "Weighbridge",
        "status": "simulated",
        "source": SCALE_NAME,
        "unit": "kg",
        "note": (
            "Simulated indicator feed. A site reads the scale indicator over "
            "RS-232 or Modbus-RTU/TCP through an edge gateway that waits for a "
            "stable weight."
        ),
    },
    {
        "kind": "plate",
        "name": "ANPR plate camera",
        "status": "simulated",
        "source": "gate camera (simulated ANPR)",
        "unit": None,
        "note": (
            "Simulated: reads the plate registered at the weighbridge and compares "
            "it with the waybill. A site joins its ANPR read with the stable "
            "weight at the edge gateway."
        ),
    },
    {
        "kind": "radiation",
        "name": "Radiation portal",
        "status": "not_installed",
        "source": None,
        "unit": "uSv/h",
        "note": (
            "Not installed. Plug-in point for a vehicle radiation portal monitor "
            "(IEC 62022), sending one observation per truck."
        ),
    },
    {
        "kind": "nir_analyzer",
        "name": "NIR fuel analyser",
        "status": "not_installed",
        "source": None,
        "unit": None,
        "note": (
            "Not installed. Plug-in point for an online NIR analyser (e.g. ZEISS "
            "SPARC) on the conveyor after acceptance: moisture, NCV and chlorine."
        ),
    },
]

INTEGRATION_NOTE = (
    "Every sensor sends the same observation record (source, kind, value, unit, "
    "uncertainty, status, measured_at_utc, sha256) in the inspection's "
    "'observations' list; the audit record seals them with the verdict. "
    "Indicators speak RS-232 or Modbus-RTU/TCP, radiation portals follow IEC 62022, "
    "and online analysers (NIR, PGNAA) report per batch after acceptance."
)


def _digest_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _digest_value(value: Any) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return _digest_bytes(canonical.encode("utf-8"))


def observation(
    *,
    source: str,
    kind: str,
    value: Any,
    status: str,
    measured_at_utc: str,
    unit: Optional[str] = None,
    uncertainty: Optional[float] = None,
    simulated: bool = False,
    note: Optional[str] = None,
    sha256: Optional[str] = None,
    frame: Optional[int] = None,
) -> Dict[str, Any]:
    """One observation record (the digest defaults to the value's)."""
    if status not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES} (got {status!r})")
    record: Dict[str, Any] = {
        "source": source,
        "kind": kind,
        "value": value,
        "unit": unit,
        "uncertainty": uncertainty,
        "status": status,
        "measured_at_utc": measured_at_utc,
        "sha256": sha256 or _digest_value(value),
        "simulated": simulated,
        "note": note,
    }
    if frame is not None:
        record["frame"] = frame
    return record


# ---------------------------------------------------------------------------
# Plug-ins
# ---------------------------------------------------------------------------


def image_metrics(photo: bytes) -> Dict[str, Any]:
    """``{sharpness, brightness, width_px, height_px}`` of a JPEG/PNG.

    Raises when Pillow/numpy are missing or the bytes are not an image.
    """
    import numpy as np  # noqa: PLC0415 — optional, as for the detector
    from PIL import Image, ImageOps  # noqa: PLC0415

    with Image.open(io.BytesIO(photo), formats=["JPEG", "PNG"]) as raw:
        width, height = raw.size
        if raw.format in ("JPEG", "MPO"):
            raw.draft("L", (_QUALITY_EDGE_PX, _QUALITY_EDGE_PX))
        grey = ImageOps.exif_transpose(raw).convert("L")
    scale = _QUALITY_EDGE_PX / max(grey.size)
    if scale < 1.0:
        grey = grey.resize(
            (max(1, round(grey.size[0] * scale)), max(1, round(grey.size[1] * scale))),
            Image.BILINEAR,
        )
    pixels = np.asarray(grey, dtype=np.float64)
    if pixels.shape[0] < 3 or pixels.shape[1] < 3:
        sharpness = 0.0
    else:
        laplacian = (
            pixels[:-2, 1:-1] + pixels[2:, 1:-1] + pixels[1:-1, :-2] + pixels[1:-1, 2:]
            - 4.0 * pixels[1:-1, 1:-1]
        )
        sharpness = float(laplacian.var())
    return {
        "sharpness": round(sharpness, 1),
        "brightness": round(float(pixels.mean()), 1),
        "width_px": int(width),
        "height_px": int(height),
    }


def image_quality(photo: bytes, frame: int, measured_at_utc: str) -> Dict[str, Any]:
    """The ``image_quality`` observation of one load photo."""
    source = "camera:main" if frame == 0 else f"camera:angle-{frame + 1}"
    t = IMAGE_QUALITY_THRESHOLDS
    try:
        metrics = image_metrics(photo)
    except Exception as exc:  # noqa: BLE001 — an unreadable photo is reported, not raised
        return observation(
            source=source,
            kind="image_quality",
            value=None,
            status="unavailable",
            measured_at_utc=measured_at_utc,
            sha256=_digest_bytes(photo),
            note=f"Photo quality not measured ({type(exc).__name__}).",
            frame=frame,
        )
    problems = []
    if metrics["sharpness"] < t["min_sharpness"]:
        problems.append(f"blurred (sharpness {metrics['sharpness']:g} < {t['min_sharpness']:g})")
    if metrics["brightness"] < t["min_brightness"]:
        problems.append(f"too dark (brightness {metrics['brightness']:g} < {t['min_brightness']:g})")
    if metrics["brightness"] > t["max_brightness"]:
        problems.append(f"overexposed (brightness {metrics['brightness']:g} > {t['max_brightness']:g})")
    short_edge = min(metrics["width_px"], metrics["height_px"])
    if short_edge < t["min_short_edge_px"]:
        problems.append(f"too small ({short_edge} px < {t['min_short_edge_px']} px)")
    note = (
        "Photo is " + "; ".join(problems) + ": retake it."
        if problems
        else (
            f"Sharp enough (≥ {t['min_sharpness']:g}), exposed within "
            f"{t['min_brightness']:g}–{t['max_brightness']:g}, "
            f"at least {t['min_short_edge_px']} px."
        )
    )
    return observation(
        source=source,
        kind="image_quality",
        value=metrics,
        status="poor" if problems else "ok",
        measured_at_utc=measured_at_utc,
        sha256=_digest_bytes(photo),
        note=note,
        frame=frame,
    )


def weighbridge_reading(
    weight_kg: Optional[float], weight_source: Optional[str], measured_at_utc: str
) -> Optional[Dict[str, Any]]:
    """The ``weighbridge`` observation of the weight the verdict used."""
    if weight_kg is None:
        return None
    if weight_source == "manual_entry":
        return observation(
            source="operator",
            kind="weighbridge",
            value=float(weight_kg),
            unit="kg",
            status="ok",
            measured_at_utc=measured_at_utc,
            note="Weight typed by the operator, not read from the scale.",
        )
    simulated = weight_source == "weighbridge_simulated"
    return observation(
        source=f"weighbridge:{SCALE_NAME}" if simulated else "weighbridge",
        kind="weighbridge",
        value=float(weight_kg),
        unit="kg",
        uncertainty=_SCALE_DIVISION_KG,
        status="ok",
        measured_at_utc=measured_at_utc,
        simulated=simulated,
        note=SIMULATED_NOTE if simulated else "Weight from the scale indicator.",
    )


def plate_reading(
    registered_plate: Optional[str], waybill_plate: Optional[str], measured_at_utc: str
) -> Optional[Dict[str, Any]]:
    """The simulated ANPR ``plate`` observation (``None`` without a plate)."""
    read = normalize_plate(registered_plate or waybill_plate)
    if not read:
        return None
    expected = normalize_plate(waybill_plate) if waybill_plate else ""
    mismatch = bool(expected) and read != expected
    if mismatch:
        note = f"Camera reads {read}; the waybill says {expected}: verify the truck."
    elif expected:
        note = f"Camera reads {read}, as on the waybill."
    else:
        note = f"Camera reads {read}; no waybill plate to compare."
    return observation(
        source="anpr:gate (simulated)",
        kind="plate",
        value=read,
        status="mismatch" if mismatch else "ok",
        measured_at_utc=measured_at_utc,
        simulated=True,
        note=note + " Simulated ANPR for the demo.",
    )


def not_installed(measured_at_utc: str) -> List[Dict[str, Any]]:
    """One ``not_installed`` record per plug-in a site has not fitted yet."""
    return [
        observation(
            source=plugin["name"],
            kind=plugin["kind"],
            value=None,
            unit=plugin["unit"],
            status="not_installed",
            measured_at_utc=measured_at_utc,
            note=plugin["note"],
        )
        for plugin in PLUGINS
        if plugin["status"] == "not_installed"
    ]


def collect(
    *,
    supplied: Sequence[Dict[str, Any]],
    frames: Sequence[bytes],
    weight_kg: Optional[float],
    weight_source: Optional[str],
    registered_plate: Optional[str],
    waybill_plate: Optional[str],
    measured_at_utc: str,
) -> List[Dict[str, Any]]:
    """This inspection's observations: what the site sent first, then the
    computed and simulated ones for every kind it did not send."""
    out = [dict(o) for o in supplied]
    sent = {o.get("kind") for o in out}
    if "image_quality" not in sent:
        out += [image_quality(data, i, measured_at_utc) for i, data in enumerate(frames) if data]
    if "weighbridge" not in sent:
        reading = weighbridge_reading(weight_kg, weight_source, measured_at_utc)
        if reading:
            out.append(reading)
    if "plate" not in sent:
        plate = plate_reading(registered_plate, waybill_plate, measured_at_utc)
        if plate:
            out.append(plate)
    out += [o for o in not_installed(measured_at_utc) if o["kind"] not in sent]
    return out


def supplied_record(raw: Dict[str, Any], measured_at_utc: str) -> Dict[str, Any]:
    """A site-sent observation in record form (its digest computed here)."""
    return observation(
        source=str(raw["source"]),
        kind=str(raw["kind"]),
        value=raw.get("value"),
        unit=raw.get("unit"),
        uncertainty=raw.get("uncertainty"),
        status=raw.get("status") or "ok",
        measured_at_utc=raw.get("measured_at_utc") or measured_at_utc,
        simulated=bool(raw.get("simulated", False)),
        note=raw.get("note"),
    )


def sensors() -> Dict[str, Any]:
    """``GET /sensors``: the plug-ins and how a site connects its own."""
    return {
        "sensors": [dict(p) for p in PLUGINS],
        "image_quality_thresholds": dict(IMAGE_QUALITY_THRESHOLDS),
        "integration_note": INTEGRATION_NOTE,
    }
