"""Crop calendar: climate-aware planting date, FAO-56 growth stages, irrigation months, harvest, rotation.

* Planting: inside the indicative Tunisian planting window of the crop (knowledge/crops.py), the
  first date whose whole frost-sensitive part of the cycle avoids months where frost occurred in
  ≥ 20 % of the last 10 years (ERA5-Land daily minimum ≤ 0 °C). Without statistics -> window middle.
* Stages: FAO-56 L_ini / L_dev / L_mid / L_late (Table 11) from the planting date.
* Soil preparation: the 30 days before planting (indicative practice, flagged as such).
* Harvest window: the last 3 weeks of the late stage (or the late stage if shorter).
* Rotation: next crop of a different botanical family whose planting window opens after harvest;
  legumes are preferred before cereals and heavy feeders (FAO "Save and Grow", 2011, ch. 3).
"""
from __future__ import annotations

from datetime import date, timedelta

from app.knowledge.crops import CROPS, Crop

FAMILY = {"wheat": "poaceae", "barley": "poaceae", "potato": "solanaceae", "tomato": "solanaceae",
          "pepper": "solanaceae", "onion": "amaryllidaceae", "watermelon": "cucurbitaceae",
          "melon": "cucurbitaceae", "carrot": "apiaceae", "artichoke": "asteraceae", "chickpea": "fabaceae",
          "faba_bean": "fabaceae", "olive": "oleaceae", "orange": "rutaceae", "date_palm": "arecaceae",
          "almond": "rosaceae", "grape": "vitaceae"}
HEAVY_FEEDERS = {"potato", "tomato", "pepper", "watermelon", "melon", "wheat"}
PREP_DAYS = 30
FROST_PROB_MAX = 0.2


def _window_dates(c: Crop, today: date) -> list[date]:
    out = []
    for y in (today.year, today.year + 1):
        for (m1, m2) in c.planting_months:
            months = list(range(m1, m2 + 1)) if m1 <= m2 else list(range(m1, 13)) + list(range(1, m2 + 1))
            for m in months:
                yy = y + (1 if m1 > m2 and m < m1 else 0)
                for d in (1, 15):
                    out.append(date(yy, m, d))
    return sorted({d for d in out if d >= today})


def _frost_months(stats: dict | None) -> set[int]:
    if not stats:
        return set()
    return {m["month"] for m in stats["months"] if m["frost_probability"] >= FROST_PROB_MAX}


def choose_planting(c: Crop, today: date, stats: dict | None) -> tuple[date, dict]:
    """Return (planting date, justification)."""
    dates = _window_dates(c, today)
    if not dates:
        from app.engines.fao56 import default_planting_date
        return default_planting_date(c, today.year, today), {"rule": "window_middle"}
    frost = _frost_months(stats)
    if not c.frost_sensitive or not frost or c.perennial:
        # middle of the first window that is still ahead (same rule as the indicative calendar)
        from app.engines.fao56 import default_planting_date
        d = default_planting_date(c, today.year, today)
        return d, {"rule": "window_middle", "frost_months": sorted(frost)}
    span = c.cycle_days
    for d in dates:
        months = {(d + timedelta(days=k)).month for k in range(0, span, 7)}
        if not months & frost:
            return d, {"rule": "first_frost_free_cycle", "frost_months": sorted(frost)}
    return dates[0], {"rule": "frost_risk_unavoidable", "frost_months": sorted(frost)}


def phases(c: Crop, planting: date, harvest: date, irrigation_months: list[str]) -> list[dict]:
    li, ld, lm, ll = c.stages
    p = planting
    out = [{"phase": "soil_preparation", "start": (p - timedelta(days=PREP_DAYS)).isoformat(),
            "end": (p - timedelta(days=1)).isoformat(), "indicative": True},
           {"phase": "planting", "start": p.isoformat(), "end": (p + timedelta(days=min(li, 10))).isoformat()}]
    if not c.perennial:
        out.append({"phase": "growth", "start": (p + timedelta(days=li)).isoformat(),
                    "end": (p + timedelta(days=li + ld + lm)).isoformat(),
                    "stages": {"initial": li, "development": ld, "mid": lm, "late": ll}})
        hw = min(21, ll)
        out.append({"phase": "harvest", "start": (harvest - timedelta(days=hw)).isoformat(),
                    "end": harvest.isoformat()})
    else:
        out.append({"phase": "growth", "start": p.isoformat(), "end": harvest.isoformat(),
                    "stages": {"initial": li, "development": ld, "mid": lm, "late": ll}})
        out.append({"phase": "harvest", "start": (harvest - timedelta(days=min(30, ll))).isoformat(),
                    "end": harvest.isoformat()})
    if irrigation_months:
        out.append({"phase": "irrigation", "start": f"{min(irrigation_months)}-01",
                    "end": f"{max(irrigation_months)}-28", "months": sorted(irrigation_months)})
    return out


def rotation(code: str, harvest: date, candidates: list[str]) -> dict | None:
    c = CROPS[code]
    if c.perennial:
        return None
    fam = FAMILY.get(code)
    best = None
    for k in candidates:
        o = CROPS.get(k)
        if o is None or o.perennial or FAMILY.get(k) == fam:
            continue
        nxt = [d for d in _window_dates(o, harvest + timedelta(days=15))][:1]
        if not nxt:
            continue
        gap = (nxt[0] - harvest).days
        score = gap - (60 if (FAMILY.get(k) == "fabaceae" and code in HEAVY_FEEDERS) else 0)
        if best is None or score < best[0]:
            best = (score, k, nxt[0])
    if best is None:
        return {"crop": None, "reason": "no_compatible_candidate"}
    return {"crop": best[1], "planting": best[2].isoformat(), "from_family": fam, "to_family": FAMILY.get(best[1]),
            "reason": "legume_after_heavy_feeder" if FAMILY.get(best[1]) == "fabaceae" and code in HEAVY_FEEDERS
            else "different_family"}
