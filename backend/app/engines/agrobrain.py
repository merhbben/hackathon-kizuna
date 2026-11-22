"""AgroBrain — orchestrates every engine to produce a farm plan.

terrain -> climate (NASA POWER, FAO-56 ET0) -> soil (farmer / SoilGrids) -> suitability
-> yields (farmer > FAOSTAT national) -> water needs per crop (FAO-56) -> MILP crop areas
(OR-Tools) -> exact-area spatial partition near water sources -> per-parcel hydraulics and
energy -> CP-SAT irrigation timetable -> PV / battery / cold rooms -> reserve contribution.
Every output carries the provenance of its inputs (`quality` / `sources`).
"""
from __future__ import annotations

import calendar
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.connectors import climate as climate_conn
from app.connectors import sources
from app.connectors.base import ConnectorError
from app.engines import cold_store, crop_calendar
from app.engines import energy as energy_eng
from app.engines import fao56, forecast, irrigation, national, optimizer, partition, policy, storage
from app.engines.hydraulics import pumping_point
from app.engines.suitability import evaluate_all, leaching_requirement
from app.knowledge.crops import CROPS, EMITTER_PRESSURE_M, IRRIGATION_EFFICIENCY
from app.knowledge.governorates import centroids
from app.models import ContributionRequest, Farm, Parcel, Plan


class PlanningError(ValueError):
    def __init__(self, code: str, detail: dict | None = None):
        super().__init__(code)
        self.code = code
        self.detail = detail or {}


def _centroid(farm: Farm) -> tuple[float, float]:
    from shapely.geometry import shape
    if farm.boundary_geojson:
        p = shape(farm.boundary_geojson).representative_point()
        return p.y, p.x
    if farm.latitude is not None:
        return farm.latitude, farm.longitude
    return centroids()[farm.governorate_code]


def climate_for(db: Session, farm: Farm) -> fao56.MonthlyClimate:
    lat, lon = _centroid(farm)
    try:
        return sources.fetch_climate_normals(db, round(lat, 2), round(lon, 2))
    except ConnectorError:
        gov = national.governorate_climates(db, fetch=True).get(farm.governorate_code)
        if gov is None:
            raise PlanningError("climate_unavailable")
        gov.source += " (governorate centroid fallback)"
        return gov


def soil_for(db: Session, farm: Farm) -> dict:
    """Soil is never typed by the farmer: read on the imported plan, otherwise SoilGrids at the farm position."""
    soil = dict(farm.soil or {})
    if soil.get("quality") != "from_plan" and not str(soil.get("source", "")).startswith("SoilGrids"):
        soil = {}                                   # older manual entries are no longer used
    if soil.get("sand_pct") is None and not soil.get("texture"):
        lat, lon = _centroid(farm)
        try:
            soil.update(sources.fetch_soil(lat, lon))
            farm.soil = soil
            db.commit()
        except ConnectorError:
            soil["source"] = "missing"
    return soil


def _yield_for(db: Session, farm: Farm, code: str) -> tuple[float | None, str]:
    y = (farm.preferences or {}).get("yields_kg_ha", {}).get(code)
    if y:
        return float(y), "measured"
    imported = [r for r in sources.series(db, "MANUAL", "yield_kg_ha", farm.governorate_code, code) if r.value]
    if imported:
        return imported[-1].value, "official_governorate"
    recs = [r for r in sources.series(db, "FAOSTAT_QCL", "yield_kg_ha", "TN", code) if r.value][-3:]
    if not recs:
        return None, "missing"
    m = sum(r.value for r in recs) / len(recs)
    flagged = any(r.quality != "official" for r in recs)
    return m, ("estimated_national_average" if flagged else "official_national_average")


def _price_cost(db: Session, farm: Farm, code: str) -> tuple[float | None, float | None]:
    prefs = farm.preferences or {}
    price = prefs.get("prices_tnd_kg", {}).get(code)
    cost = prefs.get("costs_tnd_ha", {}).get(code)
    if price is None:
        price = (policy.get(db, "economics.reference_prices_tnd_kg") or {}).get(code)
    if cost is None:
        cost = (policy.get(db, "economics.reference_costs_tnd_ha") or {}).get(code)
    return price, cost


def _monthly_capacity(farm: Farm, year: int) -> tuple[dict[str, float], float | None]:
    """'YYYY-MM' -> m3 available from authorised sources (flow x hours x days), for two years."""
    srcs = [s for s in farm.water_sources if s.authorized]
    cap = {}
    for y in (year, year + 1, year + 2):   # crop cycles planted next season can end two years ahead
        for m in range(1, 13):
            days = calendar.monthrange(y, m)[1]
            # declared daily volume (from the plan) has priority over flow x authorised hours
            cap[f"{y:04d}-{m:02d}"] = sum((s.daily_volume_m3 if s.daily_volume_m3 is not None
                                          else (s.flow_m3h or 0) * s.max_hours_per_day) * days for s in srcs)
    if not any(s.annual_quota_m3 for s in srcs):
        return cap, None
    total = 0.0
    for s in srcs:
        if s.annual_quota_m3:
            total += s.annual_quota_m3
        else:   # no quota on this source: limited only by what it can pump in a year
            daily = s.daily_volume_m3 if s.daily_volume_m3 is not None else (s.flow_m3h or 0) * s.max_hours_per_day
            total += daily * 365
    return cap, total


def _pump_efficiency(farm: Farm) -> float:
    for e in farm.equipment:
        if e.kind == "pump" and e.specs.get("efficiency"):
            return float(e.specs["efficiency"])
    return 0.5   # typical wire-to-water efficiency of small submersible pumps (estimated)


def _source_pump_kw(farm: Farm, src) -> float | None:
    """Rated electrical power of the pump installed on this source (declared by the farmer)."""
    for e in farm.equipment:
        if e.kind == "pump" and e.specs.get("power_kw") and e.specs.get("source_id") == src.id:
            return float(e.specs["power_kw"])
    pumps = [e for e in farm.equipment if e.kind == "pump" and e.specs.get("power_kw") and not e.specs.get("source_id")]
    if len(pumps) == 1 and len([s for s in farm.water_sources if s.authorized]) == 1:
        return float(pumps[0].specs["power_kw"])
    return None


def inputs_fingerprint(farm: Farm) -> str:
    """Hash of every farm input used by AgroBrain: a plan whose fingerprint differs is out of date."""
    import hashlib
    import json
    data = {
        "b": farm.boundary_geojson, "x": farm.exclusions_geojson, "m": farm.irrigation_method, "s": farm.soil,
        "season": farm.season, "gov": farm.governorate_code, "lat": farm.latitude, "lon": farm.longitude,
        "budget": farm.budget_tnd, "existing": farm.existing_crops,
        "prefs": {k: v for k, v in (farm.preferences or {}).items() if k != "entrance"},
        "w": sorted([[w.kind, round(w.latitude, 6), round(w.longitude, 6), w.flow_m3h, w.daily_volume_m3,
                      w.annual_quota_m3, w.pumping_depth_m, w.max_hours_per_day, w.salinity_ds_m, w.authorized]
                     for w in farm.water_sources], key=str),
        "e": sorted([[e.kind, {k: v for k, v in (e.specs or {}).items() if k != "source_id"}] for e in farm.equipment],
                    key=str),
    }
    return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()[:16]


MAX_SECTORS = 24


def zone_label(i: int) -> str:
    """A, B, ... Z, AA, AB ..."""
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def climate_stats(db: Session, farm: Farm, today: date) -> dict | None:
    """Cached multi-year statistics (ERA5) used for frost-aware planting; None if unreachable."""
    lat, lon = _centroid(farm)
    try:
        prof = climate_conn.climate_profile(db, lat, lon, today)
    except Exception:   # network problems must not block the plan; the plan says it is missing
        return None
    return prof.get("statistics")


def _pump_power_rating(farm: Farm) -> float | None:
    vals = [float(e.specs["power_kw"]) for e in farm.equipment if e.kind == "pump" and e.specs.get("power_kw")]
    return sum(vals) if vals else None


def _why(code: str, o, d: dict, score: dict) -> list[dict]:
    """Human-readable justification of a crop choice (keys translated by the UI)."""
    out = [{"key": "suitable_here", "data": {"relative_yield": round(o.relative_yield, 2)}},
           {"key": "water_productivity", "data": {"kg_m3": score.get("water_productivity_kg_m3")}},
           {"key": "national_need", "data": {"priority_pct": round(100 * o.national_priority)}},
           {"key": "yield_source", "data": {"quality": d["yield_quality"]}}]
    if score.get("margin_tnd_ha") is not None:
        out.append({"key": "margin", "data": {"tnd_ha": score["margin_tnd_ha"]}})
    for r in d["suitability"]["reasons"]:
        out.append({"key": f"constraint_{r}", "data": {}})
    return out


RAINFED_MIN_HA = 0.05               # no rainfed parcels on slivers of land
RAINFED_MIN_RELATIVE_YIELD = 0.5    # below half of the potential yield a rainfed crop is not proposed
DAYS_M = [31, 28.25, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]


def _cold_crops(db, options, details, res, productive_ha, cap, quota, budget, large):
    """One or two fresh crops to keep in cold storage until the national off-season (see cold_store).
    If the optimised plan has none, the best storable crop is imposed with a minimum area, halved
    while water (or land) makes it infeasible."""
    min_weeks = float(policy.get(db, "storage.offseason_min_weeks") or 8)
    cands = {o.code: details[o.code]["water_plan"].harvest for o in options if o.code in details}
    ranked = cold_store.rank(cands, national.national_balance(db).get("items", []), min_weeks)
    in_plan = [r for r in ranked if res.areas_ha.get(r["crop"], 0) > 0]
    forced = None
    if ranked and not in_plan:
        top = ranked[0]
        opt = next(o for o in options if o.code == top["crop"])
        old, f = opt.locked_ha, min(0.05 * productive_ha, COLD_FORCED_MAX_HA)
        for _ in range(6):
            opt.locked_ha = max(old, f)
            r2 = optimizer.optimize(options, productive_ha, cap, quota, budget, large)
            if r2.status != "infeasible" and r2.areas_ha.get(top["crop"], 0) > 0:
                res, forced = r2, {"crop": top["crop"], "min_ha": round(f, 2)}
                break
            f /= 2
        opt.locked_ha = old
        in_plan = [r for r in ranked if res.areas_ha.get(r["crop"], 0) > 0]
    chosen = in_plan[:2]
    info = {"required": True, "min_weeks": min_weeks, "ranked": ranked[:6], "forced": forced,
            "chosen": [c["crop"] for c in chosen], "offseason": chosen,
            "reason": None if chosen else ("no_storable_crop" if not ranked else "water_insufficient")}
    return res, info


COLD_FORCED_MAX_HA = 10.0


def _pipeline(farm, srcs, clim, hyd, suit, cap, quota, res, rres, options, geo, parcel_rows, plan, totals, method,
              stats) -> dict:
    """Real figures of every step: inputs -> models -> optimised plan (shown above the two panels)."""
    pu = farm.plan_upload or {}
    ext = pu.get("extraction") or {}
    months12 = sorted(cap)[:12]
    cap_year = round(sum(cap[m] for m in months12), 0) if cap else 0.0
    prod_ha = geo["productive_area_m2"] / 1e4
    irr_ha = sum(res.areas_ha.values())
    used = sum(res.water_use_m3.values())
    # water the chosen irrigated crop mix would need on the whole productive area
    land_ha = irr_ha + res.unused_ha            # cultivable land offered to the optimiser
    need_full = round(used / irr_ha * land_ha, 0) if irr_ha > 0 and used > 0 else None
    excluded: dict[str, int] = {}
    for sres in suit.values():
        if not sres.suitable:
            for r in sres.reasons or ["other"]:
                excluded[r] = excluded.get(r, 0) + 1
    frost = sorted(m["month"] for m in (stats or {}).get("months", []) if m["frost_probability"] >= 0.2)
    limits = [b for b in res.binding if b in ("quota", "land", "budget") or b.startswith("water_")]
    ring = (farm.boundary_geojson or {}).get("coordinates", [[]])[0]
    return {
        "inputs": {"source": "plan_file" if pu.get("parsed") else "map", "method": ext.get("method"),
                   "vertices": max(0, len(ring) - 1), "area_ha": farm.measured_area_ha,
                   "location_quality": (pu.get("location") or {}).get("quality", "user"),
                   "sources": len(srcs), "flow_m3h": [s.flow_m3h for s in srcs],
                   "daily_m3": round(sum(s.daily_volume_m3 or 0 for s in srcs), 1) or None, "quota_m3": quota,
                   "pumps_kw": [e.specs.get("power_kw") for e in farm.equipment if e.kind == "pump"],
                   "pv_kwc": sum(float(e.specs.get("kwp", 0)) for e in farm.equipment if e.kind == "pv") or None,
                   "irrigation_method": method},
        "climate": {"source": clim.source, "rain_mm": round(sum(clim.rain_mm), 0),
                    "et0_mm": round(sum(v * d for v, d in zip(clim.et0_mm_day, DAYS_M)), 0),
                    "frost_months": frost, "statistics": bool(stats)},
        "soil": {"texture": hyd.texture, "source": hyd.source},
        "suitability": {"evaluated": len(suit), "suitable": sum(1 for x in suit.values() if x.suitable),
                        "excluded": excluded},
        "water": {"annual_capacity_m3": cap_year, "quota_m3": quota, "need_full_irrigation_m3": need_full,
                  "used_m3": round(sum(res.water_use_m3.values()), 0), "limits": limits},
        "optimisation": {"irrigated_ha": round(sum(res.areas_ha.values()), 3),
                         "rainfed_ha": round(sum(rres.areas_ha.values()), 3) if rres else 0.0,
                         "crops": len(res.areas_ha) + (len(rres.areas_ha) if rres else 0),
                         "unused_ha": round(rres.unused_ha if rres else res.unused_ha, 3)},
        "partition": {"parcels": len(parcel_rows), "productive_ha": round(prod_ha, 3), "cultivable_ha": round(land_ha, 3),
                      "infrastructure_ha": round(geo["infrastructure_area_m2"] / 1e4, 3)},
        "irrigation": {"season_m3": round(totals["water_m3"], 0),
                       "conflicts": sum(w.get("conflicts", 0) for w in plan.irrigation.get("weeks", {}).values())},
        "energy": {"pump_kwh": round(totals["energy_kwh"], 0),
                   "pv_kwc_recommended": (plan.energy or {}).get("kwp_needed")},
    }


def generate_plan(db: Session, farm: Farm, locked: list[dict] | None = None, today: date | None = None) -> Plan:
    today = today or date.today()
    if not farm.boundary_geojson:
        raise PlanningError("no_boundary")
    if not farm.area_validated:
        raise PlanningError("area_not_validated")
    method = farm.irrigation_method or "drip"
    eff = IRRIGATION_EFFICIENCY.get(method, 0.75)
    prefs = farm.preferences or {}
    clim = climate_for(db, farm)
    soil = soil_for(db, farm)
    hyd = fao56.soil_from_farm(soil)
    srcs = [s for s in farm.water_sources if s.authorized]
    water_ec = max([s.salinity_ds_m for s in srcs if s.salinity_ds_m] or [0]) or None
    existing = {c.get("crop") if isinstance(c, dict) else c for c in (farm.existing_crops or [])}
    suit = evaluate_all(clim, soil, water_ec, farm.season or "annual", bool(prefs.get("allow_new_orchards")), existing)
    stats = climate_stats(db, farm, today)
    priorities = national.national_priority(db)
    pol_large = {"large_farm_min_ha": policy.get(db, "farms.large_farm_min_ha"),
                 "large_farm_min_boreholes": policy.get(db, "farms.large_farm_min_boreholes")}
    n_bh = sum(1 for s in srcs if s.kind in ("borehole", "well"))
    area_ha = farm.measured_area_ha or partition.area_m2(farm.boundary_geojson) / 1e4
    large = storage.is_large_farm(area_ha, n_bh, pol_large)
    cold_min_ha = policy.get(db, "storage.cold_building_min_ha")
    cold_required = cold_min_ha is not None and area_ha > float(cold_min_ha)

    locked = locked or []
    locked_area: dict[str, float] = {}
    for lp in locked:
        locked_area[lp["crop"]] = locked_area.get(lp["crop"], 0.0) + partition.area_m2(lp["geometry"]) / 1e4

    # --- crop options ----------------------------------------------------
    options, details, missing = [], {}, []
    for code, s in suit.items():
        if not s.suitable and code not in locked_area:
            continue
        y, yq = _yield_for(db, farm, code)
        if y is None:
            missing.append(f"yield:{code}")
            continue
        c = CROPS[code]
        planting, planting_rule = crop_calendar.choose_planting(c, today, stats)
        rainfed = bool(prefs.get("rainfed_crops", [])) and code in prefs.get("rainfed_crops", [])
        wp = fao56.crop_water_plan(c, planting, clim, rainfed=rainfed)
        lr = leaching_requirement(water_ec, c, method)
        monthly = {m: v * 10 / eff / (1 - lr) for m, v in wp.monthly_net_mm.items()}
        price, cost = _price_cost(db, farm, code)
        options.append(optimizer.CropOption(code, y, s.relative_yield, monthly, priorities.get(code, 0.3), price, cost,
                                            locked_area.get(code, 0.0)))
        details[code] = {"planting": planting, "water_plan": wp, "yield_quality": yq, "leaching": lr,
                         "suitability": s.__dict__, "price": price, "cost": cost,
                         "planting_rule": planting_rule}
    if not options:
        raise PlanningError("no_suitable_crop", {"missing": missing})
    if not srcs:
        # no irrigation source: only rainfed-possible crops with zero irrigation
        options = [o for o in options if CROPS[o.code].rainfed_possible]
        for o in options:
            o.gross_m3_ha_monthly = {k: 0.0 for k in o.gross_m3_ha_monthly}
    cap, quota = _monthly_capacity(farm, today.year)
    if not srcs:
        cap, quota = {}, None   # rainfed-only plan: irrigation needs are already zero, no water constraint

    # --- productive area from the real geometry ----------------------------
    pts = [partition.Source(s.id, s.longitude, s.latitude, s.flow_m3h or s.daily_volume_m3 or 1.0) for s in srcs]
    # sector size grows with the farm so that a big terrain gives a readable plan (~MAX_SECTORS sectors),
    # never below the hydraulic size used on small farms
    psettings = partition.PartitionSettings(sector_max_ha=max(4.0 if large else 1.0, area_ha / MAX_SECTORS))
    dry = partition.partition(farm.boundary_geojson, {"_probe": 1e12}, {"_probe": 1}, pts, farm.exclusions_geojson,
                              [(lp["crop"], lp["geometry"]) for lp in locked], psettings)
    productive_ha = sum(p["area_m2"] for p in dry["parcels"]) / 1e4
    productive_ha += sum(locked_area.values())

    res = optimizer.optimize(options, productive_ha, cap, quota, farm.budget_tnd, large)
    if res.status == "infeasible":
        raise PlanningError("optimisation_infeasible")
    cold_info = None
    if cold_required:
        res, cold_info = _cold_crops(db, options, details, res, productive_ha, cap, quota, farm.budget_tnd, large)
        cold_info["threshold_ha"] = float(cold_min_ha)
    # --- land that water cannot irrigate -> rainfed crops (FAO-33 water-yield response) ----------------
    rres = None
    rainfed_opts: list[optimizer.CropOption] = []
    if res.unused_ha > RAINFED_MIN_HA:
        for code, sres in suit.items():
            c = CROPS[code]
            if not sres.suitable or not c.rainfed_possible or code in res.areas_ha or c.perennial:
                continue
            y, yq = _yield_for(db, farm, code)
            if y is None:
                continue
            planting, planting_rule = crop_calendar.choose_planting(c, today, stats)
            wp = fao56.crop_water_plan(c, planting, clim, rainfed=True)
            bal = fao56.rainfed_balance(c, planting, clim, hyd.taw_mm_per_m)   # FAO-56 ch. 8 soil water balance
            ratio = min(1.0, bal["ratio"])
            ya_ym = 1 - c.ky * (1 - ratio)                     # FAO-33: 1 - Ya/Ym = Ky (1 - ETa/ETm)
            if ya_ym < RAINFED_MIN_RELATIVE_YIELD:
                continue
            price, cost = _price_cost(db, farm, code)
            rainfed_opts.append(optimizer.CropOption(code, y, sres.relative_yield * ya_ym,
                                                     {m: 0.0 for m in wp.monthly_net_mm}, priorities.get(code, 0.3),
                                                     price, cost))
            details[code] = {"planting": planting, "water_plan": wp, "yield_quality": yq, "leaching": 0.0,
                             "suitability": sres.__dict__, "price": price, "cost": cost, "planting_rule": planting_rule,
                             "rainfed": True, "rain_cover": round(ratio, 2), "ya_ym": round(ya_ym, 2)}
        if rainfed_opts:
            room = max(1, (7 if large else 4) - len(res.areas_ha))
            rres = optimizer.optimize(rainfed_opts, res.unused_ha, {}, None, None, large, max_crops=room,
                                      max_share=1.0 if len(rainfed_opts) == 1 else 0.6)
            if rres.status == "infeasible":
                rres = None
    options = options + [o for o in rainfed_opts if rres and o.code in rres.areas_ha]
    all_areas = {**res.areas_ha, **(rres.areas_ha if rres else {})}
    unused_ha = rres.unused_ha if rres else res.unused_ha
    free_targets = {c: max(0.0, a - locked_area.get(c, 0.0)) * 1e4 for c, a in all_areas.items()}
    intensity = {o.code: o.gross_m3_ha for o in options}
    pol = policy.energy_policy(db)
    lat, lon = _centroid(farm)
    pv, pv_error = None, None
    try:
        pv = sources.fetch_pv_profile(db, round(lat, 2), round(lon, 2))
    except ConnectorError as e:
        pv_error = str(e)
    offseason_share = float(policy.get(db, "storage.offseason_share_pct") or 0) / 100
    cold_backup_h = float(policy.get(db, "storage.cold_backup_hours") or 0)
    g_specs = next((e.specs for e in farm.equipment if e.kind == "grid"), None)
    grid_state = "unknown" if g_specs is None else ("yes" if g_specs.get("available") else "no")
    cold_site = None
    if cold_info and cold_info["chosen"]:
        prod_est = {o.code: all_areas.get(o.code, 0.0) * o.production_kg_ha / 1000 for o in options}
        cold_periods = {o["crop"]: (date.fromisoformat(o["farm_harvest"]), date.fromisoformat(o["sell_until"]))
                        for o in cold_info["offseason"]}
        est_rooms = cold_store.building_rooms(
            [(c, prod_est.get(c, 0.0) * offseason_share, *cold_periods[c]) for c in cold_info["chosen"]],
            clim.tmax_c)
        est_energy = cold_store.size_energy(est_rooms, pv["profile_kwh_per_kwp"] if pv else None, pol,
                                            grid=grid_state, backup_h=cold_backup_h)
        ent = prefs.get("entrance") or {}
        anchor = ((ent["lon"], ent["lat"]) if ent.get("lat") is not None else
                  (srcs[0].longitude, srcs[0].latitude) if srcs else (lon, lat))
        cold_site = cold_store.site(farm.boundary_geojson, farm.exclusions_geojson, anchor,
                                    cold_store.rooms_floor_m2(est_rooms) * cold_store.FOOTPRINT_FACTOR,
                                    est_energy.get("pv_area_m2") or 0.0)
        if cold_site is None:
            cold_info["site_error"] = "no_room_for_building"
    plan_exclusions = cold_store.merge_exclusions(farm.exclusions_geojson,
                                                  cold_site["exclusion"] if cold_site else None)
    geo = partition.partition(farm.boundary_geojson, {k: v for k, v in free_targets.items() if v > 1},
                              intensity, pts, plan_exclusions,
                              [(lp["crop"], lp["geometry"]) for lp in locked], psettings)

    # --- per-parcel metrics ------------------------------------------------
    pump_eff = _pump_efficiency(farm)
    slope = (soil.get("slope_pct") or 0) / 100
    opt_by = {o.code: o for o in options}
    version = (db.scalar(select(func.max(Plan.version)).where(Plan.farm_id == farm.id)) or 0) + 1
    plan = Plan(farm_id=farm.id, version=version, status="proposed")
    db.add(plan)
    db.flush()
    parcel_rows, irr_parcels = [], []
    pump_kwh_by_month = [0.0] * 12
    totals = {"production_kg": {}, "water_m3": 0.0, "energy_kwh": 0.0, "cost_tnd": 0.0, "revenue_tnd": 0.0}
    costs_known = revenue_known = True
    ordered = sorted(geo["parcels"], key=lambda x: (x["source_index"], x["pipe_length_m"]))
    crop_m2: dict[str, float] = {}
    for p in ordered:
        crop_m2[p["crop"]] = crop_m2.get(p["crop"], 0.0) + p["area_m2"]
    zone_of = {c: zone_label(k) for k, c in enumerate(sorted(crop_m2, key=lambda c: -crop_m2[c]))}
    n_sectors = {c: sum(1 for p in ordered if p["crop"] == c) for c in crop_m2}
    seen: dict[str, int] = {}
    for p in ordered:
        code = p["crop"]
        o, d = opt_by[code], details[code]
        a_ha = p["area_m2"] / 1e4
        rainfed = bool(d.get("rainfed"))
        src = srcs[p["source_index"]] if (srcs and not rainfed) else None
        wp = d["water_plan"]
        gross_monthly = {m: v * a_ha for m, v in o.gross_m3_ha_monthly.items()}
        season_m3 = sum(gross_monthly.values())
        pumping_note = None
        rated_kw = _source_pump_kw(farm, src) if src else None
        if src and src.flow_m3h:
            pp = pumping_point(src.flow_m3h, p["pipe_length_m"], src.pumping_depth_m, slope * p["pipe_length_m"],
                               EMITTER_PRESSURE_M.get(method, 10.0), pump_eff)
            se = pp.specific_energy_kwh_m3
            if rated_kw:
                # the installed pump draws its rated power while delivering the measured flow
                se = round(rated_kw / src.flow_m3h, 4)
        elif src:
            # flow not given: friction losses cannot be computed -> lower bound of the pumping energy
            head = (src.pumping_depth_m or 0) + slope * p["pipe_length_m"] + EMITTER_PRESSURE_M.get(method, 10.0)
            pp = None
            se = round(9.81 * head / 3600 / pump_eff, 4)
            pumping_note = {"flow_unknown": True, "head_min_m": round(head, 1),
                            "depth_unknown": not src.pumping_depth_m, "energy": "minimum"}
        else:
            pp, se = None, 0.0
        kwh = season_m3 * se
        for m, v in gross_monthly.items():
            pump_kwh_by_month[int(m[5:]) - 1] += v * se
        prod = a_ha * o.production_kg_ha
        totals["production_kg"][code] = totals["production_kg"].get(code, 0.0) + prod
        totals["water_m3"] += season_m3
        totals["energy_kwh"] += kwh
        cost = a_ha * d["cost"] if d["cost"] is not None else None
        rev = prod * d["price"] if d["price"] is not None else None
        costs_known &= cost is not None
        revenue_known &= rev is not None
        totals["cost_tnd"] += cost or 0
        totals["revenue_tnd"] += rev or 0
        taw = hyd.taw_mm_per_m * CROPS[code].root_depth_m[1]
        peak_gross_mm = wp.peak_etc_mm_day / eff
        interval = 1 if method == "drip" else max(1, int(fao56.adjusted_p(CROPS[code].p, wp.peak_etc_mm_day) * taw /
                                                          max(wp.peak_etc_mm_day, 0.1)))
        seen[code] = seen.get(code, 0) + 1
        zone = zone_of[code]
        label = zone if n_sectors[code] == 1 else f"{zone}{seen[code]}"
        metrics = {
            "zone": zone, "sector": seen[code], "sectors": n_sectors[code],
            "area_ha": round(a_ha, 4), "production_kg": round(prod, 0), "yield_kg_ha": round(o.production_kg_ha, 0),
            "yield_quality": d["yield_quality"], "relative_yield": o.relative_yield,
            "planting": d["planting"].isoformat(), "harvest": wp.harvest.isoformat(),
            "etc_mm": wp.etc_mm, "peff_mm": wp.peff_mm, "net_irrigation_mm": wp.net_irrigation_mm,
            "water_m3_season": round(season_m3, 1), "water_litres_season": round(season_m3 * 1000, 0),
            "water_m3_monthly": {k: round(v, 1) for k, v in gross_monthly.items() if v > 0},
            "energy_kwh_season": round(kwh, 1), "specific_energy_kwh_m3": se,
            "pumping": pp.__dict__ if pp else pumping_note, "leaching_fraction": round(d["leaching"], 3),
            "irrigation": {"method": method, "interval_days": interval,
                           "peak_dose_mm": round(peak_gross_mm * interval, 1),
                           "peak_volume_m3": round(peak_gross_mm * interval * p["area_m2"] / 1000, 1),
                           "peak_duration_min": round(60 * peak_gross_mm * interval * p["area_m2"] / 1000 /
                                                      src.flow_m3h) if (src and src.flow_m3h) else None},
            "cost_tnd": None if cost is None else round(cost, 0), "revenue_tnd": None if rev is None else round(rev, 0),
            "margin_tnd": round(rev - cost, 0) if (rev is not None and cost is not None) else None,
            "suitability_reasons": d["suitability"]["reasons"], "climate_source": clim.source,
            "pipe": None if rainfed else p.get("pipe"), "distance_m": None if rainfed else p.get("pipe_length_m"),
            "rainfed": rainfed, "rain_cover": d.get("rain_cover"), "ya_ym": d.get("ya_ym"),
            "source_name": (src.name or f"F{farm.water_sources.index(src) + 1}") if src else None, "pump_kw_rated": rated_kw,
            "pump_kw": rated_kw or (pp.power_kw if pp else None),
            "planting_rule": d["planting_rule"],
            "why": _why(code, o, d, res.scores.get(code, {})),
        }
        parcel = Parcel(plan_id=plan.id, label=label, crop_code=code, geometry_geojson=p["geometry"],
                        area_m2=p["area_m2"], locked=p.get("locked", False), water_source_id=src.id if src else None,
                        metrics=metrics)
        db.add(parcel)
        parcel_rows.append(parcel)
        if src:
            irr_parcels.append(irrigation.ParcelIrrigation(
                label, code, p["area_m2"], d["planting"], p["source_index"], src.flow_m3h,
                rated_kw or (pp.power_kw if pp else None), se,
                hyd.taw_mm_per_m, d["leaching"]))

    # --- energy, storage, contribution -----------------------------------
    existing_pv = sum(float(e.specs.get("kwp", 0)) for e in farm.equipment if e.kind == "pv") or None
    existing_bat = sum(float(e.specs.get("kwh", 0)) for e in farm.equipment if e.kind == "battery") or None

    prod_t = {k: v / 1000 for k, v in totals["production_kg"].items()}
    nat_prod = {k: (forecast.mean_last(db, "FAOSTAT_QCL", "production_t", k)) for k in prod_t}
    contrib = None
    rooms = []
    if large:
        reserve_days = float(policy.get(db, "planning.reserve_days") or 0)
        bal = {i["crop"]: i for i in national.national_balance(db).get("items", [])}
        targets = {k: bal[k]["reserve_target_kt"] * 1000 for k in prod_t if k in bal and bal[k]["reserve_target_kt"]}
        water_need = sum(res.water_use_m3.values()) or 1.0
        water_avail = sum(cap[m] for m in res.water_use_m3) if res.water_use_m3 else 0.0
        contrib = storage.contribution(prod_t, nat_prod, targets, productive_ha / max(area_ha, 1e-6),
                                       water_avail / water_need, len(srcs) / max(1, len(farm.water_sources)),
                                       float(policy.get(db, "farms.contribution_cap_pct")) / 100)
        contrib["reserve_days"] = reserve_days
        for code, it in contrib["items"].items():
            if it["storage"] == "cold_room" and it["proposed_t"] > 0:
                rooms.append(storage.cold_room(code, it["proposed_t"], clim.tmax_c,
                                               cost_tnd_m3=policy.get(db, "storage.cold_room_cost_tnd_m3")))
    share = float(prefs.get("cold_room_share_pct") or 0)
    if share > 0:
        for code, t in prod_t.items():
            if CROPS[code].storage.cold and not any(r["crop"] == code for r in rooms):
                rooms.append(storage.cold_room(code, t * share / 100, clim.tmax_c,
                                               cost_tnd_m3=policy.get(db, "storage.cold_room_cost_tnd_m3")))
    rooms = [r for r in rooms if r.get("required")]
    # off-season cold building (farms > storage.cold_building_min_ha): own rooms and dedicated solar plant
    building_rooms = []
    pump_for_design = list(pump_kwh_by_month)
    if cold_info and cold_info["chosen"]:
        building_rooms = cold_store.building_rooms(
            [(c, prod_t[c] * offseason_share, *cold_periods[c]) for c in cold_info["chosen"] if prod_t.get(c)],
            clim.tmax_c, policy.get(db, "storage.cold_room_cost_tnd_m3"))
        rooms = [r for r in rooms if r["crop"] not in cold_info["chosen"]]
        ce = cold_store.size_energy(building_rooms, pv["profile_kwh_per_kwp"] if pv else None, pol,
                                    grid=grid_state, pump_kwh_month=pump_kwh_by_month, backup_h=cold_backup_h)
        # daytime PV surplus of the cold building runs the irrigation pumps of the same month
        if ce.get("status") == "ok":
            pump_for_design = [max(0.0, a - b) for a, b in zip(pump_kwh_by_month, ce["pumps_from_surplus_kwh_month"])]
        vols: dict[int, float] = {}
        for r in building_rooms:
            vols[r["room_id"]] = max(vols.get(r["room_id"], 0.0), r["volume_m3"])
        cold_info.update(
            share_pct=round(offseason_share * 100, 1), rooms=[r["crop"] for r in building_rooms],
            stored_t={r["crop"]: r["mass_t"] for r in building_rooms},
            physical_rooms=len(vols), volume_m3=round(sum(vols.values()), 0),
            rooms_floor_m2=round(cold_store.rooms_floor_m2(building_rooms), 0),
            site={k: v for k, v in (cold_site or {}).items() if k != "exclusion"} or None, energy=ce)
    cold_kw_month = [0.0] * 12
    for r in rooms:
        for m in r["monthly"]:
            cold_kw_month[m["month"] - 1] += m["electric_kwh_day"] / 24
    # critical loads kept alive during a grid outage: cold rooms + any load declared by the farmer
    critical_kw = (max(cold_kw_month) if rooms else 0.0) + float(prefs.get("critical_load_kw") or 0)
    energy_out: dict = {"pump_kwh_month": [round(v, 1) for v in pump_kwh_by_month],
                        "pump_kwh_from_cold_pv": round(sum(pump_kwh_by_month) - sum(pump_for_design), 0),
                        "cold_kw_month": [round(v, 2) for v in cold_kw_month],
                        "pump_rated_kw": _pump_power_rating(farm), "grid": next((e.specs for e in farm.equipment
                                                                                  if e.kind == "grid"), None)}
    if pv:
        design = energy_eng.design(pump_for_design, cold_kw_month, float(prefs.get("other_load_kw") or 0),
                                   critical_kw, pv["profile_kwh_per_kwp"], pol, existing_pv, existing_bat)
        energy_out.update(design)
        energy_out["pv_source"] = {k: pv[k] for k in ("source", "years", "radiation_db", "tilt_deg",
                                                      "annual_kwh_per_kwp", "quality")}
    else:
        energy_out["status"] = "pvgis_unavailable"
        energy_out["error"] = pv_error

    # --- irrigation timetable ----------------------------------------------
    pv_kw = None
    if pv and energy_out.get("kwp_simulated"):
        k = energy_out["kwp_simulated"]
        pv_kw = [[k * v * pol.inverter_eff for v in row] for row in pv["profile_kwh_per_kwp"]]
    weeks = {}
    try:
        fc = sources.fetch_forecast(lat, lon)
        next_days, next_quality = fc["days"], "forecast"
    except ConnectorError:
        next_days = irrigation.climatology_days(today, 7, clim.et0_mm_day, clim.rain_mm)
        next_quality = "estimated"
    weeks["next_7_days"] = {**irrigation.plan_week(irr_parcels, method, next_days, pv_kw), "quality": next_quality,
                            "start": next_days[0]["date"] if next_days else today.isoformat()}
    # first week with all crops active: typical (climatology) week at the farm's peak month
    if irr_parcels:
        peak_month = max(range(12), key=lambda m: pump_kwh_by_month[m]) + 1
        start = date(today.year if peak_month >= today.month else today.year + 1, peak_month, 8)
        if any(s.planting > start for s in irr_parcels):
            start = max(s.planting for s in irr_parcels) + timedelta(days=40)
        weeks["peak_week"] = {**irrigation.plan_week(irr_parcels, method, irrigation.climatology_days(
            start, 7, clim.et0_mm_day, clim.rain_mm), pv_kw), "quality": "estimated", "start": start.isoformat()}
    seasonal: dict[str, dict] = {}
    for pr in parcel_rows:
        for m, v in pr.metrics["water_m3_monthly"].items():
            s = seasonal.setdefault(m, {"m3": 0.0, "kwh": 0.0, "parcels": []})
            s["m3"] = round(s["m3"] + v, 1)
            s["kwh"] = round(s["kwh"] + v * pr.metrics["specific_energy_kwh_m3"], 1)
            s["parcels"].append(pr.label)
    plan.irrigation = {"method": method, "efficiency": eff, "weeks": weeks,
                       "seasonal": dict(sorted(seasonal.items())),
                       "soil": {"texture": hyd.texture, "theta_fc": round(hyd.theta_fc, 3),
                                "theta_wp": round(hyd.theta_wp, 3), "source": hyd.source}}
    plan.energy = energy_out
    plan.storage = {"rooms": building_rooms + rooms, "cold_building": cold_info, "dry_storage_t": {k: round(v, 2) for k, v in prod_t.items()
                                                       if not CROPS[k].storage.cold}}
    plan.contribution = contrib or {"status": "not_large_farm"}
    plan.infrastructure_geojson = geo["infrastructure"]
    sources_used = sorted({clim.source, hyd.source, *(d["yield_quality"] for d in details.values())})
    plan.summary = {
        "large_farm": large, "rainfed_only": not srcs, "field_area_ha": round(geo["field_area_m2"] / 1e4, 4),
        "productive_area_ha": round(geo["productive_area_m2"] / 1e4, 4),
        "infrastructure_area_ha": round(geo["infrastructure_area_m2"] / 1e4, 4),
        "unused_area_ha": unused_ha, "optimizer": {"status": res.status, "binding": res.binding,
                                                   "weights": res.weights,
                                                   "scores": {**res.scores, **(rres.scores if rres else {})},
                                                   "areas_ha": all_areas, "irrigated_ha": res.areas_ha,
                                                   "rainfed_ha": rres.areas_ha if rres else {}},
        "production_t": {k: round(v, 2) for k, v in prod_t.items()},
        "water_m3": round(totals["water_m3"], 0), "energy_kwh": round(totals["energy_kwh"], 0),
        "cost_tnd": round(totals["cost_tnd"], 0) if costs_known else None,
        "revenue_tnd": round(totals["revenue_tnd"], 0) if revenue_known else None,
        "water_capacity_m3": {m: round(v, 0) for m, v in cap.items() if m in res.water_use_m3},
        "water_use_m3": res.water_use_m3, "missing": missing, "sources": sources_used,
        "national_priority": {o.code: o.national_priority for o in options},
        "climate": {"et0_mm_day": [round(v, 2) for v in clim.et0_mm_day], "rain_mm": [round(v, 1) for v in
                                                                                       clim.rain_mm],
                    "source": clim.source},
    }
    plan.summary["pipeline"] = _pipeline(farm, srcs, clim, hyd, suit, cap, quota, res, rres, options, geo,
                                         parcel_rows, plan, totals, method, stats)
    if cold_info:
        ce = cold_info.get("energy") or {}
        plan.summary["pipeline"]["cold_store"] = {
            "threshold_ha": cold_info["threshold_ha"], "chosen": cold_info["chosen"],
            "reason": cold_info.get("reason"), "forced": cold_info.get("forced"),
            "volume_m3": cold_info.get("volume_m3"), "annual_kwh": ce.get("annual_kwh"), "kwp": ce.get("kwp"),
            "panels": ce.get("panels"), "solar_coverage_pct": ce.get("solar_coverage_pct")}
    plan.inputs = {"locked": locked, "method": method, "season": farm.season, "today": today.isoformat(),
                   "fingerprint": inputs_fingerprint(farm)}
    if large and contrib and contrib.get("items"):
        db.add(ContributionRequest(farm_id=farm.id, plan_id=plan.id, proposal=contrib))
    db.commit()
    db.refresh(plan)
    return plan
