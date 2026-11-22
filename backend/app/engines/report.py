"""Tables shown under the 2D plan (Mon plan agricole), built only from the computed plan.

A. crop allocation   B. optimised irrigation programme   C. crop calendar
D. energy            E. expected results and storage
Values that cannot be computed (missing flow, prices, tariff...) are ``None`` and listed in
``missing`` so the UI shows a warning instead of a number.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date

from app.engines import crop_calendar
from app.knowledge.crops import CROPS

WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def _week_by_zone(week: dict | None) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    for e in (week or {}).get("events", []):
        out[e["parcel"]].append(e)
    return out


def _zone(p) -> str:
    return (p.metrics or {}).get("zone") or p.label


def _sum(vals):
    vals = list(vals)
    return None if any(v is None for v in vals) else round(sum(vals), 1)


def _group(rows: list[dict], keys_sum: list[str]) -> list[dict]:
    """Merge per-sector rows of the same zone (same crop) into one row; sectors kept in ``sectors``."""
    out: dict[str, dict] = {}
    for r in rows:
        g = out.get(r["zone_group"])
        if g is None:
            g = out[r["zone_group"]] = {**r, "zone": r["zone_group"], "sectors": []}
            for k in keys_sum:
                g[k] = []
        g["sectors"].append(r)
        for k in keys_sum:
            g[k].append(r[k])
    for g in out.values():
        for k in keys_sum:
            g[k] = _sum(g[k])
    return list(out.values())


def _energy_by_zone(parcels) -> list[dict]:
    out: dict[str, dict] = {}
    for p in parcels:
        m = p.metrics
        g = out.setdefault(_zone(p), {"zone": _zone(p), "crop": p.crop_code, "kwh": 0.0, "m3": 0.0, "minimum_only": False,
                                      "sectors": 0})
        g["sectors"] += 1
        if g["kwh"] is not None:
            g["kwh"] = None if m.get("energy_kwh_season") is None else g["kwh"] + m["energy_kwh_season"]
        g["m3"] += m.get("water_m3_season") or 0
        g["minimum_only"] |= (m.get("pumping") or {}).get("energy") == "minimum"
    for g in out.values():
        g["kwh_m3"] = round(g["kwh"] / g["m3"], 3) if g["kwh"] is not None and g["m3"] else None
        g["kwh"] = None if g["kwh"] is None else round(g["kwh"], 1)
    return list(out.values())


def build(farm, plan, grid_tariff: float | None = None) -> dict:
    parcels = sorted(plan.parcels, key=lambda p: (len(_zone(p)), _zone(p), (p.metrics or {}).get("sector") or 0))
    total_m2 = sum(p.area_m2 for p in parcels) or 1.0
    field_m2 = (plan.summary.get("field_area_ha") or total_m2 / 1e4) * 1e4
    missing: set[str] = set()
    srcs = {s.id: s for s in farm.water_sources}
    method = plan.irrigation.get("method") or farm.irrigation_method

    # ---------------------------------------------------------------- A
    allocation = []
    for p in parcels:
        m = p.metrics
        s = srcs.get(p.water_source_id)
        allocation.append({
            "zone": p.label, "zone_group": _zone(p), "crop": p.crop_code, "area_ha": round(p.area_m2 / 1e4, 3),
            "pct": round(100 * p.area_m2 / field_m2, 1), "water_m3": m.get("water_m3_season"),
            "production_t": round((m.get("production_kg") or 0) / 1000, 2), "yield_quality": m.get("yield_quality"),
            "irrigation": "rainfed" if (m.get("rainfed") or s is None) else method,
            "rainfed": bool(m.get("rainfed") or s is None),
            "rain_cover": m.get("rain_cover"), "ya_ym": m.get("ya_ym"),
            "source": (s.name or f"F{farm.water_sources.index(s) + 1}") if s else None, "distance_m": m.get("distance_m")})
    allocation = _group(allocation, ["area_ha", "pct", "water_m3", "production_t"])
    for g in allocation:
        g["area_ha"] = round(g["area_ha"], 3)
        g["production_t"] = round(g["production_t"], 2)
        d = [x["distance_m"] for x in g["sectors"] if x["distance_m"] is not None]
        g["distance_m"] = round(min(d)) if d else None
        g["distance_max_m"] = round(max(d)) if d else None
        g["sources"] = sorted({x["source"] for x in g["sectors"] if x["source"]})

    # ---------------------------------------------------------------- B
    weeks = plan.irrigation.get("weeks", {})
    week_key = "peak_week" if weeks.get("peak_week", {}).get("events") else "next_7_days"
    week = weeks.get(week_key) or {}
    by_zone = _week_by_zone(week)
    irrigation = []
    for p in parcels:
        m = p.metrics
        evs = by_zone.get(p.label, [])
        s = srcs.get(p.water_source_id)
        days = sorted({date.fromisoformat(e["date"]).weekday() for e in evs})
        starts = sorted({e["start"] for e in evs if e.get("start")})
        dur = [e["duration_min"] for e in evs if e.get("duration_min") is not None]
        wk_m3 = sum(e["volume_m3"] for e in evs)
        wk_kwh = sum(e["energy_kwh"] for e in evs)
        if s is not None and s.flow_m3h is None:
            missing.add("flow")
        irrigation.append({
            "zone": p.label, "zone_group": _zone(p), "crop": p.crop_code, "source": (s.name or f"F{farm.water_sources.index(s) + 1}") if s else None,
            "rainfed": bool(m.get("rainfed") or s is None), "volume_m3_event": round(wk_m3 / len(evs), 2) if evs else 0.0,
            "events_per_week": len(evs), "interval_days": (m.get("irrigation") or {}).get("interval_days"),
            "days": [WEEKDAYS[d] for d in days], "start": starts[0] if starts else None,
            "starts": starts, "duration_min": round(sum(dur) / len(dur)) if dur else None,
            "duration_unknown": bool(evs) and not dur, "kwh_event": round(wk_kwh / len(evs), 2) if evs else 0.0,
            "week_m3": round(wk_m3, 1), "week_kwh": round(wk_kwh, 1),
            "season_m3": m.get("water_m3_season"), "season_kwh": m.get("energy_kwh_season"),
            "conflict": any(e.get("conflict") for e in evs), "solar_share": (
                round(sum(e.get("solar_share", 0) for e in evs) / len(evs), 2) if evs and any(
                    "solar_share" in e for e in evs) else None)})
    sector_rows = irrigation
    irrigation = _group(irrigation, ["week_m3", "week_kwh", "season_m3", "season_kwh"])
    for g in irrigation:
        sec = g["sectors"]
        ev = [x for x in sec if x["events_per_week"]]
        g["events_per_week"] = max((x["events_per_week"] for x in sec), default=0)
        g["volume_m3_event"] = round(sum(x["volume_m3_event"] for x in ev), 2)
        g["kwh_event"] = round(sum(x["kwh_event"] for x in ev), 2)
        g["days"] = [d for d in WEEKDAYS if any(d in x["days"] for x in sec)]
        g["starts"] = sorted({st for x in sec for st in x["starts"]})
        g["start"] = g["starts"][0] if g["starts"] else None
        dur = [x["duration_min"] for x in ev if x["duration_min"] is not None]
        g["duration_min"] = sum(dur) if dur and len(dur) == len(ev) else None   # sectors one after the other
        g["duration_unknown"] = any(x["duration_unknown"] for x in sec)
        g["conflict"] = any(x["conflict"] for x in sec)
        sh = [x["solar_share"] for x in sec if x["solar_share"] is not None]
        g["solar_share"] = round(sum(sh) / len(sh), 2) if sh else None
        g["sources"] = sorted({x["source"] for x in sec if x["source"]})
    irrigation_totals = {
        "week_m3": round(sum(r["week_m3"] for r in sector_rows), 1),
        "week_kwh": round(sum(r["week_kwh"] for r in sector_rows), 1),
        "season_m3": round(sum(r["season_m3"] or 0 for r in sector_rows), 0),
        "season_kwh": round(sum(r["season_kwh"] or 0 for r in sector_rows), 0),
        "week": week_key, "week_start": week.get("start"), "week_quality": week.get("quality"),
        "conflicts": week.get("conflicts", 0)}

    # ---------------------------------------------------------------- C
    by_crop: dict[str, list] = defaultdict(list)
    for p in parcels:
        by_crop[p.crop_code].append(p)
    candidates = list(by_crop) + [k for k, v in plan.summary.get("optimizer", {}).get("scores", {}).items()
                                  if k not in by_crop]
    calendar_rows = []
    for code, ps in by_crop.items():
        m = ps[0].metrics
        planting, harvest = date.fromisoformat(m["planting"]), date.fromisoformat(m["harvest"])
        irr_months = sorted({k for q in ps for k in (q.metrics.get("water_m3_monthly") or {})})
        calendar_rows.append({
            "crop": code, "zones": sorted({_zone(q) for q in ps}), "sectors": len(ps), "planting": m["planting"], "harvest": m["harvest"],
            "planting_rule": m.get("planting_rule"), "phases": crop_calendar.phases(CROPS[code], planting, harvest,
                                                                                     irr_months),
            "rotation": crop_calendar.rotation(code, harvest, candidates)})

    # ---------------------------------------------------------------- D
    en = plan.energy or {}
    sim = (en.get("simulation") or {}).get("annual") or {}
    pump_kwh = round(sum(en.get("pump_kwh_month") or []), 0)
    pumps_kw = defaultdict(float)
    for p in parcels:
        kw = p.metrics.get("pump_kw")
        if kw and p.water_source_id:
            pumps_kw[p.water_source_id] = max(pumps_kw[p.water_source_id], kw)
    split = None
    if sim.get("load"):
        split = {"solar_kwh": round(sim.get("self") or 0, 0),
                 "basis": "existing_pv" if any(e.kind == "pv" for e in farm.equipment) else "recommended_pv", "battery_kwh": round(sim.get("batt_out") or 0, 0),
                 "grid_kwh": round(sim.get("grid") or 0, 0), "load_kwh": round(sim["load"], 0),
                 "pv_production_kwh": round(sim.get("pv") or 0, 0), "surplus_kwh": round(sim.get("surplus") or 0, 0)}
    tariff = grid_tariff if grid_tariff is not None else (en.get("policy") or {}).get("grid_tariff_tnd_kwh")
    if tariff is None:
        missing.add("grid_tariff")
    grid_kwh = split["grid_kwh"] if split else pump_kwh
    energy = {
        "pump_kwh_total": pump_kwh, "cold_kwh_total": round(sum(v * 24 * 30.4 for v in en.get("cold_kw_month") or []), 0),
        "per_zone": _energy_by_zone(parcels),
        "peak_power_kw": round(sum(pumps_kw.values()), 2) if pumps_kw else None,
        "pumps": [{"source": (srcs[k].name or f"F{farm.water_sources.index(srcs[k]) + 1}") if k in srcs else k, "kw": round(v, 2)}
                  for k, v in pumps_kw.items()],
        "pv_kwc_existing": sum(float(e.specs.get("kwp", 0)) for e in farm.equipment if e.kind == "pv") or None,
        "pv_kwc_recommended": en.get("kwp_needed"), "panels": en.get("panels"), "panel_wp": en.get("panel_wp"),
        "battery_kwh_existing": sum(float(e.specs.get("kwh", 0)) for e in farm.equipment if e.kind == "battery") or None,
        "battery_kwh_recommended": en.get("battery_kwh_needed"), "autonomy_hours": en.get("autonomy_hours"),
        "split": split, "self_sufficiency_pct": (en.get("simulation") or {}).get("self_sufficiency_pct"),
        "grid_tariff_tnd_kwh": tariff,
        "cost_tnd": round(grid_kwh * tariff, 0) if tariff is not None else None,
        "cost_grid_only_tnd": round((split["load_kwh"] if split else pump_kwh) * tariff, 0)
        if tariff is not None else None,
        "pv_source": en.get("pv_source"), "status": en.get("status")}
    if any(r["minimum_only"] for r in energy["per_zone"]):
        missing.add("pump_flow_or_depth")

    # ---------------------------------------------------------------- E
    rooms = (plan.storage or {}).get("rooms") or []
    production = []
    for code, ps in by_crop.items():
        st = CROPS[code].storage
        t = sum((q.metrics.get("production_kg") or 0) for q in ps) / 1000
        harvests = sorted(q.metrics["harvest"] for q in ps)
        room = next((r for r in rooms if r["crop"] == code), None)
        production.append({
            "crop": code, "production_t": round(t, 2), "harvest_from": harvests[0], "harvest_to": harvests[-1],
            "storable": st.cold, "storage_temp_c": st.temp_c, "storage_rh_pct": st.rh_pct,
            "max_storage_weeks": st.max_weeks,
            "volume_m3": room["volume_m3"] if room else (round(t * 1000 / st.density_kg_m3, 0)
                                                          if st.cold and st.density_kg_m3 else None),
            "refrigeration_kw": room["refrigeration_capacity_kw"] if room else None,
            "electric_kw": room["compressor_electric_kw"] if room else None,
            "annual_kwh": room["annual_kwh"] if room else None})
    s = plan.summary
    if s.get("revenue_tnd") is None:
        missing.add("prices")
    results = {"production": production, "total_t": round(sum(r["production_t"] for r in production), 2),
               "cold_rooms": rooms, "dry_storage_t": (plan.storage or {}).get("dry_storage_t") or {},
               "cost_tnd": s.get("cost_tnd"), "revenue_tnd": s.get("revenue_tnd"),
               "margin_tnd": (s["revenue_tnd"] - s["cost_tnd"]) if s.get("revenue_tnd") is not None and
               s.get("cost_tnd") is not None else None,
               "pv_kwc": en.get("kwp_needed"), "panels": en.get("panels"), "battery_kwh": en.get("battery_kwh_needed")}

    return {"allocation": allocation, "irrigation": irrigation, "irrigation_totals": irrigation_totals,
            "calendar": calendar_rows, "energy": energy, "results": results,
            "totals": {"area_ha": round(total_m2 / 1e4, 3), "zones": len(allocation), "sectors": len(parcels), "field_ha": round(field_m2 / 1e4, 3),
                       "water_m3": s.get("water_m3"), "production_t": results["total_t"]},
            "cold_building": (plan.storage or {}).get("cold_building"),
            "missing": sorted(missing)}
