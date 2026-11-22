"""Automatic climate profile of a farm from its GPS position (no manual weather input).

Three clearly separated layers, each with source, period, resolution and fetch date:

* ``normals``    — NASA POWER climatology (MERRA-2 / CERES, 25 years 2001-2025): monthly mean,
                   min, max temperature, rainfall, relative humidity, wind at 2 m, solar radiation;
                   ET0 computed with FAO-56 Penman-Monteith. Used for seasonal planning.
* ``statistics`` — ERA5 reanalysis (ECMWF / Copernicus C3S, 0.25°) daily series of the last 10
                   complete years via the Open-Meteo Historical Weather API, and ERA5-Land (0.1°)
                   daily minimum / maximum temperature: inter-annual rainfall variability (dry year
                   = 20th percentile), frost and heat day frequencies -> climate risks.
* ``recent``     — ERA5 observations of the last 30 available days (≈5 days latency) compared with
                   the normal of the same days; ``forecast`` — Open-Meteo 7-day forecast (ET0 FAO-56).
                   Used to adjust the irrigation programme, never for seasonal planning.

INM (Institut National de la Météorologie) station data are not available through a public API;
the profile says so instead of pretending to use them.
"""
from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.connectors.base import ConnectorError, http_get, mark_status, point_key, series, upsert_records
from app.engines.fao56 import et0_penman_monteith
from app.models import DataQuality

POWER_CLIM = "https://power.larc.nasa.gov/api/temporal/climatology/point"
ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
FORECAST = "https://api.open-meteo.com/v1/forecast"
MID_DOY = [15, 46, 74, 105, 135, 166, 196, 227, 258, 288, 319, 349]
DAYS_IN_MONTH = [31, 28.25, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
STAT_YEARS = 10
FROST_C = 0.0          # air frost: daily minimum ≤ 0 °C (WMO definition of a frost day)
HEAT_C = 35.0          # heat-stress day: daily maximum ≥ 35 °C (threshold shown with the result)
PROFILE_TTL_DAYS = 120  # normals and statistics change slowly; recent / forecast are refreshed every call


def _pct(vals: list[float], q: float) -> float:
    v = sorted(vals)
    if not v:
        return float("nan")
    k = (len(v) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    return v[lo] + (v[hi] - v[lo]) * (k - lo)


# ----------------------------------------------------------------- normals
def fetch_normals(lat: float, lon: float) -> dict:
    params = {"parameters": "T2M,T2M_MAX,T2M_MIN,RH2M,WS2M,ALLSKY_SFC_SW_DWN,PRECTOTCORR",
              "community": "AG", "latitude": lat, "longitude": lon, "format": "JSON"}
    js = http_get(POWER_CLIM, params, timeout=90).json()
    p = js["properties"]["parameter"]
    coords = js["geometry"]["coordinates"]
    elev = coords[2] if len(coords) > 2 else 0.0
    keys = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
    months = []
    for i, m in enumerate(keys):
        tmax, tmin = p["T2M_MAX"][m], p["T2M_MIN"][m]
        et0 = et0_penman_monteith(tmax, tmin, p["RH2M"][m], p["WS2M"][m], p["ALLSKY_SFC_SW_DWN"][m], lat, elev,
                                  MID_DOY[i])
        months.append({"month": i + 1, "tmean_c": round(p["T2M"][m], 1), "tmin_c": round(tmin, 1),
                       "tmax_c": round(tmax, 1), "rain_mm": round(p["PRECTOTCORR"][m] * DAYS_IN_MONTH[i], 1),
                       "rh_pct": round(p["RH2M"][m], 0), "wind_ms": round(p["WS2M"][m], 1),
                       "rs_mj_day": round(p["ALLSKY_SFC_SW_DWN"][m], 1), "et0_mm_day": round(et0, 2),
                       "et0_mm": round(et0 * DAYS_IN_MONTH[i], 0)})
    rng = (js.get("header") or {}).get("range") or "2001-2025 climatology"
    return {"source": "NASA POWER (MERRA-2, CERES) — ET0 FAO-56 Penman-Monteith", "url": POWER_CLIM,
            "period": rng, "resolution": "0.5° × 0.625° (météo) ; 1° (rayonnement)",
            "elevation_m": elev, "quality": DataQuality.estimated.value, "months": months,
            "annual": {"rain_mm": round(sum(x["rain_mm"] for x in months), 0),
                       "et0_mm": round(sum(x["et0_mm"] for x in months), 0),
                       "tmean_c": round(sum(x["tmean_c"] for x in months) / 12, 1)}}


# -------------------------------------------------------------- statistics
def _archive(lat: float, lon: float, start: date, end: date, daily: str, model: str) -> dict:
    js = http_get(ARCHIVE, {"latitude": lat, "longitude": lon, "start_date": start.isoformat(),
                            "end_date": end.isoformat(), "daily": daily, "models": model,
                            "timezone": "Africa/Tunis"}, timeout=120).json()
    if js.get("error") or "daily" not in js:
        raise ConnectorError(f"Open-Meteo archive: {js.get('reason', 'no daily data')}")
    return js


def fetch_statistics(lat: float, lon: float, today: date) -> dict:
    y1 = today.year - 1
    y0 = y1 - STAT_YEARS + 1
    start, end = date(y0, 1, 1), date(y1, 12, 31)
    era5 = _archive(lat, lon, start, end, "precipitation_sum,et0_fao_evapotranspiration", "era5")["daily"]
    land = _archive(lat, lon, start, end, "temperature_2m_min,temperature_2m_max", "era5_land")
    ld = land["daily"]
    if all(v is None for v in ld["temperature_2m_min"]):      # ERA5-Land masks some coastal cells
        land = _archive(lat, lon, start, end, "temperature_2m_min,temperature_2m_max", "era5")
        ld, t_model = land["daily"], "ERA5 (0.25°)"
    else:
        t_model = "ERA5-Land (0.1°)"
    rain_ym: dict[tuple[int, int], float] = {}
    frost_ym: dict[tuple[int, int], int] = {}
    heat_ym: dict[tuple[int, int], int] = {}
    tmin_abs = [99.0] * 12
    tmax_abs = [-99.0] * 12
    heavy = [0] * 12
    for i, t in enumerate(era5["time"]):
        y, m = int(t[:4]), int(t[5:7])
        r = era5["precipitation_sum"][i]
        if r is not None:
            rain_ym[(y, m)] = rain_ym.get((y, m), 0.0) + r
            if r >= 30:                                             # ≥ 30 mm/day: heavy rain day
                heavy[m - 1] += 1
    for i, t in enumerate(ld["time"]):
        y, m = int(t[:4]), int(t[5:7])
        tn, tx = ld["temperature_2m_min"][i], ld["temperature_2m_max"][i]
        if tn is not None:
            frost_ym[(y, m)] = frost_ym.get((y, m), 0) + (tn <= FROST_C)
            tmin_abs[m - 1] = min(tmin_abs[m - 1], tn)
        if tx is not None:
            heat_ym[(y, m)] = heat_ym.get((y, m), 0) + (tx >= HEAT_C)
            tmax_abs[m - 1] = max(tmax_abs[m - 1], tx)
    years = list(range(y0, y1 + 1))
    months = []
    for m in range(1, 13):
        rains = [rain_ym[(y, m)] for y in years if (y, m) in rain_ym]
        frosts = [frost_ym.get((y, m), 0) for y in years]
        heats = [heat_ym.get((y, m), 0) for y in years]
        months.append({"month": m, "rain_mean_mm": round(sum(rains) / len(rains), 1) if rains else None,
                       "rain_p20_mm": round(_pct(rains, 0.2), 1) if rains else None,
                       "rain_p80_mm": round(_pct(rains, 0.8), 1) if rains else None,
                       "frost_days_mean": round(sum(frosts) / len(years), 1),
                       "frost_probability": round(sum(1 for f in frosts if f > 0) / len(years), 2),
                       "heat_days_mean": round(sum(heats) / len(years), 1),
                       "heavy_rain_days": heavy[m - 1],
                       "tmin_abs_c": None if tmin_abs[m - 1] == 99 else round(tmin_abs[m - 1], 1),
                       "tmax_abs_c": None if tmax_abs[m - 1] == -99 else round(tmax_abs[m - 1], 1)})
    annual = [sum(rain_ym.get((y, m), 0.0) for m in range(1, 13)) for y in years]
    mean = sum(annual) / len(annual)
    sd = math.sqrt(sum((a - mean) ** 2 for a in annual) / max(1, len(annual) - 1))
    return {"source": f"ERA5 (ECMWF/Copernicus C3S) pluie & ET0 ; {t_model} températures — via Open-Meteo",
            "url": ARCHIVE, "period": f"{y0}-{y1}", "resolution": f"pluie 0.25° (~28 km) ; températures {t_model}",
            "grid_point": [land.get("latitude"), land.get("longitude")],
            "quality": DataQuality.estimated.value, "months": months,
            "thresholds": {"frost_c": FROST_C, "heat_c": HEAT_C, "heavy_rain_mm_day": 30},
            "annual": {"rain_by_year": {str(y): round(a, 0) for y, a in zip(years, annual)},
                       "rain_mean_mm": round(mean, 0), "rain_min_mm": round(min(annual), 0),
                       "rain_max_mm": round(max(annual), 0), "rain_cv_pct": round(100 * sd / mean, 0) if mean else None,
                       "rain_dry_year_mm": round(_pct(annual, 0.2), 0)}}


# ------------------------------------------------------- recent / forecast
def fetch_recent(lat: float, lon: float, today: date, normals: dict | None) -> dict:
    end = today - timedelta(days=6)                   # ERA5 latency ≈ 5 days
    start = end - timedelta(days=29)
    d = _archive(lat, lon, start, end, "precipitation_sum,et0_fao_evapotranspiration,temperature_2m_mean",
                 "era5")["daily"]
    rain = sum(v for v in d["precipitation_sum"] if v is not None)
    et0 = sum(v for v in d["et0_fao_evapotranspiration"] if v is not None)
    temps = [v for v in d["temperature_2m_mean"] if v is not None]
    normal_rain = normal_et0 = None
    if normals:
        normal_rain = normal_et0 = 0.0
        k = start
        while k <= end:
            nm = normals["months"][k.month - 1]
            normal_rain += nm["rain_mm"] / DAYS_IN_MONTH[k.month - 1]
            normal_et0 += nm["et0_mm_day"]
            k += timedelta(days=1)
    return {"source": "ERA5 (Copernicus) via Open-Meteo — observations", "url": ARCHIVE,
            "period": f"{start.isoformat()} → {end.isoformat()}", "resolution": "0.25°",
            "quality": DataQuality.measured.value, "rain_mm": round(rain, 1), "et0_mm": round(et0, 1),
            "tmean_c": round(sum(temps) / len(temps), 1) if temps else None,
            "normal_rain_mm": None if normal_rain is None else round(normal_rain, 1),
            "normal_et0_mm": None if normal_et0 is None else round(normal_et0, 1),
            "rain_anomaly_pct": round(100 * (rain - normal_rain) / normal_rain, 0) if normal_rain else None,
            "days": [{"date": t, "rain": d["precipitation_sum"][i], "et0": d["et0_fao_evapotranspiration"][i]}
                     for i, t in enumerate(d["time"])][-7:]}


def fetch_forecast(lat: float, lon: float) -> dict:
    js = http_get(FORECAST, {"latitude": lat, "longitude": lon, "timezone": "Africa/Tunis", "forecast_days": 7,
                             "daily": "et0_fao_evapotranspiration,precipitation_sum,temperature_2m_max,"
                                      "temperature_2m_min,wind_speed_10m_max"}).json()
    if js.get("error"):
        raise ConnectorError(f"Open-Meteo: {js.get('reason')}")
    d = js["daily"]
    return {"source": "Open-Meteo (modèles ECMWF IFS / ICON / GFS) — prévision", "url": FORECAST,
            "period": f"{d['time'][0]} → {d['time'][-1]}", "resolution": "≈ 9–11 km",
            "quality": DataQuality.forecast.value,
            "days": [{"date": d["time"][i], "et0": d["et0_fao_evapotranspiration"][i],
                      "rain": d["precipitation_sum"][i], "tmax": d["temperature_2m_max"][i],
                      "tmin": d["temperature_2m_min"][i], "wind_max_kmh": d["wind_speed_10m_max"][i]}
                     for i in range(len(d["time"]))]}


# ------------------------------------------------------------------ risks
def risks(normals: dict, stats: dict | None) -> dict:
    """Seasonality (dry / humid months by the FAO aridity ratio P/ET0) and climate risks."""
    out = []
    dry = [m["month"] for m in normals["months"] if m["rain_mm"] < 0.5 * m["et0_mm"]]
    humid = [m["month"] for m in normals["months"] if m["rain_mm"] >= m["et0_mm"]]
    if stats:
        frost = [m["month"] for m in stats["months"] if m["frost_probability"] >= 0.2]
        heat = [m["month"] for m in stats["months"] if m["heat_days_mean"] >= 3]
        heavy = [m["month"] for m in stats["months"] if m["heavy_rain_days"] >= 2]
        if frost:
            out.append({"code": "frost", "months": frost, "basis": "frost_probability>=0.2",
                        "value": max(m["frost_probability"] for m in stats["months"])})
        if heat:
            out.append({"code": "heat", "months": heat, "basis": "heat_days>=3",
                        "value": max(m["heat_days_mean"] for m in stats["months"])})
        if heavy:
            out.append({"code": "heavy_rain", "months": heavy, "basis": "heavy_rain_days>=2_in_10y"})
        a = stats["annual"]
        if a.get("rain_cv_pct") and a["rain_cv_pct"] >= 25:
            out.append({"code": "rain_variability", "value": a["rain_cv_pct"], "months": [],
                        "basis": "cv>=25%"})
    ai = normals["annual"]["rain_mm"] / max(normals["annual"]["et0_mm"], 1)
    zone = ("hyper_arid" if ai < 0.05 else "arid" if ai < 0.2 else "semi_arid" if ai < 0.5
            else "dry_subhumid" if ai < 0.65 else "humid")
    if len(dry) >= 6:
        out.append({"code": "long_dry_season", "months": dry, "basis": "P<0.5*ET0"})
    return {"aridity_index": round(ai, 2), "zone": zone, "dry_months": dry, "humid_months": humid,
            "items": out, "method": "UNEP aridity index P/ET0 ; seuils indiqués"}


# ---------------------------------------------------------------- profile
def climate_profile(db: Session, lat: float, lon: float, today: date | None = None, refresh: bool = False,
                    soil: dict | None = None) -> dict:
    """Full profile, cached per point (≈1 km) for the slow layers; recent / forecast are live."""
    today = today or date.today()
    lat, lon = round(lat, 2), round(lon, 2)
    entity = point_key(lat, lon)
    cached = series(db, "CLIMATE_PROFILE", "normals_statistics", entity)
    base = None
    if cached and not refresh:
        rec = cached[-1]
        age = (datetime.now(timezone.utc) - rec.fetched_at.replace(tzinfo=timezone.utc)).days
        if age <= PROFILE_TTL_DAYS:
            base = json.loads(rec.note)
    errors = {}
    if base is None:
        base = {}
        try:
            base["normals"] = fetch_normals(lat, lon)
        except (ConnectorError, KeyError) as e:
            errors["normals"] = str(e)[:200]
        try:
            base["statistics"] = fetch_statistics(lat, lon, today)
        except (ConnectorError, KeyError, ZeroDivisionError) as e:
            errors["statistics"] = str(e)[:200]
        if base.get("normals"):
            base["fetched_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            upsert_records(db, [dict(source="NASA POWER + ERA5", dataset="CLIMATE_PROFILE",
                                     indicator="normals_statistics", entity=entity, period="profile",
                                     value=None, unit="json", quality=DataQuality.estimated.value,
                                     source_url=f"{POWER_CLIM} ; {ARCHIVE}", note=json.dumps(base))])
            mark_status(db, "climate_profile", True, 1)
    prof = {"location": {"lat": lat, "lon": lon}, **base, "errors": errors,
            "inm": {"status": "not_accessible",
                    "note": "Les données de stations INM ne sont pas diffusées par une API publique ; "
                            "elles peuvent être importées par CSV (source obligatoire)."}}
    if base.get("normals"):
        prof["seasonality"] = risks(base["normals"], base.get("statistics"))
    try:
        prof["recent"] = fetch_recent(lat, lon, today, base.get("normals"))
    except (ConnectorError, KeyError) as e:
        errors["recent"] = str(e)[:200]
    try:
        prof["forecast"] = fetch_forecast(lat, lon)
    except (ConnectorError, KeyError) as e:
        errors["forecast"] = str(e)[:200]
    if soil:
        prof["soil"] = {**soil, "resolution": "250 m" if "SoilGrids" in str(soil.get("source", "")) else None,
                        "note": "estimation cartographique, pas une analyse du terrain"
                        if soil.get("quality") == "estimated" else None}
    return prof
