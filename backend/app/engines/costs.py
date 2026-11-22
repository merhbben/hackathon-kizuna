"""Automatic production cost per crop and per hectare (no manual entry by the farmer).

cost/ha = labour + seed/plants + fertilisers + plant protection + mechanisation
          + irrigation energy + network water + drip maintenance

* Labour      = (base days + harvest days/t x expected yield) x SMAG (official daily wage).
* Fertilisers = nutrients removed by the expected yield (N / efficiency, P2O5, K2O) converted into
                DAP 18-46, ammonium nitrate 33.5 % and potassium sulphate 0-0-50 at their prices.
* Energy      = irrigation m3/ha x specific pumping energy of THIS farm (rated pump kW / flow, or
                hydraulic head) x electricity tariff (farmer's STEG tariff, else ministry value).
* Water       = m3/ha drawn from public networks (dam network, canal) x network water price.
* Drip        = yearly maintenance / renewal of the drip system for irrigated crops.
Quantities depend on the crop (knowledge/costs.py) and on what this farm produces (yield, water,
pump); unit prices are ministry parameters (policy `costs.*`), each with its source and status.
An official reference cost set by the ministry (economics.reference_costs_tnd_ha) replaces the model.
"""
from __future__ import annotations

from app.knowledge.costs import (AMMONITRATE_N, COEF, DAP_N, DAP_P2O5, N_EFFICIENCY, SOP_K2O)

PRICE_KEYS = ("smag_tnd_day", "tractor_tnd_h", "treatment_tnd_ha", "ammonitrate_tnd_t", "dap_tnd_t", "sop_tnd_t",
              "cereal_seed_tnd_kg", "legume_seed_tnd_kg", "potato_seed_tnd_kg", "vegetable_seed_tnd_kg",
              "seedling_tnd_plant", "offshoot_tnd_plant", "network_water_tnd_m3", "drip_tnd_ha_year")


def unit_prices(get) -> dict[str, float | None]:
    """Ministry unit prices (``get`` = policy.get bound to the session)."""
    return {k: get(f"costs.{k}") for k in PRICE_KEYS}


def _item(qty, unit, price, quality):
    return {"qty": round(qty, 2), "unit": unit, "price": price,
            "tnd": None if price is None else round(qty * price, 1), "quality": quality}


def crop_cost_ha(code: str, yield_t_ha: float, water_m3_ha: float, kwh_per_m3: float | None,
                 tariff_tnd_kwh: float | None, network_share: float, prices: dict, qualities: dict,
                 rainfed: bool = False, official_tnd_ha: float | None = None) -> dict:
    """Breakdown of the production cost of one hectare of ``code`` on this farm."""
    if official_tnd_ha is not None:
        return {"crop": code, "total_tnd_ha": round(official_tnd_ha, 0), "quality": "official", "items": {},
                "missing": [], "basis": "ministry_reference"}
    c = COEF.get(code)
    if c is None:
        return {"crop": code, "total_tnd_ha": None, "quality": "missing", "items": {}, "missing": ["coefficients"]}
    q = lambda k: qualities.get(k, "estimated")       # noqa: E731
    items: dict[str, dict] = {}
    days = c.labour_base_days + c.harvest_days_per_t * yield_t_ha
    items["labour"] = _item(days, "day", prices["smag_tnd_day"], q("smag_tnd_day"))
    if c.seed_qty and c.seed_price_key:
        unit = "plant" if c.seed_price_key.endswith("plant") else "kg"
        items["seed"] = _item(c.seed_qty, unit, prices[c.seed_price_key], q(c.seed_price_key))
    n = c.n_per_t * yield_t_ha / N_EFFICIENCY
    p = c.p2o5_per_t * yield_t_ha
    k = c.k2o_per_t * yield_t_ha
    dap_kg = p / DAP_P2O5
    amn_kg = max(0.0, n - dap_kg * DAP_N) / AMMONITRATE_N
    sop_kg = k / SOP_K2O
    if dap_kg:
        items["dap"] = _item(dap_kg / 1000, "t", prices["dap_tnd_t"], q("dap_tnd_t"))
    if amn_kg:
        items["ammonitrate"] = _item(amn_kg / 1000, "t", prices["ammonitrate_tnd_t"], q("ammonitrate_tnd_t"))
    if sop_kg:
        items["potash"] = _item(sop_kg / 1000, "t", prices["sop_tnd_t"], q("sop_tnd_t"))
    items["treatments"] = _item(c.treatments, "treatment", prices["treatment_tnd_ha"], q("treatment_tnd_ha"))
    items["mechanisation"] = _item(c.tractor_h, "h", prices["tractor_tnd_h"], q("tractor_tnd_h"))
    missing = []
    if not rainfed and water_m3_ha > 0:
        if kwh_per_m3 is not None:
            kwh = water_m3_ha * (1 - network_share) * kwh_per_m3
            items["energy"] = _item(kwh, "kWh", tariff_tnd_kwh, "measured" if tariff_tnd_kwh is not None else "missing")
            if tariff_tnd_kwh is None:
                missing.append("grid_tariff")
        if network_share > 0:
            items["water"] = _item(water_m3_ha * network_share, "m3", prices["network_water_tnd_m3"],
                                   q("network_water_tnd_m3"))
        items["drip"] = _item(1, "ha", prices["drip_tnd_ha_year"], q("drip_tnd_ha_year"))
    for name, it in items.items():
        if it["tnd"] is None and name != "energy":
            missing.append(name)
    total = sum(it["tnd"] or 0 for it in items.values())
    return {"crop": code, "total_tnd_ha": round(total, 0), "items": items, "missing": sorted(set(missing)),
            "quality": "estimated", "basis": "technical_coefficients", "yield_t_ha": round(yield_t_ha, 2),
            "water_m3_ha": round(water_m3_ha, 0), "labour_days_ha": round(days, 1),
            "nutrients_kg_ha": {"N": round(n, 1), "P2O5": round(p, 1), "K2O": round(k, 1)}}


def energy_part(breakdown: dict) -> float:
    return (breakdown.get("items", {}).get("energy") or {}).get("tnd") or 0.0
