import cv2
import numpy as np
import pytest
from shapely.geometry import Polygon

from app.cv import plan_reader
from app.engines.partition import area_m2


def _drawn_plan():
    img = np.full((800, 1000, 3), 255, np.uint8)
    pts = np.array([[120, 100], [860, 140], [900, 650], [450, 720], [100, 600]], np.int32)
    cv2.polylines(img, [pts], True, (0, 0, 0), 4)
    cv2.circle(img, (300, 300), 12, (0, 0, 0), 3)                  # well symbol
    cv2.rectangle(img, (600, 400), (680, 470), (40, 40, 40), -1)   # building
    return img, pts


def test_boundary_detection_matches_drawn_polygon():
    img, pts = _drawn_plan()
    ok, buf = cv2.imencode(".png", img)
    det = plan_reader.detect(plan_reader.load_raster(buf.tobytes(), "plan.png"))
    assert Polygon(det["boundary_px"]).area == pytest.approx(Polygon(pts.tolist()).area, rel=0.05)
    assert det["confidence"] > 0.5
    assert any(f["type"] == "building" for f in det["features"])


def test_two_point_georeference_area():
    from app.cv.plan_reader import TO_UTM, TO_WGS
    e0, n0 = TO_UTM.transform(10.0, 35.0)
    lon1, lat1 = TO_WGS.transform(e0 + 1000, n0)            # 1 px = 1 m
    cps = [{"px": [0, 0], "lat": 35.0, "lon": 10.0}, {"px": [1000, 0], "lat": lat1, "lon": lon1}]
    M = plan_reader.fit_transform(cps)
    assert max(plan_reader.residuals_m(M, cps)) < 0.01
    gj = plan_reader.pixels_to_geojson(M, [[0, 0], [100, 0], [100, 100], [0, 100]])
    assert area_m2(gj) == pytest.approx(10000, rel=0.01)


def test_scale_anchor_transform_north_up():
    M = plan_reader.transform_from_scale(0.5, [0, 0], 35.0, 10.0)
    gj = plan_reader.pixels_to_geojson(M, [[0, 0], [200, 0], [200, 200], [0, 200]])
    assert area_m2(gj) == pytest.approx(10000, rel=0.01)
    lon, lat = plan_reader.point_px_to_lonlat(M, [0, 200])
    assert lat < 35.0          # image y grows southwards


def test_area_check():
    gj = {"type": "Polygon", "coordinates": [[[10, 35], [10.001, 35], [10.001, 35.001], [10, 35.001], [10, 35]]]}
    a = plan_reader.area_check(gj, 1.0)
    assert a["measured_ha"] == pytest.approx(1.01, rel=0.05) and a["ok"]
    assert not plan_reader.area_check(gj, 2.0)["ok"]
