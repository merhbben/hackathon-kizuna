"""Demand and yield forecasting with honest model selection.

Data
----
* Demand: FAOSTAT Food Balance Sheets (domestic supply quantity = food + feed +
  seed + processing + losses + other uses), divided by population -> kg/capita/yr.
  Forecast per-capita demand, then multiply by World Bank population projections.
* Yield: FAOSTAT QCL national yields (kg/ha), 1961-latest.

Models compared (rolling-origin / expanding-window temporal backtest):
* naive (last value), moving average (3), linear trend (OLS on year),
* LightGBM and XGBoost on a pooled panel (all crops) with scale-free features
  (ratios to the 3-year mean, lags, crop one-hot) so that short national series
  can share information.

Best model per crop = lowest backtest MAPE. Every run is written to the
`model_runs` registry with metrics, params, library versions and a signature
of the training data. With ~14 annual points per crop the ML models frequently
do NOT beat simple baselines; the selection reports that faithfully.
"""
from __future__ import annotations

import hashlib
import json
import warnings
from dataclasses import dataclass

import numpy as np
import pandas as pd
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.connectors.base import series
from app.knowledge.crops import CROPS
from app.models import DataRecord, ModelRun

warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=FutureWarning)
VERSION = "1.0.0"


# ------------------------------------------------------------------ data ---
def population_series(db: Session) -> pd.Series:
    hist = {int(r.period): r.value for r in series(db, "WB_WDI", "population")}
    proj = {int(r.period): r.value for r in series(db, "WB_POP_PROJ", "population")}
    if not hist:  # fall back to FAOSTAT FBS population (1000 persons)
        hist = {int(r.period): r.value * 1000 for r in series(db, "FAOSTAT_FBS", "population_k", "TN", "")}
    allp = {**proj, **hist}  # history wins where both exist
    return pd.Series(allp).sort_index()


def demand_per_capita_panel(db: Session) -> pd.DataFrame:
    pop = population_series(db)
    rows = []
    for code, c in CROPS.items():
        if not c.faostat_fbs:
            continue
        for r in series(db, "FAOSTAT_FBS", "domestic_supply_kt", "TN", code):
            y = int(r.period)
            if y in pop.index and r.value is not None:
                rows.append({"crop": code, "year": y, "value": r.value * 1e6 / pop[y]})  # kg/cap/yr
    return pd.DataFrame(rows)


def yield_panel(db: Session) -> pd.DataFrame:
    rows = []
    for code in CROPS:
        for r in series(db, "FAOSTAT_QCL", "yield_kg_ha", "TN", code):
            if r.value:
                rows.append({"crop": code, "year": int(r.period), "value": r.value})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- models ---
def _naive(hist: np.ndarray, _years: np.ndarray, _target_year: int) -> float:
    return float(hist[-1])


def _ma3(hist, _y, _t):
    return float(np.mean(hist[-3:]))


def _trend(hist, years, target_year):
    n = min(len(hist), 10)
    a, b = np.polyfit(years[-n:], hist[-n:], 1)
    return float(max(0.0, a * target_year + b))


BASELINES = {"naive": _naive, "moving_avg_3": _ma3, "linear_trend": _trend}


def _features(vals: np.ndarray, idx: int) -> list[float]:
    base = np.mean(vals[idx - 3:idx])
    return [vals[idx - 1] / base, vals[idx - 2] / base, vals[idx - 3] / base,
            (vals[idx - 1] - vals[idx - 2]) / base, np.std(vals[idx - 3:idx]) / base]


def _panel_xy(panel: pd.DataFrame, crops: list[str], max_year: int):
    X, y = [], []
    for c in crops:
        s = panel[(panel.crop == c) & (panel.year <= max_year)].sort_values("year")
        vals = s.value.to_numpy(float)
        for i in range(3, len(vals)):
            base = np.mean(vals[i - 3:i])
            if base <= 0:
                continue
            X.append(_features(vals, i) + [1.0 if c == k else 0.0 for k in crops])
            y.append(vals[i] / base)
    return np.array(X), np.array(y)


def _make_ml(name: str):
    if name == "lightgbm":
        import lightgbm as lgb
        return lgb.LGBMRegressor(n_estimators=200, learning_rate=0.05, num_leaves=7, min_child_samples=5,
                                 subsample=0.9, colsample_bytree=0.9, verbose=-1, random_state=42)
    import xgboost as xgb
    return xgb.XGBRegressor(n_estimators=200, learning_rate=0.05, max_depth=3, subsample=0.9,
                            colsample_bytree=0.9, random_state=42, n_jobs=1)


def _lib_versions() -> dict:
    import lightgbm
    import sklearn
    import xgboost
    return {"lightgbm": lightgbm.__version__, "xgboost": xgboost.__version__, "sklearn": sklearn.__version__,
            "numpy": np.__version__, "pandas": pd.__version__}


@dataclass
class Backtest:
    model: str
    crop: str
    mape: float
    mae: float
    n: int
    errors: list[dict]


def _signature(panel: pd.DataFrame) -> str:
    return hashlib.sha256(panel.sort_values(["crop", "year"]).to_csv(index=False).encode()).hexdigest()[:16]


def backtest(panel: pd.DataFrame, n_test_years: int = 4, min_train: int = 6) -> list[Backtest]:
    crops = sorted(panel.crop.unique())
    results: dict[tuple, list] = {}
    last_year = int(panel.year.max())
    test_years = list(range(last_year - n_test_years + 1, last_year + 1))
    ml_models = {}
    for ty in test_years:
        X, y = _panel_xy(panel, crops, ty - 1)
        if len(y) >= 10:
            for name in ("lightgbm", "xgboost"):
                m = _make_ml(name)
                m.fit(X, y)
                ml_models[(name, ty)] = m
        for c in crops:
            s = panel[panel.crop == c].sort_values("year")
            train = s[s.year < ty]
            actual = s[s.year == ty]
            if len(train) < min_train or actual.empty:
                continue
            hist, years = train.value.to_numpy(float), train.year.to_numpy(float)
            a = float(actual.value.iloc[0])
            preds = {k: f(hist, years, ty) for k, f in BASELINES.items()}
            for name in ("lightgbm", "xgboost"):
                if (name, ty) in ml_models:
                    vals = np.append(hist, np.nan)
                    feats = _features(vals, len(vals) - 1) + [1.0 if c == k else 0.0 for k in crops]
                    ratio = float(ml_models[(name, ty)].predict(np.array([feats]))[0])
                    preds[name] = ratio * float(np.mean(hist[-3:]))
            for k, p in preds.items():
                results.setdefault((k, c), []).append({"year": ty, "actual": a, "pred": p})
    out = []
    for (k, c), errs in results.items():
        ae = [abs(e["pred"] - e["actual"]) for e in errs]
        ape = [abs(e["pred"] - e["actual"]) / e["actual"] for e in errs if e["actual"]]
        out.append(Backtest(k, c, float(np.mean(ape) * 100) if ape else float("nan"), float(np.mean(ae)), len(errs),
                            errs))
    return out


def _forecast_one(panel: pd.DataFrame, crop: str, model: str, horizon_years: list[int]) -> dict[int, float]:
    crops = sorted(panel.crop.unique())
    s = panel[panel.crop == crop].sort_values("year")
    hist, years = s.value.to_numpy(float), s.year.to_numpy(float)
    out = {}
    fitted = None
    if model in ("lightgbm", "xgboost"):
        X, y = _panel_xy(panel, crops, int(panel.year.max()))
        fitted = _make_ml(model)
        fitted.fit(X, y)
    for ty in horizon_years:
        if model in BASELINES:
            p = BASELINES[model](hist, years, ty)
        else:
            vals = np.append(hist, np.nan)
            feats = _features(vals, len(vals) - 1) + [1.0 if crop == k else 0.0 for k in crops]
            p = float(fitted.predict(np.array([feats]))[0]) * float(np.mean(hist[-3:]))
        out[ty] = max(0.0, p)
        hist = np.append(hist, p)
        years = np.append(years, ty)
    return out


def train_and_select(db: Session, task: str) -> dict:
    """Run the backtest, register every model run, select best per crop. task: demand_per_capita | yield."""
    panel = demand_per_capita_panel(db) if task == "demand_per_capita" else yield_panel(db)
    if task == "yield":
        panel = panel[panel.year >= panel.year.max() - 30]   # recent regime only
    if panel.empty:
        return {"task": task, "status": "no_data", "crops": {}}
    sig = _signature(panel)
    bts = backtest(panel)
    db.execute(delete(ModelRun).where(ModelRun.task == task))
    libs = _lib_versions()
    best: dict[str, Backtest] = {}
    for b in bts:
        if np.isnan(b.mape):
            continue
        if b.crop not in best or b.mape < best[b.crop].mape:
            best[b.crop] = b
    for b in bts:
        db.add(ModelRun(task=task, item=b.crop, model_name=b.model, version=VERSION,
                        params={"libs": libs, "backtest": "expanding window, last 4 years, 1-step ahead"},
                        metrics={"mape_pct": None if np.isnan(b.mape) else round(b.mape, 2),
                                 "mae": round(b.mae, 3), "n_test": b.n,
                                 "errors": [{k: (round(v, 3) if isinstance(v, float) else v) for k, v in e.items()}
                                            for e in b.errors]},
                        data_signature=sig, selected=best.get(b.crop) is b))
    db.commit()
    summary = {}
    for crop, b in best.items():
        comp = {x.model: round(x.mape, 2) for x in bts if x.crop == crop and not np.isnan(x.mape)}
        summary[crop] = {"selected": b.model, "mape_pct": round(b.mape, 2), "comparison": comp,
                         "ml_beats_baselines": b.model in ("lightgbm", "xgboost")}
    return {"task": task, "status": "ok", "data_signature": sig, "years": [int(panel.year.min()), int(panel.year.max())],
            "crops": summary}


def selected_model(db: Session, task: str, crop: str) -> ModelRun | None:
    return db.scalar(select(ModelRun).filter_by(task=task, item=crop, selected=True))


def forecast(db: Session, task: str, crop: str, years: list[int]) -> dict | None:
    panel = demand_per_capita_panel(db) if task == "demand_per_capita" else yield_panel(db)
    if panel.empty or crop not in set(panel.crop):
        return None
    run = selected_model(db, task, crop)
    if run is None:
        train_and_select(db, task)
        run = selected_model(db, task, crop)
    model = run.model_name if run else "naive"
    s = panel[panel.crop == crop].sort_values("year")
    last = int(s.year.max())
    horizon = [y for y in range(last + 1, max(years) + 1)]
    pred = _forecast_one(panel, crop, model, horizon) if horizon else {}
    errs = [e for e in (run.metrics.get("errors", []) if run else [])]
    rel = [(e["pred"] - e["actual"]) / e["actual"] for e in errs if e["actual"]]
    sigma = float(np.std(rel)) if len(rel) >= 2 else 0.10
    hist = {int(y): float(v) for y, v in zip(s.year, s.value)}
    out = {}
    for y in years:
        if y in hist:
            out[y] = {"value": hist[y], "quality": "official", "low": hist[y], "high": hist[y]}
        elif y in pred:
            k = y - last
            band = 1.2816 * sigma * np.sqrt(k)
            band = float(band)
            out[y] = {"value": pred[y], "quality": "forecast", "low": pred[y] * max(0.0, 1 - band),
                      "high": pred[y] * (1 + band)}
    return {"crop": crop, "model": model, "mape_pct": run.metrics.get("mape_pct") if run else None,
            "last_observed_year": last, "values": out}


def latest_value(db: Session, dataset: str, indicator: str, item: str, entity: str = "TN") -> tuple[float, int] | None:
    rows = [r for r in series(db, dataset, indicator, entity, item) if r.value is not None]
    if not rows:
        return None
    r = rows[-1]
    return r.value, int(r.period[:4])


def mean_last(db: Session, dataset: str, indicator: str, item: str, n: int = 3) -> float | None:
    rows = [r.value for r in series(db, dataset, indicator, "TN", item) if r.value is not None][-n:]
    return float(np.mean(rows)) if rows else None


def dump(o) -> str:
    return json.dumps(o, default=str)


__all__ = ["train_and_select", "forecast", "population_series", "latest_value", "mean_last", "DataRecord"]
