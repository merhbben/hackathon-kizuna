"""Technical coefficients of the production-cost model (per hectare and per tonne harvested).

STATUS: indicative estimates for Tunisian open-field / drip-irrigated crops (Mediterranean practice),
to be replaced by the IRESA "Recueil des fiches technico-économiques observées des principales cultures
pratiquées en Tunisie" (tomes I-II) or CRDA sheets when available. Every cost built from them is shown
with the quality "estimated" and its full breakdown.

* labour_base_days : working days per ha and per season excluding harvest (soil, planting, weeding,
  irrigation, treatments).
* harvest_days_per_t : picking / handling days per tonne harvested (0 for combine-harvested cereals).
* tractor_h : tractor (or contractor-equivalent) hours per ha, harvest machine included for cereals.
* seed : (quantity per ha, unit price key) — kg of seed, kg of seed tubers or number of plants.
* removal : N, P2O5, K2O exported per tonne harvested (kg/t), orders of magnitude from crop-removal
  tables (IFA World Fertilizer Use Manual; FAO Fertilizer and Plant Nutrition Bulletin 16). Legumes
  fix their nitrogen (N = 0).
* treatments : plant-protection treatments per season.
Perennials: yearly maintenance of an established orchard (no planting cost).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CostCoef:
    labour_base_days: float
    harvest_days_per_t: float
    tractor_h: float
    seed_qty: float
    seed_price_key: str | None
    n_per_t: float
    p2o5_per_t: float
    k2o_per_t: float
    treatments: int


COEF: dict[str, CostCoef] = {
    #                      labour  harv/t tract  seed qty  seed price key            N     P2O5  K2O  treat
    "wheat":      CostCoef(2,      0.0,   9,     160,      "cereal_seed_tnd_kg",     25.0, 10.0, 6.0,  2),
    "barley":     CostCoef(2,      0.0,   8,     140,      "cereal_seed_tnd_kg",     22.0, 9.0,  6.0,  1),
    "potato":     CostCoef(25,     2.0,   20,    2500,     "potato_seed_tnd_kg",     3.5,  1.5,  6.0,  8),
    "tomato":     CostCoef(60,     2.5,   15,    22000,    "seedling_tnd_plant",     2.5,  1.0,  4.0,  10),
    "pepper":     CostCoef(60,     3.0,   15,    30000,    "seedling_tnd_plant",     3.0,  1.0,  4.5,  10),
    "onion":      CostCoef(45,     1.5,   12,    5,        "vegetable_seed_tnd_kg",  2.5,  1.2,  3.0,  6),
    "watermelon": CostCoef(20,     0.8,   10,    5000,     "seedling_tnd_plant",     2.0,  0.8,  3.5,  5),
    "melon":      CostCoef(30,     1.5,   10,    7000,     "seedling_tnd_plant",     3.0,  1.2,  5.0,  6),
    "carrot":     CostCoef(40,     1.5,   15,    4,        "vegetable_seed_tnd_kg",  3.0,  1.3,  5.0,  4),
    "artichoke":  CostCoef(60,     6.0,   12,    10000,    "offshoot_tnd_plant",     8.0,  2.5,  10.0, 5),
    "chickpea":   CostCoef(10,     4.0,   8,     100,      "legume_seed_tnd_kg",     0.0,  8.0,  15.0, 2),
    "faba_bean":  CostCoef(10,     5.0,   8,     150,      "legume_seed_tnd_kg",     0.0,  10.0, 15.0, 2),
    "olive":      CostCoef(15,     10.0,  6,     0,        None,                     4.0,  1.2,  6.0,  3),
    "orange":     CostCoef(25,     2.0,   8,     0,        None,                     2.0,  0.5,  3.0,  5),
    "date_palm":  CostCoef(40,     6.0,   4,     0,        None,                     3.0,  1.0,  6.0,  3),
    "almond":     CostCoef(15,     15.0,  6,     0,        None,                     30.0, 10.0, 35.0, 4),
    "grape":      CostCoef(60,     4.0,   10,    0,        None,                     3.0,  1.0,  5.0,  8),
}

N_EFFICIENCY = 0.7      # share of applied N recovered by the crop (losses: leaching, volatilisation)
DAP_N, DAP_P2O5 = 0.18, 0.46          # DAP 18-46-0
AMMONITRATE_N = 0.335                 # ammonium nitrate 33.5 % N
SOP_K2O = 0.50                        # potassium sulphate 0-0-50
