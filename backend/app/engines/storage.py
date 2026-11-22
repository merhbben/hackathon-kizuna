"""Cold-room sizing and national-reserve contribution for large farms.

Cold room heat load (ASHRAE Refrigeration Handbook, ch. 24 method, simplified):
  Q_trans  = U A (T_out - T_in)                  (PIR/PUR sandwich panels)
  Q_prod   = m_in cp (T_entry - T_in) / t_pull   (daily intake cooled in t_pull hours)
  Q_resp   = m_stored x respiration heat
  Q_inf    = V n rho dh / 86400                  (n air changes/day ~ 70/sqrt(V), ASHRAE fig.)
  Q_int    = lights + fans (8 % of the above)
  Q_total  = 1.10 x sum ; equipment sized for 18 h/day running time.
Electric power = Q / COP, with COP = 0.45 x Carnot(T_evap = T_in - 8 K, T_cond = T_out + 12 K).
"""
from __future__ import annotations

import math

from app.knowledge.crops import crop

U_PANEL = {100: 0.22, 120: 0.18, 150: 0.15}  # W/m2K for PIR panels of given thickness (mm), lambda ~ 0.022


def cold_room(crop_code: str, mass_t: float, ambient_tmax_month: list[float], daily_intake_pct: float = 10.0,
              height_m: float = 4.5, pull_down_h: float = 24.0, cost_tnd_m3: float | None = None,
              volume_m3: float | None = None) -> dict:
    """``volume_m3`` forces the room volume (room shared with a larger crop); default = mass / density."""
    c = crop(crop_code)
    st = c.storage
    if not st.cold or st.temp_c is None or not st.density_kg_m3:
        return {"crop": crop_code, "required": False, "reason": "dry_storage", "note": st.note}
    t_in = st.temp_c
    volume = max(volume_m3 or 0.0, mass_t * 1000 / st.density_kg_m3)
    floor = volume / height_m
    side = math.sqrt(floor)
    envelope = 2 * (side * side + 2 * side * height_m)
    thickness = 100 if t_in >= 5 else 120
    u = U_PANEL[thickness]
    cp = st.cp_kj_kgk or 3.6
    monthly = []
    for m, tmax in enumerate(ambient_tmax_month):
        t_out = tmax + 3.0          # sun on roof / technical room margin
        dT = max(0.0, t_out - t_in)
        q_trans = u * envelope * dT / 1000                                   # kW
        m_in = mass_t * 1000 * daily_intake_pct / 100                       # kg/day
        q_prod = m_in * cp * max(0.0, t_out - 5 - t_in) / (pull_down_h * 3600)  # field heat (product ~ ambient - 5)
        q_resp = mass_t * (st.respiration_w_t or 0) / 1000
        n = max(1.5, 70 / math.sqrt(max(volume, 1)))
        q_inf = volume * n * 1.2 * (1.25 * dT) / 86400                      # dh ~ 1.25 dT kJ/kg (sensible+latent)
        q = (q_trans + q_prod + q_resp + q_inf) * 1.08 * 1.10
        t_evap = t_in - 8 + 273.15
        t_cond = t_out + 12 + 273.15
        cop = max(1.2, 0.45 * t_evap / (t_cond - t_evap))
        monthly.append({"month": m + 1, "load_kw": round(q, 2), "cop": round(cop, 2),
                        "electric_kwh_day": round(q * 24 / cop, 1),
                        "parts_kw": {"transmission": round(q_trans, 2), "product": round(q_prod, 2),
                                     "respiration": round(q_resp, 2), "infiltration": round(q_inf, 2)}})
    peak = max(monthly, key=lambda x: x["load_kw"])
    capacity_kw = peak["load_kw"] * 24 / 18
    return {"crop": crop_code, "required": True, "mass_t": round(mass_t, 2), "volume_m3": round(volume, 1),
            "floor_m2": round(floor, 1), "height_m": height_m, "panel_mm": thickness,
            "temperature_c": t_in, "humidity_pct": st.rh_pct, "max_storage_weeks": st.max_weeks,
            "refrigeration_capacity_kw": round(capacity_kw, 2),
            "compressor_electric_kw": round(capacity_kw / peak["cop"], 2),
            "annual_kwh": round(sum(x["electric_kwh_day"] * d for x, d in zip(monthly, [31, 28, 31, 30, 31, 30, 31,
                                                                                       31, 30, 31, 30, 31])), 0),
            "monthly": monthly, "cost_tnd": round(volume * cost_tnd_m3, 0) if cost_tnd_m3 else None,
            "cost_missing": cost_tnd_m3 is None,
            "assumptions": {"density_kg_m3": st.density_kg_m3, "daily_intake_pct": daily_intake_pct,
                            "U_W_m2K": u, "respiration_W_t": st.respiration_w_t, "cp_kJ_kgK": cp,
                            "source": "USDA HB66 (conditions), ASHRAE (loads) — estimated"}}


def is_large_farm(area_ha: float, n_boreholes: int, policy: dict) -> bool:
    th_area = policy.get("large_farm_min_ha")
    th_bh = policy.get("large_farm_min_boreholes")
    return bool((th_area is not None and area_ha >= th_area) or (th_bh is not None and n_boreholes >= th_bh))


def contribution(production_t: dict[str, float], national_production_t: dict[str, float | None],
                 reserve_targets_t: dict[str, float], productive_ratio: float, water_ratio: float,
                 authorised_ratio: float, cap_pct: float) -> dict:
    """Proposed share of the farm production reserved for national stocks, per crop.

    need_c   = reserve_target_c / national_production_c      (share of national output to put in reserve)
    capacity = productive_ratio x min(1, water_ratio) x authorised_ratio
    pct_c    = min(cap_pct, need_c x capacity)
    The result is a *proposal* that must be validated by the competent authority.
    """
    out = {}
    capacity = max(0.0, min(1.0, productive_ratio) * min(1.0, water_ratio) * min(1.0, authorised_ratio))
    for c, prod in production_t.items():
        tgt = reserve_targets_t.get(c)
        nat = national_production_t.get(c)
        if not tgt or not nat or prod <= 0:
            continue
        need = tgt / nat
        pct = min(cap_pct, need * capacity)
        storable = crop(c).storage
        out[c] = {"farm_production_t": round(prod, 2), "national_production_t": round(nat, 0),
                  "reserve_target_t": tgt, "need_share": round(need, 4), "capacity_factor": round(capacity, 3),
                  "proposed_pct": round(100 * pct, 2), "proposed_t": round(prod * pct, 2),
                  "storage": "cold_room" if storable.cold else "dry_store",
                  "max_storage_weeks": storable.max_weeks}
    return {"items": out, "status": "proposal_requires_validation", "cap_pct": round(100 * cap_pct, 1),
            "factors": {"productive_ratio": round(productive_ratio, 3), "water_ratio": round(water_ratio, 3),
                        "authorised_ratio": round(authorised_ratio, 3)}}
