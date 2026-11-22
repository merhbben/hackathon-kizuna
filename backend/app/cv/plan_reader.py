"""2D farm-plan recognition (OpenCV) and georeferencing.

Supported inputs
* Raster images (PNG/JPG/TIFF/WebP) and PDF (first page rendered with PyMuPDF at 200 dpi).
* Geographic files (GeoJSON, KML, GPKG, zipped Shapefile) read with GeoPandas:
  these are already georeferenced, no computer vision needed.

Classical CV pipeline (deterministic, explainable):
 1. normalise size, denoise (bilateral), Canny edges + adaptive threshold, morphological closing;
 2. outer boundary = largest closed contour that is not the sheet frame, simplified with
    Douglas-Peucker (approxPolyDP), confidence from solidity and area share;
 3. internal features: long straight segments (probabilistic Hough) -> paths / canals,
    blue regions (HSV) -> water (basins, reservoirs), small circles (Hough) -> wells / boreholes,
    dark filled blobs -> buildings / obstacles;
 4. optional deep segmentation (app/cv/segmentation.py) when trained weights are configured.
Every detection is returned in pixel coordinates and must be confirmed or corrected by
the farmer in the editor before georeferencing.
"""
from __future__ import annotations

import io
import math
import tempfile
import zipfile
from pathlib import Path

import cv2
import numpy as np
from pyproj import Transformer
from shapely.geometry import Polygon, mapping, shape
from shapely.ops import transform, unary_union

TO_UTM = Transformer.from_crs("EPSG:4326", "EPSG:32632", always_xy=True)
TO_WGS = Transformer.from_crs("EPSG:32632", "EPSG:4326", always_xy=True)
GEO_EXT = {".geojson", ".json", ".kml", ".gpkg", ".zip", ".shp"}
IMG_EXT = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp", ".bmp"}
MAX_SIDE = 2000


class PlanError(ValueError):
    pass


def load_raster(data: bytes, filename: str) -> np.ndarray:
    ext = Path(filename).suffix.lower()
    if ext == ".pdf":
        import fitz  # PyMuPDF
        with fitz.open(stream=data, filetype="pdf") as doc:
            if doc.page_count == 0:
                raise PlanError("empty_pdf")
            pix = doc[0].get_pixmap(dpi=200)
            img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
            img = cv2.cvtColor(img, cv2.COLOR_RGBA2BGR if pix.n == 4 else cv2.COLOR_RGB2BGR)
    else:
        img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise PlanError("unreadable_image")
    h, w = img.shape[:2]
    s = min(1.0, MAX_SIDE / max(h, w))
    if s < 1.0:
        img = cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
    return img


def _contour_to_list(c) -> list[list[float]]:
    return [[float(p[0][0]), float(p[0][1])] for p in c]


def detect(img: np.ndarray) -> dict:
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    smooth = cv2.bilateralFilter(gray, 9, 50, 50)
    edges = cv2.Canny(smooth, 40, 120)
    thr = cv2.adaptiveThreshold(smooth, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 31, 7)
    mask = cv2.bitwise_or(edges, thr)
    k = max(3, int(round(min(h, w) / 300)) | 1)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (k, k)), iterations=2)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    img_area = float(h * w)
    cands = []
    for c in contours:
        a = cv2.contourArea(c)
        if a < 0.02 * img_area:
            continue
        x, y, bw, bh = cv2.boundingRect(c)
        touches_frame = x <= 2 and y <= 2 and x + bw >= w - 3 and y + bh >= h - 3
        if touches_frame and a > 0.9 * img_area:
            continue
        hull = cv2.convexHull(c)
        solidity = a / max(cv2.contourArea(hull), 1)
        cands.append((a, solidity, c))
    if not cands:
        # fall back to filled-region segmentation (plans drawn as coloured areas)
        _, otsu = cv2.threshold(smooth, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        contours, _ = cv2.findContours(otsu, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cands = [(cv2.contourArea(c), 1.0, c) for c in contours if cv2.contourArea(c) > 0.02 * img_area]
    if not cands:
        raise PlanError("no_boundary_detected")
    cands.sort(key=lambda t: -t[0])
    area, solidity, best = cands[0]
    eps = 0.006 * cv2.arcLength(best, True)
    poly = cv2.approxPolyDP(best, eps, True)
    boundary = _contour_to_list(poly)
    confidence = round(float(min(1.0, 0.5 * solidity + 0.5 * min(1.0, area / (0.25 * img_area)))), 2)

    inside = np.zeros((h, w), np.uint8)
    cv2.drawContours(inside, [poly], -1, 255, -1)
    inner = cv2.erode(inside, np.ones((k * 3, k * 3), np.uint8))

    features = []
    # long straight segments -> paths / canals
    lines = cv2.HoughLinesP(cv2.bitwise_and(edges, inner), 1, np.pi / 180, threshold=80,
                            minLineLength=int(0.15 * min(h, w)), maxLineGap=10)
    if lines is not None:
        for (x1, y1, x2, y2) in lines[:40, 0]:
            features.append({"type": "path", "line": [[float(x1), float(y1)], [float(x2), float(y2)]],
                             "length_px": round(math.hypot(x2 - x1, y2 - y1), 1)})
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    blue = cv2.inRange(hsv, (90, 60, 60), (130, 255, 255))
    blue = cv2.bitwise_and(blue, inside)
    for c in cv2.findContours(blue, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]:
        if cv2.contourArea(c) > 0.0005 * img_area:
            features.append({"type": "water", "polygon": _contour_to_list(cv2.approxPolyDP(c, 2, True))})
    dark = cv2.inRange(gray, 0, 60)
    dark = cv2.morphologyEx(cv2.bitwise_and(dark, inner), cv2.MORPH_OPEN, np.ones((k * 2, k * 2), np.uint8))
    for c in cv2.findContours(dark, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]:
        a = cv2.contourArea(c)
        if 0.0008 * img_area < a < 0.2 * img_area and a / max(cv2.contourArea(cv2.convexHull(c)), 1) > 0.8:
            features.append({"type": "building", "polygon": _contour_to_list(cv2.approxPolyDP(c, 2, True))})
    circles = cv2.HoughCircles(cv2.medianBlur(gray, 5), cv2.HOUGH_GRADIENT, dp=1.2, minDist=min(h, w) / 20,
                               param1=120, param2=35, minRadius=max(3, int(min(h, w) / 200)),
                               maxRadius=int(min(h, w) / 30))
    if circles is not None:
        for (x, y, r) in circles[0][:20]:
            if inside[int(min(y, h - 1)), int(min(x, w - 1))]:
                features.append({"type": "well", "point": [float(x), float(y)], "radius_px": float(r)})
    return {"image_size": [w, h], "boundary_px": boundary, "confidence": confidence,
            "features": features, "method": "opencv-classical-v1"}


# ------------------------------------------------------------ georef -----
def fit_transform(control_points: list[dict]) -> np.ndarray:
    """control_points: [{'px':[x,y], 'lat':..,'lon':..}] -> 2x3 matrix pixel -> UTM.
    2 points: similarity (scale+rotation+translation, image y axis flipped); >=3: least-squares affine."""
    if len(control_points) < 2:
        raise PlanError("need_two_control_points")
    src = np.array([cp["px"] for cp in control_points], float)
    dst = np.array([TO_UTM.transform(cp["lon"], cp["lat"]) for cp in control_points], float)
    if len(control_points) == 2:
        # complex-number similarity with y flip (image y grows downward)
        s = src[:, 0] - 1j * src[:, 1]
        d = dst[:, 0] + 1j * dst[:, 1]
        a = (d[1] - d[0]) / (s[1] - s[0])
        b = d[0] - a * s[0]
        # x' + i y' = a (x - i y) + b
        return np.array([[a.real, a.imag, b.real], [a.imag, -a.real, b.imag]])
    A = np.hstack([src, np.ones((len(src), 1))])
    sol, *_ = np.linalg.lstsq(A, dst, rcond=None)
    return sol.T


def transform_from_scale(meters_per_px: float, anchor_px: list[float], anchor_lat: float, anchor_lon: float,
                         rotation_deg: float = 0.0) -> np.ndarray:
    """Known scale + one anchor point. rotation_deg = bearing of the image 'up' direction,
    clockwise from true north (0 = north-up plan).
    world = x * right + (-y) * up, right = (cos t, -sin t), up = (sin t, cos t)."""
    ax, ay = TO_UTM.transform(anchor_lon, anchor_lat)
    t = math.radians(rotation_deg)
    c, s = math.cos(t) * meters_per_px, math.sin(t) * meters_per_px
    m = np.array([[c, -s, 0.0], [-s, -c, 0.0]])
    m[0, 2] = ax - (m[0, 0] * anchor_px[0] + m[0, 1] * anchor_px[1])
    m[1, 2] = ay - (m[1, 0] * anchor_px[0] + m[1, 1] * anchor_px[1])
    return m


def residuals_m(M: np.ndarray, control_points: list[dict]) -> list[float]:
    out = []
    for cp in control_points:
        x, y = cp["px"]
        e, n = M @ np.array([x, y, 1.0])
        te, tn = TO_UTM.transform(cp["lon"], cp["lat"])
        out.append(round(math.hypot(e - te, n - tn), 2))
    return out


def pixels_to_geojson(M: np.ndarray, coords_px: list[list[float]]) -> dict:
    pts = [tuple(M @ np.array([x, y, 1.0])) for x, y in coords_px]
    poly = Polygon(pts)
    if not poly.is_valid:
        poly = poly.buffer(0)
    return mapping(transform(TO_WGS.transform, poly))


def point_px_to_lonlat(M: np.ndarray, px: list[float]) -> tuple[float, float]:
    e, n = M @ np.array([px[0], px[1], 1.0])
    return TO_WGS.transform(e, n)


def read_geofile(data: bytes, filename: str) -> dict:
    import geopandas as gpd
    ext = Path(filename).suffix.lower()
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / Path(filename).name
        if ext == ".zip":
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                for n in z.namelist():
                    if ".." in n or n.startswith(("/", "\\")):
                        raise PlanError("unsafe_zip")
                z.extractall(tmp)
            shp = next(Path(tmp).rglob("*.shp"), None)
            if shp is None:
                raise PlanError("no_shapefile_in_zip")
            path = shp
        else:
            path.write_bytes(data)
        gdf = gpd.read_file(path)
    if gdf.empty:
        raise PlanError("empty_geofile")
    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326")
    gdf = gdf.to_crs("EPSG:4326")
    polys = [g for g in gdf.geometry if g is not None and g.geom_type in ("Polygon", "MultiPolygon")]
    if not polys:
        raise PlanError("no_polygon_in_geofile")
    geom = unary_union(polys)
    if geom.geom_type == "MultiPolygon":
        geom = max(geom.geoms, key=lambda g: transform(TO_UTM.transform, g).area)
    return {"boundary": mapping(geom), "georeferenced": True, "features": len(gdf), "crs": "EPSG:4326"}


def area_check(boundary_geojson: dict, declared_ha: float | None, tolerance_pct: float = 10.0) -> dict:
    a = transform(TO_UTM.transform, shape(boundary_geojson)).area / 1e4
    out = {"measured_ha": round(a, 4), "declared_ha": declared_ha, "ok": True, "deviation_pct": None}
    if declared_ha:
        dev = 100 * (a - declared_ha) / declared_ha
        out["deviation_pct"] = round(dev, 1)
        out["ok"] = abs(dev) <= tolerance_pct
    return out
