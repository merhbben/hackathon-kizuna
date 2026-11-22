"""Off-season cold-storage building for farms above storage.cold_building_min_ha (65 ha by default)."""
from datetime import date

import pytest
from fastapi.testclient import TestClient
from shapely.geometry import shape
from shapely.ops import unary_union

from app.engines import cold_store, storage
from app.engines.energy import EnergyPolicy
from app.knowledge.crops import CROPS
from tests.conftest import TEST_CLIMATE, _pv_profile
from tests.test_inputs_report import _farmer


def test_national_harvest_and_offseason_months():
    # onion planted Oct-Dec, ~150-day cycle -> harvested in spring; stored 24 weeks it reaches the summer gap
    nat = cold_store.national_harvest_months("onion")
    assert nat and nat <= {2, 3, 4, 5, 6}
    o = cold_store.offseason("onion", date(2027, 4, 20), 8)
    assert o["offseason_months"] and not set(o["offseason_months"]) & nat
    assert cold_store.offseason("tomato", date(2027, 7, 1), 8) is None      # 2 weeks of storage only
    assert cold_store.offseason("wheat", date(2027, 6, 1), 8) is None       # dry storage, no cold


def test_storage_stops_when_the_national_harvest_is_back():
    # potato harvested on the farm in January: shortage in March-April, national harvest again in May
    o = cold_store.offseason("potato", date(2027, 1, 20), 8)
    assert o["offseason_months"] == [3, 4]
    assert o["stops_at"] == "national_harvest" and o["sell_until"] == "2027-05-01"
    assert o["sell_until"] < o["conservation_limit"]                 # no refrigeration after the shortage
    assert 0 < o["efficiency"] < 1 and o["useful_days"] == 61


def test_compatible_crops_with_disjoint_periods_share_one_room():
    e = [("carrot", 30.0, date(2027, 1, 1), date(2027, 3, 1)), ("carrot", 20.0, date(2027, 6, 1), date(2027, 8, 1))]
    rooms = cold_store.building_rooms(e, TEST_CLIMATE.tmax_c)
    assert {r["room_id"] for r in rooms} == {1}
    assert rooms[0]["volume_m3"] == rooms[1]["volume_m3"] == pytest.approx(30.0 * 1000 / 350, rel=0.01)
    assert cold_store.rooms_floor_m2(rooms) == pytest.approx(rooms[0]["floor_m2"])
    # overlapping periods, or incompatible conditions (onion 68 % RH vs carrot 98 % RH): separate rooms
    e2 = [("carrot", 30.0, date(2027, 1, 1), date(2027, 3, 1)), ("carrot", 20.0, date(2027, 2, 1), date(2027, 4, 1))]
    assert len({r["room_id"] for r in cold_store.building_rooms(e2, TEST_CLIMATE.tmax_c)}) == 2
    e3 = [("carrot", 30.0, date(2027, 1, 1), date(2027, 3, 1)), ("onion", 50.0, date(2027, 6, 1), date(2027, 9, 1))]
    assert len({r["room_id"] for r in cold_store.building_rooms(e3, TEST_CLIMATE.tmax_c)}) == 2


def test_two_energy_scenarios_and_surplus_to_pumps():
    rooms = cold_store.building_rooms([("onion", 200.0, date(2027, 4, 20), date(2027, 10, 5))], TEST_CLIMATE.tmax_c)
    pumps = [0, 0, 500, 1500, 3000, 4000, 5000, 5000, 3000, 1000, 0, 0]
    tied = cold_store.size_energy(rooms, _pv_profile(), EnergyPolicy(), grid="yes", pump_kwh_month=pumps)
    off = cold_store.size_energy(rooms, _pv_profile(), EnergyPolicy(), grid="no", pump_kwh_month=pumps)
    assert tied["recommended"] == "grid_tied" and off["recommended"] == "off_grid"
    a, b = tied["scenarios"]["grid_tied"], tied["scenarios"]["off_grid"]
    assert a == off["scenarios"]["grid_tied"]                      # same study, different recommendation
    assert a["kwp"] < b["kwp"] and a["battery_kwh"] < b["battery_kwh"]
    assert a["net_coverage_pct"] == pytest.approx(100, abs=1)      # yearly PV = yearly cold consumption
    assert b["solar_coverage_pct"] >= 95 and a["grid_kwh"] > b["grid_kwh"]
    assert a["backup_hours"] == pytest.approx(6, abs=0.1)          # storage.cold_backup_hours
    for res in (tied, off):
        assert all(0 <= u <= min(s, p) + 1 for u, s, p in zip(res["pumps_from_surplus_kwh_month"],
                                                               res["scenarios"][res["recommended"]]["surplus_kwh_month"],
                                                               pumps))
    assert off["pumps_from_surplus_kwh"] > 0
    assert tied["kwh_per_t"] == pytest.approx(tied["annual_kwh"] / 200, rel=0.01)


def test_rank_uses_offseason_coverage_and_national_need():
    cands = {"onion": date(2027, 4, 20), "carrot": date(2027, 1, 20), "potato": date(2027, 5, 20)}
    base = cold_store.rank(cands, [], 8)
    assert [r["crop"] for r in base]
    assert all(r["score"] == pytest.approx(len(r["offseason_months"]) * (0.5 + 0.5 * r["efficiency"]), abs=1e-3)
               for r in base)
    # a strong national deficit on potato raises its rank
    bal = [{"crop": "potato", "gap_kt": -300.0, "required_kt": 400.0, "import_dependency_pct": 5}]
    ranked = cold_store.rank(cands, bal, 8)
    pot = next(r for r in ranked if r["crop"] == "potato")
    assert pot["need"] == pytest.approx(0.75) and pot["score"] > next(r for r in base if r["crop"] == "potato")["score"]


def test_room_runs_only_from_harvest_to_last_sale_and_solar_covers_it():
    room = storage.cold_room("onion", 200, TEST_CLIMATE.tmax_c)
    start, end = date(2027, 4, 20), date(2027, 10, 5)
    kwh = cold_store.room_monthly_kwh(room, start, end)
    assert all(v == 0 for m, v in enumerate(kwh) if m + 1 in (1, 2, 3, 11, 12))
    assert all(v > 0 for m, v in enumerate(kwh) if m + 1 in (5, 6, 7, 8, 9))
    # the field heat of the harvest is counted only during the 14 filling days (20 April -> 3 May)
    import copy
    hold = copy.deepcopy(room)
    for x in hold["monthly"]:
        x["parts_kw"]["product"] = 0.0
    k_hold = cold_store.room_monthly_kwh(hold, start, end)
    extra = [a - b for a, b in zip(kwh, k_hold)]
    assert extra[3] > 0 and extra[4] > 0 and all(abs(v) < 1e-9 for m, v in enumerate(extra) if m not in (3, 4))
    pol = EnergyPolicy()
    e = cold_store.size_energy([room], _pv_profile(), pol, {"onion": (start, end)})
    assert e["status"] == "ok" and e["annual_kwh"] == pytest.approx(sum(kwh), rel=0.01)
    assert e["kwp"] > 0 and e["panels"] == pytest.approx(e["kwp"] * 1000 / pol.panel_wp, abs=1)
    assert e["battery_kwh"] > 0 and e["solar_coverage_pct"] >= 95
    # every month with a load is covered by the dedicated PV production
    assert all(p >= l * 0.99 for p, l in zip(e["pv_kwh_month"], e["load_kwh_month"]))


def test_farm_above_65_ha_gets_a_cold_building_with_its_own_solar_plant():
    from app.main import app
    c = TestClient(app)
    H = _farmer(c, "cold-building@test.tn")
    # ~1000 m x ~800 m (about 80 ha) near Nabeul
    lon0, lat0, dx, dy = 10.70, 36.45, 0.0112, 0.0072
    poly = {"type": "Polygon", "coordinates": [[[lon0, lat0], [lon0 + dx, lat0], [lon0 + dx, lat0 + dy],
                                                [lon0, lat0 + dy], [lon0, lat0]]]}
    r = c.post("/api/farms/from-map", json={"boundary": poly}, headers=H)
    assert r.status_code == 201, r.text
    fid = r.json()["farm"]["id"]
    assert r.json()["farm"]["measured_area_ha"] > 65
    sc = c.get(f"/api/farms/{fid}/scene", headers=H).json()
    cx = sum(p[0] for p in sc["boundary"]) / len(sc["boundary"])
    cy = sum(p[1] for p in sc["boundary"]) / len(sc["boundary"])
    out = c.put(f"/api/farms/{fid}/inputs", json={
        "sources": [{"kind": "borehole", "x_m": cx, "y_m": cy, "flow_m3h": 40.0, "depth_m": 50, "pump_kw": 15.0}],
        "entrance": {"x_m": 0.0, "y_m": cy}}, headers=H).json()
    plan = out["plan"]
    assert plan, out.get("plan_error")
    rep = c.get(f"/api/farms/{fid}/plans/{plan['id']}/report", headers=H).json()
    cb = rep["cold_building"]
    assert cb["required"] and cb["threshold_ha"] == 65
    assert 1 <= len(cb["chosen"]) <= 2, cb
    for code in cb["chosen"]:
        assert CROPS[code].storage.cold and CROPS[code].storage.max_weeks >= 8
        assert code in plan["summary"]["optimizer"]["areas_ha"]
    o = cb["offseason"][0]
    assert o["offseason_months"] and not set(o["offseason_months"]) & set(o["national_harvest_months"])
    e = cb["energy"]
    assert e["status"] == "ok" and e["kwp"] > 0 and e["panels"] > 0 and e["solar_coverage_pct"] >= 90
    assert e["recommended"] == "off_grid" and e["recommendation_reason"] == "grid_unknown"   # grid not declared
    assert set(e["scenarios"]) == {"grid_tied", "off_grid"}
    # the cold PV surplus feeds the pumps: the irrigation PV design carries that much less energy
    assert plan["energy"]["pump_kwh_from_cold_pv"] == pytest.approx(e["pumps_from_surplus_kwh"], abs=2)
    # rooms of the building are in the storage results; the main PV design no longer carries the cold load
    assert {r["crop"] for r in rep["results"]["cold_rooms"] if r.get("purpose") == "offseason"} == set(cb["chosen"])
    # building and PV field drawn on the plan, inside the terrain, never on a crop parcel
    sc = c.get(f"/api/farms/{fid}/plans/{plan['id']}/scene", headers=H).json()
    kinds = {z["kind"] for z in sc["zones"]}
    assert {"cold_storage", "solar"} <= kinds
    site = unary_union([shape(cb["site"]["building"]), shape(cb["site"]["pv"])])
    assert site.difference(shape(poly).buffer(1e-7)).area < 1e-12
    parcels = unary_union([shape(p["geometry"]) for p in plan["parcels"]])
    assert parcels.intersection(site).area < 1e-10
    assert plan["summary"]["pipeline"]["cold_store"]["chosen"] == cb["chosen"]


def test_small_farm_has_no_cold_building():
    from app.main import app
    c = TestClient(app)
    H = _farmer(c, "cold-small@test.tn")
    lon0, lat0, dx, dy = 10.73, 36.45, 0.0022, 0.00135
    poly = {"type": "Polygon", "coordinates": [[[lon0, lat0], [lon0 + dx, lat0], [lon0 + dx, lat0 + dy],
                                                [lon0, lat0 + dy], [lon0, lat0]]]}
    fid = c.post("/api/farms/from-map", json={"boundary": poly}, headers=H).json()["farm"]["id"]
    out = c.put(f"/api/farms/{fid}/inputs", json={"sources": [{"kind": "borehole", "x_m": 100.0, "y_m": 70.0,
                                                               "flow_m3h": 8.0}]}, headers=H).json()
    assert out["plan"], out.get("plan_error")
    rep = c.get(f"/api/farms/{fid}/plans/{out['plan']['id']}/report", headers=H).json()
    assert rep["cold_building"] is None
