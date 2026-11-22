from app.engines import forecast
from app.models import ModelRun


def test_backtest_registers_all_models_and_selects_best(db):
    # Population falls back to FAOSTAT FBS (World Bank is offline in tests); data = real FAOSTAT extract.
    r = forecast.train_and_select(db, "demand_per_capita")
    assert r["status"] == "ok" and "wheat" in r["crops"]
    runs = db.query(ModelRun).filter_by(task="demand_per_capita", item="wheat").all()
    assert {"naive", "moving_avg_3", "linear_trend", "lightgbm", "xgboost"} <= {x.model_name for x in runs}
    sel = [x for x in runs if x.selected]
    assert len(sel) == 1
    assert sel[0].metrics["mape_pct"] == min(x.metrics["mape_pct"] for x in runs if x.metrics["mape_pct"] is not None)
    f = forecast.forecast(db, "demand_per_capita", "wheat", [2023, 2028])
    assert f["values"][2023]["quality"] == "official"
    assert f["values"][2028]["quality"] == "forecast"
    assert f["values"][2028]["low"] <= f["values"][2028]["value"] <= f["values"][2028]["high"]
