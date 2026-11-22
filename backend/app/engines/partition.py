"""Spatial partition of a farm into crop parcels (Shapely / pyproj).

Method (documented in docs/ARCHITECTURE.md):
1. Project the farm polygon to UTM 32N (EPSG:32632, covers Tunisia) so areas
   and distances are metric; remove exclusions and a boundary setback.
2. Split the field between water sources with a Voronoi diagram (each source
   irrigates its nearest area); the share of each crop follows the region area.
3. In each region build the hydraulic skeleton: a main corridor (path + main
   pipe) along the long axis of the minimum rotated rectangle, connected to the
   source, plus a technical zone (pump / filters / tank) around the source.
4. Order crops by water intensity (m3/ha, descending) and allocate contiguous
   bands at increasing distance from the source along the corridor; each band
   boundary is found by bisection so that the band area equals the optimised
   area (exact-area partition, not decorative rectangles). By the
   rearrangement inequality this ordering minimises sum(volume x pipe length)
   for the 1-D band model.
5. Bands larger than the irrigation-sector size are cut into sectors with the
   same equal-area bisection along the perpendicular axis; secondary paths are
   created between parcels by a negative buffer.
All output geometries are validated (make_valid) and returned in EPSG:4326.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from pyproj import Transformer
from shapely import affinity
from shapely.geometry import LineString, MultiPoint, Point, Polygon, mapping, shape
from shapely.ops import transform, unary_union, voronoi_diagram
from shapely.validation import make_valid

TO_UTM = Transformer.from_crs("EPSG:4326", "EPSG:32632", always_xy=True)
TO_WGS = Transformer.from_crs("EPSG:32632", "EPSG:4326", always_xy=True)


def to_utm(geom):
    return transform(TO_UTM.transform, geom)


def to_wgs(geom):
    return transform(TO_WGS.transform, geom)


def area_m2(geojson: dict) -> float:
    return to_utm(shape(geojson)).area


def _polys(g):
    g = make_valid(g)
    if g.is_empty:
        return []
    if g.geom_type == "Polygon":
        return [g]
    if hasattr(g, "geoms"):
        out = []
        for x in g.geoms:
            out.extend(_polys(x))
        return out
    return []


def _clean(g, min_area=1.0):
    parts = [p for p in _polys(g) if p.area >= min_area]
    if not parts:
        return Polygon()
    return unary_union(parts)


@dataclass
class Source:
    id: int | None
    lon: float
    lat: float
    capacity_weight: float = 1.0


@dataclass
class PartitionSettings:
    boundary_setback_m: float = 2.0
    corridor_width_m: float = 4.0
    secondary_path_m: float = 2.0
    pump_zone_radius_m: float = 6.0
    sector_max_ha: float = 2.0
    min_parcel_m2: float = 50.0


def axis_angle(poly: Polygon) -> float:
    """Angle (rad) of the long side of the minimum rotated rectangle."""
    mrr = poly.minimum_rotated_rectangle
    coords = list(mrr.exterior.coords)
    best, ang = 0.0, 0.0
    for i in range(4):
        (x1, y1), (x2, y2) = coords[i], coords[i + 1]
        L = math.hypot(x2 - x1, y2 - y1)
        if L > best:
            best, ang = L, math.atan2(y2 - y1, x2 - x1)
    return ang


def _band(region: Polygon, origin: Point, ang: float, d0: float, d1: float) -> Polygon:
    """Region ∩ {d0 <= |s - s_origin| < d1} where s is the coordinate along the axis."""
    big = 1e6
    ux, uy = math.cos(ang), math.sin(ang)
    vx, vy = -uy, ux
    ox, oy = origin.x, origin.y

    def rect(s0, s1):
        pts = [(ox + ux * s0 + vx * -big, oy + uy * s0 + vy * -big), (ox + ux * s1 + vx * -big, oy + uy * s1 + vy * -big),
               (ox + ux * s1 + vx * big, oy + uy * s1 + vy * big), (ox + ux * s0 + vx * big, oy + uy * s0 + vy * big)]
        return Polygon(pts)

    strip = unary_union([rect(d0, d1), rect(-d1, -d0)])
    return _clean(region.intersection(strip), 0.01)


def _bisect_cumulative(region, origin, ang, cum_target_m2, d_lo, d_hi):
    """Smallest distance D such that area(region within |s| < D of origin) >= cum_target_m2."""
    lo, hi = d_lo, d_hi
    for _ in range(50):
        mid = (lo + hi) / 2
        if _band(region, origin, ang, 0.0, mid).area < cum_target_m2:
            lo = mid
        else:
            hi = mid
    return hi


def _split_sectors(poly, ang, max_m2):
    """Equal-area cuts across the band (perpendicular axis) into sectors <= max_m2."""
    if poly.area <= max_m2 * 1.05:
        return [poly]
    n = math.ceil(poly.area / max_m2)
    perp = ang + math.pi / 2
    minx, miny, maxx, maxy = poly.bounds
    c = poly.centroid
    span = math.hypot(maxx - minx, maxy - miny)
    ux, uy = math.cos(perp), math.sin(perp)
    vx, vy = -uy, ux
    big = span * 4

    def halfplane(s):
        o = (c.x + ux * s, c.y + uy * s)
        return Polygon([(o[0] - ux * big + vx * -big, o[1] - uy * big + vy * -big),
                        (o[0] + vx * -big, o[1] + vy * -big), (o[0] + vx * big, o[1] + vy * big),
                        (o[0] - ux * big + vx * big, o[1] - uy * big + vy * big)])

    out, prev = [], Polygon()
    target_each = poly.area / n
    for k in range(1, n):
        lo, hi = -span, span
        for _ in range(45):
            mid = (lo + hi) / 2
            if poly.intersection(halfplane(mid)).area < target_each * k:
                lo = mid
            else:
                hi = mid
        cum = _clean(poly.intersection(halfplane(hi)), 0.01)
        piece = _clean(cum.difference(prev), 0.01)
        out.append(piece)
        prev = cum
    out.append(_clean(poly.difference(prev), 0.01))
    return [p for p in out if not p.is_empty]


@dataclass
class ParcelGeom:
    crop: str
    geom_utm: Polygon
    source_index: int
    pipe_length_m: float


def partition(field_geojson: dict, crop_areas_m2: dict[str, float], crop_water_intensity: dict[str, float],
              sources: list[Source], exclusions_geojson: dict | None = None,
              locked: list[tuple[str, dict]] | None = None, settings: PartitionSettings | None = None) -> dict:
    """Return parcels + infrastructure. crop_areas_m2: target areas of *non-locked* crops."""
    st = settings or PartitionSettings()
    field = _clean(to_utm(shape(field_geojson)))
    if field.is_empty:
        raise ValueError("Invalid farm boundary")
    if exclusions_geojson:
        field = _clean(field.difference(to_utm(shape(exclusions_geojson))))
    field = _clean(field.buffer(-st.boundary_setback_m, join_style=2))
    locked_parcels = []
    for crop, gj in (locked or []):
        g = _clean(to_utm(shape(gj)).intersection(field))
        if not g.is_empty:
            locked_parcels.append((crop, g))
            field = _clean(field.difference(g.buffer(st.secondary_path_m / 2)))
    if not sources:
        c = field.representative_point()
        lon, lat = TO_WGS.transform(c.x, c.y)
        sources = [Source(None, lon, lat)]
    src_pts = [Point(*TO_UTM.transform(s.lon, s.lat)) for s in sources]

    # 2. regions per source
    if len(src_pts) > 1:
        vor = voronoi_diagram(MultiPoint(src_pts), envelope=field.envelope.buffer(1000))
        regions = []
        for sp in src_pts:
            cell = next((v for v in vor.geoms if v.contains(sp) or v.touches(sp)), None)
            regions.append(_clean(field.intersection(cell)) if cell is not None else Polygon())
    else:
        regions = [field]

    infra_parts, parcels = [], []
    total_region = sum(r.area for r in regions) or 1.0
    order = sorted(crop_areas_m2, key=lambda c: -crop_water_intensity.get(c, 0.0))
    for idx, (region, sp) in enumerate(zip(regions, src_pts)):
        if region.is_empty:
            continue
        ang = axis_angle(region)
        centre = region.centroid
        ux, uy = math.cos(ang), math.sin(ang)
        span = max(region.bounds[2] - region.bounds[0], region.bounds[3] - region.bounds[1]) * 2 + 10
        axis = LineString([(centre.x - ux * span, centre.y - uy * span), (centre.x + ux * span, centre.y + uy * span)])
        # snap the source onto the axis to get the corridor origin
        origin = axis.interpolate(axis.project(sp))
        connector = LineString([sp, origin])
        corridor = unary_union([axis.intersection(region.buffer(1)), connector]).buffer(st.corridor_width_m / 2,
                                                                                          cap_style=2)
        pump_zone = sp.buffer(st.pump_zone_radius_m)
        infra = _clean(unary_union([corridor, pump_zone]).intersection(region.buffer(st.pump_zone_radius_m)), 0.01)
        infra_parts.append(infra)
        productive = _clean(region.difference(infra))
        share = region.area / total_region
        prod_area = productive.area
        targets = [(c, crop_areas_m2[c] * share) for c in order if crop_areas_m2[c] > 0]
        tot = sum(t for _, t in targets)
        if tot > prod_area:  # geometry smaller than planned (paths): scale down, metrics follow real areas
            targets = [(c, t * prod_area / tot * 0.999) for c, t in targets]
        dmax = span
        d0 = 0.0
        cum_target = 0.0
        for crop, tgt in targets:
            # cumulative bisection: area(band 0..d1) = sum of targets allocated so far
            cum_target += tgt
            d1 = _bisect_cumulative(productive, origin, ang, cum_target, d0, dmax)
            band = _band(productive, origin, ang, d0, d1)
            d0 = d1
            for poly in _polys(band):
                for sector in _split_sectors(poly, ang, st.sector_max_ha * 10000):
                    g = _clean(sector.buffer(-st.secondary_path_m / 2, join_style=2), st.min_parcel_m2)
                    for part in _polys(g):
                        if part.area < st.min_parcel_m2:
                            continue
                        near = origin  # pipe: source -> corridor -> along axis -> into parcel
                        p_on_axis = axis.interpolate(axis.project(part.centroid))
                        length = connector.length + near.distance(p_on_axis) + p_on_axis.distance(
                            part.exterior.interpolate(part.exterior.project(p_on_axis)))
                        parcels.append(ParcelGeom(crop, part, idx, length))
    for crop, g in locked_parcels:
        for part in _polys(g):
            dists = [sp.distance(part) for sp in src_pts]
            k = min(range(len(src_pts)), key=lambda i: dists[i])
            parcels.append(ParcelGeom(crop, part, k, dists[k] * 1.3))
    infra_all = _clean(unary_union(infra_parts), 0.01) if infra_parts else Polygon()
    return {
        "parcels": [{"crop": p.crop, "geometry": mapping(to_wgs(p.geom_utm)), "area_m2": round(p.geom_utm.area, 1),
                     "source_index": p.source_index, "pipe_length_m": round(p.pipe_length_m, 1),
                     "locked": any(p.geom_utm.equals(g) for _, g in locked_parcels)} for p in parcels],
        "infrastructure": mapping(to_wgs(infra_all)) if not infra_all.is_empty else None,
        "field_area_m2": round(to_utm(shape(field_geojson)).area, 1),
        "productive_area_m2": round(sum(p.geom_utm.area for p in parcels), 1),
        "infrastructure_area_m2": round(infra_all.area, 1),
    }


def rotate_for_preview(geom, deg):  # utility used by tests
    return affinity.rotate(geom, deg, origin="centroid")
