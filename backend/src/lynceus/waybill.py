"""Waybill (surat jalan) reading for the RDF reception gate.

The gate operator photographs the supplier's waybill at the weighbridge; one
read by the vision model chain turns it into typed fields with a confidence
each.  The operator confirms or edits them, and ``/inspect`` then compares
what was **declared** with what is **seen** and **weighed**.

* :func:`read` — one live JSON read (``VLM_MODEL`` then its fallbacks, one
  45 s budget, at most :data:`MAX_CONCURRENT_READS` reads at once and no
  vision read slot, so a waybill never queues behind an inspection).
* :func:`normalize_fields` — the model's reply as ``{field: {value,
  confidence}}``; Indonesian numbers ("32.580" = 32580, "28,5" = 28.5) and
  dates ("14/05/2025" = "2025-05-14") are parsed here, not by the model.
* :func:`derive` — the waste stream the waybill implies, whether it declares
  processed RDF, and the gross − tare = net arithmetic.
* :func:`transcript` — a deterministic text of the fields; it becomes the
  inspection's ``manifest_text`` (and its audit digest).

Offline, only the bundled sample waybill (``web/public/demo/waybill-1.jpg``,
fictitious) is "read": its sha256 selects the scripted fields, stated as
``provenance: "stub"`` with a warning.  Any other photo gets
:class:`WaybillReaderOffline` (HTTP 503: the operator types the fields).
"""

from __future__ import annotations

import base64
import copy
import hashlib
import re
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from lynceus import pipeline
from lynceus.config import Settings, provider_for_url
from lynceus.weighbridge import normalize_plate

#: Fields in reading order (also the transcript order).
FIELD_NAMES: Tuple[str, ...] = (
    "document_no",
    "plate",
    "date",
    "origin",
    "destination",
    "carrier",
    "shipper",
    "driver",
    "reference_no",
    "gross_kg",
    "tare_kg",
    "net_kg",
    "load_type",
    "moisture_pct",
    "remarks",
)
_KG_FIELDS = ("gross_kg", "tare_kg", "net_kg")
#: Fields the inspection cannot do without: missing ones count as 0 in the
#: overall read confidence instead of being left out of the mean.
CORE_FIELDS = ("plate", "carrier", "net_kg", "load_type")
#: Live waybill reads in flight process-wide (they never take a live
#: inspection slot or a vision read slot).
MAX_CONCURRENT_READS = 2
_READ_SLOTS = threading.BoundedSemaphore(MAX_CONCURRENT_READS)
#: How long a read waits for a free slot before the caller gets "busy".
_SLOT_WAIT_S = 10.0
#: Arithmetic tolerance: |gross − tare − net| within 1 % of net.
ARITHMETIC_TOLERANCE = 0.01

STUB_MODEL = "stub-waybill-reader"
STUB_WARNING = "Offline reader: fields of the bundled sample waybill"

PROMPT = (
    "You read an Indonesian truck waybill (surat jalan) photographed at the "
    "weighbridge of a refuse-derived fuel (RDF) reception gate. Reply with ONLY "
    "a JSON object, no prose, no code fences. For every key give an object "
    '{"value": ..., "confidence": number 0..1}; use {"value": null, '
    '"confidence": 0} when the field is absent or illegible. Keys: '
    '"document_no" (the waybill number, e.g. No. / No. SJ), '
    '"plate" (vehicle plate / No. Polisi, e.g. "B 1234 ABC"), '
    '"date" (the date as printed), '
    '"origin" (Asal / loading site), '
    '"destination" (Tujuan), '
    '"carrier" (the transport company / Perusahaan / Ekspedisi), '
    '"shipper" (Pengirim / consignor), '
    '"driver" (Nama Sopir / Pengemudi), '
    '"reference_no" (DO / reference number), '
    '"gross_kg" (Bruto in kg), "tare_kg" (Tara in kg), "net_kg" (Netto in kg), '
    '"load_type" (Jenis Muatan / type of load, as printed), '
    '"moisture_pct" (Kadar Air in percent), '
    '"remarks" (Keterangan / remarks, verbatim). '
    "Copy text exactly as printed; give numbers as the printed digits "
    "(keep the thousands separators as printed). Never read phone numbers, "
    "signatures or stamps. Do not guess: an unreadable field is null with "
    "confidence 0."
)

#: The bundled sample waybill (fictitious; see web/public/demo/README.md).
SAMPLE_WAYBILL_PATH = (
    Path(__file__).resolve().parents[3] / "web" / "public" / "demo" / "waybill-1.jpg"
)
#: Its digest when the file is not shipped next to the package (container).
_SAMPLE_WAYBILL_SHA256_DEFAULT = (
    "979a88fecf06eb94e43d97f750fd531603c2d3ed27589892899b977d17cd19ef"
)


def _sample_sha256() -> str:
    try:
        return hashlib.sha256(SAMPLE_WAYBILL_PATH.read_bytes()).hexdigest()
    except OSError:
        return _SAMPLE_WAYBILL_SHA256_DEFAULT


SAMPLE_WAYBILL_SHA256 = _sample_sha256()

#: What the sample waybill says (plan §"Demo waybill"); the phone number on
#: it is pixelated and never read.
SAMPLE_FIELDS: Dict[str, Dict[str, Any]] = {
    "document_no": {"value": "007842", "confidence": 0.93},
    "plate": {"value": "B 9723 KXW", "confidence": 0.95},
    "date": {"value": "2025-05-14", "confidence": 0.9},
    "origin": {"value": "TPST Bantargebang, Bekasi", "confidence": 0.9},
    "destination": {"value": "PLTSa Rorotan, Jakarta Utara", "confidence": 0.9},
    "carrier": {"value": "PT. Hijau Lestari Transport", "confidence": 0.92},
    "shipper": {"value": "TPST Bantargebang", "confidence": 0.7},
    "driver": {"value": "Slamet Riyadi", "confidence": 0.9},
    "reference_no": {"value": "DO-250514-0198", "confidence": 0.85},
    "gross_kg": {"value": 32580, "confidence": 0.9},
    "tare_kg": {"value": 16240, "confidence": 0.9},
    "net_kg": {"value": 16340, "confidence": 0.92},
    "load_type": {"value": "RDF fluff", "confidence": 0.93},
    "moisture_pct": {"value": 28, "confidence": 0.9},
    "remarks": {
        "value": "Muatan RDF fluff dari hasil proses pemilahan sampah. "
        "Pastikan terpal tertutup.",
        "confidence": 0.8,
    },
}


class WaybillReaderOffline(RuntimeError):
    """No reader can answer for this photo (HTTP 503: type the fields)."""


class WaybillReaderBusy(RuntimeError):
    """Every waybill read slot stayed taken (HTTP 503 busy)."""


class WaybillRateLimited(RuntimeError):
    """The shared endpoint throttled every retry (HTTP 429)."""


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

_THOUSANDS_DOT = re.compile(r"^\d{1,3}(\.\d{3})+$")
_THOUSANDS_COMMA = re.compile(r"^\d{1,3}(,\d{3})+$")


def parse_number(value: Any) -> Optional[float]:
    """A printed Indonesian (or English) number; ``None`` when there is none.

    "32.580" and "32,580" are thousands (32580); "28,5" and "28.5" are
    decimals; with both separators the later one is the decimal mark
    ("32.580,5" = 32580.5).  Units and spaces are ignored ("16 340 kg").
    """
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if number == number and abs(number) != float("inf") else None
    text = re.sub(r"[^\d.,\-]", "", str(value).replace(" ", ""))
    text = text.strip(".,")
    if not re.search(r"\d", text):
        return None
    if "." in text and "," in text:
        decimal = "." if text.rfind(".") > text.rfind(",") else ","
        thousands = "," if decimal == "." else "."
        text = text.replace(thousands, "").replace(decimal, ".")
    elif "." in text:
        text = text.replace(".", "") if _THOUSANDS_DOT.match(text.lstrip("-")) else text
    elif "," in text:
        text = (
            text.replace(",", "")
            if _THOUSANDS_COMMA.match(text.lstrip("-"))
            else text.replace(",", ".")
        )
    try:
        return float(text)
    except ValueError:
        return None


_MONTHS = {
    "jan": 1, "januari": 1, "january": 1,
    "feb": 2, "februari": 2, "february": 2,
    "mar": 3, "maret": 3, "march": 3,
    "apr": 4, "april": 4,
    "mei": 5, "may": 5,
    "jun": 6, "juni": 6, "june": 6,
    "jul": 7, "juli": 7, "july": 7,
    "agu": 8, "agt": 8, "agustus": 8, "aug": 8, "august": 8,
    "sep": 9, "september": 9,
    "okt": 10, "oktober": 10, "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "des": 12, "desember": 12, "dec": 12, "december": 12,
}


def parse_date(value: Any) -> Optional[str]:
    """ISO ``YYYY-MM-DD`` from an Indonesian date (day first), else ``None``.

    "14/05/2025", "14-05-2025", "14.05.25", "14 Mei 2025" and an already
    ISO "2025-05-14" all give "2025-05-14".
    """
    text = str(value or "").strip()
    match = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", text)
    if match:
        year, month, day = (int(g) for g in match.groups())
    else:
        match = re.fullmatch(r"(\d{1,2})\s*[/\-.]\s*(\d{1,2})\s*[/\-.]\s*(\d{2}|\d{4})", text)
        if match:
            day, month, year = (int(g) for g in match.groups())
        else:
            match = re.fullmatch(r"(\d{1,2})\s+([A-Za-z]+)\.?\s+(\d{4})", text)
            if not match or match.group(2).lower() not in _MONTHS:
                return None
            day, month, year = int(match.group(1)), _MONTHS[match.group(2).lower()], int(match.group(3))
    if year < 100:
        year += 2000
    if not (1 <= month <= 12 and 1 <= day <= 31 and 1990 <= year <= 2100):
        return None
    return f"{year:04d}-{month:02d}-{day:02d}"


def _confidence(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if number != number:
        return 0.0
    return round(max(0.0, min(1.0, number)), 2)


def _clean_value(name: str, value: Any, warnings: List[str]) -> Any:
    """One field's value in its typed form, or ``None``."""
    if value is None:
        return None
    if name in _KG_FIELDS or name == "moisture_pct":
        number = parse_number(value)
        if number is None or number < 0:
            return None
        if name == "moisture_pct":
            if number > 100:
                return None
            return int(number) if number == int(number) else round(number, 1)
        return int(round(number))
    text = re.sub(r"\s+", " ", str(value)).strip()
    if not text or text.lower() in ("null", "none", "-", "n/a"):
        return None
    if name == "plate":
        return normalize_plate(text)
    if name == "date":
        iso = parse_date(text)
        if iso is None:
            warnings.append(f"Date '{text[:40]}' was not understood: check it.")
            return text
        return iso
    return text[:300]


def normalize_fields(raw: Any) -> Tuple[Dict[str, Dict[str, Any]], List[str]]:
    """The model's JSON as ``{field: {"value", "confidence"}}`` plus warnings.

    A field may arrive as ``{"value", "confidence"}`` or as a bare value
    (then its confidence is unknown: 0.5).  A missing or unreadable field has
    value ``None`` and confidence 0.
    """
    raw = raw if isinstance(raw, dict) else {}
    warnings: List[str] = []
    fields: Dict[str, Dict[str, Any]] = {}
    for name in FIELD_NAMES:
        entry = raw.get(name)
        if isinstance(entry, dict):
            value, confidence = entry.get("value"), _confidence(entry.get("confidence"))
        else:
            value, confidence = entry, 0.5
        value = _clean_value(name, value, warnings)
        fields[name] = {"value": value, "confidence": confidence if value is not None else 0.0}
    return fields, warnings


def values_of(fields: Dict[str, Any]) -> Dict[str, Any]:
    """``{field: value}`` from either shape (``{value, confidence}`` or plain)."""
    return {
        name: (entry.get("value") if isinstance(entry, dict) else entry)
        for name, entry in (fields or {}).items()
    }


def clean_values(fields: Dict[str, Any]) -> Dict[str, Any]:
    """Operator-confirmed fields (either shape) as typed plain values.

    Only known :data:`FIELD_NAMES` are kept; an edited "16.340" becomes
    16340 and a typed "14/05/2025" becomes "2025-05-14", like a read.
    """
    plain = values_of(fields)
    unused: List[str] = []
    return {
        name: _clean_value(name, plain[name], unused) for name in FIELD_NAMES if name in plain
    }


def overall_confidence(fields: Dict[str, Dict[str, Any]]) -> float:
    """Mean confidence over the fields that were read; a missing core field
    (:data:`CORE_FIELDS`) counts as 0."""
    scores = [
        float(entry.get("confidence") or 0.0)
        for name, entry in fields.items()
        if entry.get("value") is not None or name in CORE_FIELDS
    ]
    return round(sum(scores) / len(scores), 2) if scores else 0.0


# ---------------------------------------------------------------------------
# Derived facts
# ---------------------------------------------------------------------------

_RDF_RE = re.compile(r"\b(rdf|srf)\b|fluff", re.IGNORECASE)
_PROCESSED_RE = re.compile(r"\b(rdf|srf)\b|fluff|pemilahan|hasil proses", re.IGNORECASE)
_MSW_RE = re.compile(r"\bmsw\b|sampah campuran", re.IGNORECASE)
_ORGANIC_RE = re.compile(r"organik|organic", re.IGNORECASE)


def waste_stream_for(load_type: Optional[str]) -> Tuple[str, Optional[str]]:
    """Engine waste stream for a printed load type, plus a warning when the
    load type was not recognised (then ``rdf-feedstock`` is assumed)."""
    text = str(load_type or "")
    if _RDF_RE.search(text):
        return "rdf-feedstock", None
    if _MSW_RE.search(text):
        return "mixed-msw", None
    if _ORGANIC_RE.search(text):
        return "organic-rich", None
    shown = text.strip() or "missing"
    return (
        "rdf-feedstock",
        f"Load type '{shown[:40]}' not recognised: assumed RDF feedstock; check the waste stream.",
    )


def declares_processed_rdf(values: Dict[str, Any]) -> bool:
    """True when the load type or the remarks declare sorted/processed RDF."""
    text = f"{values.get('load_type') or ''} {values.get('remarks') or ''}"
    return bool(_PROCESSED_RE.search(text))


def arithmetic(values: Dict[str, Any]) -> Dict[str, Any]:
    """gross − tare against the printed net (``consistent`` None when a
    number is missing)."""
    gross, tare, net = (values.get(k) for k in _KG_FIELDS)
    if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (gross, tare, net)):
        return {"gross_minus_tare_kg": None, "net_kg": net, "consistent": None}
    difference = gross - tare
    return {
        "gross_minus_tare_kg": int(round(difference)),
        "net_kg": net,
        "consistent": abs(difference - net) <= ARITHMETIC_TOLERANCE * max(abs(net), 1),
    }


def derive(values: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    """``derived`` block of a read (plain values in) plus its warnings."""
    stream, warning = waste_stream_for(values.get("load_type"))
    return (
        {
            "waste_stream": stream,
            "declares_processed_rdf": declares_processed_rdf(values),
            "arithmetic": arithmetic(values),
        },
        [warning] if warning else [],
    )


def transcript(values: Dict[str, Any]) -> str:
    """Deterministic one-line text of the fields (the inspection's manifest)."""

    def kg(value: Any) -> str:
        return f"{int(value):,} kg"

    parts = [f"SURAT JALAN {values.get('document_no') or '(no number)'}"]
    labelled = (
        ("date", "Date", str),
        ("plate", "Plate", str),
        ("carrier", "Carrier", str),
        ("shipper", "Shipper", str),
        ("driver", "Driver", str),
        ("origin", "Origin", str),
        ("destination", "Destination", str),
        ("reference_no", "Ref", str),
        ("load_type", "Load type", str),
        ("gross_kg", "Gross", kg),
        ("tare_kg", "Tare", kg),
        ("net_kg", "Net", kg),
        ("moisture_pct", "Moisture", lambda v: f"{v} %"),
        ("remarks", "Remarks", str),
    )
    for name, label, show in labelled:
        value = values.get(name)
        if value is None or value == "":
            continue
        try:
            parts.append(f"{label} {show(value)}")
        except (TypeError, ValueError):
            parts.append(f"{label} {value}")
    return " | ".join(parts)


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def _response(
    fields: Dict[str, Dict[str, Any]],
    *,
    model: str,
    provider: Optional[str],
    latency_ms: Optional[float],
    provenance: str,
    warnings: List[str],
) -> Dict[str, Any]:
    values = values_of(fields)
    derived, derive_warnings = derive(values)
    warnings = list(warnings) + derive_warnings
    if derived["arithmetic"]["consistent"] is False:
        warnings.append("Gross minus tare does not equal the printed net: check the numbers.")
    if all(entry["value"] is None for entry in fields.values()):
        warnings.append("No waybill fields were found: type the fields.")
    return {
        "fields": fields,
        "derived": derived,
        "confidence": overall_confidence(fields),
        "transcript": transcript(values),
        "model": model,
        "provider": provider,
        "latency_ms": None if latency_ms is None else round(latency_ms, 1),
        "provenance": provenance,
        "warnings": warnings,
    }


def stub_response(extra_warnings: Optional[List[str]] = None) -> Dict[str, Any]:
    """The bundled sample waybill's scripted fields, labelled as a stub."""
    return _response(
        copy.deepcopy(SAMPLE_FIELDS),
        model=STUB_MODEL,
        provider=None,
        latency_ms=None,
        provenance="stub",
        warnings=[STUB_WARNING, *(extra_warnings or [])],
    )


def is_sample(image_bytes: bytes) -> bool:
    return hashlib.sha256(image_bytes).hexdigest() == SAMPLE_WAYBILL_SHA256


def _rate_limited(exc: BaseException) -> bool:
    seen: Optional[BaseException] = exc
    while seen is not None:
        if isinstance(seen, pipeline.RateLimitSpentError):
            return True
        seen = seen.__cause__
    return False


def read(image_bytes: bytes, settings: Settings, *, demo: bool = False) -> Dict[str, Any]:
    """Read one waybill photo (already validated JPEG/PNG bytes).

    ``demo`` forces the offline reader.  Raises :class:`WaybillReaderOffline`,
    :class:`WaybillReaderBusy` or :class:`WaybillRateLimited`.
    """
    sample = is_sample(image_bytes)
    offline_ok = sample and (demo or settings.allow_stub_fallback)
    if demo or not pipeline._vlm_reachable(settings):
        if offline_ok:
            return stub_response()
        raise WaybillReaderOffline("Waybill reader offline: type the fields.")

    if not _READ_SLOTS.acquire(timeout=_SLOT_WAIT_S):
        raise WaybillReaderBusy("Two waybills are being read: try again in a moment.")
    try:
        client = pipeline.VLLMClient(settings=settings)
        image = base64.b64encode(image_bytes).decode("ascii")
        try:
            parsed, model, failed, latency_ms = client.read_document(image, PROMPT)
        except Exception as exc:  # noqa: BLE001 — mapped below, never a 500
            if _rate_limited(exc):
                raise WaybillRateLimited(
                    "The AMD endpoint is rate-limited: try again in a moment or type the fields."
                ) from exc
            if offline_ok:
                return stub_response(
                    [f"Live reader failed ({type(exc).__name__}); showing the sample's fields."]
                )
            raise WaybillReaderOffline("Waybill reader offline: type the fields.") from exc
    finally:
        _READ_SLOTS.release()

    fields, warnings = normalize_fields(parsed)
    if failed:
        warnings.append(f"Vision model fallback: {'; '.join(failed)} failed, {model} answered.")
    return _response(
        fields,
        model=model,
        provider=provider_for_url(settings.vllm_vlm_url),
        latency_ms=latency_ms,
        provenance="live",
        warnings=warnings,
    )
