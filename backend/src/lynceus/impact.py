"""Lynceus measurable-impact layer (presentation, not audit).

Estimates the Rupiah / USD value of a verdict so the demo UI can show
"dampak terukur" (measurable impact) next to every inspection.  Every
number is traceable to ``docs/research/realcase-indonesia.md`` and each
basis entry carries its source URL — no invented figures.

This module is deliberately pure and deterministic: same inputs → same
outputs, no clock, no randomness, no I/O — except
:func:`load_benchmark_summary`, which reads the validation benchmark's
summary file for the expected-value model (:func:`value_model`).
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

__all__ = [
    "estimate_prevented_loss",
    "ARM_ROLL_TRIP_KG",
    "USD_IDR_RATE",
    "EUR_IDR_RATE",
    "benchmark_rates",
    "load_benchmark_summary",
    "scenario_value",
    "value_model",
    "value_model_from_benchmark",
]


# ---------------------------------------------------------------------------
# Research-backed constants (docs/research/realcase-indonesia.md §5, §3a)
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
            "Default load weight (arm roll)",
            f"≈ {ARM_ROLL_TRIP_KG / 1000:.1f} tonnes/trip (14 m³ × 372.71 kg/m³)",
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
                    "Shredder damage (1 unit)",
                    f"Rp {SHREDDER_COST_IDR:,.0f}",
                    _first_url(SHREDDER_SOURCE),
                ),
                _basis(
                    "Kiln downtime (1 hour, low end of research range)",
                    f"US$ {downtime_usd:,.0f} @ Rp {USD_IDR_RATE:,.0f}/USD "
                    f"= Rp {downtime_idr:,.0f}",
                    _first_url(KILN_DOWNTIME_SOURCE),
                ),
                _basis(
                    "USD→Rp conversion rate",
                    f"Rp {USD_IDR_RATE:,.0f}/USD (explicit, research range "
                    "Rp 15,000–16,500)",
                    "https://github.com/rafilajhh/lynceus/blob/main/docs/research/realcase-indonesia.md",
                ),
            ]
        )
        note = (
            "REJECT with a hard contaminant: worst-case loss exposure avoided "
            "= shredder replacement cost (RDI 2024, Annex 2A) + 1 hour of "
            "kiln downtime at the low end of the research range "
            "(US$28,000/hour, up to US$100,000/hour). This assumes the item "
            "would certainly have caused that damage; the probability-weighted "
            "figure is the shift report's value model (per 1,000 trucks)."
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
                    "ESCALATE: combustion impact cannot be estimated — "
                    "the VLM reported no usable moisture estimate."
                ),
            }
        water_kg = weight * moisture
        energy_mj = water_kg * WATER_LATENT_HEAT_MJ_PER_KG
        rdf_eq_tonnes = energy_mj / (RDF_CALORIFIC_MJ_PER_KG * 1000.0)
        penalty_idr = rdf_eq_tonnes * RDF_PRICE_IDR_PER_TONNE
        basis.extend(
            [
                _basis(
                    "Visual moisture of the load (VLM)",
                    f"{moisture:.0%} × {weight / 1000:.1f} t = "
                    f"{water_kg / 1000:.2f} tonnes of water",
                    "VLM visual moisture estimate (inspection pipeline)",
                ),
                _basis(
                    "Energy to evaporate water (latent heat)",
                    f"{WATER_LATENT_HEAT_MJ_PER_KG} MJ/kg × "
                    f"{water_kg / 1000:.2f} t = {energy_mj:,.0f} MJ",
                    "Physical constant (latent heat of water vapour, ~100°C)",
                ),
                _basis(
                    "RDF calorific value (energy-equivalent basis)",
                    "≈ 3,000 kcal/kg ≈ 12.55 MJ/kg",
                    _first_url(RDF_CALORIFIC_SOURCE),
                ),
                _basis(
                    "RDF energy price",
                    f"Rp {RDF_PRICE_IDR_PER_TONNE:,.0f}/tonne (midpoint of the "
                    "Rp 300–450k/tonne band)",
                    _first_url(RDF_PRICE_SOURCE),
                ),
            ]
        )
        note = (
            "ESCALATE: combustion-efficiency penalty for a wet load — the "
            "energy lost to evaporating the load's moisture is converted to "
            "RDF-equivalent tonnage and valued at the RDF market price. "
            "Conservative assumptions: all moisture evaporates in the kiln, "
            "and energy is priced at RDF calorific value, not coal."
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
                "RDF load value forwarded",
                f"{tonnes:.1f} tonnes × Rp {RDF_PRICE_IDR_PER_TONNE:,.0f}/tonne "
                "(midpoint of the Rp 300–450k/tonne band)",
                _first_url(RDF_PRICE_SOURCE),
            )
        )
        note = (
            "ACCEPT: the load passed the gates and is forwarded as RDF "
            "feedstock — this figure is the load's market value (not a "
            "prevented loss). Price band Rp 300–450k/tonne from the "
            "Bantargebang/Cilacap/Kalsel cases."
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
            f"Verdict '{verdict or 'unknown'}': no quantitative research "
            "basis for an impact figure — an honest report with no estimate."
        ),
    }


# ---------------------------------------------------------------------------
# Expected-value model: with vs without Lynceus, per 1,000 trucks
# ---------------------------------------------------------------------------
#
# The per-verdict figure above is a worst case: it books a whole shredder and
# an hour of kiln downtime for every rejected hard contaminant.  The model
# below weighs that damage by explicit probabilities and compares a gate that
# checks every truck by hand (without) with Lynceus screening every truck and
# sending only flagged ones to that same manual check (with).  Every
# parameter carries its source URLs or ``assumption: True`` plus a rationale,
# and has a low / base / high value: "low" is the end least favourable to
# Lynceus, "high" the most favourable.

#: Display-only EUR rate for the console's IDR/EUR toggle (the model itself
#: computes in IDR): ECB euro reference rate of 13 Oct 2026, EUR 1 = IDR 20,004.87.
EUR_IDR_RATE = 20_004.87
EUR_IDR_RATE_DATE = "2026-10-13"
EUR_IDR_SOURCE_URL = (
    "https://www.ecb.europa.eu/stats/policy_and_exchange_rates/"
    "euro_reference_exchange_rates/html/eurofxref-graph-idr.en.html"
)

#: Gate-staff labour cost: RDF plant Cilacap, 32 staff, Rp 1.497 billion/year
#: (RDI 2024, Annex 3; docs/research/realcase-indonesia.md §5c) spread over
#: 2,080 paid hours/year (assumption: 40 h/week × 52 weeks).
LABOUR_COST_IDR_PER_YEAR = 1_497_000_000.0
LABOUR_STAFF = 32
LABOUR_HOURS_PER_YEAR = 2_080.0
OPERATOR_COST_IDR_PER_MINUTE = (
    LABOUR_COST_IDR_PER_YEAR / LABOUR_STAFF / LABOUR_HOURS_PER_YEAR / 60.0
)

#: The model's unit: results are per this many trucks.
VALUE_MODEL_TRUCKS = 1_000

#: Benchmark summaries, preferred first: the offline replay re-score, then the
#: live run it replays.
BENCHMARK_SUMMARY_FILES = (
    "2026-10-13.rescore.summary.json",
    "2026-10-13.summary.json",
)
_REPO_BLOB = "https://github.com/rafilajhh/lynceus/blob/main/"
_RESEARCH_DOC = _REPO_BLOB + "docs/research/realcase-indonesia.md"
_MANUAL_TIME_SEARCH = _REPO_BLOB + "docs/research/token-factory-probe.md"

#: Lynceus's own price: a proposal (docs/BUSINESS.md §7, Rp 6 million per
#: gate a month), not a sourced figure.  Spread over calendar days.
SUBSCRIPTION_IDR_PER_GATE_MONTH = 6_000_000.0
DAYS_PER_YEAR = 365.0

#: Actual RDF output per plant, tonnes/day (RDI 2024 Table III.2, research
#: doc §2e): Banyumas 35, Cilacap 75, Bantargebang 400.
RDF_PLANT_OUTPUT_SOURCE = (
    "https://dashboard.rdiglobal.org/storage/publications/file/"
    "OgidnCyQqXihV2iFnsOB2cDOTmjDRVkOZ9cSFMUM.pdf"
)

#: One escaped hard item that does cause damage: shredder + 1 h of kiln.
DAMAGE_COST_IDR = SHREDDER_COST_IDR + (
    KILN_DOWNTIME_USD_PER_HOUR * KILN_DOWNTIME_HOURS * USD_IDR_RATE
)


def _benchmark_dir() -> Path:
    value = os.environ.get("LYNCEUS_BENCHMARK_DIR", "").strip()
    return Path(value) if value else Path(__file__).resolve().parents[2] / "benchmark"


def _fraction(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if 0.0 <= value <= 1.0 else None


def _confusion_row(
    summary: Dict[str, Any], truth: str
) -> Optional[Tuple[Dict[str, float], int]]:
    """Shares of one ground-truth class's verdicts, and that class's size."""
    confusion = summary.get("confusion")
    row = confusion.get(truth) if isinstance(confusion, dict) else None
    if not isinstance(row, dict):
        return None
    counts: Dict[str, float] = {}
    for key in ("reject", "escalate", "accept", "error"):
        value = row.get(key, 0)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            return None
        counts[key] = float(value)
    total = sum(counts.values())
    if total <= 0:
        return None
    return {key: value / total for key, value in counts.items()}, int(total)


def benchmark_rates(summary: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Lynceus's measured verdict rates for hard-contaminant and clean loads.

    Hard loads are the benchmark's ``reject`` ground-truth class (RealWaste
    Metal); clean loads its ``accept`` class.  The re-score summary's
    ``clean_*_rate`` keys win over the confusion matrix; ``reject.recall``
    wins for the hard reject rate.  A pipeline error counts as a flag for
    the manual check (the gate cannot pass a truck it could not inspect), so
    a class's errored share is added to its escalate rate whichever source
    that rate came from.  ``None`` when the summary cannot supply every
    rate.  Pure.
    """
    if not isinstance(summary, dict):
        return None
    hard = _confusion_row(summary, "reject")
    clean = _confusion_row(summary, "accept")
    reject_block = summary.get("reject")
    reject_block = reject_block if isinstance(reject_block, dict) else {}

    hard_reject = _fraction(reject_block.get("recall"))
    if hard_reject is None and hard is not None:
        hard_reject = hard[0]["reject"]
    hard_escalate = (hard[0]["escalate"] + hard[0]["error"]) if hard else 0.0

    clean_reject = _fraction(summary.get("clean_reject_rate"))
    clean_escalate = _fraction(summary.get("clean_escalate_rate"))
    if (clean_reject is None or clean_escalate is None) and clean is not None:
        clean_reject = clean[0]["reject"]
        clean_escalate = clean[0]["escalate"]
    if clean_escalate is not None and clean is not None:
        clean_escalate += clean[0]["error"]

    if hard_reject is None or clean_reject is None or clean_escalate is None:
        return None
    return {
        "hard_reject_rate": hard_reject,
        "hard_escalate_rate": min(hard_escalate, 1.0 - hard_reject),
        "clean_reject_rate": clean_reject,
        "clean_escalate_rate": min(clean_escalate, 1.0 - clean_reject),
        "reject_precision": _fraction(reject_block.get("precision")),
        "n_hard": hard[1] if hard else None,
        "n_clean": clean[1] if clean else None,
    }


def load_benchmark_summary(
    results_dir: Optional[Path] = None,
) -> Optional[Tuple[Dict[str, Any], str]]:
    """``(summary, file name)`` of the first usable file in
    :data:`BENCHMARK_SUMMARY_FILES`, else ``None``.  The one I/O function."""
    directory = (
        Path(results_dir) if results_dir is not None else _benchmark_dir() / "results"
    )
    for name in BENCHMARK_SUMMARY_FILES:
        try:
            summary = json.loads((directory / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if benchmark_rates(summary) is not None:
            return summary, name
    return None


#: z for a two-sided 95% interval (the /validation page uses the same).
_WILSON_Z = 1.96


def _wilson(p: float, n: Optional[int]) -> Tuple[float, float]:
    """95% Wilson score interval for an observed share ``p`` of ``n`` images;
    ``(p, p)`` when ``n`` is unknown.  Pure."""
    if not n:
        return p, p
    z2 = _WILSON_Z * _WILSON_Z
    denom = 1.0 + z2 / n
    centre = (p + z2 / (2 * n)) / denom
    half = _WILSON_Z * math.sqrt(p * (1.0 - p) / n + z2 / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def _param(
    key: str,
    label: str,
    unit: str,
    low: float,
    base: float,
    high: float,
    *,
    sources: Tuple[str, ...] = (),
    assumption: bool = False,
    rationale: str,
) -> Dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "unit": unit,
        "low": low,
        "base": base,
        "high": high,
        "sources": list(sources),
        "assumption": assumption,
        "rationale": rationale,
    }


def _parameters(
    rates: Dict[str, Any], summary_name: str, summary: Dict[str, Any]
) -> List[Dict[str, Any]]:
    bench = (_REPO_BLOB + "backend/benchmark/results/" + summary_name,)
    hard_n = f" ({rates['n_hard']} images)" if rates.get("n_hard") else ""
    clean_n = f" ({rates['n_clean']} images)" if rates.get("n_clean") else ""
    bench_note = "Measured on public RealWaste photos, not plant data."
    if summary.get("kind") == "replay" or summary_name.endswith(".rescore.summary.json"):
        disclosure = summary.get("disclosure")
        bench_note = (
            "From a replay of the recorded live model outputs under the current "
            "decision rules, not a held-out measurement."
            + (f" {disclosure}" if isinstance(disclosure, str) and disclosure else "")
            + " " + bench_note
        )

    def measured(key: str, label: str, value: float, rationale: str,
                 low: float, high: float, n: Optional[int]) -> Dict[str, Any]:
        spread = (
            "Low and high: the 95% Wilson interval for this sample size."
            if n else "Held fixed across scenarios."
        )
        return _param(key, label, "share", low, value, high, sources=bench,
                      rationale=f"{rationale} {bench_note} {spread}")

    # Low is the end least favourable to Lynceus: fewer hard loads rejected,
    # more clean loads rejected or flagged.  Each level keeps a class's
    # shares summing to at most 1.
    n_hard, n_clean = rates.get("n_hard"), rates.get("n_clean")
    hard_reject_lo, hard_reject_hi = _wilson(rates["hard_reject_rate"], n_hard)
    clean_reject_lo, clean_reject_hi = _wilson(rates["clean_reject_rate"], n_clean)
    clean_esc_lo, clean_esc_hi = _wilson(rates["clean_escalate_rate"], n_clean)
    hard_escalate = rates["hard_escalate_rate"]

    return [
        _param(
            "hard_load_rate", "Trucks carrying a visible hard contaminant", "share",
            0.005, 0.02, 0.05, assumption=True,
            rationale=(
                "No per-truck rate is published. Metal is 3.11% of national MSW "
                "by weight (SIPSN 2025, research doc §1a), but most of that is "
                "small cans; a shredder-threatening item visible at the gate is "
                "rarer."
            ),
        ),
        measured("hard_reject_rate", "Lynceus rejects a hard-contaminant load",
                 rates["hard_reject_rate"],
                 f"Reject recall on the metal class{hard_n}.",
                 hard_reject_lo, hard_reject_hi, n_hard),
        _param(
            "hard_escalate_rate", "Lynceus escalates a hard-contaminant load", "share",
            hard_escalate, hard_escalate, min(hard_escalate, 1.0 - hard_reject_hi),
            sources=bench,
            rationale=(
                f"Escalated (or errored) share of the metal class{hard_n}; these "
                f"go to the manual check. {bench_note} Held fixed, except that "
                "high caps it so the metal class's shares sum to at most 1."
            ),
        ),
        measured("clean_reject_rate", "Lynceus wrongly rejects a clean load",
                 rates["clean_reject_rate"],
                 f"Rejected share of the clean class{clean_n}.",
                 clean_reject_hi, clean_reject_lo, n_clean),
        measured("clean_escalate_rate", "Lynceus sends a clean load to the manual check",
                 rates["clean_escalate_rate"],
                 f"Escalated (or errored) share of the clean class{clean_n}.",
                 min(clean_esc_hi, 1.0 - clean_reject_hi), clean_esc_lo, n_clean),
        _param(
            "manual_catch_rate", "Manual visual check catches a visible hard item",
            "share", 0.9, 0.7, 0.5, assumption=True,
            rationale=(
                "No published detection rate. The gate officer sees the same "
                "top surface as the camera; attention varies over a shift. "
                "Also applied to loads Lynceus escalates."
            ),
        ),
        _param(
            "damage_probability", "An escaped hard item causes the damage below",
            "share", 0.02, 0.05, 0.10, assumption=True,
            rationale=(
                "No published rate. Many items pass a shredder or are caught "
                "downstream (magnets, operators); the worst-case per-reject "
                "figure assumes 1.0."
            ),
        ),
        _param(
            "damage_cost_idr", "Cost of one damage incident", "IDR",
            DAMAGE_COST_IDR, DAMAGE_COST_IDR, DAMAGE_COST_IDR,
            sources=(_first_url(SHREDDER_SOURCE), _first_url(KILN_DOWNTIME_SOURCE)),
            rationale=(
                f"Shredder Rp {SHREDDER_COST_IDR:,.0f} (RDI 2024) + 1 h kiln "
                f"downtime at US${KILN_DOWNTIME_USD_PER_HOUR:,.0f}/h, the low "
                f"end of the research range, at Rp {USD_IDR_RATE:,.0f}/USD. "
                "Held fixed."
            ),
        ),
        _param(
            "load_tonnes", "Load per truck", "t",
            ARM_ROLL_TRIP_KG / 1000.0, ARM_ROLL_TRIP_KG / 1000.0,
            ARM_ROLL_TRIP_KG / 1000.0,
            sources=(_first_url(ARM_ROLL_SOURCE),),
            rationale="Arm roll 14 m³ × 372.71 kg/m³, weighbridge-measured.",
        ),
        _param(
            "rdf_price_idr_per_tonne", "Value lost per wrongly rejected tonne",
            "IDR/t", 450_000.0, RDF_PRICE_IDR_PER_TONNE, 300_000.0,
            sources=(
                "https://www.switch-asia.eu/site/assets/files/4106/sbi_final.pdf",
                "https://suarindonesia.com/sampah-low-value-plastik-ciki-cikian-"
                "jadi-bahan-bakar-pabrik-semen-di-kalsel",
            ),
            rationale=(
                "Indonesian RDF price band Rp 300-450k/t; a wrongly rejected "
                "load is booked at its full market value."
            ),
        ),
        _param(
            "manual_check_minutes", "Manual visual check per truck", "min",
            2.0, 3.0, 5.0, assumption=True, sources=(_MANUAL_TIME_SEARCH,),
            rationale=(
                "Searched, no published duration (token-factory-probe.md). "
                "A flagged truck gets the same check the baseline gives every "
                "truck."
            ),
        ),
        _param(
            "capture_minutes", "Photo and waybill entry per truck (with Lynceus)",
            "min", 1.0, 0.5, 0.25, assumption=True,
            rationale=(
                "Extra gate time to photograph the load and type the waybill "
                "into Lynceus; the weighbridge registration itself happens "
                "either way."
            ),
        ),
        _param(
            "operator_cost_idr_per_minute", "Gate staff cost", "IDR/min",
            OPERATOR_COST_IDR_PER_MINUTE, OPERATOR_COST_IDR_PER_MINUTE,
            OPERATOR_COST_IDR_PER_MINUTE, assumption=True,
            sources=(_first_url(SHREDDER_SOURCE), _RESEARCH_DOC),
            rationale=(
                "RDF plant Cilacap: Rp 1.497 billion/year for 32 staff (RDI "
                "2024, Annex 3), over 2,080 paid hours/year (assumption: "
                "40 h/week × 52)."
            ),
        ),
        _param(
            "subscription_idr_per_month", "Lynceus subscription per gate a month",
            "IDR", SUBSCRIPTION_IDR_PER_GATE_MONTH, SUBSCRIPTION_IDR_PER_GATE_MONTH,
            SUBSCRIPTION_IDR_PER_GATE_MONTH, assumption=True,
            rationale=(
                "Proposal, not a sourced figure: the Indonesian price in "
                "docs/BUSINESS.md §7 (Rp 72 million a year). Spread over "
                f"{DAYS_PER_YEAR:.0f} days a year (assumption: the gate takes "
                "trucks every day; fewer operating days raise the fee per "
                "truck). Install hardware is quoted at cost and model "
                "inference cost is not yet known; neither is included. Held "
                "fixed."
            ),
        ),
        _param(
            "gate_rdf_tonnes_per_day", "RDF received at one gate a day", "t/day",
            35.0, 75.0, 400.0, assumption=True, sources=(RDF_PLANT_OUTPUT_SOURCE,),
            rationale=(
                "Actual RDF output of three Indonesian plants (RDI 2024, Table "
                "III.2): Banyumas 35, Cilacap 75, Bantargebang 400 t/day. "
                "Assumption: one plant's output crosses one gate in trucks of "
                f"the load above ({ARM_ROLL_TRIP_KG / 1000:.1f} t), so about "
                "6.7 / 14.4 / 76.9 trucks a day and 148.6 / 69.3 / 13.0 days "
                "per 1,000 trucks. Low (the smallest plant) spreads the monthly "
                "fee over the fewest trucks."
            ),
        ),
    ]


def scenario_value(
    p: Dict[str, float], trucks: int = VALUE_MODEL_TRUCKS
) -> Dict[str, Any]:
    """With vs without Lynceus for ``trucks`` trucks under parameters ``p``.

    Without: every truck gets the manual check, which catches
    ``manual_catch_rate`` of hard items and (generously to the baseline)
    never rejects a clean load.  With: Lynceus screens every truck; rejects
    stop the load, escalations get the manual check.  Pure.
    """
    hard = trucks * p["hard_load_rate"]
    clean = trucks - hard
    harm = p["damage_probability"] * p["damage_cost_idr"]

    escaped_without = hard * (1.0 - p["manual_catch_rate"])
    damage_without = escaped_without * harm
    minutes_without = trucks * p["manual_check_minutes"]

    caught_with = hard * (
        p["hard_reject_rate"] + p["hard_escalate_rate"] * p["manual_catch_rate"]
    )
    escaped_with = hard - caught_with
    damage_with = escaped_with * harm
    flagged = hard * (p["hard_reject_rate"] + p["hard_escalate_rate"]) + clean * (
        p["clean_reject_rate"] + p["clean_escalate_rate"]
    )
    minutes_with = trucks * p["capture_minutes"] + flagged * p["manual_check_minutes"]
    false_rejects = clean * p["clean_reject_rate"]
    false_reject_cost = false_rejects * p["load_tonnes"] * p["rdf_price_idr_per_tonne"]

    loss_avoided = damage_without - damage_with
    minutes_saved = minutes_without - minutes_with
    time_value = minutes_saved * p["operator_cost_idr_per_minute"]
    net = loss_avoided - false_reject_cost + time_value
    # Days one gate needs to receive ``trucks`` trucks, and the subscription
    # paid over those days.
    days = trucks * p["load_tonnes"] / p["gate_rdf_tonnes_per_day"]
    subscription = p["subscription_idr_per_month"] * 12.0 / DAYS_PER_YEAR * days
    return {
        "without": {
            "escaped_hard_loads": round(escaped_without, 2),
            "expected_damage_idr": round(damage_without),
            "trucks_checked_by_hand": round(float(trucks), 1),
            "operator_minutes": round(minutes_without, 1),
            "false_rejects": 0.0,
            "false_reject_cost_idr": 0,
        },
        "with": {
            "escaped_hard_loads": round(escaped_with, 2),
            "expected_damage_idr": round(damage_with),
            "trucks_checked_by_hand": round(flagged, 1),
            "operator_minutes": round(minutes_with, 1),
            "false_rejects": round(false_rejects, 2),
            "false_reject_cost_idr": round(false_reject_cost),
        },
        "expected_loss_avoided_idr": round(loss_avoided),
        "false_reject_cost_idr": round(false_reject_cost),
        "operator_minutes_saved": round(minutes_saved, 1),
        "operator_time_value_idr": round(time_value),
        "net_value_idr": round(net),
        "days_per_1000_trucks": round(days * VALUE_MODEL_TRUCKS / trucks, 1),
        "subscription_cost_idr": round(subscription),
        "net_after_subscription_idr": round(net - subscription),
    }


def value_model(summary: Dict[str, Any], summary_name: str) -> Optional[Dict[str, Any]]:
    """Expected value per :data:`VALUE_MODEL_TRUCKS` trucks: low / base / high.

    ``None`` when the benchmark summary cannot supply Lynceus's rates.  Pure.
    """
    rates = benchmark_rates(summary)
    if rates is None:
        return None
    params = _parameters(rates, summary_name, summary)
    scenarios = {
        level: scenario_value({row["key"]: row[level] for row in params})
        for level in ("low", "base", "high")
    }
    return {
        "trucks": VALUE_MODEL_TRUCKS,
        "scenarios": scenarios,
        "parameters": params,
        "worst_case_per_incident_idr": round(DAMAGE_COST_IDR),
        "benchmark_file": summary_name,
        "benchmark_reject_precision": rates["reject_precision"],
        "eur_idr_rate": EUR_IDR_RATE,
        "eur_idr_rate_date": EUR_IDR_RATE_DATE,
        "eur_idr_source_url": EUR_IDR_SOURCE_URL,
        "note": (
            "Expected value, not a forecast: escaped hard items are weighted "
            "by the probability that one causes damage. Low uses every "
            "adjustable parameter, and each measured rate's 95% interval, at "
            "the end least favourable to Lynceus, high the most favourable. Loads are either hard-contaminated or clean; "
            "wet or organic loads are not modelled. Net after subscription "
            "subtracts Lynceus's proposed per-gate fee over the days one gate "
            "takes to receive these trucks; install hardware and model "
            "inference cost are not included."
        ),
    }


def value_model_from_benchmark(
    results_dir: Optional[Path] = None,
) -> Optional[Dict[str, Any]]:
    """:func:`value_model` over the newest usable benchmark summary file."""
    loaded = load_benchmark_summary(results_dir)
    if loaded is None:
        return None
    return value_model(*loaded)
