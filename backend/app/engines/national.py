"""National planning engine (ministry).

Balance per crop c for target year Y (all quantities in kt):
  demand_c      = per-capita domestic supply forecast (kg/cap) x population projection(Y)
  required_c    = demand_c x (1 + safety margin) + exports_planned_c - imports_planned_c
  reserve_c     = demand_c / 365 x reserve_days      (storable crops only)
  expected_c    = yield forecast(Y) x mean harvested area (last 3 FAOSTAT years)
  gap_c         = expected_c - required_c            (< 0 deficit, > 0 surplus)
  hectares_c    = required_c / yield(Y)
Governorate allocation (OR-Tools LP) runs only where land/water capacities are
known (ONAGRI/CRDA import or registered farms). Otherwise the dashboard shows
the per-governorate water needs and suitability as guidance and lists the
missing data — no invented regional split.
"""
from __future__ import annotations

from datetime import date

import numpy as np
from ortools.linear_solver import pywraplp
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.connectors import sources
from app.connectors.base import ConnectorError, series
from app.engines import fao56, forecast, policy
from app.engines.suitability import evaluate
from app.knowledge.crops import CROPS, IRRIGATION_EFFICIENCY
from app.knowledge.governorates import GOVERNORATES, centroids
from app.models import Alert, DataRecord, Farm, Parcel, Plan


def season_of(code: str) -> str:
    c = CROPS[code]
    if c.perennial:
        return "perennial"
    m = c.planting_months[0][0]
    return "autumn_winter" if m >= 8 or m <= 2 else "spring_summer"


def governorate_climates(db: Session, fetch: bool = True) -> dict[str, fao56.MonthlyClimate]:
    out = {}
    for code, (lat, lon) in centroids().items():
        cached = series(db, "NASA_POWER_CLIM", "et0_mm_day", code)
        if len(cached) == 12:
            out[code] = sources.climate_from_db(db, code)
        elif fetch:
            try:
                out[code] = sources.fetch_climate_normals(db, lat, lon, entity=code)
            except ConnectorError:
                continue
    return out


def irrigation_need_m3_ha(code: str, clim: fao56.MonthlyClimate, method: str = "drip") -> float:
    c = CROPS[code]
    year = date.today().year
    planting = date(year, c.planting_months[0][0], 15 if c.planting_months[0][0] == c.planting_months[0][1] else 1)
    wp = fao56.crop_water_plan(c, planting, clim)
    return wp.net_irrigation_mm * 10 / IRRIGATION_EFFICIENCY[method]


def _planned_trade(db: Session, key: str, indicator: str, crop: str) -> tuple[float, str]:
    v = (policy.get(db, key) or {}).get(crop)
    if v is not None:
        return float(v), "policy"
    m = forecast.mean_last(db, "FAOSTAT_FBS", indicator, crop)
    return (m or 0.0), "faostat_3y_mean"


_CACHE: dict[tuple, dict] = {}


def _data_version(db: Session) -> tuple:
    """Changes whenever input data, models or policies change (cache invalidation key)."""
    from app.models import ModelRun, PolicySetting
    return (db.scalar(select(func.count(DataRecord.id))), db.scalar(select(func.max(DataRecord.fetched_at))),
            db.scalar(select(func.max(ModelRun.created_at))), db.scalar(select(func.max(PolicySetting.updated_at))))


def national_balance(db: Session, year: int | None = None, overrides: dict | None = None) -> dict:
    import json as _json
    key = ("balance", year, _json.dumps(overrides or {}, sort_keys=True), _data_version(db))
    if key not in _CACHE:
        if len(_CACHE) > 64:
            _CACHE.clear()
        _CACHE[key] = _national_balance(db, year, overrides)
    return _CACHE[key]


def _national_balance(db: Session, year: int | None = None, overrides: dict | None = None) -> dict:
    """overrides (simulation): population_pct, yield_pct, rain_pct, import_cut_pct, margin_pct, water_pct."""
    ov = overrides or {}
    year = year or int(policy.get(db, "planning.horizon_year"))
    margin = float(ov.get("margin_pct", policy.get(db, "planning.safety_margin_pct"))) / 100
    reserve_days = float(policy.get(db, "planning.reserve_days") or 0)
    pop = forecast.population_series(db)
    if pop.empty:
        return {"status": "no_population_data", "items": []}
    pop_y = float(pop.get(year, pop.iloc[-1])) * (1 + ov.get("population_pct", 0) / 100)
    pop_quality = "official" if year in {int(r.period) for r in series(db, "WB_WDI", "population")} else "forecast"
    elasticities = policy.get(db, "planning.price_elasticity") or {}
    items = []
    clims = governorate_climates(db, fetch=False)
    for code, c in CROPS.items():
        if not c.faostat_fbs:
            continue
        fc = forecast.forecast(db, "demand_per_capita", code, [year])
        yf = forecast.forecast(db, "yield", code, [year])
        if not fc or year not in fc["values"]:
            continue
        per_cap = fc["values"][year]["value"]
        demand = per_cap * pop_y / 1e6
        exp_kt, exp_src = _planned_trade(db, "planning.exports_planned_kt", "export_kt", code)
        imp_kt, imp_src = _planned_trade(db, "planning.imports_planned_kt", "import_kt", code)
        imp_kt *= 1 - ov.get("import_cut_pct", 0) / 100
        required = demand * (1 + margin) + exp_kt - imp_kt
        reserve = demand / 365 * reserve_days if (c.storage.cold or c.category in ("cereal", "legume") or
                                                  code in ("date_palm",)) else 0.0
        area = forecast.mean_last(db, "FAOSTAT_QCL", "area_harvested_ha", code)
        yld = yf["values"][year]["value"] if yf and year in yf["values"] else None
        if yld is not None:
            yld *= 1 + ov.get("yield_pct", 0) / 100
            if c.rainfed_possible and ov.get("rain_pct"):
                # FAO-33: 1 - Ya/Ym = Ky (1 - ETa/ETm); rainfed ETa scales ~ with rainfall deficit
                yld *= max(0.0, 1 - c.ky * max(0.0, -ov["rain_pct"] / 100))
        expected = (yld * area / 1e6) if (yld and area) else None
        gap = (expected - required) if expected is not None else None
        hectares = required * 1e6 / yld if yld else None
        needs = [irrigation_need_m3_ha(code, cl) for cl in clims.values()] if clims else []
        need_med = float(np.median(needs)) * (1 - ov.get("rain_pct", 0) / 100 * 0.3) if needs else None
        water_mm3 = hectares * need_med / 1e6 if (hectares and need_med) else None
        latest_stock = forecast.mean_last(db, "FAOSTAT_FBS", "stock_variation_kt", code)
        pressure = None
        if gap is not None and required > 0:
            ratio = gap / required
            e = elasticities.get(code)
            pressure = {"direction": "down" if ratio > margin else ("up" if ratio < 0 else "stable"),
                        "supply_ratio_pct": round(100 * ratio, 1),
                        "indicative_price_change_pct": round(-100 * ratio / abs(e), 1) if e else None,
                        "note": "indicative_only"}
        items.append({
            "crop": code, "season": season_of(code), "per_capita_kg": round(per_cap, 2),
            "per_capita_quality": fc["values"][year]["quality"], "demand_model": fc["model"],
            "demand_mape_pct": fc["mape_pct"], "demand_kt": round(demand, 1),
            "demand_low_kt": round(fc["values"][year]["low"] * pop_y / 1e6, 1),
            "demand_high_kt": round(fc["values"][year]["high"] * pop_y / 1e6, 1),
            "imports_kt": round(imp_kt, 1), "imports_source": imp_src, "exports_kt": round(exp_kt, 1),
            "exports_source": exp_src, "required_kt": round(required, 1), "reserve_target_kt": round(reserve, 1),
            "expected_production_kt": None if expected is None else round(expected, 1),
            "yield_kg_ha": None if yld is None else round(yld, 0), "yield_model": yf["model"] if yf else None,
            "harvested_area_ha": None if area is None else round(area, 0),
            "gap_kt": None if gap is None else round(gap, 1),
            "hectares_needed": None if hectares is None else round(hectares, 0),
            "irrigation_m3_ha_median": None if need_med is None else round(need_med, 0),
            "water_mm3_if_irrigated": None if water_mm3 is None else round(water_mm3, 1),
            "rainfed_possible": c.rainfed_possible, "stock_variation_kt_3y": latest_stock,
            "price_pressure": pressure,
            "import_dependency_pct": _import_dependency(db, code)})
    return {"status": "ok", "year": year, "population": round(pop_y), "population_quality": pop_quality,
            "safety_margin_pct": round(margin * 100, 2), "reserve_days": reserve_days, "items": items,
            "kcal_per_capita_day": forecast.latest_value(db, "FAOSTAT_FBS", "kcal_cap_day", "_total"),
            "protein_g_per_capita_day": forecast.latest_value(db, "FAOSTAT_FBS", "protein_g_cap_day", "_total"),
            "overrides": ov}


def _import_dependency(db: Session, code: str) -> float | None:
    imp = forecast.mean_last(db, "FAOSTAT_FBS", "import_kt", code)
    dom = forecast.mean_last(db, "FAOSTAT_FBS", "domestic_supply_kt", code)
    if imp is None or not dom:
        return None
    return round(100 * imp / dom, 1)


def national_priority(db: Session) -> dict[str, float]:
    """0..1 priority per crop used by farm optimisation: import dependency (FAOSTAT FBS).
    Crops without a specific food balance get a neutral 0.3 (flagged in the UI)."""
    out = {}
    for code, c in CROPS.items():
        dep = _import_dependency(db, code) if c.faostat_fbs else None
        out[code] = min(1.0, max(0.0, dep / 100)) if dep is not None else 0.3
    return out


def capacities(db: Session) -> dict[str, dict]:
    """Known land/water capacities per governorate: imported official data first, registered farms otherwise."""
    out: dict[str, dict] = {}
    for g in GOVERNORATES:
        land = [r for r in series(db, "MANUAL", "irrigated_area_ha", g) if r.value]
        water = [r for r in series(db, "MANUAL", "water_allocation_mm3", g) if r.value]
        out[g] = {"land_ha": land[-1].value if land else None, "land_source": "import" if land else None,
                  "water_mm3": water[-1].value if water else None, "water_source": "import" if water else None}
    rows = db.execute(select(Farm.governorate_code, func.sum(Farm.measured_area_ha), func.count(Farm.id))
                      .group_by(Farm.governorate_code)).all()
    for g, area, n in rows:
        if g in out:
            out[g]["registered_farms"] = n
            out[g]["registered_area_ha"] = round(area or 0, 2)
            if out[g]["land_ha"] is None and area:
                out[g]["land_ha"] = area
                out[g]["land_source"] = "registered_farms"
    return out


def allocate(db: Session, balance: dict) -> dict:
    caps = capacities(db)
    clims = governorate_climates(db, fetch=False)
    usable = {g: c for g, c in caps.items() if c.get("land_ha") and g in clims}
    if not usable:
        return {"status": "missing_capacities", "governorates": [],
                "missing": ["MANUAL/irrigated_area_ha", "MANUAL/water_allocation_mm3"]}
    items = [i for i in balance["items"] if i["yield_kg_ha"] and i["required_kt"] > 0]
    solver = pywraplp.Solver.CreateSolver("GLOP")
    x, need = {}, {}
    for g in usable:
        for it in items:
            code = it["crop"]
            s = evaluate(CROPS[code], clims[g], {}, None, "annual", True, set())
            if not s.suitable:
                continue
            x[(g, code)] = solver.NumVar(0, solver.infinity(), f"x_{g}_{code}")
            need[(g, code)] = (irrigation_need_m3_ha(code, clims[g]), s.relative_yield)
    for g, cap in usable.items():
        solver.Add(sum(v for (gg, _), v in x.items() if gg == g) <= cap["land_ha"])
        if cap.get("water_mm3"):
            solver.Add(sum(v * need[k][0] for k, v in x.items() if k[0] == g) <= cap["water_mm3"] * 1e6)
    short, over = {}, {}
    for it in items:
        code = it["crop"]
        prod = sum(v * it["yield_kg_ha"] * need[k][1] / 1e6 for k, v in x.items() if k[1] == code)
        short[code] = solver.NumVar(0, solver.infinity(), f"s_{code}")
        over[code] = solver.NumVar(0, solver.infinity(), f"o_{code}")
        solver.Add(prod + short[code] - over[code] == it["required_kt"])
    solver.Minimize(sum(short[c] / max(1.0, i["required_kt"]) * 10 + over[c] / max(1.0, i["required_kt"])
                        for i in items for c in [i["crop"]])
                    + sum(v * need[k][0] * 1e-9 for k, v in x.items()))
    status = solver.Solve()
    if status != pywraplp.Solver.OPTIMAL:
        return {"status": "infeasible", "governorates": []}
    out = []
    for (g, code), v in x.items():
        if v.solution_value() > 0.5:
            it = next(i for i in items if i["crop"] == code)
            out.append({"governorate": g, "crop": code, "season": season_of(code), "hectares": round(v.solution_value()),
                        "production_kt": round(v.solution_value() * it["yield_kg_ha"] * need[(g, code)][1] / 1e6, 2),
                        "water_mm3": round(v.solution_value() * need[(g, code)][0] / 1e6, 2),
                        "land_source": usable[g]["land_source"]})
    return {"status": "ok", "governorates": out,
            "shortfall_kt": {c: round(v.solution_value(), 1) for c, v in short.items() if v.solution_value() > 0.05},
            "capacities_used": usable}


def governorate_guidance(db: Session) -> list[dict]:
    key = ("guidance", _data_version(db))
    if key not in _CACHE:
        _CACHE[key] = _governorate_guidance(db)
    return _CACHE[key]


def _governorate_guidance(db: Session) -> list[dict]:
    clims = governorate_climates(db, fetch=False)
    out = []
    for g, cl in clims.items():
        crops = []
        for code, c in CROPS.items():
            s = evaluate(c, cl, {}, None, "annual", True, set())
            crops.append({"crop": code, "suitable": s.suitable, "relative_yield": s.relative_yield,
                          "irrigation_m3_ha": round(irrigation_need_m3_ha(code, cl)), "reasons": s.reasons})
        out.append({"governorate": g, "annual_rain_mm": round(sum(cl.rain_mm)),
                    "annual_et0_mm": round(sum(e * d for e, d in zip(cl.et0_mm_day, sources.DAYS_IN_MONTH))),
                    "crops": crops, "climate_source": cl.source})
    return out


def platform_production(db: Session) -> dict:
    """Production planned in the latest plan of every registered farm (WAGRI-like sharing)."""
    latest = select(Plan.farm_id, func.max(Plan.version).label("v")).group_by(Plan.farm_id).subquery()
    rows = db.execute(select(Parcel.crop_code, func.sum(Parcel.area_m2), Farm.governorate_code, Parcel.metrics)
                      .join(Plan, Parcel.plan_id == Plan.id).join(Farm, Plan.farm_id == Farm.id)
                      .join(latest, (latest.c.farm_id == Plan.farm_id) & (latest.c.v == Plan.version))
                      .group_by(Parcel.id)).all()
    agg: dict[str, dict] = {}
    for crop, area, g, metrics in rows:
        a = agg.setdefault(crop, {"area_ha": 0.0, "production_t": 0.0, "water_m3": 0.0, "governorates": set()})
        a["area_ha"] += (area or 0) / 1e4
        a["production_t"] += (metrics or {}).get("production_kg", 0) / 1000
        a["water_m3"] += (metrics or {}).get("water_m3_season", 0)
        a["governorates"].add(g)
    return {k: {**v, "governorates": sorted(v["governorates"]), "area_ha": round(v["area_ha"], 2),
                "production_t": round(v["production_t"], 2), "water_m3": round(v["water_m3"], 0)}
            for k, v in agg.items()}


def dams(db: Session) -> list[dict]:
    rows = db.scalars(select(DataRecord).where(DataRecord.dataset == "MANUAL",
                                               DataRecord.indicator.in_(["dam_storage_mm3", "dam_capacity_mm3"])))
    agg: dict[tuple, dict] = {}
    for r in rows:
        d = agg.setdefault((r.entity, r.item), {"governorate": r.entity, "dam": r.item})
        if r.indicator == "dam_storage_mm3":
            if r.period >= d.get("period", ""):
                d["storage_mm3"], d["period"], d["source"] = r.value, r.period, r.source_url
        else:
            d["capacity_mm3"] = r.value
    out = []
    for d in agg.values():
        if d.get("capacity_mm3") and d.get("storage_mm3") is not None:
            d["fill_pct"] = round(100 * d["storage_mm3"] / d["capacity_mm3"], 1)
        out.append(d)
    return out


# ------------------------------------------------------------- alerts ----
def refresh_alerts(db: Session, with_rain: bool = True) -> list[Alert]:
    db.query(Alert).filter(Alert.active.is_(True)).update({"active": False})
    new: list[Alert] = []
    warn = policy.get(db, "alerts.rain_anomaly_warning")
    crit = policy.get(db, "alerts.rain_anomaly_critical")
    if with_rain:
        clims = governorate_climates(db, fetch=False)
        for g, (lat, lon) in centroids().items():
            if g not in clims:
                continue
            try:
                r = sources.fetch_recent_rain_anomaly(lat, lon)
            except ConnectorError as e:
                new.append(Alert(kind="data", severity="info", entity=g, title={"fr": "Pluie récente indisponible",
                                 "ar": "معطيات المطر ما وصلتش"}, detail={"error": str(e)[:200]}))
                break
            start, end = date.fromisoformat(r["start"]), date.fromisoformat(r["end"])
            normal = 0.0
            d = start
            from datetime import timedelta
            while d <= end:
                normal += clims[g].rain_mm[d.month - 1] / 30.4
                d += timedelta(days=1)
            if normal < 20:        # dry season: ratio not meaningful
                continue
            ratio = r["rain_mm"] / normal
            if ratio < warn:
                sev = "critical" if ratio < crit else "warning"
                new.append(Alert(kind="drought", severity=sev, entity=g,
                                 title={"fr": f"Déficit de pluie {GOVERNORATES[g]['fr']} : {round(100 * ratio)} % "
                                              f"de la normale", "ar": f"نقص في المطر في {GOVERNORATES[g]['ar']}: "
                                                                     f"{round(100 * ratio)}٪ من العادة"},
                                 evidence={**r, "normal_mm": round(normal, 1), "ratio": round(ratio, 2),
                                           "quality": "estimated"}))
    for d in dams(db):
        fill = d.get("fill_pct")
        if fill is None:
            continue
        if fill < policy.get(db, "alerts.dam_fill_warning_pct"):
            sev = "critical" if fill < policy.get(db, "alerts.dam_fill_critical_pct") else "warning"
            new.append(Alert(kind="water", severity=sev, entity=d["governorate"], item=d["dam"],
                             title={"fr": f"Barrage {d['dam']} rempli à {fill} %",
                                    "ar": f"السد {d['dam']} معبّي {fill}٪"}, evidence=d))
    bal = national_balance(db)
    for it in bal.get("items", []):
        if it["gap_kt"] is None or not it["required_kt"]:
            continue
        r = it["gap_kt"] / it["required_kt"]
        if r < -0.05:
            new.append(Alert(kind="shortage", severity="critical" if r < -0.15 else "warning", item=it["crop"],
                             title={"fr": f"Déficit prévu {CROPS[it['crop']].name_fr} : {abs(it['gap_kt'])} kt",
                                    "ar": f"نقص متوقع في {CROPS[it['crop']].name_ar}: {abs(it['gap_kt'])} ألف طن"},
                             evidence={"gap_kt": it["gap_kt"], "required_kt": it["required_kt"],
                                       "year": bal["year"], "quality": "forecast"}))
        elif r > bal["safety_margin_pct"] / 100 + 0.10:
            new.append(Alert(kind="surplus", severity="warning", item=it["crop"],
                             title={"fr": f"Surplus prévu {CROPS[it['crop']].name_fr} : +{it['gap_kt']} kt "
                                          "(risque de gaspillage / baisse de prix)",
                                    "ar": f"فايض متوقع في {CROPS[it['crop']].name_ar}: +{it['gap_kt']} ألف طن"},
                             evidence={"gap_kt": it["gap_kt"], "year": bal["year"], "quality": "forecast"}))
    # power: large cold rooms without enough backup autonomy
    for plan in db.scalars(select(Plan).order_by(Plan.id.desc()).limit(500)):
        e = plan.energy or {}
        aut = e.get("autonomy_hours")
        if plan.storage and plan.storage.get("rooms") and (aut is None or aut < 12):
            new.append(Alert(kind="power", severity="warning", entity=plan.farm.governorate_code,
                             item=str(plan.farm_id), title={"fr": f"Chambre froide sans secours suffisant "
                                                                  f"({plan.farm.name})",
                                                            "ar": f"بيت التبريد ما عندوش باتري كافية ({plan.farm.name})"},
                             evidence={"autonomy_hours": aut, "farm_id": plan.farm_id}))
    for a in new:
        db.add(a)
    db.commit()
    return new
