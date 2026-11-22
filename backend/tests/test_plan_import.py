"""Plan recognition tests on the user's synthetic technical plans (tests/fixtures/plans).

Fixtures: one page per plan extracted from Atlas_4_plans_agricoles_test.pdf (provided by the user),
exported as PDF, SVG, colour PNG (150 dpi) and black & white PNG (Otsu). Reference JSON = values
printed on each plan + geometry read from the PDF vector primitives.
"""
import json
import math
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from shapely.geometry import Polygon, shape

from app.cv.plan_parser import parse, to_geo
from app.engines import partition

FIX = Path(__file__).parent / "fixtures" / "plans"
PLANS = ["nabeul", "kairouan", "sfax", "gafsa"]
_cache: dict = {}


def ref(name):
    return json.loads((FIX / f"{name}.json").read_text(encoding="utf-8"))


def parsed(name, variant):
    key = (name, variant)
    if key not in _cache:
        fn = f"{name}{variant}"
        _cache[key] = parse((FIX / fn).read_bytes(), fn)
    return _cache[key]


def _common_checks(r, R, area_tol_pct, wp_tol_m, edge_tol=(0.005, 0.2)):
    assert r["ok"], r.get("warnings")
    printed = R["printed"]
    # 1. area vs printed area
    assert abs(r["area"]["measured_m2"] - printed["area_m2"]) / printed["area_m2"] * 100 <= area_tol_pct
    # 2. contour: same number of vertices, high overlap with the vector reference (same local frame)
    ref_poly = Polygon(R["vector_reference"]["boundary_m"])
    got = Polygon(r["boundary_m"])
    assert len(r["boundary_m"]) == len(R["vector_reference"]["boundary_m"])
    iou = got.intersection(ref_poly).area / got.union(ref_poly).area
    assert iou >= R["tolerances"]["iou_raster"]
    # 3. dimensions: every reference edge length found within 2 %
    ref_edges = sorted(e["length_m"] for e in R["vector_reference"]["edges"])
    got_edges = sorted(e["length_m"] for e in r["edges"])
    for a, b in zip(ref_edges, got_edges):
        assert abs(a - b) <= max(edge_tol[0] * a, edge_tol[1]), (a, b)
    # 4. water points: count and position
    rw = R["vector_reference"]["water_points"]
    assert len(r["water_points"]) == len(rw)
    for w in rw:
        d = min(math.dist((w["x_m"], w["y_m"]), (g["x_m"], g["y_m"])) for g in r["water_points"])
        assert d <= wp_tol_m, (w["name"], d)
    # 5. location
    assert r["metadata"]["governorate"]["code"] == printed["governorate"]


@pytest.mark.parametrize("name", PLANS)
@pytest.mark.parametrize("variant", [".pdf", ".svg"])
def test_vector_plans_exact(name, variant):
    R = ref(name)
    r = parsed(name, variant)
    _common_checks(r, R, area_tol_pct=0.5, wp_tol_m=1.0)
    assert r["method"] == "vector"
    assert sorted(r["vertex_labels"], key=lambda s: int(s[1:])) == R["vertex_labels"]
    m = r["metadata"]
    for k in ("water_m3_day", "pump_kw", "solar_kwc", "battery_kwh"):          # resources printed on the plan
        assert m[k] == pytest.approx(R["printed"][k]), k
    kinds = {}
    for z in r["zones"]:
        kinds[z["kind"]] = kinds.get(z["kind"], 0) + 1
    assert kinds == R["expected_zones"]
    lk = {}
    for ln in r["lines"]:
        lk[ln["kind"]] = lk.get(ln["kind"], 0) + 1
    assert lk == R["expected_lines"]


@pytest.mark.parametrize("name", PLANS)
@pytest.mark.parametrize("variant", [".png", "_bw.png"])
def test_raster_plans_ocr(name, variant):
    R = ref(name)
    r = parsed(name, variant)
    _common_checks(r, R, area_tol_pct=R["tolerances"]["area_pct_raster"], wp_tol_m=R["tolerances"]["water_point_m"],
                   edge_tol=(0.03, 2.0))
    assert r["method"] == "raster"
    assert r["metadata"]["pump_kw"] == pytest.approx(R["printed"]["pump_kw"])


def test_never_takes_page_frame_or_scale_bar_as_boundary():
    for name in PLANS:
        r = parsed(name, ".pdf")
        b = Polygon(r["boundary_m"])
        assert b.area == pytest.approx(ref(name)["printed"]["area_m2"], rel=0.005)   # frame would be far larger
        assert len(r["boundary_m"]) >= 4


@pytest.mark.parametrize("name", PLANS)
def test_partition_on_recognised_plan(name):
    r = parsed(name, ".pdf")
    geo = to_geo(r, 35.0, 10.0)
    excl = [shape(e["geometry"]) for e in geo["exclusions"]]
    from shapely.ops import unary_union
    excl_gj = unary_union(excl).__geo_interface__ if excl else None
    A = partition.area_m2(geo["boundary"])
    srcs = [partition.Source(None, w["longitude"], w["latitude"]) for w in geo["water_points"]]
    targets = {"tomato": 0.25 * A, "wheat": 0.35 * A, "onion": 0.15 * A}
    res = partition.partition(geo["boundary"], targets, {"tomato": 6000, "wheat": 2500, "onion": 5000}, srcs, excl_gj)
    polys = [partition.to_utm(shape(p["geometry"])) for p in res["parcels"]]
    field = partition.to_utm(shape(geo["boundary"]))
    ex_utm = [partition.to_utm(e) for e in excl]
    for p in polys:
        assert p.is_valid and p.area > 0
        assert field.buffer(0.5).contains(p)                                   # inside the boundary
        for e in ex_utm:
            assert p.intersection(e).area < 1.0                                # never on a building / basin / path
    for i in range(len(polys)):
        for j in range(i + 1, len(polys)):
            assert polys[i].intersection(polys[j]).area < 1.0                  # no overlap
    # surface conservation: parcels never exceed the targets and lose only paths / setbacks
    by = {}
    for p in res["parcels"]:
        by[p["crop"]] = by.get(p["crop"], 0) + p["area_m2"]
    for c, tgt in targets.items():
        assert 0.75 * tgt <= by.get(c, 0) <= tgt * 1.001, (c, by.get(c), tgt)
    total = sum(p.area for p in polys) + res["infrastructure_area_m2"] + sum(e.intersection(field).area for e in ex_utm)
    assert total <= field.area * 1.001


def _farmer(c):
    r = c.post("/api/auth/register", json={"email": "plans@test.tn", "full_name": "Plan Tester", "password": "password1"})
    if r.status_code == 409:
        r = c.post("/api/auth/token", data={"username": "plans@test.tn", "password": "password1"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_import_to_plan_scene_export_and_reopen():
    from app.main import app
    c = TestClient(app)
    H = _farmer(c)
    r = c.post("/api/farms/import", files={"file": ("kairouan.pdf", (FIX / "kairouan.pdf").read_bytes())}, headers=H)
    assert r.status_code == 201, r.text
    j = r.json()
    assert j["status"] == "ok" and j["plan"], j.get("plan_error")
    assert j["location_quality"] == "governorate_centroid"                     # no GPS on the plan: flagged
    farm, plan = j["farm"], j["plan"]
    assert farm["area_validated"] and farm["measured_area_ha"] == pytest.approx(4.4445, rel=0.005)
    assert {w["data_source"] for w in farm["water_sources"]} == {"plan"}
    assert sum(w["daily_volume_m3"] for w in farm["water_sources"]) == pytest.approx(26.0)
    assert {e["kind"] for e in farm["equipment"]} >= {"pump", "pv"}
    # declared water is a hard constraint: monthly use never exceeds 26 m3/day x days
    for m, used in plan["summary"]["water_use_m3"].items():
        assert used <= plan["summary"]["water_capacity_m3"][m] + 0.5                # summary values are rounded
    sc = c.get(f"/api/farms/{farm['id']}/plans/{plan['id']}/scene", headers=H).json()
    assert sc["format"] == "agrosphere.scene" and len({p["id"] for p in sc["parcels"]}) == len(plan["parcels"])
    assert sum(Polygon(p["polygon"]).area for p in sc["parcels"]) == pytest.approx(
        sum(p["area_m2"] for p in plan["parcels"]), rel=0.01)
    for fmt, ctype in (("svg", "image/svg+xml"), ("pdf", "application/pdf"), ("json", "application/json")):
        e = c.get(f"/api/farms/{farm['id']}/plans/{plan['id']}/export.{fmt}", headers=H)
        assert e.status_code == 200 and e.headers["content-type"].startswith(ctype) and len(e.content) > 500
    saved = json.loads(c.get(f"/api/farms/{farm['id']}/plans/{plan['id']}/export.json", headers=H).content)
    assert saved == sc                                                         # export -> re-open is lossless
    re = c.post("/api/scenes/render", json={"scene": saved, "format": "pdf"}, headers=H)
    assert re.status_code == 200 and re.content[:4] == b"%PDF"
    bad = c.post("/api/scenes/render", json={"scene": {"format": "x"}}, headers=H)
    assert bad.status_code == 422
    # crop change on a parcel -> full recalculation (new version, edited parcel locked)
    target = plan["parcels"][0]
    new_crop = "onion" if target["crop"] != "onion" else "pepper"
    rp = c.post(f"/api/farms/{farm['id']}/plans/{plan['id']}/replan",
                json={"edits": [{"parcel_id": target["id"], "crop_code": new_crop}]}, headers=H)
    assert rp.status_code == 201 and rp.json()["version"] == plan["version"] + 1
    # optional correction: give the pump flow -> durations become computable
    cr = c.post(f"/api/farms/{farm['id']}/corrections", json={"flow_m3h": 4.0}, headers=H).json()
    assert cr["plan"] and all(w["flow_m3h"] == 4.0 for w in cr["farm"]["water_sources"])
