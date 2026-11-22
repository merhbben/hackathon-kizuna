"""Real public data connectors (no invented endpoints).

| key          | provider                     | endpoint                                                                 |
|--------------|------------------------------|--------------------------------------------------------------------------|
| worldbank    | World Bank WDI + projections | https://api.worldbank.org/v2/country/TUN/indicator/SP.POP.TOTL          |
| faostat      | FAOSTAT bulk downloads       | https://bulks-faostat.fao.org/production/*_E_Africa.zip (area 222)      |
| nasa_power   | NASA POWER climatology/daily | https://power.larc.nasa.gov/api/temporal/{climatology,daily}/point      |
| open_meteo   | Open-Meteo forecast          | https://api.open-meteo.com/v1/forecast                                   |
| pvgis        | EU JRC PVGIS 5.3             | https://re.jrc.ec.europa.eu/api/v5_3/{PVcalc,seriescalc}                 |
| soilgrids    | ISRIC SoilGrids 2.0          | https://rest.isric.org/soilgrids/v2.0/properties/query                   |
| sentinel2    | Element84 Earth Search STAC  | https://earth-search.aws.element84.com/v1/search                         |
"""
from __future__ import annotations

import csv
import io
import math
import zipfile
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy.orm import Session

from app.connectors.base import ConnectorError, http_get, mark_status, point_key, series, upsert_records
from app.core.config import get_settings
from app.engines.fao56 import MonthlyClimate, et0_penman_monteith
from app.knowledge.crops import CROPS
from app.models import DataQuality

WB = "https://api.worldbank.org/v2/country/TUN/indicator/SP.POP.TOTL"


# ------------------------------------------------------------ World Bank ---
def fetch_population(db: Session) -> int:
    rows = []
    for source, quality, dataset in ((2, DataQuality.official, "WB_WDI"), (40, DataQuality.forecast, "WB_POP_PROJ")):
        r = http_get(WB, {"format": "json", "per_page": 200, "source": source,
                          "date": "1990:2024" if source == 2 else "2024:2050"})
        data = r.json()
        if not isinstance(data, list) or len(data) < 2 or data[1] is None:
            raise ConnectorError("World Bank: unexpected payload")
        for d in data[1]:
            if d["value"] is None:
                continue
            rows.append(dict(source="World Bank", dataset=dataset, indicator="population", entity="TN",
                             period=d["date"], value=float(d["value"]), unit="persons", quality=quality.value,
                             source_url=f"{WB}?source={source}",
                             note="WDI (INS/UN WPP based)" if source == 2 else
                             "Population estimates and projections (World Bank source 40)"))
    n = upsert_records(db, rows)
    mark_status(db, "worldbank", True, n)
    return n


# ------------------------------------------------------------ FAOSTAT -----
FAOSTAT_BULK = {
    "FBS": "https://bulks-faostat.fao.org/production/FoodBalanceSheets_E_Africa.zip",
    "QCL": "https://bulks-faostat.fao.org/production/Production_Crops_Livestock_E_Africa.zip",
}
FBS_ELEMENTS = {"5301": "domestic_supply_kt", "5511": "production_kt", "5611": "import_kt", "5911": "export_kt",
                "5072": "stock_variation_kt", "5142": "food_kt", "5123": "losses_kt", "5521": "feed_kt",
                "5527": "seed_kt", "5131": "processing_kt", "645": "food_kg_cap_yr", "664": "kcal_cap_day",
                "674": "protein_g_cap_day", "511": "population_k"}
QCL_ELEMENTS = {"5312": "area_harvested_ha", "5412": "yield_kg_ha", "5510": "production_t"}


def _faostat_rows(text: str, domain: str) -> list[dict]:
    reader = csv.DictReader(io.StringIO(text))
    fbs_map = {c.faostat_fbs: code for code, c in CROPS.items() if c.faostat_fbs}
    qcl_map: dict[int, str] = {}
    for code, c in CROPS.items():
        for it in c.faostat_qcl:
            qcl_map[it] = code
    rows: list[dict] = []
    for rec in reader:
        if rec.get("Area Code") != "222":
            continue
        el = rec["Element Code"]
        item = int(rec["Item Code"])
        if domain == "FBS":
            if el not in FBS_ELEMENTS:
                continue
            if item == 2901:
                crop = "_total"
            elif item == 2501:
                crop = ""
            elif item in fbs_map:
                crop = fbs_map[item]
            else:
                continue
            indicator = FBS_ELEMENTS[el]
        else:
            if el not in QCL_ELEMENTS or item not in qcl_map:
                continue
            crop = qcl_map[item]
            indicator = QCL_ELEMENTS[el]
            if len(CROPS[crop].faostat_qcl) > 1:
                indicator = f"{indicator}@{item}"   # summed later (e.g. oranges + tangerines)
        for k, v in rec.items():
            if k and k.startswith("Y") and k[1:].isdigit() and v not in ("", None):
                flag = (rec.get(k + "F") or "").strip()
                # FAOSTAT flags: A official, X international org, E estimated, I imputed, M missing
                quality = DataQuality.estimated.value if flag in ("E", "I") else DataQuality.official.value
                rows.append(dict(source="FAOSTAT", dataset=f"FAOSTAT_{domain}", indicator=indicator, entity="TN",
                                 item=crop, period=k[1:], value=float(v), unit=rec["Unit"], quality=quality,
                                 source_url=FAOSTAT_BULK[domain], note=f"{rec['Item']} [flag {flag or '-'}]"))
    # aggregate multi-item crops (sum production/area, recompute yield)
    agg: dict[tuple, float] = {}
    agg_q: dict[tuple, str] = {}
    out = []
    for r in rows:
        if "@" in r["indicator"]:
            base = r["indicator"].split("@")[0]
            if base == "yield_kg_ha":
                continue
            k = (base, r["item"], r["period"], r["unit"])
            agg[k] = agg.get(k, 0.0) + r["value"]
            if r["quality"] != DataQuality.official.value:
                agg_q[k] = r["quality"]
        else:
            out.append(r)
    for (base, crop, period, unit), v in agg.items():
        out.append(dict(source="FAOSTAT", dataset=f"FAOSTAT_{domain}", indicator=base, entity="TN", item=crop,
                        period=period, value=v, unit=unit,
                        quality=agg_q.get((base, crop, period, unit), DataQuality.official.value),
                        source_url=FAOSTAT_BULK[domain], note="sum of FAOSTAT items " +
                        "+".join(map(str, CROPS[crop].faostat_qcl))))
    for (base, crop, period, unit), area in list(agg.items()):
        if base == "area_harvested_ha" and area > 0:
            prod = agg.get(("production_t", crop, period, "t"))
            if prod is not None:
                out.append(dict(source="FAOSTAT", dataset="FAOSTAT_QCL", indicator="yield_kg_ha", entity="TN",
                                item=crop, period=period, value=prod * 1000 / area, unit="kg/ha",
                                quality=DataQuality.official.value, source_url=FAOSTAT_BULK[domain],
                                note="derived: production / area harvested"))
    return out


def load_faostat(db: Session, refresh: bool = False) -> int:
    """Load Tunisia rows from the cached FAOSTAT extract, or refresh from the bulk service."""
    ref = get_settings().reference_dir
    total = 0
    for domain, fname in (("FBS", "faostat_fbs_tunisia.csv"), ("QCL", "faostat_qcl_tunisia.csv")):
        path = ref / fname
        if refresh or not path.exists():
            r = http_get(FAOSTAT_BULK[domain], timeout=180)
            with zipfile.ZipFile(io.BytesIO(r.content)) as z:
                name = next(n for n in z.namelist() if n.endswith("_E_Africa.csv"))
                text = z.read(name).decode("latin-1")
            lines = text.splitlines()
            keep = [lines[0]] + [ln for ln in lines[1:] if ln.startswith('"222",')]
            path.write_text("\n".join(keep), encoding="utf-8")
        text = Path(path).read_text(encoding="utf-8")
        total += upsert_records(db, _faostat_rows(text, domain))
    mark_status(db, "faostat", True, total, "Tunisia (FAOSTAT area code 222)")
    return total


# ------------------------------------------------------------ NASA POWER --
POWER_CLIM = "https://power.larc.nasa.gov/api/temporal/climatology/point"
POWER_DAILY = "https://power.larc.nasa.gov/api/temporal/daily/point"
MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
DAYS_IN_MONTH = [31, 28.25, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
MID_DOY = [15, 46, 74, 105, 135, 166, 196, 227, 258, 288, 319, 349]


def fetch_climate_normals(db: Session, lat: float, lon: float, entity: str | None = None) -> MonthlyClimate:
    """Monthly normals from NASA POWER climatology; ET0 computed with FAO-56 Penman-Monteith."""
    entity = entity or point_key(lat, lon)
    cached = series(db, "NASA_POWER_CLIM", "et0_mm_day", entity)
    if len(cached) == 12:
        return climate_from_db(db, entity)
    params = {"parameters": "T2M_MAX,T2M_MIN,RH2M,WS2M,ALLSKY_SFC_SW_DWN,PRECTOTCORR",
              "community": "AG", "latitude": lat, "longitude": lon, "format": "JSON"}
    js = http_get(POWER_CLIM, params).json()
    p = js["properties"]["parameter"]
    elev = js["geometry"]["coordinates"][2] if len(js["geometry"]["coordinates"]) > 2 else 0.0
    rows = []
    for i, m in enumerate(MONTHS):
        tmax, tmin = p["T2M_MAX"][m], p["T2M_MIN"][m]
        et0 = et0_penman_monteith(tmax, tmin, p["RH2M"][m], p["WS2M"][m], p["ALLSKY_SFC_SW_DWN"][m], lat, elev,
                                  MID_DOY[i])
        vals = {"et0_mm_day": (et0, "mm/day"), "rain_mm": (p["PRECTOTCORR"][m] * DAYS_IN_MONTH[i], "mm/month"),
                "tmax_c": (tmax, "°C"), "tmin_c": (tmin, "°C"), "rs_mj_day": (p["ALLSKY_SFC_SW_DWN"][m], "MJ/m2/day")}
        for ind, (v, unit) in vals.items():
            rows.append(dict(source="NASA POWER", dataset="NASA_POWER_CLIM", indicator=ind, entity=entity,
                             period=f"{i + 1:02d}", value=round(v, 3), unit=unit, quality=DataQuality.estimated.value,
                             source_url=POWER_CLIM, note=f"lat={lat}, lon={lon}, elev={elev} m; ET0 = FAO-56 PM"
                             if ind == "et0_mm_day" else f"lat={lat}, lon={lon} (MERRA-2/CERES climatology)"))
    upsert_records(db, rows)
    mark_status(db, "nasa_power", True, len(rows))
    return climate_from_db(db, entity)


def climate_from_db(db: Session, entity: str) -> MonthlyClimate:
    def vals(ind):
        return [r.value for r in series(db, "NASA_POWER_CLIM", ind, entity)]
    return MonthlyClimate(vals("et0_mm_day"), vals("rain_mm"), vals("tmax_c"), vals("tmin_c"),
                          "NASA POWER climatology + FAO-56 Penman-Monteith (estimated)")


def fetch_recent_rain_anomaly(lat: float, lon: float, days: int = 90) -> dict:
    """Rainfall of the last `days` days vs. the same window of the climatology (drought early warning)."""
    end = date.today() - timedelta(days=5)          # POWER latency
    start = end - timedelta(days=days)
    js = http_get(POWER_DAILY, {"parameters": "PRECTOTCORR", "community": "AG", "latitude": lat, "longitude": lon,
                                "start": start.strftime("%Y%m%d"), "end": end.strftime("%Y%m%d"),
                                "format": "JSON"}).json()
    vals = [v for v in js["properties"]["parameter"]["PRECTOTCORR"].values() if v is not None and v > -900]
    return {"start": start.isoformat(), "end": end.isoformat(), "rain_mm": round(sum(vals), 1),
            "days_with_data": len(vals), "source": POWER_DAILY}


# ------------------------------------------------------------ Open-Meteo --
OPEN_METEO = "https://api.open-meteo.com/v1/forecast"


def fetch_forecast(lat: float, lon: float) -> dict:
    """7-day forecast ET0 (FAO-56, computed by Open-Meteo), rain, temperatures, shortwave radiation."""
    js = http_get(OPEN_METEO, {
        "latitude": lat, "longitude": lon, "timezone": "Africa/Tunis", "forecast_days": 7,
        "daily": "et0_fao_evapotranspiration,precipitation_sum,temperature_2m_max,temperature_2m_min,"
                 "shortwave_radiation_sum,wind_speed_10m_max"}).json()
    if js.get("error"):
        raise ConnectorError(f"Open-Meteo: {js.get('reason')}")
    d = js["daily"]
    return {"source": OPEN_METEO, "quality": DataQuality.forecast.value, "days": [
        {"date": d["time"][i], "et0": d["et0_fao_evapotranspiration"][i], "rain": d["precipitation_sum"][i],
         "tmax": d["temperature_2m_max"][i], "tmin": d["temperature_2m_min"][i],
         "rs_mj": d["shortwave_radiation_sum"][i]} for i in range(len(d["time"]))]}


# ------------------------------------------------------------ PVGIS -------
PVGIS = "https://re.jrc.ec.europa.eu/api/v5_3"


def fetch_pv_profile(db: Session, lat: float, lon: float, tilt: float | None = None, azimuth: float = 0.0,
                     loss_pct: float = 14.0) -> dict:
    """Hourly PV output per kWp averaged per month (12 x 24, kWh/kWp) + monthly totals.

    Uses PVGIS seriescalc over a recent multi-year window (SARAH-3) with optimal tilt unless given.
    """
    entity = point_key(lat, lon)
    cached = series(db, "PVGIS", "hourly_profile", entity)
    if cached and cached[0].note:
        import json
        return json.loads(cached[0].note)
    params = {"lat": lat, "lon": lon, "pvcalculation": 1, "peakpower": 1, "loss": loss_pct, "outputformat": "json",
              "startyear": 2019, "endyear": 2023, "aspect": azimuth}
    if tilt is None:
        params["optimalinclination"] = 1
    else:
        params["angle"] = tilt
    js = http_get(f"{PVGIS}/seriescalc", params, timeout=120).json()
    hourly = js["outputs"]["hourly"]
    sums = [[0.0] * 24 for _ in range(12)]
    counts = [[0] * 24 for _ in range(12)]
    for h in hourly:
        t = h["time"]                       # 'YYYYMMDD:HHMM' (UTC)
        m = int(t[4:6]) - 1
        hr = (int(t[9:11]) + 1) % 24        # Africa/Tunis = UTC+1 (no DST)
        sums[m][hr] += h["P"] / 1000.0      # W per kWp -> kWh/kWp for that hour
        counts[m][hr] += 1
    profile = [[round(sums[m][h] / counts[m][h], 4) if counts[m][h] else 0.0 for h in range(24)] for m in range(12)]
    monthly_kwh = [round(sum(profile[m]) * DAYS_IN_MONTH[m], 1) for m in range(12)]
    used_tilt = js["inputs"]["mounting_system"]["fixed"]["slope"]["value"]
    result = {"profile_kwh_per_kwp": profile, "monthly_kwh_per_kwp": monthly_kwh,
              "annual_kwh_per_kwp": round(sum(monthly_kwh), 0), "tilt_deg": used_tilt, "azimuth_deg": azimuth,
              "loss_pct": loss_pct, "source": f"{PVGIS}/seriescalc", "years": "2019-2023",
              "radiation_db": js["inputs"]["meteo_data"]["radiation_db"], "quality": DataQuality.estimated.value}
    import json
    upsert_records(db, [dict(source="PVGIS", dataset="PVGIS", indicator="hourly_profile", entity=entity, period="tmy",
                             value=result["annual_kwh_per_kwp"], unit="kWh/kWp/yr", quality="estimated",
                             source_url=result["source"], note=json.dumps(result))])
    mark_status(db, "pvgis", True, 1)
    return result


# ------------------------------------------------------------ SoilGrids ---
SOILGRIDS = "https://rest.isric.org/soilgrids/v2.0/properties/query"


def fetch_soil(lat: float, lon: float) -> dict:
    """Topsoil (0-30 cm, thickness-weighted) clay/sand/silt %, pH, organic matter % from SoilGrids 250 m."""
    params = [("lon", lon), ("lat", lat), ("value", "mean")]
    for prop in ("clay", "sand", "silt", "phh2o", "soc"):
        params.append(("property", prop))
    for depth in ("0-5cm", "5-15cm", "15-30cm"):
        params.append(("depth", depth))
    js = http_get(SOILGRIDS, params, timeout=60).json()
    weights = {"0-5cm": 5, "5-15cm": 10, "15-30cm": 15}
    out = {}
    for layer in js["properties"]["layers"]:
        d_factor = layer["unit_measure"]["d_factor"]
        acc = wsum = 0.0
        for dep in layer["depths"]:
            v = dep["values"].get("mean")
            if v is None:
                continue
            w = weights.get(dep["label"], 0)
            acc += v / d_factor * w
            wsum += w
        out[layer["name"]] = acc / wsum if wsum else None
    if out.get("clay") is None:
        raise ConnectorError("SoilGrids: no data at this location (water/urban mask?)")
    soc_pct = (out.get("soc") or 0) / 10.0   # g/kg -> %
    return {"clay_pct": round(out["clay"], 1), "sand_pct": round(out["sand"], 1), "silt_pct": round(out["silt"], 1),
            "ph": round(out["phh2o"], 2) if out.get("phh2o") else None,
            "organic_matter_pct": round(soc_pct * 1.724, 2), "source": "SoilGrids 2.0 (ISRIC) 0-30 cm",
            "quality": DataQuality.estimated.value, "source_url": SOILGRIDS}


# ------------------------------------------------------------ Sentinel-2 --
STAC = "https://earth-search.aws.element84.com/v1/search"


def search_sentinel2(bbox: list[float], days: int = 60, max_cloud: int = 20) -> list[dict]:
    """Recent Sentinel-2 L2A scenes over a farm (scene discovery; NDVI requires COG reading)."""
    end = date.today()
    start = end - timedelta(days=days)
    import httpx
    from app.core.config import get_settings
    s = get_settings()
    body = {"collections": ["sentinel-2-l2a"], "bbox": bbox, "datetime": f"{start}T00:00:00Z/{end}T23:59:59Z",
            "limit": 10, "query": {"eo:cloud_cover": {"lt": max_cloud}},
            "sortby": [{"field": "properties.datetime", "direction": "desc"}]}
    try:
        r = httpx.post(STAC, json=body, timeout=s.http_timeout_s, headers={"User-Agent": s.http_user_agent})
        r.raise_for_status()
    except httpx.HTTPError as e:
        raise ConnectorError(f"STAC: {e}") from e
    return [{"id": f["id"], "datetime": f["properties"]["datetime"], "cloud": f["properties"].get("eo:cloud_cover"),
             "thumbnail": f["assets"].get("thumbnail", {}).get("href"),
             "red": f["assets"].get("red", {}).get("href"), "nir": f["assets"].get("nir", {}).get("href")}
            for f in r.json().get("features", [])]


def bbox_of(geojson: dict) -> list[float]:
    from shapely.geometry import shape
    b = shape(geojson).bounds
    return [round(b[0], 6), round(b[1], 6), round(b[2], 6), round(b[3], 6)]


def haversine_m(lat1, lon1, lat2, lon2) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))
