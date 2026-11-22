"""Crop knowledge base used by AgroBrain.

Every parameter carries its reference so it can be audited and calibrated by
agronomists (CRDA / INRAT). Values are *reference* values, not field data:

* Kc, stage lengths, rooting depth, depletion fraction p:
  FAO Irrigation & Drainage Paper 56 (Allen et al., 1998), Tables 11, 12, 22.
  Stage lengths were taken from the "Mediterranean" / "arid region" rows when
  available and adapted to Tunisian calendars; flagged `calibrate=True`.
* Ky (yield response to water): FAO-33 (Doorenbos & Kassam, 1979) / FAO-66.
* Salinity thresholds (ECe at 100 % yield, dS/m) and slope (% loss per dS/m):
  FAO-29 rev.1 (Ayers & Westcot, 1985), Maas & Hoffman (1977).
* Storage conditions: USDA Agriculture Handbook 66 (Gross et al., 2016).
* Respiration heat / specific heat: ASHRAE Refrigeration Handbook (order of
  magnitude values for cold-room sizing).
* Storage density (kg of product per m3 of gross room volume, palletised bins):
  engineering estimate, configurable per project.
* Planting windows: indicative Tunisian calendar; to be validated by CRDA.

Yields are NOT stored here: they come from FAOSTAT (national average) or from
imported governorate statistics (ONAGRI / CRDA) — see engines/yields.py.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Storage:
    cold: bool                 # requires refrigerated storage
    temp_c: float | None
    rh_pct: float | None
    max_weeks: float | None
    density_kg_m3: float | None
    respiration_w_t: float | None
    cp_kj_kgk: float | None
    note: str = ""


@dataclass(frozen=True)
class Crop:
    code: str
    name_fr: str
    name_ar: str
    category: str                       # cereal | vegetable | legume | fruit_tree | industrial
    color: str
    perennial: bool
    stages: tuple[int, int, int, int]   # L_ini, L_dev, L_mid, L_late (days)
    kc: tuple[float, float, float]      # Kc_ini, Kc_mid, Kc_end
    root_depth_m: tuple[float, float]
    p: float                            # soil water depletion fraction for no stress
    ky: float
    ece_threshold: float                # dS/m
    ece_slope: float                    # % yield loss per dS/m above threshold
    planting_months: tuple[tuple[int, int], ...]
    rainfed_possible: bool
    frost_sensitive: bool
    min_hot_month_tmax_c: float | None  # e.g. date palm needs very hot summers
    storage: Storage
    faostat_qcl: tuple[int, ...]        # FAOSTAT production item codes
    faostat_fbs: int | None             # FAOSTAT Food Balance item code (None = no specific balance)
    calibrate: bool = True
    refs: tuple[str, ...] = field(default=("FAO-56", "FAO-29", "USDA HB66"))

    @property
    def cycle_days(self) -> int:
        return sum(self.stages)


def _s(cold, t, rh, w, d, r, cp, note=""):
    return Storage(cold, t, rh, w, d, r, cp, note)


DRY = _s(False, None, 65, 52, None, None, None, "Stockage sec (silo / magasin), pas de froid")

CROPS: dict[str, Crop] = {c.code: c for c in [
    Crop("wheat", "Blé", "قمح", "cereal", "#d4a72c", False, (30, 60, 70, 40), (0.40, 1.15, 0.30),
         (1.2, 1.8), 0.55, 1.05, 5.9, 3.8, ((11, 12),), True, False, None, DRY, (15,), 2511),
    Crop("barley", "Orge", "شعير", "cereal", "#c9b26b", False, (25, 50, 60, 35), (0.30, 1.15, 0.25),
         (1.0, 1.5), 0.55, 1.00, 8.0, 5.0, ((10, 12),), True, False, None, DRY, (44,), 2513),
    Crop("potato", "Pomme de terre", "بطاطا", "vegetable", "#a0703c", False, (25, 30, 45, 30), (0.50, 1.15, 0.75),
         (0.4, 0.6), 0.35, 1.10, 1.7, 12.0, ((1, 2), (8, 9)), False, True, None,
         _s(True, 7.0, 95, 16, 350, 25, 3.43, "Pomme de terre de consommation"), (116,), 2531),
    Crop("tomato", "Tomate", "طماطم", "vegetable", "#e2483d", False, (30, 40, 45, 30), (0.60, 1.15, 0.80),
         (0.7, 1.5), 0.40, 1.05, 2.5, 9.9, ((3, 4),), False, True, None,
         _s(True, 12.5, 92, 2, 250, 55, 3.98, "Récolte stade tournant ; non stockable longtemps"), (388,), 2601),
    Crop("pepper", "Piment / poivron", "فلفل", "vegetable", "#2f9e44", False, (25, 35, 40, 20), (0.60, 1.05, 0.90),
         (0.5, 1.0), 0.30, 1.10, 1.5, 14.0, ((3, 4),), False, True, None,
         _s(True, 7.5, 95, 2.5, 200, 40, 3.95), (401,), None),
    Crop("onion", "Oignon sec", "بصل", "vegetable", "#b5838d", False, (15, 25, 70, 40), (0.70, 1.05, 0.75),
         (0.3, 0.6), 0.30, 1.10, 1.2, 16.0, ((10, 12),), False, False, None,
         _s(True, 0.0, 68, 24, 300, 9, 3.77), (403,), 2602),
    Crop("watermelon", "Pastèque", "دلاع", "vegetable", "#38a169", False, (20, 30, 30, 30), (0.40, 1.00, 0.75),
         (0.8, 1.5), 0.40, 1.10, 2.5, 13.0, ((3, 4),), False, True, None,
         _s(True, 12.0, 90, 2, 250, 22, 4.08, "Seuil de salinité approché (cucurbitacées)"), (567,), None),
    Crop("melon", "Melon", "بطيخ", "vegetable", "#f6ad55", False, (30, 45, 35, 10), (0.50, 0.85, 0.60),
         (0.8, 1.5), 0.45, 1.10, 1.0, 8.4, ((3, 4),), False, True, None,
         _s(True, 3.0, 95, 2, 250, 25, 3.93), (568,), None),
    Crop("carrot", "Carotte", "سفنارية", "vegetable", "#ed8936", False, (20, 30, 50, 20), (0.70, 1.05, 0.95),
         (0.5, 1.0), 0.35, 1.00, 1.0, 14.0, ((8, 10),), False, False, None,
         _s(True, 0.0, 98, 20, 350, 46, 3.79), (426,), None),
    Crop("artichoke", "Artichaut", "قنارية", "vegetable", "#6b8e23", False, (30, 40, 100, 30), (0.50, 1.00, 0.95),
         (0.6, 0.9), 0.45, 1.00, 6.1, 11.5, ((8, 9),), False, False, None,
         _s(True, 0.0, 95, 2, 180, 70, 3.65), (366,), None),
    Crop("chickpea", "Pois chiche", "حمص", "legume", "#d69e2e", False, (20, 30, 50, 20), (0.40, 1.00, 0.35),
         (0.6, 1.0), 0.50, 0.85, 1.6, 9.6, ((1, 3),), True, False, None, DRY, (191,), None,
         refs=("FAO-56", "Seuil salinité approché (légumineuses, Maas & Hoffman)")),
    Crop("faba_bean", "Fève (sèche)", "فول", "legume", "#8d6e63", False, (30, 45, 60, 25), (0.50, 1.15, 0.30),
         (0.5, 0.7), 0.45, 0.90, 1.6, 9.6, ((10, 11),), True, False, None, DRY, (181,), None),
    Crop("olive", "Olivier", "زيتون", "fruit_tree", "#556b2f", True, (30, 90, 60, 90), (0.65, 0.70, 0.70),
         (1.2, 1.7), 0.65, 0.80, 4.0, 3.6, ((3, 3),), True, False, None,
         _s(True, 7.5, 90, 4, 400, 30, 3.5, "Olive de table fraîche avant transformation"), (260,), None),
    Crop("orange", "Agrumes (orange)", "برتقال", "fruit_tree", "#f08c00", True, (60, 90, 120, 95), (0.70, 0.65, 0.70),
         (1.2, 1.5), 0.50, 0.90, 1.7, 16.0, ((1, 1),), False, True, None,
         _s(True, 5.0, 90, 8, 300, 14, 3.81), (490, 495), 2611),
    Crop("date_palm", "Palmier dattier", "نخيل (تمر)", "fruit_tree", "#8b5a2b", True, (90, 90, 120, 65), (0.90, 0.95, 0.95),
         (1.5, 2.5), 0.50, 0.80, 4.0, 3.6, ((1, 1),), False, False, 38.0,
         _s(True, 0.0, 75, 26, 400, 5, 2.2, "Dattes demi-molles (Deglet Nour)"), (577,), 2619),
    Crop("almond", "Amandier", "لوز", "fruit_tree", "#c08497", True, (20, 70, 120, 60), (0.40, 0.90, 0.65),
         (1.0, 2.0), 0.40, 0.80, 1.5, 19.0, ((3, 3),), True, False, None,
         _s(False, 5.0, 65, 52, 350, 2, 1.9, "Fruit sec : stockage sec, froid facultatif"), (221,), None),
    Crop("grape", "Vigne (raisin de table)", "عنب", "fruit_tree", "#7b2cbf", True, (20, 40, 120, 60), (0.30, 0.85, 0.45),
         (1.0, 2.0), 0.35, 0.85, 1.5, 9.6, ((4, 4),), False, False, None,
         _s(True, -0.5, 92, 8, 200, 4, 3.6), (560,), 2620),
]}


def crop(code: str) -> Crop:
    if code not in CROPS:
        raise KeyError(f"Unknown crop '{code}'")
    return CROPS[code]


IRRIGATION_EFFICIENCY = {
    # Application efficiency, FAO-56 Table 20 / Brouwer et al. (FAO training manual 4)
    "drip": 0.90,
    "sprinkler": 0.75,
    "surface": 0.60,
}

EMITTER_PRESSURE_M = {"drip": 10.0, "sprinkler": 30.0, "surface": 2.0}  # operating head (m)
