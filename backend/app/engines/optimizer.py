"""Crop-area optimisation for one farm (OR-Tools MILP, SCIP backend).

Decision variables: a_c >= 0 hectares of crop c, z_c in {0,1} crop selected.

    max   sum_c a_c * score_c
    s.t.  sum_c a_c                         <= A_productive
          sum_c a_c * gross_c,m              <= W_m          (each month m, m3)
          sum_c a_c * gross_c,year           <= Quota        (if an annual quota is set)
          sum_c a_c * cost_c                 <= Budget       (if costs and budget are known)
          a_c <= share_max * A_productive * z_c ;  a_c >= a_min * z_c
          sum_c z_c <= n_max ;  a_c >= locked_c

score_c is a weighted sum of normalised criteria:
    economic margin (if prices/costs are known), water productivity (kg/m3),
    national priority (import dependency from FAOSTAT FBS, or ministry targets),
    and relative yield from the suitability analysis.
Water-hungry crops are therefore reduced automatically when W_m is binding,
and unused land is reported instead of being silently filled.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ortools.linear_solver import pywraplp


@dataclass
class CropOption:
    code: str
    yield_kg_ha: float
    relative_yield: float
    gross_m3_ha_monthly: dict[str, float]   # 'YYYY-MM' -> m3/ha
    national_priority: float                 # 0..1
    price_tnd_kg: float | None = None
    cost_tnd_ha: float | None = None
    locked_ha: float = 0.0

    @property
    def gross_m3_ha(self) -> float:
        return sum(self.gross_m3_ha_monthly.values())

    @property
    def production_kg_ha(self) -> float:
        return self.yield_kg_ha * self.relative_yield

    @property
    def margin_tnd_ha(self) -> float | None:
        if self.price_tnd_kg is None or self.cost_tnd_ha is None:
            return None
        return self.production_kg_ha * self.price_tnd_kg - self.cost_tnd_ha


@dataclass
class OptimizationResult:
    status: str
    areas_ha: dict[str, float]
    objective: float
    binding: list[str]
    unused_ha: float
    water_use_m3: dict[str, float]
    weights: dict[str, float]
    scores: dict[str, dict] = field(default_factory=dict)


def _norm(vals: dict[str, float]) -> dict[str, float]:
    if not vals:
        return {}
    lo, hi = min(vals.values()), max(vals.values())
    if hi - lo < 1e-9:
        return {k: 1.0 for k in vals}
    return {k: (v - lo) / (hi - lo) for k, v in vals.items()}


def optimize(options: list[CropOption], productive_ha: float, water_m3_monthly: dict[str, float],
             annual_quota_m3: float | None = None, budget_tnd: float | None = None, large_farm: bool = False,
             max_crops: int | None = None, max_share: float | None = None, min_area_ha: float | None = None,
             weights: dict[str, float] | None = None) -> OptimizationResult:
    if not options or productive_ha <= 0:
        return OptimizationResult("no_options", {}, 0.0, [], productive_ha, {}, {})
    max_crops = max_crops or (7 if large_farm else 4)
    max_share = max_share or (0.6 if large_farm else 0.45)
    min_area_ha = min_area_ha if min_area_ha is not None else min(0.05 * productive_ha, 2.0 if large_farm else 0.05)
    w = dict(weights or ({"economic": 0.35, "water": 0.25, "national": 0.30, "yield": 0.10} if large_farm else
                         {"economic": 0.45, "water": 0.30, "national": 0.15, "yield": 0.10}))
    margins = {o.code: o.margin_tnd_ha for o in options}
    if any(m is None for m in margins.values()):
        # economic criterion only if every option has prices and costs; otherwise its weight is redistributed
        extra = w.pop("economic", 0.0)
        rest = sum(w.values())
        w = {k: v + extra * v / rest for k, v in w.items()}
    wp = {o.code: (o.production_kg_ha / o.gross_m3_ha) if o.gross_m3_ha > 1 else o.production_kg_ha
          for o in options}
    n_wp = _norm(wp)
    n_m = _norm({k: v for k, v in margins.items() if v is not None}) if "economic" in w else {}
    scores = {}
    for o in options:
        s = (w.get("water", 0) * n_wp[o.code] + w.get("national", 0) * o.national_priority
             + w.get("yield", 0) * o.relative_yield + w.get("economic", 0) * n_m.get(o.code, 0.0))
        scores[o.code] = {"score": round(s, 4), "water_productivity_kg_m3": round(wp[o.code], 3),
                          "national_priority": round(o.national_priority, 3),
                          "margin_tnd_ha": None if margins[o.code] is None else round(margins[o.code], 1)}

    solver = pywraplp.Solver.CreateSolver("SCIP")
    if solver is None:  # pragma: no cover
        solver = pywraplp.Solver.CreateSolver("CBC")
    a = {o.code: solver.NumVar(0.0, productive_ha, f"a_{o.code}") for o in options}
    z = {o.code: solver.BoolVar(f"z_{o.code}") for o in options}
    cons = {}
    cons["land"] = solver.Add(sum(a.values()) <= productive_ha)
    months = sorted({m for o in options for m in o.gross_m3_ha_monthly})
    for m in months:
        cap = water_m3_monthly.get(m[5:], water_m3_monthly.get(m))
        if cap is None:
            continue
        cons[f"water_{m}"] = solver.Add(sum(a[o.code] * o.gross_m3_ha_monthly.get(m, 0.0) for o in options) <= cap)
    if annual_quota_m3:
        cons["quota"] = solver.Add(sum(a[o.code] * o.gross_m3_ha for o in options) <= annual_quota_m3)
    if budget_tnd and all(o.cost_tnd_ha is not None for o in options):
        cons["budget"] = solver.Add(sum(a[o.code] * o.cost_tnd_ha for o in options) <= budget_tnd)
    for o in options:
        upper = max(max_share * productive_ha, o.locked_ha)
        solver.Add(a[o.code] <= upper * z[o.code])
        solver.Add(a[o.code] >= min(min_area_ha, upper) * z[o.code])
        if o.locked_ha > 0:
            solver.Add(a[o.code] >= o.locked_ha)
    solver.Add(sum(z.values()) <= max(max_crops, sum(1 for o in options if o.locked_ha > 0)))
    # tiny penalty on idle land avoids degenerate solutions; score scaled to keep the MILP well conditioned
    solver.Maximize(sum(a[o.code] * (scores[o.code]["score"] + 1e-3) for o in options))
    status = solver.Solve()
    if status not in (pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE):
        return OptimizationResult("infeasible", {}, 0.0, [], productive_ha, {}, w, scores)
    areas = {k: round(v.solution_value(), 4) for k, v in a.items() if v.solution_value() > 1e-4}
    used = sum(areas.values())
    binding = []
    for name, c in cons.items():
        act = sum(c.GetCoefficient(v) * v.solution_value() for v in a.values())
        if abs(act - c.ub()) <= max(1e-6, 1e-4 * abs(c.ub())):
            binding.append(name)
    water_use = {m: round(sum(areas.get(o.code, 0) * o.gross_m3_ha_monthly.get(m, 0) for o in options), 1)
                 for m in months}
    return OptimizationResult("optimal" if status == pywraplp.Solver.OPTIMAL else "feasible", areas,
                              solver.Objective().Value(), binding, round(productive_ha - used, 4), water_use, w,
                              scores)
