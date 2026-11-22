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

from app.connectors import sources
from app.connectors.base import ConnectorError
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
    soil = dict(farm.soil or {})
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
    for y in (year, year + 1):
        for m in range(1, 13):
            days = calendar.monthrange(y, m)[1]
            cap[f"{y:04d}-{m:02d}"] = sum(s.flow_m3h * s.max_hours_per_day * days for s in srcs)
    quotas = [s.annual_quota_m3 for s in srcs if s.annual_quota_m3]
    return cap, (sum(quotas) if quotas else None)


def _pump_efficiency(farm: Farm) -> float:
    for e in farm.equipment:
        if e.kind == "pump" and e.specs.get("efficiency"):
            return float(e.specs["efficiency"])
    return 0.5   # typical wire-to-water efficiency of small submersible pumps (estimated)


def _pump_power_rating(farm: Farm) -> float | None:
    vals = [float(e.specs["power_kw"]) for e in farm.equipment if e.kind == "pump" and e.specs.get("power_kw")]
    return sum(vals) if vals else None


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
    priorities = national.national_priority(db)
    pol_large = {"large_farm_min_ha": policy.get(db, "farms.large_farm_min_ha"),
                 "large_farm_min_boreholes": policy.get(db, "farms.large_farm_min_boreholes")}
    n_bh = sum(1 for s in srcs if s.kind in ("borehole", "well"))
    area_ha = farm.measured_area_ha or partition.area_m2(farm.boundary_geojson) / 1e4
    large = storage.is_large_farm(area_ha, n_bh, pol_large)

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
        planting = fao56.default_planting_date(c, today.year, today)
        rainfed = bool(prefs.get("rainfed_crops", [])) and code in prefs.get("rainfed_crops", [])
        wp = fao56.crop_water_plan(c, planting, clim, rainfed=rainfed)
        lr = leaching_requirement(water_ec, c, method)
        monthly = {m: v * 10 / eff / (1 - lr) for m, v in wp.monthly_net_mm.items()}
        price, cost = _price_cost(db, farm, code)
        options.append(optimizer.CropOption(code, y, s.relative_yield, monthly, priorities.get(code, 0.3), price, cost,
                                            locked_area.get(code, 0.0)))
        details[code] = {"planting": planting, "water_plan": wp, "yield_quality": yq, "leaching": lr,
                         "suitability": s.__dict__, "price": price, "cost": cost}
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
    pts = [partition.Source(s.id, s.longitude, s.latitude, s.flow_m3h) for s in srcs]
    psettings = partition.PartitionSettings(sector_max_ha=4.0 if large else 1.0)
    dry = partition.partition(farm.boundary_geojson, {"_probe": 1e12}, {"_probe": 1}, pts, farm.exclusions_geojson,
                              [(lp["crop"], lp["geometry"]) for lp in locked], psettings)
    productive_ha = sum(p["area_m2"] for p in dry["parcels"]) / 1e4
    productive_ha += sum(locked_area.values())

    res = optimizer.optimize(options, productive_ha, cap, quota, farm.budget_tnd, large)
    if res.status == "infeasible":
        raise PlanningError("optimisation_infeasible")
    free_targets = {c: max(0.0, a - locked_area.get(c, 0.0)) * 1e4 for c, a in res.areas_ha.items()}
    intensity = {o.code: o.gross_m3_ha for o in options}
    geo = partition.partition(farm.boundary_geojson, {k: v for k, v in free_targets.items() if v > 1},
                              intensity, pts, farm.exclusions_geojson,
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
    for i, p in enumerate(sorted(geo["parcels"], key=lambda x: (x["source_index"], x["pipe_length_m"]))):
        code = p["crop"]
        o, d = opt_by[code], details[code]
        a_ha = p["area_m2"] / 1e4
        src = srcs[p["source_index"]] if srcs else None
        wp = d["water_plan"]
        gross_monthly = {m: v * a_ha for m, v in o.gross_m3_ha_monthly.items()}
        season_m3 = sum(gross_monthly.values())
        if src:
            pp = pumping_point(src.flow_m3h, p["pipe_length_m"], src.pumping_depth_m, slope * p["pipe_length_m"],
                               EMITTER_PRESSURE_M.get(method, 10.0), pump_eff)
            se = pp.specific_energy_kwh_m3
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
        label = f"P{i + 1}"
        metrics = {
            "area_ha": round(a_ha, 4), "production_kg": round(prod, 0), "yield_kg_ha": round(o.production_kg_ha, 0),
            "yield_quality": d["yield_quality"], "relative_yield": o.relative_yield,
            "planting": d["planting"].isoformat(), "harvest": wp.harvest.isoformat(),
            "etc_mm": wp.etc_mm, "peff_mm": wp.peff_mm, "net_irrigation_mm": wp.net_irrigation_mm,
            "water_m3_season": round(season_m3, 1), "water_litres_season": round(season_m3 * 1000, 0),
            "water_m3_monthly": {k: round(v, 1) for k, v in gross_monthly.items() if v > 0},
            "energy_kwh_season": round(kwh, 1), "specific_energy_kwh_m3": se,
            "pumping": pp.__dict__ if pp else None, "leaching_fraction": round(d["leaching"], 3),
            "irrigation": {"method": method, "interval_days": interval,
                           "peak_dose_mm": round(peak_gross_mm * interval, 1),
                           "peak_volume_m3": round(peak_gross_mm * interval * p["area_m2"] / 1000, 1),
                           "peak_duration_min": round(60 * peak_gross_mm * interval * p["area_m2"] / 1000 /
                                                      src.flow_m3h) if src else None},
            "cost_tnd": None if cost is None else round(cost, 0), "revenue_tnd": None if rev is None else round(rev, 0),
            "margin_tnd": round(rev - cost, 0) if (rev is not None and cost is not None) else None,
            "suitability_reasons": d["suitability"]["reasons"], "climate_source": clim.source,
        }
        parcel = Parcel(plan_id=plan.id, label=label, crop_code=code, geometry_geojson=p["geometry"],
                        area_m2=p["area_m2"], locked=p.get("locked", False), water_source_id=src.id if src else None,
                        metrics=metrics)
        db.add(parcel)
        parcel_rows.append(parcel)
        if src:
            irr_parcels.append(irrigation.ParcelIrrigation(
                label, code, p["area_m2"], d["planting"], p["source_index"], src.flow_m3h, pp.power_kw, se,
                hyd.taw_mm_per_m, d["leaching"]))

    # --- energy, storage, contribution -----------------------------------
    pol = policy.energy_policy(db)
    lat, lon = _centroid(farm)
    pv = None
    try:
        pv = sources.fetch_pv_profile(db, round(lat, 2), round(lon, 2))
    except ConnectorError as e:
        pv_error = str(e)
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
    cold_kw_month = [0.0] * 12
    for r in rooms:
        for m in r["monthly"]:
            cold_kw_month[m["month"] - 1] += m["electric_kwh_day"] / 24
    # critical loads kept alive during a grid outage: cold rooms + any load declared by the farmer
    critical_kw = (max(cold_kw_month) if rooms else 0.0) + float(prefs.get("critical_load_kw") or 0)
    energy_out: dict = {"pump_kwh_month": [round(v, 1) for v in pump_kwh_by_month],
                        "cold_kw_month": [round(v, 2) for v in cold_kw_month],
                        "pump_rated_kw": _pump_power_rating(farm), "grid": next((e.specs for e in farm.equipment
                                                                                  if e.kind == "grid"), None)}
    if pv:
        design = energy_eng.design(pump_kwh_by_month, cold_kw_month, float(prefs.get("other_load_kw") or 0),
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
    plan.storage = {"rooms": rooms, "dry_storage_t": {k: round(v, 2) for k, v in prod_t.items()
                                                       if not CROPS[k].storage.cold}}
    plan.contribution = contrib or {"status": "not_large_farm"}
    plan.infrastructure_geojson = geo["infrastructure"]
    sources_used = sorted({clim.source, hyd.source, *(d["yield_quality"] for d in details.values())})
    plan.summary = {
        "large_farm": large, "rainfed_only": not srcs, "field_area_ha": round(geo["field_area_m2"] / 1e4, 4),
        "productive_area_ha": round(geo["productive_area_m2"] / 1e4, 4),
        "infrastructure_area_ha": round(geo["infrastructure_area_m2"] / 1e4, 4),
        "unused_area_ha": res.unused_ha, "optimizer": {"status": res.status, "binding": res.binding,
                                                       "weights": res.weights, "scores": res.scores,
                                                       "areas_ha": res.areas_ha},
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
    plan.inputs = {"locked": locked, "method": method, "season": farm.season, "today": today.isoformat()}
    if large and contrib and contrib.get("items"):
        db.add(ContributionRequest(farm_id=farm.id, plan_id=plan.id, proposal=contrib))
    db.commit()
    db.refresh(plan)
    return plan
