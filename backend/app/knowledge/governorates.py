"""Tunisian governorates (ISO 3166-2:TN codes).

Boundaries: geoBoundaries gbOpen TUN ADM1 (ODbL, OpenStreetMap contributors),
stored in data/reference/geoboundaries_tun_adm1.geojson. Centroids are computed
from those polygons at runtime — no hard-coded coordinates.
"""
from __future__ import annotations

import json
from functools import lru_cache

from shapely.geometry import shape

from app.core.config import get_settings

GOVERNORATES: dict[str, dict[str, str]] = {
    "TN-11": {"fr": "Tunis", "ar": "تونس"},
    "TN-12": {"fr": "Ariana", "ar": "أريانة"},
    "TN-13": {"fr": "Ben Arous", "ar": "بن عروس"},
    "TN-14": {"fr": "Manouba", "ar": "منوبة"},
    "TN-21": {"fr": "Nabeul", "ar": "نابل"},
    "TN-22": {"fr": "Zaghouan", "ar": "زغوان"},
    "TN-23": {"fr": "Bizerte", "ar": "بنزرت"},
    "TN-31": {"fr": "Béja", "ar": "باجة"},
    "TN-32": {"fr": "Jendouba", "ar": "جندوبة"},
    "TN-33": {"fr": "Le Kef", "ar": "الكاف"},
    "TN-34": {"fr": "Siliana", "ar": "سليانة"},
    "TN-41": {"fr": "Kairouan", "ar": "القيروان"},
    "TN-42": {"fr": "Kasserine", "ar": "القصرين"},
    "TN-43": {"fr": "Sidi Bouzid", "ar": "سيدي بوزيد"},
    "TN-51": {"fr": "Sousse", "ar": "سوسة"},
    "TN-52": {"fr": "Monastir", "ar": "المنستير"},
    "TN-53": {"fr": "Mahdia", "ar": "المهدية"},
    "TN-61": {"fr": "Sfax", "ar": "صفاقس"},
    "TN-71": {"fr": "Gafsa", "ar": "قفصة"},
    "TN-72": {"fr": "Tozeur", "ar": "توزر"},
    "TN-73": {"fr": "Kébili", "ar": "قبلي"},
    "TN-81": {"fr": "Gabès", "ar": "قابس"},
    "TN-82": {"fr": "Médenine", "ar": "مدنين"},
    "TN-83": {"fr": "Tataouine", "ar": "تطاوين"},
}


@lru_cache
def boundaries() -> dict:
    path = get_settings().reference_dir / "geoboundaries_tun_adm1.geojson"
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache
def centroids() -> dict[str, tuple[float, float]]:
    """(lat, lon) of a representative point inside each governorate."""
    out: dict[str, tuple[float, float]] = {}
    for f in boundaries()["features"]:
        code = f["properties"]["shapeISO"]
        p = shape(f["geometry"]).representative_point()
        out[code] = (round(p.y, 4), round(p.x, 4))
    return out


def governorate_at(lat: float, lon: float) -> str | None:
    from shapely.geometry import Point
    pt = Point(lon, lat)
    for f in boundaries()["features"]:
        if shape(f["geometry"]).contains(pt):
            return f["properties"]["shapeISO"]
    return None
