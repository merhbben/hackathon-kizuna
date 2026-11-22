"""FAO-56 crop water requirements (Allen, Pereira, Raes & Smith, 1998).

Implements:
* Penman-Monteith reference evapotranspiration ET0 (eq. 6 and supporting eqs 7-40).
* Single crop coefficient curve (eq. 66 interpolation).
* Effective rainfall (FAO/AGLW formula, Smith 1992, used in CROPWAT).
* Total and readily available water, with p adjustment (Table 22 note).
* Saxton & Rawls (2006) pedotransfer functions for field capacity / wilting point.
"""
from __future__ import annotations

import calendar
import math
from dataclasses import dataclass
from datetime import date, timedelta

from app.knowledge.crops import Crop


# ---------------------------------------------------------------- ET0 ------
def _svp(t: float) -> float:
    """Saturation vapour pressure (kPa), eq. 11."""
    return 0.6108 * math.exp(17.27 * t / (t + 237.3))


def et0_penman_monteith(tmax: float, tmin: float, rh_mean: float, u2: float, rs_mj: float,
                        lat_deg: float, elevation_m: float, doy: int) -> float:
    """Daily ET0 (mm/day). rs_mj is incoming shortwave radiation (MJ m-2 day-1)."""
    tmean = (tmax + tmin) / 2.0
    p = 101.3 * ((293.0 - 0.0065 * elevation_m) / 293.0) ** 5.26        # eq. 7
    gamma = 0.665e-3 * p                                                  # eq. 8
    delta = 4098 * _svp(tmean) / (tmean + 237.3) ** 2                     # eq. 13
    es = (_svp(tmax) + _svp(tmin)) / 2.0                                  # eq. 12
    ea = rh_mean / 100.0 * es                                             # eq. 19
    phi = math.radians(lat_deg)
    dr = 1 + 0.033 * math.cos(2 * math.pi * doy / 365)                    # eq. 23
    dec = 0.409 * math.sin(2 * math.pi * doy / 365 - 1.39)                # eq. 24
    ws = math.acos(max(-1.0, min(1.0, -math.tan(phi) * math.tan(dec))))   # eq. 25
    ra = (24 * 60 / math.pi) * 0.0820 * dr * (
        ws * math.sin(phi) * math.sin(dec) + math.cos(phi) * math.cos(dec) * math.sin(ws))  # eq. 21
    rso = (0.75 + 2e-5 * elevation_m) * ra                                # eq. 37
    rns = (1 - 0.23) * rs_mj                                              # eq. 38
    sigma = 4.903e-9
    ratio = min(1.0, rs_mj / rso) if rso > 0 else 0.5
    rnl = sigma * (((tmax + 273.16) ** 4 + (tmin + 273.16) ** 4) / 2) * (0.34 - 0.14 * math.sqrt(max(ea, 0))) * (
        1.35 * ratio - 0.35)                                              # eq. 39
    rn = rns - rnl
    g = 0.0
    num = 0.408 * delta * (rn - g) + gamma * (900 / (tmean + 273)) * u2 * (es - ea)
    den = delta + gamma * (1 + 0.34 * u2)
    return max(0.0, num / den)


def wind_to_2m(u_z: float, z: float) -> float:
    """eq. 47"""
    return u_z * 4.87 / math.log(67.8 * z - 5.42)


# ---------------------------------------------------------------- Kc -------
def kc_on_day(c: Crop, day: int) -> float:
    """Kc for day index since planting (0-based), FAO-56 Fig. 25 / eq. 66."""
    li, ld, lm, ll = c.stages
    kini, kmid, kend = c.kc
    if day < li:
        return kini
    if day < li + ld:
        return kini + (day - li) / ld * (kmid - kini)
    if day < li + ld + lm:
        return kmid
    if day < li + ld + lm + ll:
        return kmid + (day - li - ld - lm) / ll * (kend - kmid)
    return kend


def stage_on_day(c: Crop, day: int) -> str:
    li, ld, lm, _ = c.stages
    if day < li:
        return "initial"
    if day < li + ld:
        return "development"
    if day < li + ld + lm:
        return "mid"
    return "late"


# ---------------------------------------------------------------- rain -----
def effective_rain_monthly(p_mm: float) -> float:
    """FAO/AGLW formula (CROPWAT): monthly effective rainfall."""
    if p_mm <= 75:
        return max(0.0, 0.6 * p_mm - 10)
    return 0.8 * p_mm - 25


def effective_rain_usda_scs(p_mm: float) -> float:
    """USDA Soil Conservation Service formula (CROPWAT option), monthly: removes surface runoff only.
    Used by the rainfed soil-water balance, where deep percolation is handled by the root-zone capacity."""
    if p_mm <= 250:
        return max(0.0, p_mm * (125 - 0.2 * p_mm) / 125)
    return 125 + 0.1 * p_mm


# ---------------------------------------------------------------- soil -----
@dataclass
class SoilHydraulics:
    texture: str
    theta_fc: float  # m3/m3
    theta_wp: float
    sand: float
    clay: float
    om_pct: float
    source: str

    @property
    def taw_mm_per_m(self) -> float:
        return 1000 * max(0.02, self.theta_fc - self.theta_wp)


def saxton_rawls(sand: float, clay: float, om_pct: float) -> tuple[float, float]:
    """Return (theta_33kPa, theta_1500kPa). sand/clay as fractions 0-1, OM in %."""
    S, C, OM = sand, clay, min(om_pct, 8.0)
    t1500t = -0.024 * S + 0.487 * C + 0.006 * OM + 0.005 * S * OM - 0.013 * C * OM + 0.068 * S * C + 0.031
    t1500 = t1500t + (0.14 * t1500t - 0.02)
    t33t = -0.251 * S + 0.195 * C + 0.011 * OM + 0.006 * S * OM - 0.027 * C * OM + 0.452 * S * C + 0.299
    t33 = t33t + (1.283 * t33t ** 2 - 0.374 * t33t - 0.015)
    return max(t33, t1500 + 0.02), max(0.01, t1500)


def usda_texture(sand: float, clay: float) -> str:
    """USDA texture triangle, fractions 0-1."""
    s, c = sand * 100, clay * 100
    si = 100 - s - c
    if si + 1.5 * c < 15:
        return "sand"
    if si + 1.5 * c >= 15 and si + 2 * c < 30:
        return "loamy_sand"
    if (7 <= c < 20 and s > 52 and si + 2 * c >= 30) or (c < 7 and si < 50 and si + 2 * c >= 30):
        return "sandy_loam"
    if 7 <= c < 27 and 28 <= si < 50 and s <= 52:
        return "loam"
    if (si >= 50 and 12 <= c < 27) or (50 <= si < 80 and c < 12):
        return "silt_loam"
    if si >= 80 and c < 12:
        return "silt"
    if 20 <= c < 35 and si < 28 and s > 45:
        return "sandy_clay_loam"
    if 27 <= c < 40 and 20 < s <= 45:
        return "clay_loam"
    if 27 <= c < 40 and s <= 20:
        return "silty_clay_loam"
    if c >= 35 and s > 45:
        return "sandy_clay"
    if c >= 40 and si >= 40:
        return "silty_clay"
    return "clay"


# Typical fractions per texture (centroid of USDA class) for when the farmer only knows the class.
TEXTURE_FRACTIONS = {
    "sand": (0.92, 0.03), "loamy_sand": (0.82, 0.06), "sandy_loam": (0.65, 0.10), "loam": (0.40, 0.20),
    "silt_loam": (0.20, 0.15), "silt": (0.07, 0.06), "sandy_clay_loam": (0.60, 0.27),
    "clay_loam": (0.32, 0.34), "silty_clay_loam": (0.10, 0.34), "sandy_clay": (0.52, 0.42),
    "silty_clay": (0.07, 0.47), "clay": (0.22, 0.60),
}


def soil_from_farm(soil: dict) -> SoilHydraulics:
    sand = soil.get("sand_pct")
    clay = soil.get("clay_pct")
    source = soil.get("source", "farmer")
    if sand is None or clay is None:
        tex = soil.get("texture") or "loam"
        sand_f, clay_f = TEXTURE_FRACTIONS.get(tex, TEXTURE_FRACTIONS["loam"])
        source = f"{source} (class centroid)"
    else:
        sand_f, clay_f = sand / 100, clay / 100
    om = soil.get("organic_matter_pct") or 1.0
    fc, wp = saxton_rawls(sand_f, clay_f, om)
    return SoilHydraulics(usda_texture(sand_f, clay_f), fc, wp, sand_f, clay_f, om, source)


def adjusted_p(p_table: float, etc_mm_day: float) -> float:
    return min(0.8, max(0.1, p_table + 0.04 * (5 - etc_mm_day)))


# ---------------------------------------------------------- requirements ---
@dataclass
class MonthlyClimate:
    """Monthly climate normals for one location (12 values each)."""
    et0_mm_day: list[float]
    rain_mm: list[float]
    tmax_c: list[float]
    tmin_c: list[float]
    source: str


@dataclass
class CropWaterPlan:
    planting: date
    harvest: date
    etc_mm: float
    peff_mm: float
    net_irrigation_mm: float
    monthly_net_mm: dict[str, float]  # 'YYYY-MM' -> mm
    peak_etc_mm_day: float
    daily: list[dict]                 # per-day (date, kc, etc, stage) — weekly aggregated by callers


def crop_water_plan(c: Crop, planting: date, clim: MonthlyClimate, rainfed: bool = False) -> CropWaterPlan:
    """Day-by-day ETc over the crop cycle with monthly effective rainfall shares."""
    cycle = c.cycle_days if not c.perennial else 365
    etc_tot = peff_tot = net_tot = 0.0
    monthly: dict[str, float] = {}
    peak = 0.0
    daily = []
    for d in range(cycle):
        day = planting + timedelta(days=d)
        m = day.month - 1
        # perennials: one annual cycle starting at the season start; Kc_end after the late stage
        kc = kc_on_day(c, d)
        etc = kc * clim.et0_mm_day[m]
        dim = calendar.monthrange(day.year, day.month)[1]
        peff = effective_rain_monthly(clim.rain_mm[m]) / dim
        net = 0.0 if rainfed else max(0.0, etc - peff)
        etc_tot += etc
        peff_tot += min(peff, etc)
        net_tot += net
        key = f"{day.year:04d}-{day.month:02d}"
        monthly[key] = monthly.get(key, 0.0) + net
        peak = max(peak, etc)
        daily.append({"date": day.isoformat(), "kc": round(kc, 3), "etc": round(etc, 2),
                      "net": round(net, 2), "stage": stage_on_day(c, d) if not c.perennial else "perennial"})
    return CropWaterPlan(planting, planting + timedelta(days=cycle), round(etc_tot, 1), round(peff_tot, 1),
                         round(net_tot, 1), {k: round(v, 1) for k, v in monthly.items()}, round(peak, 2), daily)


def default_planting_date(c: Crop, year: int, today: date | None = None) -> date:
    """Middle of the next planting window (indicative calendar)."""
    today = today or date.today()
    candidates = []
    for (m1, m2) in c.planting_months:
        for y in (year, year + 1):
            mid_month = (m1 + m2) // 2
            day = 15 if m1 == m2 else 1
            candidates.append(date(y, mid_month, day))
    future = [d for d in sorted(candidates) if d >= today]
    return future[0] if future else sorted(candidates)[-1]


def rainfed_balance(c: Crop, planting: date, clim: MonthlyClimate, taw_mm_per_m: float,
                    initial_depletion_frac: float = 1.0) -> dict:
    """Rainfed daily root-zone water balance (FAO-56 ch. 8, eq. 84-85), no irrigation.

    Dr(i) = Dr(i-1) - Peff(i) + ETa(i), bounded to [0, TAW]; rain above field capacity drains.
    Peff: USDA-SCS monthly effective rain spread evenly over the days of the month.
    ETa = Ks * ETc with Ks = (TAW - Dr) / ((1 - p) TAW) when Dr > RAW, else 1.
    Root depth grows linearly from Zr_min to Zr_max during the initial + development stages.
    Default: soil dry at sowing (initial_depletion_frac = 1), i.e. no stored water is assumed.
    Returns ETc, ETa (mm) and ETa/ETc, used with FAO-33 Ky to estimate the rainfed yield.
    """
    cycle = c.cycle_days if not c.perennial else 365
    li, ld = c.stages[0], c.stages[1]
    zmin, zmax = c.root_depth_m
    etc_tot = eta_tot = 0.0
    zr = zmin if not c.perennial else zmax
    dr = initial_depletion_frac * taw_mm_per_m * zr
    for d in range(cycle):
        day = planting + timedelta(days=d)
        m = day.month - 1
        new_zr = zmax if c.perennial else zmin + (zmax - zmin) * min(1.0, d / max(1, li + ld))
        dr += taw_mm_per_m * (new_zr - zr) * initial_depletion_frac   # new soil explored is at its initial state
        zr = new_zr
        taw = taw_mm_per_m * zr
        etc = kc_on_day(c, d) * clim.et0_mm_day[m]
        p = adjusted_p(c.p, etc)
        raw = p * taw
        dim = calendar.monthrange(day.year, day.month)[1]
        peff = effective_rain_usda_scs(clim.rain_mm[m]) / dim   # runoff only; percolation via the TAW cap
        dr = max(0.0, dr - peff)
        ks = 1.0 if dr <= raw else max(0.0, (taw - dr) / ((1 - p) * taw)) if taw > 0 else 0.0
        eta = ks * etc
        dr = min(taw, dr + eta)
        etc_tot += etc
        eta_tot += eta
    return {"etc_mm": round(etc_tot, 1), "eta_mm": round(eta_tot, 1),
            "ratio": round(eta_tot / etc_tot, 3) if etc_tot else 1.0}
