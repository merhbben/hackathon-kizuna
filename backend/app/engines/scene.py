"""2D scene model shared by the Phaser editor, SVG/PDF export and plan re-opening.

A scene is plain JSON in local metres (x east, y north, origin = south-west corner of the
farm bounding box, UTM 32N), so the editor never deals with geographic projections:

    {"format": "agrosphere.scene", "version": 1, "units": "m", "origin": {...},
     "boundary": [[x, y], ...], "zones": [...], "sources": [...], "parcels": [...],
     "pipes": [...], "infrastructure": [[[x, y], ...]], "lines": [...], "meta": {...}}
"""
from __future__ import annotations

import html
import math

from pyproj import Transformer
from shapely.geometry import shape

TO_UTM = Transformer.from_crs("EPSG:4326", "EPSG:32632", always_xy=True)
TO_WGS = Transformer.from_crs("EPSG:32632", "EPSG:4326", always_xy=True)
FORMAT = "agrosphere.scene"
VERSION = 1

ZONE_COLORS = {"reservoir": "#7cc4ff", "solar": "#7b8fd1", "building": "#7a8a80", "cold_storage": "#5b6b61",
               "orchard": "#6b8e23", "exclusion": "#e8b4a8", "obstacle": "#9aa5a0", "path": "#c9c3b5",
               "slope": "#b4675a"}


def _holefree(poly) -> list:
    """Split a polygon with holes into hole-free pieces of identical total area (the scene format stores
    outer rings only): cut along the vertical line through the first hole, recursively."""
    from shapely.geometry import LineString
    from shapely.ops import split
    if not poly.interiors:
        return [poly]
    x = poly.interiors[0].centroid.x
    _, miny, _, maxy = poly.bounds
    out = []
    for piece in split(poly, LineString([(x, miny - 1), (x, maxy + 1)])).geoms:
        if piece.geom_type == "Polygon" and piece.area > 0:
            out.extend(_holefree(piece))
    return out or [poly]


def _rings(geom) -> list[list[list[float]]]:
    g = shape(geom) if isinstance(geom, dict) else geom
    polys = [g] if g.geom_type == "Polygon" else [p for p in getattr(g, "geoms", []) if p.geom_type == "Polygon"]
    return [[list(c) for c in q.exterior.coords[:-1]] for p in polys for q in _holefree(p)]


def build_scene(farm, plan=None) -> dict:
    b = shape(farm.boundary_geojson)
    minx, miny, _, _ = _utm_bounds(b)

    def loc(lon, lat):
        x, y = TO_UTM.transform(lon, lat)
        return [round(x - minx, 2), round(y - miny, 2)]

    def ring(geom):
        return [[loc(lon, lat) for lon, lat in r] for r in _rings(geom)]

    pu = farm.plan_upload or {}
    zones = []
    for z in pu.get("geo_exclusions", []):
        for r in ring(z["geometry"]):
            zones.append({"kind": z["kind"], "label": z.get("label", ""), "polygon": r})
    if not zones and farm.exclusions_geojson:
        g = farm.exclusions_geojson
        geoms = g.get("geometries", [g]) if g.get("type") == "GeometryCollection" else [g]
        for gg in geoms:
            for r in ring(gg):
                zones.append({"kind": "obstacle", "label": "", "polygon": r})
    lines = []
    for ln in pu.get("geo_lines", []):
        coords = ln["geometry"]["coordinates"]
        lines.append({"kind": ln["kind"], "label": ln.get("label", ""), "line": [loc(x, y) for x, y in coords]})
    scene = {
        "format": FORMAT, "version": VERSION, "units": "m",
        "origin": {"utm_zone": "32N", "easting": round(minx, 2), "northing": round(miny, 2),
                   "location_quality": (pu.get("location") or {}).get("quality", "user")},
        "boundary": ring(farm.boundary_geojson)[0],
        "zones": zones, "lines": lines,
        "sources": [{"id": s.id, "kind": s.kind, "name": s.name or "", "code": f"F{i + 1}",
                     "xy": loc(s.longitude, s.latitude), "flow_m3h": s.flow_m3h, "daily_volume_m3": s.daily_volume_m3,
                     "depth_m": s.pumping_depth_m or None, "pump_kw": _pump_kw(farm, s)}
                    for i, s in enumerate(farm.water_sources)],
        "parcels": [], "pipes": [], "infrastructure": [],
        "meta": {"farm": farm.name, "governorate": farm.governorate_code, "area_ha": farm.measured_area_ha},
    }
    ent = (farm.preferences or {}).get("entrance")
    if ent and ent.get("lat") is not None:
        scene["entrance"] = loc(ent["lon"], ent["lat"])
    bd = scene["boundary"]
    scene["edges"] = [round(math.dist(bd[i], bd[(i + 1) % len(bd)]), 1) for i in range(len(bd))]
    if plan is not None:
        for p in plan.parcels:
            m = p.metrics or {}
            for r in ring(p.geometry_geojson):
                scene["parcels"].append({
                    "id": p.id, "label": p.label, "zone": m.get("zone") or p.label, "crop": p.crop_code,
                    "polygon": r, "area_m2": round(p.area_m2, 1),
                    "locked": p.locked, "rainfed": bool(m.get("rainfed")), "production_kg": m.get("production_kg"),
                    "water_m3": m.get("water_m3_season"), "planting": m.get("planting"), "harvest": m.get("harvest")})
            if m.get("pipe"):
                scene["pipes"].append({"parcel_id": p.id, "line": [loc(x, y) for x, y in m["pipe"]["coordinates"]]})
        if plan.infrastructure_geojson:
            scene["infrastructure"] = ring(plan.infrastructure_geojson)
        site = ((plan.storage or {}).get("cold_building") or {}).get("site") or {}
        for kind, key in (("cold_storage", "building"), ("solar", "pv")):
            if site.get(key):
                for rr in ring(site[key]):
                    scene["zones"].append({"kind": kind, "label": "", "polygon": rr, "plan": True})
        # land left uncultivated (e.g. not enough water): boundary - parcels - zones - infrastructure
        from shapely.geometry import Polygon as P_
        from shapely.ops import unary_union
        used = [P_(p["polygon"]).buffer(2.5) for p in scene["parcels"]] + [P_(z["polygon"]) for z in zones] +                [P_(r).buffer(1) for r in scene["infrastructure"]]
        rest = P_(scene["boundary"]).buffer(-2.5).difference(unary_union(used)) if used else None
        fallow = []
        if rest is not None and not rest.is_empty:
            for g in ([rest] if rest.geom_type == "Polygon" else list(getattr(rest, "geoms", []))):
                if g.geom_type == "Polygon" and g.area > 100:
                    fallow.append([[round(x, 2), round(y, 2)] for x, y in g.exterior.coords[:-1]])
        scene["fallow"] = fallow
        scene["meta"].update(plan_id=plan.id, plan_version=plan.version,
                             unused_area_ha=(plan.summary or {}).get("unused_area_ha"),
                             rainfed_only=(plan.summary or {}).get("rainfed_only", False))
    return scene


def _pump_kw(farm, src):
    for e in farm.equipment:
        if e.kind == "pump" and (e.specs or {}).get("source_id") == src.id and e.specs.get("power_kw"):
            return float(e.specs["power_kw"])
    return None


def local_to_lonlat(farm, x: float, y: float) -> tuple[float, float]:
    """Inverse of the scene projection: local metres of this farm's scene -> (lon, lat)."""
    minx, miny, _, _ = _utm_bounds(shape(farm.boundary_geojson))
    lon, lat = TO_WGS.transform(minx + x, miny + y)
    return float(lon), float(lat)


def _utm_bounds(geom):
    from shapely.ops import transform
    return transform(TO_UTM.transform, geom).bounds


def validate(scene: dict) -> dict:
    """Minimal structural validation used when a saved scene is re-opened."""
    if not isinstance(scene, dict) or scene.get("format") != FORMAT:
        raise ValueError("not_a_scene")
    if scene.get("version", 0) > VERSION:
        raise ValueError("scene_version_unsupported")
    b = scene.get("boundary")
    if not isinstance(b, list) or len(b) < 3:
        raise ValueError("scene_boundary_invalid")
    for p in scene.get("parcels", []):
        if len(p.get("polygon", [])) < 3:
            raise ValueError("scene_parcel_invalid")
    return scene


def to_svg(scene: dict, colors: dict[str, str], names: dict[str, str], title: str = "") -> str:
    """Print-ready SVG: plan at scale with legend, scale bar and north arrow (y flipped: SVG y grows down)."""
    validate(scene)
    xs = [p[0] for p in scene["boundary"]]
    ys = [p[1] for p in scene["boundary"]]
    W, H = max(xs) - min(xs), max(ys) - min(ys)
    pad = max(W, H) * 0.06
    vw, vh = W + 2 * pad, H + 2 * pad
    k = 900 / max(vw, vh)                                  # px per metre in the drawing
    legend_w = 260

    def P(pt):
        return f"{(pt[0] - min(xs) + pad) * k:.1f},{(max(ys) - pt[1] + pad) * k:.1f}"

    def poly(pts, fill, stroke="#ffffff", sw=1.2, op=1.0, extra=""):
        return f'<polygon points="{" ".join(P(p) for p in pts)}" fill="{fill}" fill-opacity="{op}" stroke="{stroke}" stroke-width="{sw}" {extra}/>'

    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{vw * k + legend_w:.0f}" height="{vh * k + 60:.0f}" '
           f'viewBox="0 0 {vw * k + legend_w:.0f} {vh * k + 60:.0f}" font-family="Arial, sans-serif">',
           f'<rect width="100%" height="100%" fill="#ffffff"/>',
           f'<text x="16" y="{vh * k + 40:.0f}" font-size="16" font-weight="bold" fill="#103a20">{html.escape(title)}</text>',
           poly(scene["boundary"], "#f3f8f2", "#1f7a3d", 3)]
    for z in scene.get("zones", []):
        out.append(poly(z["polygon"], ZONE_COLORS.get(z["kind"], "#9aa5a0"), "#5b6b61", 1, 0.85))
    for r in scene.get("fallow", []):
        out.append(poly(r, "#e9ece6", "#c3c9c0", 0.8, 0.9))
    for r in scene.get("infrastructure", []):
        out.append(poly(r, "#f6b93b", "#c98a06", 0.8, 0.55))
    used = {}
    groups: dict[str, dict] = {}
    for p in scene.get("parcels", []):
        c = colors.get(p["crop"], "#7a8a80")
        used[p["crop"]] = c
        out.append(poly(p["polygon"], c, c, 0.6, 0.82))
        z = p.get("zone") or p["label"]
        g = groups.setdefault(z, {"crop": p["crop"], "ids": set(), "m2": 0.0, "big": None, "big_a": -1.0})
        if p["id"] not in g["ids"]:
            g["ids"].add(p["id"])
            g["m2"] += p["area_m2"]
        a_ = _ring_area(p["polygon"])
        if a_ > g["big_a"]:
            g["big"], g["big_a"] = p["polygon"], a_
    for z, g in groups.items():
        cx, cy = _ring_centroid(g["big"])
        x, y = P([cx, cy]).split(",")
        out.append(f'<text x="{x}" y="{y}" font-size="12" text-anchor="middle" fill="#16201a" font-weight="bold" '
                   f'paint-order="stroke" stroke="#ffffff" stroke-width="3">{html.escape(z)} · '
                   f'{html.escape(names.get(g["crop"], g["crop"]))} · {g["m2"] / 1e4:.2f} ha</text>')
    for pp in scene.get("pipes", []):
        out.append(f'<polyline points="{" ".join(P(q) for q in pp["line"])}" fill="none" stroke="#1c6fb8" '
                   f'stroke-width="1.6" stroke-dasharray="5 3"/>')
    for s in scene.get("sources", []):
        x, y = P(s["xy"]).split(",")
        out.append(f'<circle cx="{x}" cy="{y}" r="7" fill="#1c6fb8" stroke="#ffffff" stroke-width="2.5"/>')
        out.append(f'<text x="{float(x) + 10:.1f}" y="{float(y) - 8:.1f}" font-size="11" fill="#134c7f">{html.escape(s["name"] or s["kind"])}</text>')
    # scale bar (round length ~ 1/4 of width) and north arrow
    nice = [1, 2, 5]
    target = W / 4
    exp = 10 ** math.floor(math.log10(max(target, 1)))
    L = min((n * exp for n in nice), key=lambda v: abs(v - target))
    y0 = (vh - pad / 2) * k
    out.append(f'<line x1="{pad * k:.1f}" y1="{y0:.1f}" x2="{(pad + L) * k:.1f}" y2="{y0:.1f}" stroke="#16201a" stroke-width="4"/>')
    out.append(f'<text x="{pad * k:.1f}" y="{y0 + 16:.1f}" font-size="11">0</text>')
    out.append(f'<text x="{(pad + L) * k:.1f}" y="{y0 + 16:.1f}" font-size="11" text-anchor="middle">{L:g} m</text>')
    ax = (vw - pad / 2) * k
    out.append(f'<path d="M {ax:.1f} {pad * k * 0.3:.1f} l -8 22 l 8 -6 l 8 6 z" fill="#16201a"/>'
               f'<text x="{ax:.1f}" y="{pad * k * 0.3 + 36:.1f}" font-size="13" text-anchor="middle" font-weight="bold">N</text>')
    lx = vw * k + 16
    out.append(f'<text x="{lx}" y="30" font-size="14" font-weight="bold" fill="#103a20">TuniNō</text>')
    yy = 56
    for crop, c in used.items():
        out.append(f'<rect x="{lx}" y="{yy - 11}" width="14" height="14" fill="{c}"/>'
                   f'<text x="{lx + 22}" y="{yy}" font-size="12">{html.escape(names.get(crop, crop))}</text>')
        yy += 22
    out.append(f'<text x="{lx}" y="{yy + 10}" font-size="10" fill="#5b6b61">Échelle graphique · Nord en haut</text>')
    out.append("</svg>")
    return "\n".join(out)


def _ring_area(pts) -> float:
    return abs(sum(pts[i][0] * pts[i - 1][1] - pts[i - 1][0] * pts[i][1] for i in range(len(pts)))) / 2


def _ring_centroid(pts) -> tuple[float, float]:
    from shapely.geometry import Polygon
    c = Polygon(pts).representative_point()
    return c.x, c.y


def svg_to_pdf(svg: str) -> bytes:
    import fitz
    doc = fitz.open(stream=svg.encode("utf-8"), filetype="svg")
    return doc.convert_to_pdf()
