"""Irrigation planning: doses, intervals, durations and a CP-SAT daily timetable.

Per parcel and day:  ETc = Kc(day) x ET0(day)   (Open-Meteo forecast if available,
otherwise NASA POWER climatology).  Effective forecast rain = 0.8 x rain if > 5 mm.
* drip: daily dose (high-frequency practice) = net / efficiency.
* sprinkler / surface: soil-water balance, irrigate when depletion reaches RAW
  (FAO-56 ch. 8), dose = depletion / efficiency (+ leaching requirement).
Timetable: for each day an OR-Tools CP-SAT model places every irrigation event
(interval of duration = volume / source flow) inside the allowed window, with
NoOverlap per water source (one sector at a time on a pump), minimising energy
not covered by solar PV and, for sprinklers, irrigation during windy/hot hours.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta

from ortools.sat.python import cp_model

from app.engines.fao56 import adjusted_p, kc_on_day, stage_on_day
from app.knowledge.crops import IRRIGATION_EFFICIENCY, crop

SLOT_MIN = 15


@dataclass
class ParcelIrrigation:
    label: str
    crop: str
    area_m2: float
    planting: date
    source_index: int
    flow_m3h: float | None       # None: not given on the plan -> durations cannot be computed
    pump_kw: float | None
    specific_energy_kwh_m3: float
    taw_mm_per_m: float
    leaching: float = 0.0


def daily_requirements(p: ParcelIrrigation, method: str, days: list[dict]) -> list[dict]:
    """days: [{'date','et0','rain'}]. Returns irrigation events (before timetabling)."""
    c = crop(p.crop)
    eff = IRRIGATION_EFFICIENCY.get(method, 0.75)
    zr = c.root_depth_m[1]
    taw = p.taw_mm_per_m * zr
    depletion = 0.0
    out = []
    for d in days:
        dt = date.fromisoformat(d["date"])
        k = (dt - p.planting).days
        if k < 0 or (not c.perennial and k >= c.cycle_days):
            continue
        kc = kc_on_day(c, k)
        etc = kc * (d["et0"] or 0.0)
        rain = d.get("rain") or 0.0
        peff = d["peff"] if "peff" in d else (0.8 * rain if rain > 5 else 0.0)
        raw = adjusted_p(c.p, etc) * taw
        # rooting depth grows during development for annual crops (FAO-56 eq. 8 simplification)
        net = 0.0
        if method == "drip":
            net = max(0.0, etc - peff)
        else:
            depletion = max(0.0, depletion + etc - peff)
            if depletion >= raw:
                net = depletion
                depletion = 0.0
        if net <= 0.05:
            continue
        gross_mm = net / eff / (1 - p.leaching)
        vol = gross_mm * p.area_m2 / 1000.0
        hours = vol / p.flow_m3h if p.flow_m3h else None
        out.append({"date": d["date"], "parcel": p.label, "crop": p.crop, "stage": stage_on_day(c, k),
                    "kc": round(kc, 2), "etc_mm": round(etc, 2), "net_mm": round(net, 2),
                    "gross_mm": round(gross_mm, 2), "volume_m3": round(vol, 2),
                    "duration_min": math.ceil(hours * 60) if hours is not None else None,
                    "source_index": p.source_index, "energy_kwh": round(vol * p.specific_energy_kwh_m3, 2),
                    "pump_kw": p.pump_kw})
    return out


def timetable_day(events: list[dict], pv_kw_by_hour: list[float] | None, method: str,
                  window: tuple[int, int] = (5, 22), max_hours_by_source: dict[int, float] | None = None) -> list[dict]:
    """Place events of one day with CP-SAT. Events too long for the window are split over several pulses."""
    if not events:
        return []
    start_slot, end_slot = window[0] * 60 // SLOT_MIN, window[1] * 60 // SLOT_MIN
    horizon = end_slot - start_slot
    m = cp_model.CpModel()
    by_src: dict[int, list] = {}
    starts, cost_vars, placed = [], [], []
    for i, ev in enumerate(events):
        dur = max(1, math.ceil(ev["duration_min"] / SLOT_MIN))
        if dur > horizon:
            dur = horizon
            ev["truncated"] = True
        cost = []
        for s in range(horizon - dur + 1):
            c = 0.0
            for k in range(dur):
                hour = (start_slot + s + k) * SLOT_MIN // 60
                pv = pv_kw_by_hour[hour] if pv_kw_by_hour else 0.0
                uncovered = max(0.0, ev["pump_kw"] - pv)
                c += uncovered * SLOT_MIN / 60
                if method == "sprinkler" and 11 <= hour < 17:
                    c += 0.5 * ev["pump_kw"] * SLOT_MIN / 60 + 1.0   # wind drift / evaporation losses
                if method != "drip" and not pv_kw_by_hour and 11 <= hour < 17:
                    c += 0.2
            cost.append(int(round(c * 100)))
        st = m.NewIntVar(0, horizon - dur, f"s{i}")
        iv = m.NewIntervalVar(st, dur, st + dur, f"iv{i}")
        cv = m.NewIntVar(0, max(cost) if cost else 0, f"c{i}")
        m.AddElement(st, cost, cv)
        by_src.setdefault(ev["source_index"], []).append(iv)
        starts.append((st, dur))
        cost_vars.append(cv)
        placed.append(ev)
    for ivs in by_src.values():
        m.AddNoOverlap(ivs)
    m.Minimize(sum(cost_vars))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 5.0
    solver.parameters.num_workers = 4
    res = solver.Solve(m)
    out = []
    feasible = res in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    for (st, dur), ev in zip(starts, placed):
        if feasible:
            s_min = (start_slot + solver.Value(st)) * SLOT_MIN
        else:
            s_min = None
        e = dict(ev)
        if s_min is not None:
            e["start"] = f"{s_min // 60:02d}:{s_min % 60:02d}"
            end = s_min + ev["duration_min"]
            e["end"] = f"{(end // 60) % 24:02d}:{end % 60:02d}"
            if pv_kw_by_hour:
                covered = 0.0
                for k in range(dur):
                    hour = (s_min + k * SLOT_MIN) // 60
                    covered += min(ev["pump_kw"], pv_kw_by_hour[hour % 24]) * SLOT_MIN / 60
                tot = ev["pump_kw"] * dur * SLOT_MIN / 60
                e["solar_share"] = round(covered / tot, 2) if tot else 0.0
        else:
            e["start"] = e["end"] = None
            e["conflict"] = True   # pump capacity insufficient for the day
        out.append(e)
    out.sort(key=lambda x: (x.get("start") or "99"))
    return out


def plan_week(parcels: list[ParcelIrrigation], method: str, days: list[dict], pv_kw_by_month_hour=None) -> dict:
    all_events = []
    for p in parcels:
        all_events.extend(daily_requirements(p, method, days))
    by_day: dict[str, list] = {}
    for e in all_events:
        by_day.setdefault(e["date"], []).append(e)
    schedule = []
    for d in sorted(by_day):
        month = int(d[5:7]) - 1
        pv = pv_kw_by_month_hour[month] if pv_kw_by_month_hour else None
        timed = [e for e in by_day[d] if e["duration_min"] is not None and e["pump_kw"] is not None]
        untimed = [{**e, "start": None, "end": None, "duration_unknown": True} for e in by_day[d]
                   if e["duration_min"] is None or e["pump_kw"] is None]
        schedule.extend(timetable_day(timed, pv, method) + untimed)
    return {"events": schedule,
            "total_m3": round(sum(e["volume_m3"] for e in schedule), 1),
            "total_kwh": round(sum(e["energy_kwh"] for e in schedule), 1),
            "conflicts": sum(1 for e in schedule if e.get("conflict"))}


def climatology_days(start: date, n: int, et0_month: list[float], rain_month: list[float]) -> list[dict]:
    """Day list from monthly normals; monthly effective rainfall (FAO/AGLW) is spread evenly."""
    import calendar

    from app.engines.fao56 import effective_rain_monthly
    out = []
    for k in range(n):
        d = start + timedelta(days=k)
        dim = calendar.monthrange(d.year, d.month)[1]
        out.append({"date": d.isoformat(), "et0": et0_month[d.month - 1], "rain": rain_month[d.month - 1] / dim,
                    "peff": effective_rain_monthly(rain_month[d.month - 1]) / dim, "quality": "estimated"})
    return out
