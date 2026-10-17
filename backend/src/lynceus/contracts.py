"""Example RDF supply contract: specs, price adjustments and the breach fee.

Every term here is an EXAMPLE. The reference SOP says the penalty rate "is
set by the supply contract and not by this reference SOP" (SOP-RDF-5.3), so
a site replaces :data:`DEFAULT_CONTRACT` with its own terms.

Sources of the example terms (.omc/research/industry-2026-10-17.md):

* Moisture <= 20 % and NCV >= 3,000 kcal/kg (12.6 MJ/kg): the public
  Bantargebang to SBI/Indocement RDF spec (Indonesia Water Portal).  SBI
  Cilacap actually receives 22.6-24.2 % moisture, so moisture breaches are
  the everyday case, not the exception.
* Chlorine <= 1.0 % dry: the ISO 21640 class-3 boundary; typical plant
  acceptance is 0.5-1.0 % dry (White Rose review).  No public Indonesian
  chlorine limit exists.
* Base price Rp 360,000/t: the published Bantargebang RDF price (ASI),
  already cited in the SOP and in :mod:`lynceus.impact`.  The Indocement to
  Rorotan supply agreement of Dec 2025 is quality-tiered (USD 24-44/t, tier
  parameters not public): :data:`PRICE_BAND`.

:func:`evaluate` is pure: one lab result plus the weighbridge net weight in,
the contract effect out.  Rules (applied in this order):

* chlorine above ``chlorine_pct_max`` (1.0 % dry): the load is refused for
  kiln feed, price 0, returned at the supplier's cost.  Nothing else applies.
* chlorine above ``chlorine_pct_warn`` (0.8 %) up to the max: a warning
  only, no price effect.
* moisture above ``moisture_pct_max`` (20 %): minus 2 % of the base price
  per percentage point above spec (fractional points count pro rata).
* NCV below ``ncv_mj_kg_min`` (12.6 MJ/kg): the price is scaled by
  actual / min.
* Moisture and NCV adjustments multiply: ``base x (1 - 2 % x points) x
  (actual / min)``; the price never goes below 0.

Each result also carries an indicative ISO 21640:2021 class code
(:func:`iso21640_class`) from the single sample.

The declared-sorted-but-hard-contaminant breach fee (:data:`BREACH_FEE_IDR`
per incident) is not a lab effect: it is charged per sealed REJECT whose
declaration check failed with a hard contaminant (see
:func:`lynceus.followups.ledger_row`).
"""

from __future__ import annotations

import math
from typing import Any, Dict, Mapping, Optional

__all__ = [
    "BASE_PRICE_IDR_PER_T",
    "BASE_PRICE_SOURCE",
    "BREACH_FEE_IDR",
    "CONTRACT_NOTE",
    "DEFAULT_CONTRACT",
    "ISO21640_LIMITS",
    "PRICE_BAND",
    "SPECS",
    "evaluate",
    "iso21640_class",
]

#: The label every surface shows next to these terms.
CONTRACT_NOTE = "Example supply contract: terms are set per contract (SOP-RDF-5.3)."

#: Bantargebang RDF selling price (the source string cited in impact.py).
BASE_PRICE_IDR_PER_T = 360_000
BASE_PRICE_SOURCE = (
    "Bantargebang Rp 360.000/ton "
    "(https://asi.or.id/id/pemprov-dki-mulai-jual-rdf-bantargebang-dibanderol-rp-360-000-per-ton)"
)

SPECS: Dict[str, float] = {
    "moisture_pct_max": 20.0,
    "ncv_mj_kg_min": 12.6,
    "chlorine_pct_max": 1.0,
    "chlorine_pct_warn": 0.8,
}
SPEC_SOURCES: Dict[str, str] = {
    "moisture_pct_max": (
        "Bantargebang to SBI/Indocement RDF spec: moisture <= 20 % "
        "(https://indonesiawaterportal.com/news/dki-governor-inaugurates-the-largest-rdf-plant-in-indonesia/)"
    ),
    "ncv_mj_kg_min": (
        "Same spec: NCV >= 3,000 kcal/kg, about 12.6 MJ/kg "
        "(https://indonesiawaterportal.com/news/dki-governor-inaugurates-the-largest-rdf-plant-in-indonesia/)"
    ),
    "chlorine_pct_max": (
        "Dry basis; ISO 21640 class-3 boundary. Typical plant acceptance "
        "0.5-1.0 % dry (https://eprints.whiterose.ac.uk/156590); no public "
        "Indonesian limit."
    ),
    "chlorine_pct_warn": "Example warning band 0.8-1.0 % dry: no price effect.",
}

#: Quality-tiered pricing seen in the market; tier parameters are not public.
PRICE_BAND: Dict[str, Any] = {
    "label": "Indocement-Rorotan supply agreement (Dec 2025): quality-tiered price",
    "usd_per_t_min": 24.0,
    "usd_per_t_max": 44.0,
    "note": "Tier parameters are not public; the example contract prices in IDR from the base price.",
    "source": (
        "https://www.indocement.co.id/en/news-events/indocement-strengthens-"
        "sustainable-waste-management-through-rdf-utilization-at-rorotan-plant-jakarta"
    ),
}

#: ISO 21640:2021 class limits for classes 1..5 (configuration, not code:
#: the Hg limits come from a secondary source and are uncertain).
ISO21640_LIMITS: Dict[str, Any] = {
    "ncv_mj_kg_min": (25.0, 20.0, 15.0, 10.0, 3.0),
    "chlorine_pct_dry_max": (0.2, 0.6, 1.0, 1.5, 3.0),
    "hg_mg_mj_median_max": (0.02, 0.03, 0.05, 0.10, 0.15),
    "hg_source": "Classes 3-5 from a secondary source (measurlabs.com); treat as configuration.",
}
ISO21640_LABEL = "indicative (single sample; ISO 21640 classifies on lot statistics)"

#: Minus this share of the base price per moisture point above spec.
MOISTURE_PENALTY_PER_POINT = 0.02
#: Flat fee per load declared as sorted RDF that carried a hard contaminant.
BREACH_FEE_IDR = 1_500_000

#: 1 kcal = 4.184 kJ.
_KCAL_PER_MJ = 1000.0 / 4.184

DEFAULT_CONTRACT: Dict[str, Any] = {
    "name": "Example RDF supply contract",
    "note": CONTRACT_NOTE,
    "example": True,
    "sop_ref": "SOP-RDF-5.3",
    "currency": "IDR",
    "base_price_idr_per_t": BASE_PRICE_IDR_PER_T,
    "base_price_source": BASE_PRICE_SOURCE,
    "price_band": PRICE_BAND,
    "specs": dict(SPECS),
    "spec_sources": dict(SPEC_SOURCES),
    "ncv_kcal_kg_min": round(SPECS["ncv_mj_kg_min"] * _KCAL_PER_MJ),
    "penalties": [
        {
            "param": "moisture_pct",
            "rule": "Above 20 %: minus 2 % of the base price per percentage point above spec.",
        },
        {
            "param": "ncv_mj_kg",
            "rule": "Below 12.6 MJ/kg: price x (actual NCV / 12.6).",
        },
        {
            "param": "chlorine_pct",
            "rule": (
                "Above 1.0 % dry: refused for kiln feed, price 0, returned at "
                "the supplier's cost. 0.8 to 1.0 %: warning only."
            ),
        },
        {
            "param": "declaration",
            "rule": (
                "Load declared as sorted RDF that carries a hard contaminant: "
                "flat breach fee Rp 1,500,000 per incident."
            ),
        },
    ],
    "breach_fee_idr": BREACH_FEE_IDR,
    "iso21640": {"limits": ISO21640_LIMITS, "label": ISO21640_LABEL},
}


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number (got {value!r})")
    value = float(value)
    if math.isnan(value) or math.isinf(value):
        raise ValueError(f"{name} must be finite (got {value!r})")
    return value


def _class_at_least(value: float, minima: tuple) -> Optional[int]:
    """Class 1..5 for a value that must be at least each class's minimum."""
    for number, minimum in enumerate(minima, start=1):
        if value >= minimum:
            return number
    return None


def _class_at_most(value: float, maxima: tuple) -> Optional[int]:
    """Class 1..5 for a value that must be at most each class's maximum."""
    for number, maximum in enumerate(maxima, start=1):
        if value <= maximum:
            return number
    return None


def iso21640_class(
    ncv_mj_kg: float, chlorine_pct_dry: float, hg_mg_mj: Optional[float] = None
) -> Dict[str, Any]:
    """Indicative ISO 21640:2021 class code from one sample.

    ``code`` reads like the standard's ("NCV 4; Cl 3; Hg n/a"); a value
    outside class 5 is "out", an unmeasured one "n/a".  A real class needs
    lot statistics (mean, median, 80th percentile), hence ``label``.
    """
    ncv = _class_at_least(ncv_mj_kg, ISO21640_LIMITS["ncv_mj_kg_min"])
    cl = _class_at_most(chlorine_pct_dry, ISO21640_LIMITS["chlorine_pct_dry_max"])
    hg = (
        None if hg_mg_mj is None
        else _class_at_most(hg_mg_mj, ISO21640_LIMITS["hg_mg_mj_median_max"])
    )

    def part(name: str, value: Optional[int], measured: bool) -> str:
        if not measured:
            return f"{name} n/a"
        return f"{name} {value}" if value is not None else f"{name} out"

    return {
        "code": "; ".join([
            part("NCV", ncv, True), part("Cl", cl, True), part("Hg", hg, hg_mg_mj is not None),
        ]),
        "classes": {"ncv": ncv, "cl": cl, "hg": hg},
        "label": ISO21640_LABEL,
    }


def evaluate(lab: Mapping[str, Any], net_kg: float) -> Dict[str, Any]:
    """Contract effect of one lab result on a load of ``net_kg`` kilograms.

    ``lab`` carries ``moisture_pct``, ``ncv_mj_kg`` (as received) and
    ``chlorine_pct`` (dry), optionally ``hg_mg_mj``.  Raises ``ValueError``
    for a missing or non-finite number or a negative weight.  Each breach
    carries ``severity``: ``refusal``, ``penalty`` or ``warning`` (a warning
    has no price effect).
    """
    moisture = _finite(lab.get("moisture_pct"), "moisture_pct")
    ncv = _finite(lab.get("ncv_mj_kg"), "ncv_mj_kg")
    chlorine = _finite(lab.get("chlorine_pct"), "chlorine_pct")
    hg = lab.get("hg_mg_mj")
    hg = None if hg is None else _finite(hg, "hg_mg_mj")
    net_kg = _finite(net_kg, "net_kg")
    if net_kg < 0:
        raise ValueError(f"net_kg must be non-negative (got {net_kg!r})")

    base = float(BASE_PRICE_IDR_PER_T)
    breaches: list[Dict[str, Any]] = []
    refused = chlorine > SPECS["chlorine_pct_max"]
    if refused:
        factor = 0.0
        breaches.append({
            "param": "chlorine_pct",
            "value": chlorine,
            "limit": SPECS["chlorine_pct_max"],
            "severity": "refusal",
            "effect": "Refused for kiln feed: price 0, returned at the supplier's cost.",
        })
    else:
        factor = 1.0
        if chlorine > SPECS["chlorine_pct_warn"]:
            breaches.append({
                "param": "chlorine_pct",
                "value": chlorine,
                "limit": SPECS["chlorine_pct_warn"],
                "severity": "warning",
                "effect": "Warning: chlorine close to the 1.0 % limit; no price effect.",
            })
        if moisture > SPECS["moisture_pct_max"]:
            points = round(moisture - SPECS["moisture_pct_max"], 2)
            cut = min(1.0, MOISTURE_PENALTY_PER_POINT * points)
            factor *= 1.0 - cut
            breaches.append({
                "param": "moisture_pct",
                "value": moisture,
                "limit": SPECS["moisture_pct_max"],
                "severity": "penalty",
                "effect": f"{points:g} points above spec: minus {round(cut * 100, 2):g} % of the price.",
            })
        if ncv < SPECS["ncv_mj_kg_min"]:
            ratio = ncv / SPECS["ncv_mj_kg_min"]
            factor *= ratio
            breaches.append({
                "param": "ncv_mj_kg",
                "value": ncv,
                "limit": SPECS["ncv_mj_kg_min"],
                "severity": "penalty",
                "effect": f"Below spec: price x {ratio:.3f} (actual / minimum NCV).",
            })

    adjusted = max(0.0, round(base * factor))
    net_t = round(net_kg / 1000.0, 3)
    full = round(base * net_t)
    payable = round(adjusted * net_t)
    return {
        "spec": dict(SPECS),
        "breaches": breaches,
        "base_price_idr_per_t": int(base),
        "adjusted_price_idr_per_t": int(adjusted),
        "adjustment_pct": round((adjusted / base - 1.0) * 100.0, 2),
        "net_t": net_t,
        "payable_idr": int(payable),
        "deduction_idr": int(full - payable),
        "refused": refused,
        "iso21640": iso21640_class(ncv, chlorine, hg),
        "note": CONTRACT_NOTE,
    }
