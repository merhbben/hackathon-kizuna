"""Off-season cold-storage building required on large farms, with its own solar plant.

Rule (policy ``storage.cold_building_min_ha``, default 65 ha, draft to be validated by the ministry):
a farm larger than the threshold must include a refrigerated building that keeps one or two fresh
crops of its harvest until the national OFF-SEASON, when the country lacks them.

1. Shortage season: months outside the national harvest window, derived from the indicative
   Tunisian calendar (``CROPS[c].planting_months`` + cycle length; CRDA to validate).
2. Storage period of a crop = farm harvest -> end of the shortage (the national harvest is back) or
   end of its conservation life (USDA HB66), whichever comes first. Refrigerating beyond the
   shortage would only cost energy, so it is never planned.
3. Candidates: annual crops whose cold storage lasts >= ``storage.offseason_min_weeks`` (8 weeks).
       coverage   = shortage months reached during the storage period
       efficiency = days stored inside the shortage / days stored  (energy spent usefully)
       need       = max(national deficit share, import dependency)          (FAOSTAT balance)
       score      = coverage x (1 + need) x (0.5 + 0.5 efficiency)
   The one or two best crops present in the optimised plan are stored; if none is present the best
   one is imposed to the optimiser (minimum area halved while water does not allow it).
4. Rooms: each crop needs its own conditions (USDA HB66). Two crops share ONE room when their
   conditions are compatible (|dT| <= 1 K, |dRH| <= 5 %) and their storage periods do not overlap:
   the room is sized for the larger crop and used twice a year (smaller building, less energy).
   Loads per room: ASHRAE method (``storage.cold_room``) counted only during the storage period:
   holding loads every day + field heat of the whole harvest during the FILL_DAYS filling days.
5. Building = rooms floor x 1.35 (machine room, airlock, loading dock), placed with its PV field near
   the entrance (else the main borehole), removed from the cultivated land.
6. Energy, two scenarios studied hour by hour with the PVGIS profile of the place:
   * grid-connected: PV sized on the annual cold consumption (net), battery only as a backup for
     ``storage.cold_backup_hours`` of outage (between the crisis reserve and the usable bottom);
   * off-grid: PV sized on the worst month, battery for the night deficit of the worst month plus
     the same backup.
   Recommendation: grid-connected when the farm declares the grid, off-grid otherwise. The monthly
   PV surplus of the recommended system feeds the irrigation pumps of the same month (daytime load),
   which lowers the PV of the irrigation system.
"""
from __future__ import annotations

import math
from datetime import date, timedelta

from shapely.geometry import Point, Polygon, mapping, shape
from shapely.ops import unary_union

from app.engines import energy as energy_eng
from app.engines import partition
from app.engines import storage as storage_eng
from app.knowledge.crops import CROPS

FOOTPRINT_FACTOR = 1.35          # machine room, airlock, loading dock around the cold rooms
PV_SPACING = 1.6                 # ground area / panel area (row spacing), same as energy.design
BUILDING_RATIO = 2.0             # length / width of the building
FILL_DAYS = 14                   # the room is filled during the harvest (product cooled in 24 h)
HEAT_MARGIN = 1.08 * 1.10        # internal loads + safety, as in storage.cold_room
SHARE_DT_K = 1.0                 # rooms can be shared if storage temperatures differ by <= 1 K
SHARE_DRH_PCT = 5.0              # ... and relative humidities by <= 5 %


def national_harvest_months(code: str) -> set[int]:
    """Months in which the crop is harvested somewhere in Tunisia (indicative national calendar)."""
    c = CROPS[code]
    out = set()
    for a, b in c.planting_months:
        months = range(a, b + 1) if a <= b else list(range(a, 13)) + list(range(1, b + 1))
        for m in months:
            for day in (1, 15, 28):
                out.add((date(2026, m, day) + timedelta(days=c.cycle_days)).month)
    return out


def offseason(code: str, farm_harvest: date, min_weeks: float) -> dict | None:
    """Shortage months the farm's harvest can supply thanks to cold storage, and the storage period
    (harvest -> end of the shortage or of the conservation life). None if not storable long enough."""
    c = CROPS[code]
    st = c.storage
    if c.perennial or not st.cold or not st.max_weeks or st.max_weeks < min_weeks:
        return None
    nat = national_harvest_months(code)
    limit = farm_harvest + timedelta(weeks=st.max_weeks)
    reached: list[int] = []
    useful = 0
    entered = False
    d = farm_harvest
    end = limit
    while d < limit:
        if d.month in nat:
            if entered:              # the national harvest is back: storing longer is useless
                end = d
                break
        else:
            entered = True
            useful += 1
            if d.month not in reached:
                reached.append(d.month)
        d += timedelta(days=1)
    if not entered:
        end = farm_harvest
    days = max(1, (end - farm_harvest).days)
    return {"crop": code, "national_harvest_months": sorted(nat), "offseason_months": reached,
            "storage_weeks": st.max_weeks, "farm_harvest": farm_harvest.isoformat(),
            "sell_until": end.isoformat(), "conservation_limit": limit.isoformat(),
            "stored_days": days, "useful_days": useful, "efficiency": round(useful / days, 3),
            "stops_at": "national_harvest" if end < limit else "conservation_limit"}


def rank(candidates: dict[str, date], balance_items: list[dict], min_weeks: float) -> list[dict]:
    """Score storable candidate crops (code -> farm harvest date), best first; only score > 0."""
    bal = {i["crop"]: i for i in balance_items}
    out = []
    for code, harvest in candidates.items():
        o = offseason(code, harvest, min_weeks)
        if not o or not o["offseason_months"]:
            continue
        it = bal.get(code) or {}
        deficit = 0.0
        if it.get("gap_kt") is not None and it.get("required_kt"):
            deficit = max(0.0, -it["gap_kt"]) / it["required_kt"]
        dep = (it.get("import_dependency_pct") or 0) / 100
        need = max(deficit, dep)
        score = len(o["offseason_months"]) * (1 + need) * (0.5 + 0.5 * o["efficiency"])
        o.update(national_deficit_share=round(deficit, 3), import_dependency=round(dep, 3), need=round(need, 3),
                 score=round(score, 3), national_data=bool(it))
        out.append(o)
    return sorted(out, key=lambda x: -x["score"])


def _compatible(a: str, b: str) -> bool:
    sa, sb = CROPS[a].storage, CROPS[b].storage
    return (abs((sa.temp_c or 0) - (sb.temp_c or 0)) <= SHARE_DT_K and
            abs((sa.rh_pct or 0) - (sb.rh_pct or 0)) <= SHARE_DRH_PCT)


def _overlap(p: tuple[date, date], q: tuple[date, date]) -> bool:
    """Storage periods overlap, comparing day-of-year windows (the building is used every year)."""
    def days(x):
        s, e = x
        out, d = set(), s
        while d < e:
            out.add((d.month, d.day))
            d += timedelta(days=1)
        return out
    return bool(days(p) & days(q))


def building_rooms(entries: list[tuple[str, float, date, date]], tmax_month: list[float],
                   cost_tnd_m3: float | None = None) -> list[dict]:
    """Rooms of the building for [(crop, stored t, start, end)]. Compatible crops with disjoint storage
    periods share one room (sized for the larger one). Each returned room dict is the ASHRAE sizing of
    one crop with ``room_id``, ``shared_with``, ``operating`` (period and kWh per month)."""
    groups: list[list[tuple[str, float, date, date]]] = []
    for e in sorted(entries, key=lambda x: -x[1]):
        for g in groups:
            if all(_compatible(e[0], x[0]) and not _overlap((e[2], e[3]), (x[2], x[3])) for x in g):
                g.append(e)
                break
        else:
            groups.append([e])
    rooms = []
    for k, g in enumerate(groups):
        vol = max(t * 1000 / CROPS[c].storage.density_kg_m3 for c, t, _, _ in g)
        for c, t, start, end in g:
            r = storage_eng.cold_room(c, t, tmax_month, cost_tnd_m3=cost_tnd_m3, volume_m3=vol)
            if not r.get("required"):
                continue
            mk = room_monthly_kwh(r, start, end)
            r.update(purpose="offseason", room_id=k + 1, shared_with=[x[0] for x in g if x[0] != c],
                     annual_kwh=round(sum(mk), 0),
                     operating={"from": start.isoformat(), "to": end.isoformat(),
                                "kwh_month": [round(v, 0) for v in mk]})
            rooms.append(r)
    return rooms


def rooms_floor_m2(rooms: list[dict]) -> float:
    """Floor of the physical rooms (a shared room is counted once)."""
    seen: dict[int, float] = {}
    for r in rooms:
        seen[r.get("room_id", id(r))] = max(seen.get(r.get("room_id", id(r)), 0.0), r["floor_m2"])
    return sum(seen.values())


def room_monthly_kwh(room: dict, start: date | None, end: date | None) -> list[float]:
    """Electric kWh per calendar month of one room. With a storage period the room runs only during
    that period: holding loads (walls, respiration, air changes) every occupied day, plus the field
    heat of the whole stored mass during the first FILL_DAYS."""
    by_m = {x["month"]: x for x in room["monthly"]}
    out = [0.0] * 12
    if start is None or end is None:
        for m in range(12):
            out[m] = by_m[m + 1]["electric_kwh_day"] * energy_eng.DAYS[m]
        return out
    d = start
    while d < end:
        x = by_m[d.month]
        p = x["parts_kw"]
        hold_kw = (p["transmission"] + p["respiration"] + p["infiltration"]) * HEAT_MARGIN
        fill_kw = 0.0
        if (d - start).days < FILL_DAYS:
            # parts_kw["product"] is the field heat of 10 % of the mass per day; the whole mass is cooled
            # over FILL_DAYS days
            fill_kw = p["product"] * (100 / room["assumptions"]["daily_intake_pct"]) / FILL_DAYS * HEAT_MARGIN
        out[d.month - 1] += (hold_kw + fill_kw) * 24 / x["cop"]
        d += timedelta(days=1)
    return out


def _scenario(kind: str, loads, pv_profile, pol: energy_eng.EnergyPolicy, peak_kw: float,
              backup_h: float) -> dict:
    eff = pol.inverter_eff
    reserve_window = max(0.05, pol.crisis_min_soc - (1 - pol.battery_dod))
    backup = peak_kw * backup_h / (pol.battery_roundtrip * reserve_window)
    if kind == "grid_tied":
        annual_load = sum(sum(loads[m]) * energy_eng.DAYS[m] for m in range(12))
        annual_pv = sum(sum(pv_profile[m]) * energy_eng.DAYS[m] * eff for m in range(12))
        kwp = annual_load / annual_pv
        night = 0.0
        battery = backup                     # outage backup only, no daily cycling
    else:
        kwp = max(sum(loads[m]) / (sum(pv_profile[m]) * eff) for m in range(12) if sum(pv_profile[m]) > 0)
        night = max(sum(max(0.0, loads[m][h] - kwp * pv_profile[m][h] * eff) for h in range(24)) for m in range(12))
        battery = night / (max(0.05, 1 - pol.crisis_min_soc) * pol.battery_roundtrip)
        battery = max(battery, backup)       # the reserve below crisis_min_soc is the outage backup
    sim = energy_eng.simulate(loads, pv_profile, kwp, battery, pol)
    panels = math.ceil(kwp * 1000 / pol.panel_wp)
    pv_month = [round(kwp * sum(pv_profile[m]) * eff * energy_eng.DAYS[m], 0) for m in range(12)]
    out = {"kind": kind, "kwp": round(kwp, 2), "panels": panels, "panel_wp": pol.panel_wp,
           "pv_area_m2": round(panels * pol.panel_area_m2 * PV_SPACING, 0), "battery_kwh": round(battery, 1),
           "night_kwh_worst_day": round(night, 1), "pv_kwh_month": pv_month, "pv_annual_kwh": round(sum(pv_month), 0),
           "solar_coverage_pct": sim["self_sufficiency_pct"], "grid_kwh": sim["annual"]["grid"],
           # yearly PV production / yearly consumption (what net metering with STEG would compensate)
           "net_coverage_pct": round(min(100.0, 100 * sum(pv_month) / max(1e-9, sum(sum(loads[m]) * energy_eng.DAYS[m]
                                                                               for m in range(12)))), 1),
           "export_within_cap_kwh": sim["export"]["within_cap_kwh"], "injection_cap_pct": pol.injection_cap_pct,
           "surplus_kwh": sim["annual"]["surplus"], "surplus_kwh_month": [x["surplus"] for x in sim["monthly"]],
           "grid_kwh_month": [x["grid"] for x in sim["monthly"]],
           "backup_hours": round(battery * reserve_window * pol.battery_roundtrip / peak_kw, 1) if peak_kw else None,
           "pv_cost_tnd": round(kwp * pol.pv_cost_tnd_kwp, 0) if pol.pv_cost_tnd_kwp is not None else None,
           "battery_cost_tnd": round(battery * pol.battery_cost_tnd_kwh, 0)
           if pol.battery_cost_tnd_kwh is not None else None}
    if pol.grid_tariff_tnd_kwh is not None:
        out["grid_cost_tnd"] = round(sim["annual"]["grid"] * pol.grid_tariff_tnd_kwh, 0)
    return out


def size_energy(rooms: list[dict], pv_profile: list[list[float]] | None, pol: energy_eng.EnergyPolicy,
                periods: dict[str, tuple[date, date]] | None = None, grid: str = "unknown",
                pump_kwh_month: list[float] | None = None, backup_h: float = 6.0) -> dict:
    """Dedicated solar system of the cold building: two scenarios studied, one recommended."""
    monthly_kwh = [0.0] * 12
    for r in rooms:
        if r.get("operating"):
            mk = r["operating"]["kwh_month"]
        else:
            start, end = (periods or {}).get(r["crop"], (None, None))
            mk = room_monthly_kwh(r, start, end)
        for m, v in enumerate(mk):
            monthly_kwh[m] += v
    cold_kw = [monthly_kwh[m] / (24 * energy_eng.DAYS[m]) for m in range(12)]
    stored_t = sum(r.get("mass_t") or 0 for r in rooms)
    out = {"load_kw_month": [round(v, 2) for v in cold_kw], "load_kwh_month": [round(v, 0) for v in monthly_kwh],
           "annual_kwh": round(sum(monthly_kwh), 0), "peak_kw": round(max(cold_kw), 2),
           "operating_months": [m + 1 for m in range(12) if monthly_kwh[m] > 0],
           "compressor_kw": round(sum(r.get("compressor_electric_kw") or 0 for r in rooms), 2),
           "kwh_per_t": round(sum(monthly_kwh) / stored_t, 1) if stored_t else None,
           "backup_hours_target": backup_h, "grid": grid}
    if not pv_profile or not out["annual_kwh"]:
        out["status"] = "pvgis_unavailable" if not pv_profile else "no_load"
        return out
    loads = energy_eng.load_profiles([0.0] * 12, cold_kw, 0.0, pv_profile)
    sc = {k: _scenario(k, loads, pv_profile, pol, out["peak_kw"], backup_h) for k in ("grid_tied", "off_grid")}
    rec = "grid_tied" if grid == "yes" else "off_grid"
    best = sc[rec]
    # surplus of the cold PV used by the irrigation pumps in the same month (both run in daytime)
    pumps = [min(s, p) for s, p in zip(best["surplus_kwh_month"], pump_kwh_month or [0.0] * 12)]
    out.update(status="ok", scenarios=sc, recommended=rec, recommendation_reason=f"grid_{grid}",
               worst_month=min(range(12), key=lambda m: sum(pv_profile[m]) / max(sum(loads[m]), 1e-9)) + 1,
               pumps_from_surplus_kwh_month=[round(v, 0) for v in pumps],
               pumps_from_surplus_kwh=round(sum(pumps), 0),
               method="hourly PVGIS profile x kWp vs 24 h cold load; two scenarios simulated hour by hour",
               **{k: best[k] for k in ("kwp", "panels", "panel_wp", "pv_area_m2", "battery_kwh", "pv_kwh_month",
                                       "pv_annual_kwh", "solar_coverage_pct", "grid_kwh", "surplus_kwh",
                                       "backup_hours", "pv_cost_tnd", "battery_cost_tnd", "night_kwh_worst_day",
                                       "net_coverage_pct")})
    return out


def _rect(c: Point, length: float, width: float, ang: float) -> Polygon:
    ux, uy = math.cos(ang), math.sin(ang)
    vx, vy = -uy, ux
    pts = [(c.x + ux * a + vx * b, c.y + uy * a + vy * b)
           for a, b in ((-length / 2, -width / 2), (length / 2, -width / 2), (length / 2, width / 2),
                        (-length / 2, width / 2))]
    return Polygon(pts)


def _place(free, anchor: Point, length: float, width: float, ang: float) -> Polygon | None:
    """Rectangle inside ``free`` as close as possible to ``anchor`` (centre on the inner offset area)."""
    r = math.hypot(length, width) / 2 + 1.0
    inner = free.buffer(-r)
    if inner.is_empty:
        return None
    from shapely.ops import nearest_points
    c = nearest_points(inner, anchor)[0]
    return _rect(c, length, width, ang)


def site(field_geojson: dict, exclusions_geojson: dict | None, anchor_lonlat: tuple[float, float],
         building_m2: float, pv_m2: float, setback_m: float = 2.0) -> dict | None:
    """Building + dedicated PV field placed inside the terrain near the anchor (entrance or borehole)."""
    field = partition._clean(partition.to_utm(shape(field_geojson))).buffer(-setback_m, join_style=2)
    if exclusions_geojson:
        excl = unary_union(partition._polys(partition.to_utm(shape(exclusions_geojson))))
        if not excl.is_empty:
            field = field.difference(excl.buffer(2))
    ang = partition._long_angle(field)
    anchor = Point(*partition.TO_UTM.transform(*anchor_lonlat))
    width = math.sqrt(building_m2 / BUILDING_RATIO)
    b = _place(field, anchor, width * BUILDING_RATIO, width, ang)
    if b is None:
        return None
    out = {"building": b, "pv": None}
    if pv_m2 > 0:
        pv_w = max(width, math.sqrt(pv_m2 / 2.0))
        free = field.difference(b.buffer(4))     # 4 m service lane around the building
        out["pv"] = _place(free, b.centroid, pv_m2 / pv_w, pv_w, ang)
    res = {"building": mapping(partition.to_wgs(b)), "building_m2": round(b.area, 0),
           "building_dims_m": [round(width * BUILDING_RATIO, 1), round(width, 1)],
           "pv": mapping(partition.to_wgs(out["pv"])) if out["pv"] is not None else None,
           "pv_m2": round(out["pv"].area, 0) if out["pv"] is not None else 0.0,
           "pv_placed": out["pv"] is not None}
    parts = [g for g in (b, out["pv"]) if g is not None]
    res["exclusion"] = mapping(partition.to_wgs(unary_union([g.buffer(2) for g in parts])))
    return res


def merge_exclusions(a: dict | None, b: dict | None) -> dict | None:
    geoms = []
    for g in (a, b):
        if not g:
            continue
        geoms.extend(g.get("geometries", [g]) if g.get("type") == "GeometryCollection" else [g])
    return {"type": "GeometryCollection", "geometries": geoms} if geoms else None
