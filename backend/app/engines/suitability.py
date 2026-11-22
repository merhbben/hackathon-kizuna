"""Crop suitability for a location: climate, soil, water salinity, season.

Rules are transparent and each exclusion/penalty returns a reason code that the
UI translates. Salinity response uses the Maas-Hoffman linear model
(FAO-29): Yr = 1 - b (ECe - a)/100 for ECe > a, with ECe ~= 1.5 x ECw
(FAO-29, 15-20 % leaching fraction).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.engines.fao56 import MonthlyClimate
from app.knowledge.crops import CROPS, Crop

SEASON_MONTHS = {
    # Tunisian practice: arrière-saison / hiver (Aug-Jan plantings) vs saison / primeur (Feb-Jul plantings)
    "autumn_winter": {8, 9, 10, 11, 12, 1},
    "spring_summer": {2, 3, 4, 5, 6, 7},
    "annual": set(range(1, 13)),
}


@dataclass
class Suitability:
    crop: str
    suitable: bool
    relative_yield: float
    needs_irrigation: bool
    reasons: list[str] = field(default_factory=list)


def _planting_months(c: Crop) -> set[int]:
    out = set()
    for a, b in c.planting_months:
        m = a
        while True:
            out.add(m)
            if m == b:
                break
            m = m % 12 + 1
    return out


def evaluate(c: Crop, clim: MonthlyClimate, soil: dict, water_ec: float | None, season: str = "annual",
             allow_new_orchards: bool = False, existing: set[str] | None = None) -> Suitability:
    reasons: list[str] = []
    ok = True
    ry = 1.0
    existing = existing or set()
    if c.perennial and c.code not in existing and not allow_new_orchards:
        ok = False
        reasons.append("perennial_not_planned")
    if season in SEASON_MONTHS and not c.perennial and not (_planting_months(c) & SEASON_MONTHS[season]):
        ok = False
        reasons.append("out_of_season")
    if c.min_hot_month_tmax_c is not None and max(clim.tmax_c) < c.min_hot_month_tmax_c:
        ok = False
        reasons.append("summer_not_hot_enough")
    if c.frost_sensitive and not c.perennial:
        # months of the cycle with mean minimum temperature below 2 °C
        cold = [i + 1 for i, t in enumerate(clim.tmin_c) if t < 2.0]
        if cold and (_planting_months(c) & set(cold)):
            ry *= 0.7
            reasons.append("frost_risk")
    if c.perennial and c.frost_sensitive and min(clim.tmin_c) < 0.0:
        ry *= 0.6
        reasons.append("frost_risk")
    annual_rain = sum(clim.rain_mm)
    needs_irrigation = not (c.rainfed_possible and annual_rain >= 350)
    if c.rainfed_possible and annual_rain < 350:
        reasons.append("rainfed_insufficient_rain")
    ph = soil.get("ph")
    if ph is not None and (ph > 8.5 or ph < 5.5):
        ry *= 0.85
        reasons.append("soil_ph")
    ece = None
    if soil.get("ece_ds_m") is not None:
        ece = soil["ece_ds_m"]
    elif water_ec is not None:
        ece = 1.5 * water_ec
    if ece is not None and ece > c.ece_threshold:
        loss = c.ece_slope * (ece - c.ece_threshold) / 100
        ry *= max(0.0, 1 - loss)
        reasons.append("salinity")
        if 1 - loss < 0.5:
            ok = False
    slope = soil.get("slope_pct")
    if slope is not None and slope > 12 and c.category in ("vegetable",):
        ry *= 0.85
        reasons.append("steep_slope")
    return Suitability(c.code, ok, round(ry, 3), needs_irrigation, reasons)


def evaluate_all(clim: MonthlyClimate, soil: dict, water_ec: float | None, season: str,
                 allow_new_orchards: bool, existing: set[str]) -> dict[str, Suitability]:
    return {code: evaluate(c, clim, soil, water_ec, season, allow_new_orchards, existing) for code, c in CROPS.items()}


def leaching_requirement(ecw: float | None, c: Crop, method: str) -> float:
    """FAO-29: surface/sprinkler LR = ECw / (5 ECe_t - ECw); drip LR = ECw / (2 max ECe),
    max ECe = ECe at 100 % yield loss = a + 100 / b."""
    if not ecw:
        return 0.0
    if method == "drip":
        ece_max = c.ece_threshold + 100 / c.ece_slope
        return min(0.3, ecw / (2 * ece_max))
    den = 5 * c.ece_threshold - ecw
    return min(0.3, ecw / den) if den > 0 else 0.3
