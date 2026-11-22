"""Technical farm-plan parser: one black & white (or colour) plan -> geometry + metadata.

Two extraction paths sharing the same interpretation layer:

* **Vector** (PDF, SVG): PyMuPDF reads the drawing primitives (lines, curves,
  rectangles, stroke/fill/dash) and the text with exact positions. No OCR,
  no approximation: geometry is recovered exactly.
* **Raster** (PNG, JPG, scanned PDF without vectors): OpenCV (binarisation,
  contours, Hough circles/lines) + RapidOCR (ONNX, local) for texts.

Interpretation (identical for both paths):
* boundary = closed polygon whose vertices carry the boundary-marker labels
  (B1, B2, ... / borne) — never the page border or the map frame; without
  markers, the most boundary-like closed stroke (thickness, size, no title text);
* scale = graphic scale bar (numbers + ticks/bar) or "1:N" text (vector only),
  cross-checked with the area printed on the plan when present;
* water points = labels FORAGE / PUITS / SONDAGE / POINT EAU / SOURCE + nearest
  circle symbol;
* zones inside the boundary classified by label keywords or by the plan legend
  (fill colour -> legend text);
* lines (paths, pipes, slopes) classified by nearby label;
* metadata (governorate, delegation, GPS, season, soil, water volume, flow,
  pump power, PV, batteries, cold room) parsed from the texts.

Nothing is invented: every missing or unreadable item produces a warning with
a code the UI translates, and items that need a human check are flagged.
"""
from __future__ import annotations

import io
import math
import os
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from shapely.geometry import LineString, Point, Polygon
from shapely.validation import make_valid

from app.knowledge.governorates import GOVERNORATES

VECTOR_EXT = {".pdf", ".svg"}
RASTER_EXT = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp", ".bmp"}

WATER_WORDS = ("FORAGE", "PUITS", "SONDAGE", "POINT EAU", "POINTEAU", "EAU AUTORIS", "SOURCE", "BIR ")
ZONE_KEYWORDS = [
    ("reservoir", ("BASSIN", "CUVE", "RESERVOIR", "MAJEL", "CITERNE")),
    ("solar", ("PV", "SOLAIRE", "PANNEAU", "CENTRALE")),
    ("cold_storage", ("FROID", "FRIGO", "CHAMBRE FROIDE")),
    ("building", ("BATIMENT", "LOCAL", "HANGAR", "STOCKAGE", "ENTREPOT", "MAISON", "DEPOT")),
    ("orchard", ("VERGER", "OLIVIER", "ARBRE", "PALMIER", "AGRUME")),
    ("exclusion", ("ZONE EXCLUE", "EXCLUE", "NON CULTIVABLE", "INCULTE", "ROCHE")),
]
LEGEND_KINDS = [
    ("boundary", ("LIMITE",)), ("water_point", ("FORAGE", "POINT D'EAU", "POINT D EAU")),
    ("reservoir", ("BASSIN", "CUVE")), ("solar", ("PANNEAUX", "SOLAIRE")),
    ("building", ("BATIMENT", "STOCKAGE")), ("exclusion", ("NON CULTIVABLE", "ZONE EXCLUE")),
]
LINE_KEYWORDS = [
    ("pipe", ("CONDUITE", "RESEAU", "CANALISATION", "TUYAU")),
    ("path", ("CHEMIN", "PISTE", "VOIE", "ACCES", "ROUTE", "ALLEE")),
    ("slope", ("TALUS", "FOSSE", "OUED", "RAVIN")),
]
VERTEX_RE = re.compile(r"^(B|P|S|BORNE\s*)(\d{1,3})$")


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", s.upper().replace("²", "2").replace("³", "3")).strip()


def compact(s: str) -> str:
    return re.sub(r"[^A-Z0-9.,:/]", "", norm(s))


@dataclass
class Token:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    score: float = 1.0

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2

    @property
    def n(self) -> str:
        return norm(self.text)


@dataclass
class Shape:
    points: list[tuple[float, float]]
    closed: bool
    stroke: tuple | None
    fill: tuple | None
    width: float
    dashed: bool
    kind: str  # poly | line | circle


@dataclass
class Extraction:
    method: str
    units: str                         # 'pt' (vector) | 'px' (raster)
    page_size: tuple[float, float]
    tokens: list[Token]
    shapes: list[Shape] = field(default_factory=list)
    image: np.ndarray | None = None    # raster only


# ============================================================ loading =====
def load(data: bytes, filename: str, page: int = 0, ocr=None) -> Extraction:
    ext = Path(filename).suffix.lower()
    if ext in VECTOR_EXT:
        import fitz
        doc = fitz.open(stream=data, filetype="svg" if ext == ".svg" else "pdf")
        pg = doc[min(page, doc.page_count - 1)]
        if ext == ".pdf" and len(pg.get_drawings()) < 5:      # scanned PDF -> raster path
            pix = pg.get_pixmap(dpi=200)
            img = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, pix.n)[:, :, :3][:, :, ::-1].copy()
            return _raster_extraction(img, ocr)
        ex = _vector_extraction(pg)
        _add_glyph_labels(ex, pg, ocr)
        return ex
    if ext in RASTER_EXT:
        import cv2
        img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError("unreadable_image")
        return _raster_extraction(img, ocr)
    raise ValueError("unsupported_format")


def _vector_extraction(pg) -> Extraction:
    tokens: list[Token] = []
    d = pg.get_text("dict")
    for b in d["blocks"]:
        for ln in b.get("lines", []):
            txt = "".join(s["text"] for s in ln["spans"]).strip()
            if txt:
                x0, y0, x1, y1 = ln["bbox"]
                tokens.append(Token(txt, x0, y0, x1, y1))
    shapes: list[Shape] = []
    W, H = pg.rect.width, pg.rect.height
    pending_pattern = None
    for dr in pg.get_drawings():
        r = dr["rect"]
        if r.x1 < 0 or r.y1 < 0 or r.x0 > W or r.y0 > H:   # pattern tiles live outside the page
            if dr.get("fill") and pending_pattern is None:
                pending_pattern = tuple(dr["fill"])       # background colour of the pattern tile
            continue
        pattern_fill, pending_pattern = pending_pattern, None
        pts: list[tuple[float, float]] = []
        kinds = [it[0] for it in dr["items"]]
        for it in dr["items"]:
            if it[0] == "l":
                for p in it[1:3]:
                    _push(pts, (p.x, p.y))
            elif it[0] == "c":
                _push(pts, (it[1].x, it[1].y))
                _push(pts, (it[4].x, it[4].y))
            elif it[0] == "re":
                rc = it[1]
                for p in ((rc.x0, rc.y0), (rc.x1, rc.y0), (rc.x1, rc.y1), (rc.x0, rc.y1)):
                    _push(pts, p)
            elif it[0] == "qu":
                q = it[1]
                for p in (q.ul, q.ur, q.lr, q.ll):
                    _push(pts, (p.x, p.y))
        if len(pts) < 2:
            continue
        closed = bool(dr.get("closePath")) or "re" in kinds or "qu" in kinds or \
            (len(pts) >= 3 and math.dist(pts[0], pts[-1]) < 1.0) or (dr.get("fill") is not None and len(pts) >= 3)
        if len(pts) >= 3 and math.dist(pts[0], pts[-1]) < 1.0:
            pts = pts[:-1]
        is_circle = kinds and all(k == "c" for k in kinds) and r.width < 25 and abs(r.width - r.height) < 2
        dashes = dr.get("dashes") or ""
        shapes.append(Shape(
            points=[((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2), (r.width / 2, 0)] if is_circle else pts,
            closed=closed, stroke=tuple(dr["color"]) if dr.get("color") else None,
            fill=tuple(dr["fill"]) if dr.get("fill") else pattern_fill, width=float(dr.get("width") or 0),
            dashed=bool(re.search(r"\d", str(dashes).split("]")[0])) if dashes else False,
            kind="circle" if is_circle else ("poly" if closed and len(pts) >= 3 else "line")))
    return Extraction("vector", "pt", (W, H), tokens, shapes)


def _push(pts, p):
    if not pts or math.dist(pts[-1], p) > 0.05:
        pts.append((float(p[0]), float(p[1])))


def _add_glyph_labels(ex: Extraction, pg, ocr=None) -> None:
    """Labels are often converted to outlines (paths) by CAD/PDF exporters: they are invisible to text
    extraction. Render the page and OCR it, keep only texts that are not already present as real text."""
    if os.environ.get("AGRO_PLAN_OCR", "1") == "0":
        return
    import fitz
    zoom = 2.0
    pix = pg.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
    img = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, pix.n)[:, :, :3][:, :, ::-1].copy()
    res, _ = (ocr or get_ocr())(img)
    for box, txt, score in res or []:
        xs = [p[0] / zoom for p in box]
        ys = [p[1] / zoom for p in box]
        t = Token(txt, min(xs), min(ys), max(xs), max(ys), float(score))
        if score < 0.6:
            continue
        dup = any(abs(u.cx - t.cx) < 12 and abs(u.cy - t.cy) < 6 and (compact(u.text)[:4] == compact(t.text)[:4]
                                                                      or compact(t.text) in compact(u.text)
                                                                      or compact(u.text) in compact(t.text))
                  for u in ex.tokens)
        if not dup:
            ex.tokens.append(t)


_OCR = None


def get_ocr():
    global _OCR
    if _OCR is None:
        from rapidocr_onnxruntime import RapidOCR
        _OCR = RapidOCR()
    return _OCR


def _raster_extraction(img: np.ndarray, ocr=None) -> Extraction:
    import cv2
    h, w = img.shape[:2]
    # normalise resolution: morphology kernels and OCR are tuned for ~2000 px wide drawings
    target = 2000 if w < 1800 else (2400 if w > 2600 else w)
    if target != w:
        f = target / w
        img = cv2.resize(img, (int(w * f), int(h * f)), interpolation=cv2.INTER_CUBIC if f > 1 else cv2.INTER_AREA)
        h, w = img.shape[:2]
    ocr = ocr or get_ocr()
    res, _ = ocr(img)
    tokens = []
    for box, txt, score in res or []:
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        tokens.append(Token(txt, min(xs), min(ys), max(xs), max(ys), float(score)))
    return Extraction("raster", "px", (w, h), tokens, [], img)


# ===================================================== interpretation =====
def parse(data: bytes, filename: str, page: int = 0, ocr=None, known_edge: tuple[int, float] | None = None) -> dict:
    """known_edge = (edge index, length in metres) given by the farmer when no scale can be read."""
    ex = load(data, filename, page, ocr)
    warnings: list[dict] = []
    vertex_tokens = _vertex_tokens(ex.tokens)
    if ex.method == "vector":
        boundary, bmeta = _vector_boundary(ex, vertex_tokens)
    else:
        boundary, bmeta = _raster_boundary(ex, vertex_tokens)
        if boundary is not None and _ocr_map_area(ex, boundary, ocr):
            vertex_tokens = _vertex_tokens(ex.tokens)
            boundary, bmeta = _raster_boundary(ex, vertex_tokens)
    if boundary is None:
        return {"ok": False, "method": ex.method, "warnings": [_w("boundary_not_found", "critical")],
                "texts": [t.text for t in ex.tokens]}
    scale = _scale(ex)
    meta = _metadata(ex.tokens)
    stated = meta.pop("stated_area_m2", None)
    if known_edge is not None:
        pts = list(boundary.exterior.coords)[:-1]
        i, length = known_edge
        a, b = pts[i % len(pts)], pts[(i + 1) % len(pts)]
        if math.dist(a, b) > 0 and length > 0:
            scale = {"m_per_unit": length / math.dist(a, b), "method": "user_edge", "confidence": 1.0,
                     "edge": i, "length_m": length}
    if scale is None and stated:
        # no readable scale bar: derive it from the printed area (flagged)
        scale = {"m_per_unit": math.sqrt(stated / boundary.area), "method": "printed_area", "confidence": 0.6}
        warnings.append(_w("scale_from_area", "warning"))
    if scale is None:
        return {"ok": False, "method": ex.method, "warnings": [_w("scale_not_found", "critical")],
                "boundary_units": [list(p) for p in boundary.exterior.coords[:-1]], "metadata": meta,
                "vertex_labels": bmeta.get("labels") or []}
    s = scale["m_per_unit"]
    minx, miny, maxx, maxy = boundary.bounds

    def to_m(p):  # page coords (y down) -> local metres (x east, y north), origin bottom-left of the boundary
        return (round((p[0] - minx) * s, 3), round((maxy - p[1]) * s, 3))

    b_m = Polygon([to_m(p) for p in boundary.exterior.coords[:-1]])
    b_m = make_valid(b_m) if not b_m.is_valid else b_m
    area = b_m.area
    area_check = {"measured_m2": round(area, 1), "stated_m2": stated, "deviation_pct": None, "ok": None}
    if stated:
        dev = 100 * (area - stated) / stated
        area_check.update(deviation_pct=round(dev, 2), ok=abs(dev) <= 3.0)
        if abs(dev) > 3.0:
            warnings.append(_w("area_mismatch", "warning", {"measured": round(area), "stated": round(stated),
                                                             "deviation": round(dev, 1)}))
    else:
        warnings.append(_w("area_not_printed", "info"))
    labels = bmeta.get("labels") or []
    coords = list(b_m.exterior.coords)[:-1]
    edges = []
    for i in range(len(coords)):
        a, b = coords[i], coords[(i + 1) % len(coords)]
        edges.append({"from": labels[i] if i < len(labels) else f"S{i + 1}",
                      "to": labels[(i + 1) % len(coords)] if labels else f"S{(i + 1) % len(coords) + 1}",
                      "length_m": round(math.dist(a, b), 2)})
    water = _water_points(ex, boundary)
    if not water:
        warnings.append(_w("no_water_point", "warning"))
    legend = _legend(ex)
    zones = _zones(ex, boundary, legend)
    lines = _lines(ex, boundary)
    north = any(t.n == "N" for t in ex.tokens)
    if not north:
        warnings.append(_w("north_assumed", "info"))
    if not meta.get("governorate") and not meta.get("gps"):
        warnings.append(_w("location_missing", "critical"))
    elif not meta.get("gps"):
        warnings.append(_w("gps_missing", "warning"))
    for key, code in (("water_m3_day", "water_volume_missing"), ("flow_m3h", "flow_missing"),
                      ("pump_kw", "pump_missing"), ("season", "season_missing"), ("soil", "soil_missing")):
        if meta.get(key) is None:
            warnings.append(_w(code, "info" if key in ("season", "soil", "flow_m3h") else "warning"))
    if meta.get("test_data"):
        warnings.append(_w("declared_test_values", "info"))
    if ex.method == "raster":
        low = [t.text for t in ex.tokens if t.score < 0.8]
        if low:
            warnings.append(_w("ocr_low_confidence", "info", {"texts": low[:10]}))
    return {
        "ok": True, "method": ex.method,
        "scale": {**scale, "m_per_unit": round(scale["m_per_unit"], 6)},
        "boundary_m": [list(p) for p in coords], "vertex_labels": labels,
        "boundary_detection": {k: v for k, v in bmeta.items() if k != "labels"},
        "area": area_check, "edges": edges,
        "perimeter_m": round(b_m.length, 2),
        "water_points": [{**w_, "x_m": to_m((w_["x"], w_["y"]))[0], "y_m": to_m((w_["x"], w_["y"]))[1]}
                         for w_ in water],
        "zones": [{**z, "polygon_m": [list(to_m(p)) for p in z.pop("polygon")]} for z in zones],
        "lines": [{**ln, "line_m": [list(to_m(p)) for p in ln.pop("line")],
                   "width_m": round(ln.pop("width_units") * s, 2)} for ln in lines],
        "metadata": meta, "north_detected": north, "warnings": warnings,
        "texts": [t.text for t in ex.tokens],
    }


def _w(code: str, severity: str, data: dict | None = None) -> dict:
    return {"code": code, "severity": severity, "data": data or {}}


# --------------------------------------------------------------- vertices
def _vertex_tokens(tokens: list[Token]) -> list[Token]:
    out = []
    for t in tokens:
        c = compact(t.text)
        if VERTEX_RE.match(c):
            out.append(t)
    return out


def _label_score(poly_pts, vtoks: list[Token], tol: float) -> tuple[int, list[str]]:
    """Number of vertex labels sitting next to a vertex, and the label of each vertex."""
    labels = [None] * len(poly_pts)
    used = 0
    for t in vtoks:
        d = [math.dist((t.cx, t.cy), p) for p in poly_pts]
        k = int(np.argmin(d))
        if d[k] <= tol and labels[k] is None:
            labels[k] = compact(t.text)
            used += 1
    return used, labels


def _vector_boundary(ex: Extraction, vtoks: list[Token]):
    W, H = ex.page_size
    best, best_score, meta = None, -1e9, {}
    title_words = ("FICHE", "SYMBOLES", "LEGENDE", "CARTOUCHE", "PLAN PARCELLAIRE")
    for sh in ex.shapes:
        if sh.kind != "poly" or sh.stroke is None or len(sh.points) < 3:
            continue
        poly = Polygon(sh.points)
        if not poly.is_valid or poly.area < 0.01 * W * H:
            continue
        x0, y0, x1, y1 = poly.bounds
        if x0 <= 2 and y0 <= 2 and x1 >= W - 2 and y1 >= H - 2:
            continue                                        # page border
        n_lab, labels = _label_score(sh.points, vtoks, tol=0.03 * max(W, H))
        has_title = any(any(w in t.n for w in title_words) and poly.contains(Point(t.cx, t.cy)) for t in ex.tokens)
        score = 10 * n_lab + 2 * min(sh.width, 4) + 3 * poly.area / (W * H) - (25 if has_title else 0)
        if score > best_score:
            best, best_score = poly, score
            meta = {"labels": labels if n_lab else [], "labels_matched": n_lab, "stroke_width": sh.width,
                    "method": "vertex_labels" if n_lab >= 3 else "largest_stroked_polygon"}
    if best is None:
        return None, {}
    if meta["labels_matched"] < 3:
        meta["labels"] = []
    return best, meta


def _ocr_map_area(ex: Extraction, boundary: Polygon, ocr=None) -> bool:
    """Second OCR pass on the map area at 2x: small labels (B1.., FORAGE F1) are often missed on the full page."""
    import cv2
    h, w = ex.image.shape[:2]
    x0, y0, x1, y1 = boundary.bounds
    mx, my = 0.12 * (x1 - x0) + 20, 0.12 * (y1 - y0) + 20
    X0, Y0, X1, Y1 = int(max(0, x0 - mx)), int(max(0, y0 - my)), int(min(w, x1 + mx)), int(min(h, y1 + my))
    crop = cv2.resize(ex.image[Y0:Y1, X0:X1], None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    res, _ = (ocr or get_ocr())(crop)
    added = False
    for box, txt, score in res or []:
        if score < 0.6:
            continue
        xs = [X0 + p[0] / 2 for p in box]
        ys = [Y0 + p[1] / 2 for p in box]
        t = Token(txt, min(xs), min(ys), max(xs), max(ys), float(score))
        if not any(abs(u.cx - t.cx) < 15 and abs(u.cy - t.cy) < 8 for u in ex.tokens):
            ex.tokens.append(t)
            added = True
    return added


def _stroke_mask(img: np.ndarray) -> np.ndarray:
    """Dark, line-like strokes only: thin details (dots, hatching, grid, thin outlines) and filled
    blobs (title band, patterns, buildings) are removed so that only boundary-weight lines remain."""
    import cv2
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    mask = (gray < 150).astype(np.uint8) * 255
    m = cv2.morphologyEx(mask, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
    core = cv2.erode(m, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (13, 13)))
    core = cv2.dilate(core, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (25, 25)))
    return cv2.bitwise_and(m, cv2.bitwise_not(core))


def _merge_segments(segs: np.ndarray, w: int) -> list[dict]:
    """Group Hough segments lying on the same straight line (angle and offset) into one line with extent."""
    lines: list[dict] = []
    for x1, y1, x2, y2 in segs:
        ang = math.atan2(y2 - y1, x2 - x1) % math.pi
        nx, ny = -math.sin(ang), math.cos(ang)
        off = x1 * nx + y1 * ny
        for L in lines:
            da = min(abs(ang - L["ang"]), math.pi - abs(ang - L["ang"]))
            if da < math.radians(3) and abs(off - L["off"]) < 0.004 * w + 4:
                L["pts"] += [(x1, y1), (x2, y2)]
                break
        else:
            lines.append({"ang": ang, "off": off, "pts": [(x1, y1), (x2, y2)]})
    for L in lines:
        ux, uy = math.cos(L["ang"]), math.sin(L["ang"])
        ts = [px * ux + py * uy for px, py in L["pts"]]
        i0, i1 = int(np.argmin(ts)), int(np.argmax(ts))
        L["a"], L["b"] = L["pts"][i0], L["pts"][i1]
        L["len"] = ts[i1] - ts[i0]
    return [L for L in lines if L["len"] > 0.05 * w]


def _intersection(L1, L2):
    (x1, y1), (x2, y2) = L1["a"], L1["b"]
    (x3, y3), (x4, y4) = L2["a"], L2["b"]
    d = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(d) < 1e-9:
        return None
    t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / d
    return (x1 + t * (x2 - x1), y1 + t * (y2 - y1))


def _raster_boundary(ex: Extraction, vtoks: list[Token]):
    """Boundary = largest closed cycle of the graph (corners = intersections of thick straight lines that
    end at the same point). Robust to labels drawn over the boundary line, which break pixel contours."""
    import cv2
    img = ex.image
    h, w = img.shape[:2]
    mask = _stroke_mask(img)
    segs = cv2.HoughLinesP(mask, 1, np.pi / 360, threshold=80, minLineLength=int(0.05 * w), maxLineGap=int(0.02 * w))
    if segs is None:
        return None, {}
    lines = _merge_segments(np.asarray(segs).reshape(-1, 4).astype(float), w)
    tol = 0.012 * w + 6
    corners: list[dict] = []
    for i in range(len(lines)):
        for j in range(i + 1, len(lines)):
            da = min(abs(lines[i]["ang"] - lines[j]["ang"]), math.pi - abs(lines[i]["ang"] - lines[j]["ang"]))
            if da < math.radians(15):
                continue
            p = _intersection(lines[i], lines[j])
            if p is None or not (0 <= p[0] < w and 0 <= p[1] < h):
                continue
            if min(math.dist(p, lines[i]["a"]), math.dist(p, lines[i]["b"])) > tol:
                continue
            if min(math.dist(p, lines[j]["a"]), math.dist(p, lines[j]["b"])) > tol:
                continue
            for c in corners:
                if math.dist(c["p"], p) < tol:
                    c["lines"] |= {i, j}
                    break
            else:
                corners.append({"p": p, "lines": {i, j}})
    # adjacency: consecutive corners along the same line
    adj: dict[int, set[int]] = {k: set() for k in range(len(corners))}
    for li in range(len(lines)):
        on = [k for k, c in enumerate(corners) if li in c["lines"]]
        if len(on) < 2:
            continue
        ux, uy = math.cos(lines[li]["ang"]), math.sin(lines[li]["ang"])
        on.sort(key=lambda k: corners[k]["p"][0] * ux + corners[k]["p"][1] * uy)
        for a_, b_ in zip(on, on[1:]):
            adj[a_].add(b_)
            adj[b_].add(a_)
    cycles = _cycles(adj, limit=40)
    best, best_score, meta = None, -1e9, {}
    for cyc in cycles:
        pts = [corners[k]["p"] for k in cyc]
        poly = Polygon(pts)
        if not poly.is_valid or poly.area < 0.01 * w * h:
            continue
        n_lab, labels = _label_score(pts, vtoks, tol=0.04 * w)
        score = 10 * n_lab + 5 * poly.area / (w * h)
        if score > best_score:
            best_score, best = score, (poly, pts, labels, n_lab)
    if best is None:
        return _raster_boundary_contour(ex, vtoks)
    poly, pts, labels, n_lab = best
    # orientation: start at the lowest label number if labels are known
    meta = {"labels": labels if n_lab >= 3 else [], "labels_matched": n_lab,
            "method": "line_graph+vertex_labels" if n_lab >= 3 else "line_graph", "corners": len(pts)}
    return poly, meta


def _cycles(adj: dict[int, set[int]], limit: int = 40) -> list[list[int]]:
    """Simple cycles of a small undirected graph (each found once)."""
    out, seen = [], set()

    def dfs(start, node, path, visited):
        if len(out) > 500 or len(path) > limit:
            return
        for nb in adj[node]:
            if nb == start and len(path) >= 3:
                key = frozenset(path)
                if key not in seen:
                    seen.add(key)
                    out.append(list(path))
            elif nb not in visited and nb > start:
                visited.add(nb)
                path.append(nb)
                dfs(start, nb, path, visited)
                path.pop()
                visited.discard(nb)

    for s_ in adj:
        dfs(s_, s_, [s_], {s_})
    return out


def _raster_boundary_contour(ex: Extraction, vtoks: list[Token]):
    import cv2
    img = ex.image
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    dark = (gray < 150).astype(np.uint8) * 255
    for t in ex.tokens:                                     # remove text so it does not merge with strokes
        cv2.rectangle(dark, (int(t.x0) - 2, int(t.y0) - 2), (int(t.x1) + 2, int(t.y1) + 2), 0, -1)
    # keep thick strokes only: opening with a small disk removes dots, hatching and thin grid lines
    k = max(3, int(round(min(h, w) / 450)))
    thick = cv2.morphologyEx(dark, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    thick = cv2.morphologyEx(thick, cv2.MORPH_CLOSE, np.ones((k * 2 + 1, k * 2 + 1), np.uint8))
    contours, hier = cv2.findContours(thick, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    best, best_score, meta = None, -1e9, {}
    n_expected = len(vtoks)
    for i, c in enumerate(contours):
        a = cv2.contourArea(c)
        if a < 0.01 * w * h:
            continue
        x, y, bw, bh = cv2.boundingRect(c)
        if x <= 3 and y <= 3 and x + bw >= w - 4 and y + bh >= h - 4:
            continue
        peri = cv2.arcLength(c, True)
        approx = None
        for eps in (0.004, 0.006, 0.008, 0.012, 0.018, 0.025):
            ap = cv2.approxPolyDP(c, eps * peri, True)
            approx = ap
            if n_expected >= 3 and len(ap) <= n_expected:
                break
            if n_expected < 3 and len(ap) <= 12:
                break
        pts = [(float(p[0][0]), float(p[0][1])) for p in approx]
        if len(pts) < 3:
            continue
        n_lab, labels = _label_score(pts, vtoks, tol=0.035 * max(w, h))
        is_hole = hier[0][i][3] >= 0
        has_title = any(("FICHE" in t.n or "SYMBOLES" in t.n) and cv2.pointPolygonTest(c, (t.cx, t.cy), False) > 0
                        for t in ex.tokens)
        score = 10 * n_lab + 3 * a / (w * h) - (25 if has_title else 0) + (0.5 if is_hole else 0)
        if score > best_score:
            best_score, best = score, (c, pts, is_hole, i)
            meta = {"labels": labels if n_lab >= 3 else [], "labels_matched": n_lab,
                    "method": "vertex_labels" if n_lab >= 3 else "largest_closed_stroke"}
    if best is None:
        return None, {}
    c, pts, is_hole, idx = best
    poly = Polygon(pts)
    # the stroke has a thickness: move from the detected edge of the stroke to its centre line
    sw = _stroke_width(thick, c)
    poly = poly.buffer(sw / 2 if is_hole else -sw / 2, join_style=2)
    if poly.geom_type != "Polygon":
        poly = max(poly.geoms, key=lambda g: g.area)
    simp = poly.simplify(sw, preserve_topology=True)
    pts2 = list(simp.exterior.coords)[:-1]
    _, labels = _label_score(pts2, vtoks, tol=0.035 * max(w, h))
    meta.update(stroke_width=round(sw, 2), labels=[l_ for l_ in labels] if meta["labels"] else [])
    return Polygon(pts2), meta


def _stroke_width(mask, contour) -> float:
    import cv2
    dist = cv2.distanceTransform((mask > 0).astype(np.uint8), cv2.DIST_L2, 5)
    vals = []
    for p in contour[:: max(1, len(contour) // 200)]:
        x, y = int(p[0][0]), int(p[0][1])
        win = dist[max(0, y - 6): y + 7, max(0, x - 6): x + 7]
        if win.size:
            vals.append(float(win.max()))
    return 2 * float(np.median(vals)) if vals else 2.0


# ------------------------------------------------------------------ scale
def _num(s: str) -> float | None:
    m = re.match(r"^\s*(\d+(?:[.,]\d+)?)\s*(M|KM)?\s*$", norm(s))
    if not m:
        return None
    v = float(m.group(1).replace(",", "."))
    return v * 1000 if m.group(2) == "KM" else v


def _scale(ex: Extraction) -> dict | None:
    toks = [(t, _num(t.text)) for t in ex.tokens]
    nums = [(t, v) for t, v in toks if v is not None]
    best = None
    for t, v in nums:
        if "M" not in t.n:                                  # the row is anchored on the label carrying the unit
            continue
        row = [(u, val) for u, val in nums if abs(u.cy - t.cy) < 0.6 * (t.y1 - t.y0) + 2 and u.x1 <= t.x1 + 1]
        row = sorted({(round(u.cx, 1), val): (u, val) for u, val in row}.values(), key=lambda p: p[0].cx)
        if len(row) < 2:
            continue
        xs = np.array([_digit_center(u) for u, _ in row])
        vs = np.array([val for _, val in row])
        if len(set(vs)) < 2 or np.any(np.diff(vs) <= 0):
            continue
        xs = _snap_ticks(ex, xs, row)
        a, b = np.polyfit(xs, vs, 1)                       # metres = a * x + b
        resid = float(np.max(np.abs(a * xs + b - vs))) if len(xs) > 2 else 0.0
        cand = {"m_per_unit": float(a), "method": "scale_bar", "labels": [float(v_) for v_ in vs],
                "confidence": 0.95 if resid < 0.02 * vs.max() else 0.7}
        if ex.method == "raster":
            xs2 = _raster_ticks(ex, row, xs)
            if xs2 is not None:
                a, b = np.polyfit(xs2, vs, 1)
                cand = {**cand, "m_per_unit": float(a), "method": "scale_bar_ticks"}
        if best is None or len(vs) > len(best["labels"]):
            best = cand
    if best:
        return best
    for t in ex.tokens:                                     # "Échelle 1:500" (vector pages in points only)
        m = re.search(r"1\s*[:/]\s*(\d{2,6})", t.n)
        if m and ("ECHELLE" in t.n or "SCALE" in t.n) and ex.units == "pt":
            return {"m_per_unit": int(m.group(1)) * 0.0254 / 72, "method": "ratio_text", "confidence": 0.8}
    return None


def _digit_center(t: Token) -> float:
    """x of the centre of the digits (labels like '50 m' are centred on the tick with the unit appended)."""
    txt = t.text.strip()
    m = re.match(r"^\s*([\d.,]+)", txt)
    if not m or len(txt) == len(m.group(1)):
        return t.cx
    frac = len(m.group(1)) / max(1, len(txt))
    return t.x0 + (t.x1 - t.x0) * frac / 2


def _snap_ticks(ex: Extraction, xs: np.ndarray, row) -> np.ndarray:
    """Vector: snap each label to the closest vertical tick drawn just above it."""
    if ex.method != "vector":
        return xs
    out = xs.copy()
    for i, (u, _) in enumerate(row):
        best, bd = None, 1e9
        for sh in ex.shapes:
            if sh.kind != "line" or len(sh.points) != 2:
                continue
            (x1, y1), (x2, y2) = sh.points
            if abs(x1 - x2) > 0.5 or not (3 <= abs(y1 - y2) <= 40):   # short vertical tick, not a grid line
                continue
            if not (min(y1, y2) - 40 < u.y0 and max(y1, y2) < u.y1 + 2):
                continue
            d = abs(x1 - xs[i])
            if d < bd and d < 15:
                best, bd = x1, d
        if best is not None:
            out[i] = best
    return out


def _binary_gray(img: np.ndarray) -> np.ndarray:
    """Otsu black & white version: colour plans are analysed exactly like black & white ones."""
    import cv2
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return bw


def _raster_ticks(ex, row, xs):
    """Raster: snap label positions to the tick marks of the scale bar (column profile above the labels)."""
    gray = _binary_gray(ex.image)
    y_lab = int(min(u.y0 for u, _ in row))
    spacing = float(np.min(np.diff(np.sort(xs)))) if len(xs) > 1 else 50.0
    x_lo, x_hi = int(max(0, xs.min() - spacing)), int(min(gray.shape[1], xs.max() + spacing))
    band = (gray[max(0, y_lab - 90): y_lab + 3, x_lo:x_hi] < 150)
    if band.size == 0:
        return None
    col = band.sum(axis=0).astype(float)
    base = float(np.median(col[col > 0])) if np.any(col > 0) else 0.0
    peaks = []
    for x in range(2, len(col) - 2):
        if col[x] >= base + max(2.5, 0.12 * base) and col[x] == col[max(0, x - 4): x + 5].max():
            if not peaks or x - peaks[-1][-1] > 3:
                peaks.append([x])
            else:
                peaks[-1].append(x)
    centers = [x_lo + float(np.mean(p)) for p in peaks]
    if len(centers) < 2:
        return None
    out = []
    for x in xs:
        c = min(centers, key=lambda c_: abs(c_ - x))
        if abs(c - x) > 0.4 * spacing:
            return None
        out.append(c)
    out = np.array(out)
    return out if len(set(np.round(out))) == len(out) else None


def _refine_with_bar(ex, cand, row, xs, vs):
    """Raster: the scale bar's dark horizontal extent gives sharper end positions than OCR boxes."""
    import cv2
    gray = cv2.cvtColor(ex.image, cv2.COLOR_BGR2GRAY)
    y_lab = int(min(u.y0 for u, _ in row))
    band = gray[max(0, y_lab - 45): y_lab, :]
    if band.size == 0:
        return cand
    mask = (band < 120).astype(np.uint8)
    cols = mask.sum(axis=0) > 0
    x_lo, x_hi = xs.min() - 0.15 * (xs.max() - xs.min()) - 30, xs.max() + 30
    best_run, start = (0, 0, 0), None
    for x in range(int(max(0, x_lo)), int(min(len(cols), x_hi))):
        if cols[x] and start is None:
            start = x
        if (not cols[x] or x == int(min(len(cols), x_hi)) - 1) and start is not None:
            if x - start > best_run[0]:
                best_run = (x - start, start, x)
            start = None
    length, xa, xb = best_run
    if length <= 0:
        return cand
    v_max = float(vs.max())
    v_min_bar = 0.0                                          # graphic scales start at 0
    est = (v_max - v_min_bar) / length
    if abs(est - cand["m_per_unit"]) / cand["m_per_unit"] < 0.12:
        return {**cand, "m_per_unit": est, "method": "scale_bar+bar_extent", "confidence": 0.9}
    return cand


# --------------------------------------------------------------- metadata
def _metadata(tokens: list[Token]) -> dict:
    full = " | ".join(t.n for t in tokens)
    flat = compact(" ".join(t.text for t in tokens))
    meta: dict = {}
    # governorate (longest names first: "SIDI BOUZID" before "SIDI")
    names = []
    for code, n in GOVERNORATES.items():
        for v in {norm(n["fr"]), norm(n["fr"]).replace("LE ", "")}:
            names.append((v, code))
    for v, code in sorted(names, key=lambda x: -len(x[0])):
        if re.search(rf"\b{re.escape(v)}\b", full) or v.replace(" ", "") in flat:
            meta["governorate"] = {"code": code, "name": GOVERNORATES[code]["fr"], "quality": "from_plan"}
            break
    m = re.search(r"DELEGATION\s*:?\s*([A-Z][A-Z \-']{2,40})", full)
    if m:
        meta["delegation"] = m.group(1).strip().title()
    gps = _gps(full)
    if gps:
        meta["gps"] = gps

    tok_flat = [compact(t.text) for t in tokens]

    def val(pattern, src=flat):
        # search token by token first (a following token must not alter the match, e.g. "3KW"+"CONDUITE")
        for tf in tok_flat:
            m_ = re.search(pattern + "$", tf) or re.search(pattern, tf)
            if m_:
                return float(m_.group(1).replace(",", "."))
        m_ = re.search(pattern, src)
        return float(m_.group(1).replace(",", ".")) if m_ else None

    meta["water_m3_day"] = val(r"EAU[A-Z]*:([\d.,]+)M[23']?/(?:JOUR|J)")
    meta["flow_m3h"] = val(r"DEBIT[A-Z]*:([\d.,]+)M3/H")
    meta["pump_kw"] = val(r"POMPES?:([\d.,]+)KW(?!H|C)")
    meta["solar_kwc"] = val(r"SOLAIRE:([\d.,]+)KWC")
    meta["battery_kwh"] = val(r"BATTERIES?:([\d.,]+)KWH")
    meta["depth_m"] = val(r"PROFONDEUR[A-Z]*:([\d.,]+)M")
    meta["cold_room_m3"] = val(r"(?:CHAMBREFROIDE|STOCKAGEFROID)[A-Z]*:([\d.,]+)M3")
    m = re.search(r"SAISON\s*:?\s*([A-Z /\-]+)", full)
    meta["season"] = _season(m.group(1)) if m else None
    m = re.search(r"\bSOL\s*:?\s*([A-Z \-]+)", full)
    meta["soil"] = _soil(m.group(1)) if m else None
    meta["test_data"] = "NON MESURE" in full or "DONNEES DE TEST" in full or "TERRAIN FICTIF" in full
    # printed area: prefer a (m2, ha) pair that agrees; handles "44,445 m2" (EN thousands) and "44 445 m2"
    m2 = re.search(r"([\d][\d ,.]*)\s*M2", full)
    ha = re.search(r"([\d]+[.,]\d+|\d+)\s*HA\b", full)
    stated = None
    if m2:
        raw = m2.group(1).strip()
        cands = {float(raw.replace(" ", "").replace(",", "").replace(".", "")) if re.search(r"[.,]\d{3}$", raw) else None,
                 _float(raw)}
        cands = {c for c in cands if c}
        if ha:
            h_ = _float(ha.group(1))
            if h_:
                stated = min(cands, key=lambda c: abs(c - h_ * 10000)) if cands else h_ * 10000
        elif cands:
            stated = max(cands)
    elif ha:
        h_ = _float(ha.group(1))
        stated = h_ * 10000 if h_ else None
    meta["stated_area_m2"] = stated
    return meta


def _float(s: str) -> float | None:
    s = s.strip().replace(" ", "")
    if s.count(",") == 1 and s.count(".") == 0:
        s = s.replace(",", ".")
    s = s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def _gps(full: str) -> dict | None:
    m = re.search(r"(3[0-7][.,]\d{3,})\s*[°N]*\s*[,;/ ]\s*(0?[7-9]|1[01])[.,](\d{3,})", full)
    if m:
        return {"lat": float(m.group(1).replace(",", ".")), "lon": float(f"{m.group(2)}.{m.group(3)}"),
                "quality": "from_plan"}
    m = re.search(r"(\d{2})\s*°\s*(\d{1,2})\s*['’]\s*([\d.]+)?\s*\"?\s*N.{0,6}?(\d{1,2})\s*°\s*(\d{1,2})\s*['’]\s*([\d.]+)?\s*\"?\s*E", full)
    if m:
        lat = int(m.group(1)) + int(m.group(2)) / 60 + float(m.group(3) or 0) / 3600
        lon = int(m.group(4)) + int(m.group(5)) / 60 + float(m.group(6) or 0) / 3600
        return {"lat": round(lat, 6), "lon": round(lon, 6), "quality": "from_plan"}
    return None


def _season(s: str) -> str | None:
    s = s.strip()
    if any(k in s for k in ("HIVER", "AUTOMNE", "ARRIERE")):
        return "autumn_winter"
    if any(k in s for k in ("PRINTEMPS", "ETE", "PRIMEUR")):
        return "spring_summer"
    if "ANNUEL" in s or "TOUTE" in s:
        return "annual"
    return None


def _soil(s: str) -> dict | None:
    for key, tex in (("ARGILO-SABL", "sandy_clay"), ("ARGILO-LIMON", "silty_clay"), ("LIMONO-ARGIL", "clay_loam"),
                     ("SABLO-LIMON", "sandy_loam"), ("LIMONO-SABL", "sandy_loam"), ("ARGIL", "clay"),
                     ("SABL", "sand"), ("LIMON", "loam")):
        if key in s:
            return {"texture": tex, "source": "plan"}
    return None


# ----------------------------------------------------------- water points
def _water_points(ex: Extraction, boundary: Polygon) -> list[dict]:
    bx0, by0, bx1, by1 = boundary.bounds
    mx, my = 0.15 * (bx1 - bx0), 0.15 * (by1 - by0)
    labels = [t for t in ex.tokens if any(w.replace(" ", "") in compact(t.text) for w in WATER_WORDS)
              and len(t.text) < 40 and "/" not in t.text
              and bx0 - mx <= t.cx <= bx1 + mx and by0 - my <= t.cy <= by1 + my]
    circles = []
    if ex.method == "vector":
        circles = [(sh.points[0], sh.points[1][0]) for sh in ex.shapes if sh.kind == "circle"]
    else:
        import cv2
        gray = _binary_gray(ex.image)
        h, w = gray.shape
        # water-point symbols are larger than boundary vertex markers (which must not be taken as wells)
        cs = cv2.HoughCircles(cv2.medianBlur(gray, 3), cv2.HOUGH_GRADIENT, dp=1, minDist=12, param1=120, param2=14,
                              minRadius=max(6, int(0.0042 * w)), maxRadius=int(0.013 * w))
        if cs is not None:
            circles = [((float(x), float(y)), float(r)) for x, y, r in cs[0]]
            # keep symbols that stand out from the background (filled / ringed disks), not pattern noise
            keep = []
            for (x, y), r in circles:
                R = int(2.1 * r) + 1
                X0, Y0 = max(0, int(x) - R), max(0, int(y) - R)
                win = gray[Y0: int(y) + R + 1, X0: int(x) + R + 1].astype(float)
                yy, xx = np.ogrid[Y0:Y0 + win.shape[0], X0:X0 + win.shape[1]]
                d2 = (xx - x) ** 2 + (yy - y) ** 2
                inner = win[d2 <= (0.9 * r) ** 2]
                outer = win[(d2 >= (1.4 * r) ** 2) & (d2 <= (2.0 * r) ** 2)]
                if inner.size and outer.size:
                    contrast = abs(float(np.mean(outer)) - float(np.mean(inner)))
                    if contrast > 35:
                        keep.append((((x, y), r), contrast))
            circles = [c for c, _ in sorted(keep, key=lambda k: -k[1])]
    out = []
    used = set()
    diag = math.hypot(*ex.page_size)
    for t in labels:
        best, bd = None, 0.06 * diag
        for i, ((cx, cy), r) in enumerate(circles):
            if i in used:
                continue
            d = math.dist((cx, cy), (t.cx, t.cy))
            if d < bd:
                best, bd = i, d
        txt = t.n
        kind = "borehole" if ("FORAGE" in txt or "SONDAGE" in txt) else "well" if "PUITS" in txt else \
            "network" if "POINT" in txt or "RACCORD" in txt else "source"
        name = re.sub(r"^(FORAGE|PUITS|SONDAGE|SOURCE)\s*", "", txt).strip() or txt
        if best is not None:
            used.add(best)
            (cx, cy), _ = circles[best]
            out.append({"name": name, "kind": kind, "x": cx, "y": cy, "label": t.text, "position": "symbol"})
        else:
            out.append({"name": name, "kind": kind, "x": t.cx, "y": t.cy, "label": t.text, "position": "label_only"})
    return out


# ------------------------------------------------------------------ legend
def _legend(ex: Extraction) -> list[tuple[tuple, str]]:
    """Legend swatches (small filled squares with a text on their right) -> zone kind."""
    if ex.method != "vector":
        return []
    out = []
    for sh in ex.shapes:
        if sh.kind != "poly" or sh.fill is None or len(sh.points) != 4:
            continue
        p = Polygon(sh.points)
        x0, y0, x1, y1 = p.bounds
        if not (4 < x1 - x0 < 20 and 4 < y1 - y0 < 20):
            continue
        txt = [t for t in ex.tokens if abs(t.cy - (y0 + y1) / 2) < 6 and 0 < t.x0 - x1 < 30]
        if not txt:
            continue
        for kind, words in LEGEND_KINDS:
            if any(w in txt[0].n for w in words):
                out.append((sh.fill, kind))
                break
    return out


def _zones(ex: Extraction, boundary: Polygon, legend) -> list[dict]:
    zones = []
    if ex.method == "vector":
        cands = [Polygon(sh.points) for sh in ex.shapes if sh.kind == "poly" and len(sh.points) >= 3]
        fills = {id(c): sh.fill for c, sh in zip(cands, [s for s in ex.shapes if s.kind == "poly" and len(s.points) >= 3])}
    else:
        cands, fills = _raster_rectangles(ex, boundary), {}
    seen: list[Polygon] = []
    order = sorted(range(len(cands)), key=lambda i: -cands[i].area)   # largest first: inner copies are dropped
    cands = [cands[i] for i in order]
    for c in cands:
        if not c.is_valid or c.area < 0.002 * boundary.area or c.area > 0.6 * boundary.area:
            continue
        if not boundary.buffer(1).contains(c.centroid):
            continue
        if any(c.intersection(s).area > 0.8 * c.area for s in seen):
            continue                                        # same zone drawn twice (fill + outline / clip)
        lab = [t for t in ex.tokens if c.buffer(2).contains(Point(t.cx, t.cy)) and not VERTEX_RE.match(compact(t.text))]
        text_area = sum((t.x1 - t.x0) * (t.y1 - t.y0) for t in lab)
        fill = fills.get(id(c))
        whiteish = fill is not None and min(fill) > 0.93
        if lab and (c.area < 1.8 * text_area or (whiteish and c.area < 5 * text_area)):
            continue                                        # white box behind a label, not a zone
        text = " ".join(t.n for t in lab)
        flat_text = compact(text)
        kind = None
        for k, words in ZONE_KEYWORDS:
            # OCR may drop spaces ("VERGEREXISTANT"): also match on the compacted text
            if any(re.search(rf"\b{w}\b", text) or (len(w) > 3 and w.replace(" ", "") in flat_text) for w in words):
                kind = k
                break
        if kind is None and fills.get(id(c)) is not None:
            for col, k in legend:
                if k not in ("boundary", "water_point") and np.allclose(col, fills[id(c)], atol=0.03):
                    kind = k
                    break
        if kind is None:
            if not lab:
                continue                                    # unlabeled small shapes (symbols, tags) are ignored
            kind = "obstacle"
        seen.append(c)
        zones.append({"kind": kind, "label": " ".join(t.text for t in lab)[:60], "area_units": c.area,
                      "polygon": list(c.exterior.coords)[:-1]})
    return zones


def _raster_rectangles(ex: Extraction, boundary: Polygon) -> list[Polygon]:
    import cv2
    gray = cv2.cvtColor(ex.image, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 50, 150)
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8))
    cs, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    out = []
    for c in cs:
        peri = cv2.arcLength(c, True)
        ap = cv2.approxPolyDP(c, 0.03 * peri, True)
        if 4 <= len(ap) <= 6 and cv2.isContourConvex(ap):
            p = Polygon([(float(q[0][0]), float(q[0][1])) for q in ap])
            if p.is_valid and boundary.contains(p.centroid):
                out.append(p)
    out.sort(key=lambda p: -p.area)
    return out


# ------------------------------------------------------------------- lines
def _lines(ex: Extraction, boundary: Polygon) -> list[dict]:
    out = []
    if ex.method == "vector":
        segs = [sh for sh in ex.shapes if sh.kind == "line" and sh.stroke is not None and len(sh.points) >= 2
                and sh.width >= 1.5]
        for sh in segs:
            ln = LineString(sh.points)
            if ln.length < 0.04 * math.hypot(*boundary.bounds[2:]) or not ln.intersects(boundary.buffer(20)):
                continue
            near = sorted(ex.tokens, key=lambda t: ln.distance(Point(t.cx, t.cy)))[:3]
            near = [t for t in near if ln.distance(Point(t.cx, t.cy)) < 30]
            kind, label = None, ""
            for t in near:
                for k, words in LINE_KEYWORDS:
                    if any(w in t.n for w in words):
                        kind, label = k, t.text
                        break
                if kind:
                    break
            if kind is None:
                kind = "pipe" if sh.dashed else None
            if kind is None:
                continue
            if _is_scale_bar(ex, ln):
                continue
            out.append({"kind": kind, "label": label, "dashed": sh.dashed, "line": sh.points,
                        "width_units": sh.width, "inside_boundary": boundary.contains(ln.centroid)})
        return out
    # raster: lines near a keyword label (paths, pipes, slopes)
    import cv2
    gray = cv2.cvtColor(ex.image, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 50, 150)
    segs = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=60, minLineLength=int(0.05 * max(gray.shape)), maxLineGap=12)
    if segs is None:
        return out
    segs = np.asarray(segs).reshape(-1, 4)
    for t in ex.tokens:
        kind = next((k for k, words in LINE_KEYWORDS if any(w in t.n for w in words)), None)
        if kind is None or len(t.text) > 30 or ";" in t.text:
            continue
        bx0, by0, bx1, by1 = boundary.bounds
        if not (bx0 - 0.2 * (bx1 - bx0) <= t.cx <= bx1 + 0.2 * (bx1 - bx0) and by0 - 0.2 * (by1 - by0) <= t.cy <= by1 + 0.2 * (by1 - by0)):
            continue                                        # sentence of the technical sheet, not a map label
        near = [s for s in segs if LineString([(s[0], s[1]), (s[2], s[3])]).distance(Point(t.cx, t.cy)) < 40]
        if not near:
            continue
        s = max(near, key=lambda q: math.hypot(q[2] - q[0], q[3] - q[1]))
        ln = LineString([(float(s[0]), float(s[1])), (float(s[2]), float(s[3]))])
        if _is_scale_bar(ex, ln):
            continue
        out.append({"kind": kind, "label": t.text, "dashed": False, "line": list(ln.coords), "width_units": 4.0,
                    "inside_boundary": boundary.contains(ln.centroid)})
    return out


def _is_scale_bar(ex: Extraction, ln: LineString) -> bool:
    for t in ex.tokens:
        if _num(t.text) is not None and "M" in t.n and ln.distance(Point(t.cx, t.cy)) < 25:
            return True
    return False


# ======================================================== geo conversion ==
def to_geo(parsed: dict, anchor_lat: float, anchor_lon: float) -> dict:
    """Place the local metric plan on the map: its centroid at (anchor_lat, anchor_lon), north up."""
    from pyproj import Transformer
    from shapely.geometry import mapping
    from shapely.ops import transform
    to_utm = Transformer.from_crs("EPSG:4326", "EPSG:32632", always_xy=True)
    to_wgs = Transformer.from_crs("EPSG:32632", "EPSG:4326", always_xy=True)
    ax, ay = to_utm.transform(anchor_lon, anchor_lat)
    b = Polygon(parsed["boundary_m"])
    c = b.centroid

    def shift(x, y, z=None):
        return to_wgs.transform(ax + (np.asarray(x) - c.x), ay + (np.asarray(y) - c.y))

    out = {"boundary": mapping(transform(shift, b)), "exclusions": [], "water_points": [], "lines": []}
    for z in parsed["zones"]:
        if z["kind"] in ("reservoir", "solar", "building", "cold_storage", "orchard", "exclusion", "obstacle"):
            out["exclusions"].append({"kind": z["kind"], "label": z["label"],
                                      "geometry": mapping(transform(shift, Polygon(z["polygon_m"])))})
    for ln in parsed["lines"]:
        g = LineString(ln["line_m"])
        if ln["kind"] in ("path", "slope") and b.intersects(g):
            width = max(3.0, ln["width_m"]) if ln["kind"] == "path" else 4.0
            out["exclusions"].append({"kind": ln["kind"], "label": ln["label"],
                                      "geometry": mapping(transform(shift, g.buffer(width / 2, cap_style=2)))})
        out["lines"].append({**ln, "geometry": mapping(transform(shift, g))})
    for w in parsed["water_points"]:
        lon, lat = shift(w["x_m"], w["y_m"])
        out["water_points"].append({**w, "latitude": float(lat), "longitude": float(lon)})
    return out


def rescale(parsed: dict, f: float) -> dict:
    """Multiply every metric quantity of a parse result by f (farmer-corrected side length)."""
    import copy
    out = copy.deepcopy(parsed)
    out["boundary_m"] = [[x * f, y * f] for x, y in out["boundary_m"]]
    for e in out.get("edges", []):
        e["length_m"] = round(e["length_m"] * f, 2)
    out["perimeter_m"] = round(out["perimeter_m"] * f, 2)
    for w in out.get("water_points", []):
        w["x_m"], w["y_m"] = w["x_m"] * f, w["y_m"] * f
    for z in out.get("zones", []):
        z["polygon_m"] = [[x * f, y * f] for x, y in z["polygon_m"]]
    for ln in out.get("lines", []):
        ln["line_m"] = [[x * f, y * f] for x, y in ln["line_m"]]
        ln["width_m"] = round(ln.get("width_m", 0) * f, 2)
    a = out["area"]
    a["measured_m2"] = round(a["measured_m2"] * f * f, 1)
    if a.get("stated_m2"):
        dev = 100 * (a["measured_m2"] - a["stated_m2"]) / a["stated_m2"]
        a.update(deviation_pct=round(dev, 2), ok=abs(dev) <= 3.0)
    out["scale"] = {**out["scale"], "m_per_unit": round(out["scale"]["m_per_unit"] * f, 6), "method": "user_edge",
                    "confidence": 1.0}
    out["warnings"] = [w for w in out.get("warnings", []) if w["code"] not in ("scale_from_area", "area_mismatch")]
    if a.get("ok") is False:
        out["warnings"].append({"code": "area_mismatch", "severity": "warning",
                                "data": {"measured": round(a["measured_m2"]), "stated": round(a["stated_m2"]),
                                         "deviation": round(a["deviation_pct"], 1)}})
    return out
