"""Planning module v2: simplified inputs -> automatic climate -> optimised 2D plan -> tables A-E.

Network is off (conftest): climate statistics are absent unless a test injects TEST data.
"""
from datetime import date, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from shapely.geometry import Polygon, shape
from shapely.ops import unary_union

from app.connectors import climate
from app.engines import crop_calendar
from app.knowledge.crops import CROPS

FIX = Path(__file__).parent / "fixtures" / "plans"


def _farmer(c, email):
    r = c.post("/api/auth/register", json={"email": email, "full_name": "Tester", "password": "password1"})
    if r.status_code == 409:
        r = c.post("/api/auth/token", data={"username": email, "password": "password1"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# ------------------------------------------------------------- unit tests
def _stats(frost_months):
    return {"months": [{"month": m, "frost_probability": 0.5 if m in frost_months else 0.0,
                        "heat_days_mean": 0, "heavy_rain_days": 0} for m in range(1, 13)],
            "annual": {"rain_cv_pct": 10}}


def test_frost_aware_planting_avoids_frost_months():
    tomato = CROPS["tomato"]
    assert tomato.frost_sensitive
    d, why = crop_calendar.choose_planting(tomato, date(2026, 1, 5), _stats({1, 2, 3}))
    months = {(d.toordinal() + k) for k in range(0, tomato.cycle_days, 7)}
    assert why["rule"] in ("first_frost_free_cycle", "frost_risk_unavoidable")
    if why["rule"] == "first_frost_free_cycle":
        assert not {date.fromordinal(o).month for o in months} & {1, 2, 3}
    # without frost statistics: middle of the indicative window
    d2, why2 = crop_calendar.choose_planting(tomato, date(2026, 1, 5), None)
    assert why2["rule"] == "window_middle"


def test_rotation_changes_family_and_prefers_legumes_after_heavy_feeders():
    r = crop_calendar.rotation("tomato", date(2026, 7, 1), ["pepper", "faba_bean", "wheat", "onion"])
    assert r["crop"] != "pepper" and crop_calendar.FAMILY[r["crop"]] != "solanaceae"
    assert crop_calendar.rotation("olive", date(2026, 7, 1), ["wheat"]) is None


def test_climate_risks_from_normals_and_statistics():
    normals = {"months": [{"month": m, "rain_mm": 60 if m in (11, 12, 1) else 5, "et0_mm": 100} for m in range(1, 13)],
               "annual": {"rain_mm": 225, "et0_mm": 1200}}
    r = climate.risks(normals, _stats({1}))
    assert r["zone"] == "arid" and 7 in r["dry_months"]
    assert any(i["code"] == "frost" and i["months"] == [1] for i in r["items"])
    assert any(i["code"] == "long_dry_season" for i in r["items"])


def test_phases_follow_fao56_stages():
    c = CROPS["onion"]
    p = date(2026, 10, 1)
    h = date.fromordinal(p.toordinal() + c.cycle_days)
    ph = {x["phase"]: x for x in crop_calendar.phases(c, p, h, ["2026-11", "2027-01"])}
    assert ph["soil_preparation"]["indicative"] and ph["soil_preparation"]["end"] < p.isoformat()
    assert ph["growth"]["stages"]["mid"] == c.stages[2]
    assert ph["harvest"]["end"] == h.isoformat()
    assert ph["irrigation"]["months"] == ["2026-11", "2027-01"]


# -------------------------------------------------------------- end to end
def test_inputs_to_optimised_plan_and_tables():
    from app.main import app
    c = TestClient(app)
    H = _farmer(c, "inputs-v2@test.tn")
    r = c.post("/api/farms/import", files={"file": ("kairouan.pdf", (FIX / "kairouan.pdf").read_bytes())}, headers=H)
    j = r.json()
    farm = j["farm"]
    fid = farm["id"]
    inp = c.get(f"/api/farms/{fid}/inputs", headers=H).json()
    assert "gps" in inp["missing"]                                  # no GPS on the plan: asked, not invented
    assert any(m.startswith("flow") for m in inp["missing"])
    sc = c.get(f"/api/farms/{fid}/plans/{j['plan']['id']}/scene", headers=H).json()
    assert len(sc["edges"]) == len(sc["boundary"])
    # farmer gives: GPS, sources (same positions), flow, depth, pump power, grid, tariff, PV
    srcs = [{"kind": "borehole", "name": s["name"], "x_m": s["xy"][0], "y_m": s["xy"][1], "flow_m3h": 6.0,
             "depth_m": 40, "pump_kw": 3.0, "daily_volume_m3": 13.0} for s in sc["sources"]]
    body = {"latitude": 35.68, "longitude": 10.10, "delegation": "Kairouan Sud", "sources": srcs, "grid": "yes",
            "grid_tariff_tnd_kwh": 0.2, "pv_kwc": 5, "irrigation_method": "drip",
            "entrance": {"x_m": sc["boundary"][0][0], "y_m": sc["boundary"][0][1]}}
    r = c.put(f"/api/farms/{fid}/inputs", json=body, headers=H)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["plan"], out["plan_error"]
    assert out["farm"]["delegation"] == "Kairouan Sud"
    assert "gps" not in out["inputs"]["missing"] and "grid" not in out["inputs"]["missing"]
    plan = out["plan"]
    # same terrain: area of the boundary unchanged by the re-anchoring (exact contour kept)
    assert out["farm"]["measured_area_ha"] == pytest.approx(4.4445, rel=0.005)
    # zones labelled A, B, C ... ; parcels valid, non-overlapping, inside the terrain
    # one zone letter per crop (A = largest), its pieces are sectors A1, A2 ...
    labels = [p["label"] for p in plan["parcels"]]
    assert any(x.startswith("A") for x in labels)
    zones = {}
    for x in labels:
        z = x.rstrip("0123456789")
        assert z.isalpha() and len(z) <= 2
        zones.setdefault(z, []).append(x)
    crops_by_zone = {}
    for p in plan["parcels"]:
        crops_by_zone.setdefault(p["label"].rstrip("0123456789"), set()).add(p["crop"])
    assert all(len(c) == 1 for c in crops_by_zone.values())          # a zone = one crop
    assert len(crops_by_zone) == len({p["crop"] for p in plan["parcels"]})  # a crop = one zone
    polys = [shape(p["geometry"]) for p in plan["parcels"]]
    assert all(p.is_valid for p in polys)
    b = shape(out["farm"]["boundary"])
    assert unary_union(polys).difference(b.buffer(1e-7)).area < 1e-9
    tot = sum(p.area for p in polys)
    assert unary_union(polys).area == pytest.approx(tot, rel=1e-6)    # no overlap
    # tables A-E
    rep = c.get(f"/api/farms/{fid}/plans/{plan['id']}/report", headers=H).json()
    A = rep["allocation"]
    assert [a["zone"] for a in A] == sorted(zones, key=lambda x: (len(x), x))     # one row per zone
    assert sorted(x["zone"] for a in A for x in a["sectors"]) == sorted(labels)
    assert rep["totals"]["zones"] == len(zones) and rep["totals"]["sectors"] == len(labels)
    assert sum(a["pct"] for a in A) <= 100.5
    irr = [a for a in A if not a["rainfed"]]
    assert irr and all(a["distance_m"] is not None and a["distance_m"] >= 0 for a in irr)
    assert all(a["irrigation"] == "drip" for a in irr)
    assert all(a["irrigation"] == "rainfed" and a["distance_m"] is None for a in A if a["rainfed"])
    B = rep["irrigation"]
    assert any(x["events_per_week"] > 0 for x in B)
    assert all(x["duration_min"] is not None for x in B if x["events_per_week"])   # flow known -> durations
    # pump power declared: specific energy = 3 kW / 6 m3/h = 0.5 kWh/m3
    assert all(p["metrics"]["specific_energy_kwh_m3"] == pytest.approx(0.5) for p in plan["parcels"]
               if not p["metrics"]["rainfed"])
    # one pump never irrigates two zones at the same time
    week = plan["irrigation"]["weeks"]
    for wk in week.values():
        by = {}
        for e in wk["events"]:
            if e.get("start"):
                by.setdefault((e["date"], e["source_index"]), []).append(e)
        for evs in by.values():
            iv = sorted((datetime.strptime(e["start"], "%H:%M"), e["duration_min"]) for e in evs)
            for (s1, d1), (s2, _) in zip(iv, iv[1:]):
                assert (s2 - s1).total_seconds() / 60 >= d1 - 15         # 15-min slots
    C = rep["calendar"]
    assert C and all({"soil_preparation", "planting", "growth", "harvest"} <= {p["phase"] for p in x["phases"]}
                     for x in C)
    D = rep["energy"]
    assert D["pump_kwh_total"] > 0 and D["grid_tariff_tnd_kwh"] == 0.2 and D["cost_tnd"] is not None
    # production cost computed automatically for every crop of the plan (nothing typed by the farmer)
    S = plan["summary"]
    assert S["cost_tnd"] is not None and S["cost_tnd"] > 0
    assert set(S["costs"]) == {p["crop"] for p in plan["parcels"]}
    assert all(b["total_tnd_ha"] > 0 and b["items"]["labour"]["quality"] == "official" for b in S["costs"].values())
    assert D["split"] and D["split"]["basis"] == "existing_pv"
    E = rep["results"]
    assert E["total_t"] == pytest.approx(sum(x["production_t"] for x in E["production"]), abs=0.05)
    assert "grid_tariff" not in rep["missing"]


def test_side_length_rescales_the_imported_plan():
    from app.main import app
    c = TestClient(app)
    H = _farmer(c, "inputs-edge@test.tn")
    j = c.post("/api/farms/import", files={"file": ("nabeul.pdf", (FIX / "nabeul.pdf").read_bytes())},
               headers=H).json()
    fid = j["farm"]["id"]
    edges = c.get(f"/api/farms/{fid}/inputs", headers=H).json()["terrain"]["edges"]
    a0 = j["farm"]["measured_area_ha"]
    r = c.put(f"/api/farms/{fid}/inputs", json={"edge_index": 0, "edge_length_m": edges[0]["length_m"] * 2,
                                               "generate": False}, headers=H).json()
    assert r["farm"]["measured_area_ha"] == pytest.approx(4 * a0, rel=0.01)
    assert r["farm"]["area_validated"]
    e2 = r["inputs"]["terrain"]["edges"]
    assert e2 is None or e2[0]["length_m"] == pytest.approx(2 * edges[0]["length_m"], rel=1e-3)


def test_tight_quota_fills_remaining_land_with_rainfed_crops(monkeypatch):
    """Water quota too small for the whole terrain: irrigated area shrinks, the rest gets rainfed crops
    whose yield is reduced with FAO-33 (Ky), never irrigated, and the pipeline explains the limit."""
    from app.connectors import sources
    from app.engines.fao56 import MonthlyClimate
    from app.main import app
    from tests.conftest import TEST_CLIMATE
    wet = MonthlyClimate(TEST_CLIMATE.et0_mm_day, [r * 1.6 for r in TEST_CLIMATE.rain_mm], TEST_CLIMATE.tmax_c,
                         TEST_CLIMATE.tmin_c, "TEST FIXTURE (wetter)")
    monkeypatch.setattr(sources, "fetch_climate_normals", lambda db, lat, lon, entity=None: wet)
    c = TestClient(app)
    H = _farmer(c, "inputs-quota@test.tn")
    j = c.post("/api/farms/import", files={"file": ("kairouan.pdf", (FIX / "kairouan.pdf").read_bytes())},
               headers=H).json()
    fid = j["farm"]["id"]
    sc = c.get(f"/api/farms/{fid}/scene", headers=H).json()
    srcs = [{"kind": "borehole", "x_m": s["xy"][0], "y_m": s["xy"][1], "flow_m3h": 6.0, "depth_m": 40,
             "pump_kw": 3.0, "annual_quota_m3": 400.0} for s in sc["sources"][:1]]
    out = c.put(f"/api/farms/{fid}/inputs", json={"sources": srcs, "latitude": 35.68, "longitude": 10.10},
                headers=H).json()
    plan = out["plan"]
    assert plan, out["plan_error"]
    pl = plan["summary"]["pipeline"]
    assert "quota" in pl["water"]["limits"] and pl["water"]["quota_m3"] == 400
    assert pl["water"]["need_full_irrigation_m3"] > 400
    assert pl["optimisation"]["rainfed_ha"] > 0
    rain = [p for p in plan["parcels"] if p["metrics"]["rainfed"]]
    assert rain and all(p["metrics"]["water_m3_season"] == 0 and p["metrics"]["pipe"] is None for p in rain)
    assert all(0.5 <= p["metrics"]["ya_ym"] <= 1 for p in rain)
    assert all(CROPS[p["crop"]].rainfed_possible for p in rain)
    used = sum(p["metrics"]["water_m3_season"] for p in plan["parcels"])
    assert used <= 400 * 1.01
    rep = c.get(f"/api/farms/{fid}/plans/{plan['id']}/report", headers=H).json()
    assert any(a["irrigation"] == "rainfed" for a in rep["allocation"])


def test_create_farm_from_map_needs_no_surface_or_place():
    """Drawn outline only -> governorate, GPS and area computed from the geometry; outside Tunisia refused."""
    from app.main import app
    c = TestClient(app)
    H = _farmer(c, "from-map@test.tn")
    # ~200 m x ~150 m rectangle near Nabeul (Cap Bon)
    lon0, lat0, dx, dy = 10.73, 36.45, 0.0022, 0.00135
    poly = {"type": "Polygon", "coordinates": [[[lon0, lat0], [lon0 + dx, lat0], [lon0 + dx, lat0 + dy],
                                                [lon0, lat0 + dy], [lon0, lat0]]]}
    r = c.post("/api/farms/from-map", json={"boundary": poly}, headers=H)
    assert r.status_code == 201, r.text
    f = r.json()["farm"]
    assert f["governorate_code"] == "TN-21" and f["area_validated"]
    assert 2.5 < f["measured_area_ha"] < 3.5
    assert f["latitude"] == pytest.approx(lat0 + dy / 2, abs=1e-3)
    assert "gps" not in r.json()["inputs"]["missing"]
    far = {"type": "Polygon", "coordinates": [[[2.0, 48.0], [2.01, 48.0], [2.01, 48.01], [2.0, 48.0]]]}
    assert c.post("/api/farms/from-map", json={"boundary": far}, headers=H).status_code == 422
