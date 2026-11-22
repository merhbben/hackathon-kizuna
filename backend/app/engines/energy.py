"""PV sizing, battery sizing and hourly energy dispatch (typical day per month).

Production: PVGIS hourly output per kWp (SARAH-3, 2019-2023 mean per month/hour).
Strategy (configurable, see policy keys `energy.*`):
  1. `reserve_share` (default 20 %) of each hour's PV output is first offered to
     the battery (backup protection) as long as the battery is below 100 %.
  2. The remainder supplies the farm loads (pumps, cold rooms, other).
  3. Unmet loads use the battery down to `crisis_min_soc` (default 30 %), then the grid.
  4. Remaining PV charges the battery, and only then is counted as *exportable surplus*.
Exportable surplus is capped by the regulatory injection ceiling configured by
the ministry (default 30 % of annual production for self-producers, Decree
2020-105 revising Decree 2016-1123, Law 2015-12 / 2019-47 — status: to be
verified with STEG/ANME for each contract and voltage level). The "80 % sale"
scenario is reported only as an unverified hypothesis.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

DAYS = [31, 28.25, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]


@dataclass
class EnergyPolicy:
    reserve_share: float = 0.20
    crisis_min_soc: float = 0.50      # normal operation never discharges below this (crisis reserve)
    autonomy_hours: float = 24.0
    battery_dod: float = 0.90         # LiFePO4 usable depth of discharge
    battery_roundtrip: float = 0.90
    inverter_eff: float = 0.96
    panel_wp: float = 550.0
    panel_area_m2: float = 2.6
    coverage: str = "worst_month"           # worst_month | annual
    injection_cap_pct: float | None = 0.30
    injection_cap_status: str = "to_verify"
    hypothesis_sale_pct: float = 0.80
    pv_cost_tnd_kwp: float | None = None
    battery_cost_tnd_kwh: float | None = None
    grid_tariff_tnd_kwh: float | None = None
    export_tariff_tnd_kwh: float | None = None


def load_profiles(pump_kwh_month: list[float], cold_kw_month: list[float], other_kw: float,
                  pv_profile: list[list[float]], pumping_window: tuple[int, int] = (5, 22)) -> list[list[float]]:
    """Hourly load (kW) per month. Pumping energy follows the PV shape inside the
    pumping window (what the scheduler aims for), cold rooms run continuously."""
    out = []
    for m in range(12):
        day_pump = pump_kwh_month[m] / DAYS[m]
        shape = [pv_profile[m][h] if pumping_window[0] <= h < pumping_window[1] else 0.0 for h in range(24)]
        tot = sum(shape) or 1.0
        out.append([day_pump * shape[h] / tot + cold_kw_month[m] + other_kw for h in range(24)])
    return out


def size_pv(loads: list[list[float]], pv_profile: list[list[float]], pol: EnergyPolicy) -> float:
    ratios = []
    for m in range(12):
        demand = sum(loads[m])
        prod = sum(pv_profile[m]) * pol.inverter_eff * (1 - pol.reserve_share * 0.5)
        if prod > 0:
            ratios.append(demand / prod)
    if not ratios:
        return 0.0
    if pol.coverage == "annual":
        return sum(sum(loads[m]) * DAYS[m] for m in range(12)) / sum(
            sum(pv_profile[m]) * DAYS[m] * pol.inverter_eff for m in range(12))
    return max(ratios)


def size_battery(critical_kw: float, pol: EnergyPolicy) -> float:
    """Capacity so that the crisis reserve (between crisis_min_soc and 1 - DoD) covers
    `autonomy_hours` of critical load during a grid outage."""
    usable = critical_kw * pol.autonomy_hours / pol.battery_roundtrip
    window = max(0.05, pol.crisis_min_soc - (1 - pol.battery_dod))
    return usable / window


def simulate(loads, pv_profile, kwp: float, battery_kwh: float, pol: EnergyPolicy) -> dict:
    monthly = []
    soc = battery_kwh * 0.6
    min_soc = battery_kwh * pol.crisis_min_soc
    tot = {"pv": 0.0, "load": 0.0, "self": 0.0, "batt_out": 0.0, "grid": 0.0, "surplus": 0.0, "to_reserve": 0.0}
    hourly_example = {}
    for m in range(12):
        acc = {k: 0.0 for k in tot}
        # run 3 identical days, keep the last one (steady state)
        for rep in range(3):
            day = {k: 0.0 for k in tot}
            hours = []
            for h in range(24):
                pv = kwp * pv_profile[m][h] * pol.inverter_eff
                load = loads[m][h]
                room = max(0.0, battery_kwh - soc)
                to_res = min(pv * pol.reserve_share, room / pol.battery_roundtrip ** 0.5)
                soc += to_res * pol.battery_roundtrip ** 0.5
                avail = pv - to_res
                direct = min(avail, load)
                rest_load = load - direct
                avail -= direct
                from_batt = min(rest_load, max(0.0, soc - min_soc) * pol.battery_roundtrip ** 0.5)
                soc -= from_batt / pol.battery_roundtrip ** 0.5
                grid = rest_load - from_batt
                room = max(0.0, battery_kwh - soc)
                charge = min(avail, room / pol.battery_roundtrip ** 0.5)
                soc += charge * pol.battery_roundtrip ** 0.5
                surplus = avail - charge
                for k, v in (("pv", pv), ("load", load), ("self", direct), ("batt_out", from_batt), ("grid", grid),
                             ("surplus", surplus), ("to_reserve", to_res)):
                    day[k] += v
                hours.append({"h": h, "pv": round(pv, 3), "load": round(load, 3), "soc_pct":
                              round(100 * soc / battery_kwh, 1) if battery_kwh else 0, "grid": round(grid, 3),
                              "surplus": round(surplus, 3)})
            if rep == 2:
                acc = day
                hourly_example[m] = hours
        monthly.append({k: round(v * DAYS[m], 1) for k, v in acc.items()})
        for k in tot:
            tot[k] += acc[k] * DAYS[m]
    annual = {k: round(v, 0) for k, v in tot.items()}
    cap = pol.injection_cap_pct
    export_reg = None if cap is None else round(min(annual["surplus"], cap * annual["pv"]), 0)
    export_hyp = round(min(annual["surplus"], pol.hypothesis_sale_pct * annual["pv"]), 0)
    return {"monthly": monthly, "annual": annual, "hourly_typical_day": hourly_example,
            "self_sufficiency_pct": round(100 * (1 - annual["grid"] / annual["load"]), 1) if annual["load"] else None,
            "export": {"potential_kwh": annual["surplus"], "regulatory_cap_pct": cap,
                       "regulatory_cap_status": pol.injection_cap_status, "within_cap_kwh": export_reg,
                       "hypothesis_80pct_kwh": export_hyp,
                       "hypothesis_note": "hypothesis_not_authorised"}}


def design(pump_kwh_month: list[float], cold_kw_month: list[float], other_kw: float, critical_kw: float,
           pv_profile: list[list[float]], pol: EnergyPolicy, existing_kwp: float | None = None,
           existing_battery_kwh: float | None = None) -> dict:
    loads = load_profiles(pump_kwh_month, cold_kw_month, other_kw, pv_profile)
    kwp_needed = size_pv(loads, pv_profile, pol)
    kwp = existing_kwp if existing_kwp else kwp_needed
    batt_needed = size_battery(critical_kw, pol) if critical_kw > 0 else 0.0
    batt = existing_battery_kwh if existing_battery_kwh else batt_needed
    sim = simulate(loads, pv_profile, kwp, batt, pol)
    panels = math.ceil(kwp_needed * 1000 / pol.panel_wp) if kwp_needed > 0 else 0
    reserve_window = max(0.0, pol.crisis_min_soc - (1 - pol.battery_dod))
    autonomy_h = (batt * reserve_window * pol.battery_roundtrip / critical_kw) if critical_kw > 0 and batt else None
    costs = {"pv_tnd": None, "battery_tnd": None, "annual_savings_tnd": None, "export_revenue_tnd": None,
             "payback_years": None, "missing": []}
    if pol.pv_cost_tnd_kwp is not None:
        costs["pv_tnd"] = round(kwp_needed * pol.pv_cost_tnd_kwp, 0)
    else:
        costs["missing"].append("energy.pv_cost_tnd_kwp")
    if pol.battery_cost_tnd_kwh is not None:
        costs["battery_tnd"] = round(batt_needed * pol.battery_cost_tnd_kwh, 0)
    else:
        costs["missing"].append("energy.battery_cost_tnd_kwh")
    if pol.grid_tariff_tnd_kwh is not None:
        costs["annual_savings_tnd"] = round((sim["annual"]["self"] + sim["annual"]["batt_out"]) *
                                            pol.grid_tariff_tnd_kwh, 0)
    else:
        costs["missing"].append("energy.grid_tariff_tnd_kwh")
    if pol.export_tariff_tnd_kwh is not None and sim["export"]["within_cap_kwh"] is not None:
        costs["export_revenue_tnd"] = round(sim["export"]["within_cap_kwh"] * pol.export_tariff_tnd_kwh, 0)
    if costs["pv_tnd"] is not None and costs["annual_savings_tnd"]:
        invest = costs["pv_tnd"] + (costs["battery_tnd"] or 0)
        costs["payback_years"] = round(invest / (costs["annual_savings_tnd"] + (costs["export_revenue_tnd"] or 0)), 1)
    return {"kwp_needed": round(kwp_needed, 2), "kwp_simulated": round(kwp, 2), "panels": panels,
            "panel_wp": pol.panel_wp, "pv_area_m2": round(panels * pol.panel_area_m2 * 1.6, 0),
            "battery_kwh_needed": round(batt_needed, 1), "battery_kwh_simulated": round(batt, 1),
            "critical_load_kw": round(critical_kw, 2), "autonomy_hours": None if autonomy_h is None else
            round(autonomy_h, 1), "policy": pol.__dict__, "simulation": sim, "costs": costs,
            "load_kwh_month": [round(sum(loads[m]) * DAYS[m], 1) for m in range(12)]}
