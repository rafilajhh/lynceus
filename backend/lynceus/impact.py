"""Lynceus measurable-impact layer (presentation, not audit).

Estimates the Rupiah / USD value of a verdict so the demo UI can show
"dampak terukur" (measurable impact) next to every inspection.  Every
number is traceable to ``docs/research-realcase-indonesia.md`` and each
basis entry carries its source URL — no invented figures.

This module is deliberately pure and deterministic: same inputs → same
outputs, no clock, no randomness, no I/O.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

__all__ = ["estimate_prevented_loss", "ARM_ROLL_TRIP_KG", "USD_IDR_RATE"]


# ---------------------------------------------------------------------------
# Research-backed constants (docs/research-realcase-indonesia.md §5, §3a)
# ---------------------------------------------------------------------------

#: Explicit USD→IDR conversion rate used everywhere in this module.
#: Research doc header: kurs 2023–2026 ≈ Rp 15.000–16.500/USD; §5a uses 16.000.
USD_IDR_RATE = 16_000.0

#: One shredder unit, 5-year economic life (RDI 2024 Lampiran 2A, Banyumas).
SHREDDER_COST_IDR = 350_000_000.0
SHREDDER_SOURCE = (
    "RDI (2024) Kajian Strategi Pembiayaan dan Analisis Ekonomi Proyek RDF, "
    "Lampiran 2A (Banyumas): shredder Rp 350.000.000/unit — "
    "https://dashboard.rdiglobal.org/storage/publications/file/"
    "OgidnCyQqXihV2iFnsOB2cDOTmjDRVkOZ9cSFMUM.pdf"
)

#: Kiln unplanned-downtime cost, conservative low end of the research range
#: (§5a: rata-rata unplanned shutdown produsen AS ~US$28.000/jam lost
#: clinker; rentang idle kiln US$12.500–100.000/jam).
KILN_DOWNTIME_USD_PER_HOUR = 28_000.0
KILN_DOWNTIME_HOURS = 1.0
KILN_DOWNTIME_SOURCE = (
    "Oxmaint: rata-rata unplanned shutdown kiln ~US$28.000/jam lost clinker "
    "(rentang idle US$12.500-100.000/jam) — "
    "https://oxmaint.ai/article/cement-plant-maintenance-cmms-system-guide"
)

#: RDF market price band (§5d): Rp 300.000/ton (Cilacap/Tangerang ke SBI),
#: Rp 360.000 (Bantargebang), Rp 414.000 (RDI aktual Cilacap),
#: ~Rp 450.000 (Kalsel).  Midpoint of the Rp 300–450 ribu band is used.
RDF_PRICE_IDR_PER_TONNE = 375_000.0
RDF_PRICE_SOURCE = (
    "Band harga RDF Indonesia Rp 300.000-450.000/ton: Cilacap Rp 300.000/ton "
    "(https://www.switch-asia.eu/site/assets/files/4106/sbi_final.pdf); "
    "Bantargebang Rp 360.000/ton "
    "(https://asi.or.id/id/pemprov-dki-mulai-jual-rdf-bantargebang-dibanderol-rp-360-000-per-ton); "
    "RDI aktual Cilacap Rp 414.000/ton "
    "(https://dashboard.rdiglobal.org/storage/publications/file/"
    "OgidnCyQqXihV2iFnsOB2cDOTmjDRVkOZ9cSFMUM.pdf); Kalsel ~Rp 450.000/ton "
    "(https://suarindonesia.com/sampah-low-value-plastik-ciki-cikian-jadi-bahan-bakar-pabrik-semen-di-kalsel)"
)

#: Default arm-roll trip load: 14 m³ × 372,71 kg/m³ ≈ 5,2 ton/trip
#: (jurnal ITATS Surabaya, jembatan timbang TPA Benowo — §3a).
ARM_ROLL_TRIP_KG = 5_200.0
ARM_ROLL_SOURCE = (
    "Jurnal ITATS Surabaya (Semnas SNTT VIII 2020): arm roll 14 m³ × "
    "372,71 kg/m³ ≈ 5,2 ton/trip, diukur jembatan timbang TPA Benowo — "
    "https://ejurnal.itats.ac.id/sntekpan/article/download/1267/1030"
)

#: Calorific value of RDF ≈ 3.000 kcal/kg (SWITCH-Asia SBI case study, §2c)
#: → 3.000 × 4,184 J/kcal ≈ 12,55 MJ/kg.
RDF_CALORIFIC_MJ_PER_KG = 3_000.0 * 0.004184
RDF_CALORIFIC_SOURCE = (
    "Nilai kalor RDF ~3.000 kcal/kg (SBI Cilacap, EU SWITCH-Asia case study "
    "2024) — https://www.switch-asia.eu/site/assets/files/4106/sbi_final.pdf"
)

#: Latent heat of vaporisation of water at ~100 °C (physical constant),
#: used to price the energy burned away evaporating moisture in the kiln.
WATER_LATENT_HEAT_MJ_PER_KG = 2.26

_HARD_CONTAMINANT_TERMS = (
    "metal",
    "rock",
    "concrete",
    "tire",
    "tyre",
    "e-waste",
)


def _basis(label: str, value: str, source_url: str) -> Dict[str, str]:
    return {"label": label, "value": value, "source_url": source_url}


def _first_url(source: str) -> str:
    """First http(s) URL in a source string (compact provenance field)."""
    start = source.find("https://")
    if start < 0:
        return source
    end = len(source)
    for sep in (" ;", ";", " "):
        idx = source.find(sep, start)
        if 0 <= idx < end:
            end = idx
    return source[start:end].rstrip(".,;)")


def _has_hard_contaminant(vlm_result: Optional[Dict[str, Any]]) -> bool:
    detected = (vlm_result or {}).get("detected") or {}
    hard = detected.get("hard_contaminants")
    if isinstance(hard, (list, tuple)):
        return any(
            str(item).strip().lower() in _HARD_CONTAMINANT_TERMS for item in hard
        )
    blob = " ".join(str(part) for part in detected.values()).lower()
    return any(term in blob for term in _HARD_CONTAMINANT_TERMS)


def _effective_weight_kg(
    weight_kg: Optional[float], basis: List[Dict[str, str]]
) -> float:
    if weight_kg is not None and weight_kg > 0:
        return float(weight_kg)
    basis.append(
        _basis(
            "Berat muatan default (arm roll)",
            f"≈ {ARM_ROLL_TRIP_KG / 1000:.1f} ton/trip (14 m³ × 372,71 kg/m³)",
            _first_url(ARM_ROLL_SOURCE),
        )
    )
    return ARM_ROLL_TRIP_KG


def _visual_moisture_fraction(vlm_result: Optional[Dict[str, Any]]) -> Optional[float]:
    detected = (vlm_result or {}).get("detected") or {}
    value = detected.get("moisture")
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    if value <= 0 or value != value:  # positive, not NaN
        return None
    if value > 1.0:  # percent → fraction
        value = value / 100.0
    return value if value < 1.0 else None


# ---------------------------------------------------------------------------
# The estimator
# ---------------------------------------------------------------------------


def estimate_prevented_loss(
    verdict: str,
    vlm_result: Optional[Dict[str, Any]],
    weight_kg: Optional[float],
) -> Dict[str, Any]:
    """Estimate the measurable monetary impact of one inspection verdict.

    - ``reject`` with a hard contaminant → shredder damage + kiln downtime.
    - ``escalate_human`` → combustion-efficiency (energy) penalty of a wet
      load: latent-heat energy needed to evaporate its moisture, priced at
      the RDF energy-equivalent value.
    - ``accept`` → the market value of the load forwarded as RDF feedstock.
    - anything else (incl. ``refuse_insufficient_input``) → 0 with an honest
      note; a refusal never invents a number.

    Returns ``{prevented_loss_idr, prevented_loss_usd, basis, note}`` where
    ``basis`` is a list of ``{label, value, source_url}`` provenance rows.
    Pure and deterministic: no clock, no randomness, no I/O.
    """
    verdict = str(verdict or "").strip().lower()
    basis: List[Dict[str, str]] = []
    weight = _effective_weight_kg(weight_kg, basis)

    if verdict == "reject" and _has_hard_contaminant(vlm_result):
        downtime_usd = KILN_DOWNTIME_USD_PER_HOUR * KILN_DOWNTIME_HOURS
        downtime_idr = downtime_usd * USD_IDR_RATE
        total_idr = SHREDDER_COST_IDR + downtime_idr
        basis.extend(
            [
                _basis(
                    "Kerusakan shredder (1 unit)",
                    f"Rp {SHREDDER_COST_IDR:,.0f}",
                    _first_url(SHREDDER_SOURCE),
                ),
                _basis(
                    "Downtime kiln (1 jam, batas bawah rentang riset)",
                    f"US$ {downtime_usd:,.0f} @ kurs Rp {USD_IDR_RATE:,.0f}/USD "
                    f"= Rp {downtime_idr:,.0f}",
                    _first_url(KILN_DOWNTIME_SOURCE),
                ),
                _basis(
                    "Kurs konversi USD→Rp",
                    f"Rp {USD_IDR_RATE:,.0f}/USD (eksplisit, rentang riset "
                    "Rp 15.000-16.500)",
                    "https://docs.research-realcase-indonesia.md",
                ),
            ]
        )
        note = (
            "REJECT dengan kontaminan keras: estimasi kerugian yang dicegah = "
            "biaya penggantian shredder (RDI 2024, Lampiran 2A) + 1 jam "
            "downtime kiln pada batas bawah rentang riset (US$28.000/jam, "
            "rentang hingga US$100.000/jam). Konservatif: kerusakan parsial "
            "dan downtime lebih panjang tidak dihitung."
        )
        return {
            "prevented_loss_idr": round(total_idr),
            "prevented_loss_usd": round(total_idr / USD_IDR_RATE),
            "basis": basis,
            "note": note,
        }

    if verdict == "escalate_human":
        moisture = _visual_moisture_fraction(vlm_result)
        if moisture is None:
            return {
                "prevented_loss_idr": 0,
                "prevented_loss_usd": 0,
                "basis": basis,
                "note": (
                    "ESCALATE: estimasi dampak pembakaran tidak dapat dihitung — "
                    "VLM tidak melaporkan estimasi kadar air yang dapat dipakai."
                ),
            }
        water_kg = weight * moisture
        energy_mj = water_kg * WATER_LATENT_HEAT_MJ_PER_KG
        rdf_eq_tonnes = energy_mj / (RDF_CALORIFIC_MJ_PER_KG * 1000.0)
        penalty_idr = rdf_eq_tonnes * RDF_PRICE_IDR_PER_TONNE
        basis.extend(
            [
                _basis(
                    "Kadar air visual muatan (VLM)",
                    f"{moisture:.0%} × {weight / 1000:.1f} ton = "
                    f"{water_kg / 1000:.2f} ton air",
                    "VLM visual moisture estimate (inspection pipeline)",
                ),
                _basis(
                    "Energi menguapkan air (kalor laten)",
                    f"{WATER_LATENT_HEAT_MJ_PER_KG} MJ/kg × "
                    f"{water_kg / 1000:.2f} t = {energy_mj:,.0f} MJ",
                    "Konstanta fisis (kalor laten uap air, ~100°C)",
                ),
                _basis(
                    "Nilai kalor RDF (basis energi setara)",
                    "≈ 3.000 kcal/kg ≈ 12,55 MJ/kg",
                    _first_url(RDF_CALORIFIC_SOURCE),
                ),
                _basis(
                    "Harga energi RDF",
                    f"Rp {RDF_PRICE_IDR_PER_TONNE:,.0f}/ton (titik tengah band "
                    "Rp 300-450 ribu/ton)",
                    _first_url(RDF_PRICE_SOURCE),
                ),
            ]
        )
        note = (
            "ESCALATE: penalti efisiensi pembakaran muatan lembap — energi "
            "yang hilang menguapkan air muatan dikonversi ke tonase setara "
            "RDF dan dinilai pada harga pasar RDF. Asumsi konservatif: seluruh "
            "kadar air terevaporasi di kiln dan energi dipricing pada nilai "
            "kalor RDF, bukan batu bara."
        )
        return {
            "prevented_loss_idr": round(penalty_idr),
            "prevented_loss_usd": round(penalty_idr / USD_IDR_RATE),
            "basis": basis,
            "note": note,
        }

    if verdict == "accept":
        tonnes = weight / 1000.0
        value_idr = tonnes * RDF_PRICE_IDR_PER_TONNE
        basis.append(
            _basis(
                "Nilai muatan RDF diteruskan",
                f"{tonnes:.1f} ton × Rp {RDF_PRICE_IDR_PER_TONNE:,.0f}/ton "
                "(titik tengah band Rp 300-450 ribu/ton)",
                _first_url(RDF_PRICE_SOURCE),
            )
        )
        note = (
            "ACCEPT: muatan lolos gerbang dan diteruskan sebagai feedstock RDF "
            "— angka ini adalah nilai pasar muatan (bukan kerugian yang "
            "dicegah). Band harga Rp 300-450 ribu/ton dari kasus "
            "Bantargebang/Cilacap/Kalsel."
        )
        return {
            "prevented_loss_idr": round(value_idr),
            "prevented_loss_usd": round(value_idr / USD_IDR_RATE),
            "basis": basis,
            "note": note,
        }

    return {
        "prevented_loss_idr": 0,
        "prevented_loss_usd": 0,
        "basis": basis,
        "note": (
            f"Verdict '{verdict or 'unknown'}': tidak ada basis kuantitatif "
            "dari riset untuk angka dampak — laporan jujur tanpa estimasi."
        ),
    }
