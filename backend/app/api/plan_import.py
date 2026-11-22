"""One-step import of a technical farm plan: Import -> Read -> Understand -> Verify -> Optimise.

POST /api/farms/import            multipart file (+ optional 'corrections' JSON)
POST /api/farms/{id}/corrections  optional corrections (location, flow, depth, season, area) -> re-plan
GET  /api/farms/{id}/plans/{pid}/scene | export.svg | export.pdf
POST /api/scenes/render           re-open a saved scene JSON -> svg | pdf
"""
from __future__ import annotations

import json
import logging
import secrets
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import audit, current_user, owned_farm
from app.api.farms import farm_out, plan_out
from app.connectors import sources
from app.connectors.base import ConnectorError
from app.core.config import get_settings
from app.cv import plan_parser
from app.db.session import get_db
from app.engines import agrobrain, scene as scene_eng
from app.knowledge.crops import CROPS
from app.knowledge.governorates import GOVERNORATES, centroids, governorate_at
from app.models import Equipment, Farm, Plan, Role, User, WaterSource

router = APIRouter(tags=["plan-import"])
log = logging.getLogger(__name__)
ALLOWED = plan_parser.VECTOR_EXT | plan_parser.RASTER_EXT


class Corrections(BaseModel):
    governorate_code: str | None = None
    latitude: float | None = Field(None, ge=30.0, le=37.6)
    longitude: float | None = Field(None, ge=7.4, le=11.7)
    flow_m3h: float | None = Field(None, gt=0, le=2000)
    depth_m: float | None = Field(None, ge=0, le=500)
    water_m3_day: float | None = Field(None, gt=0)
    season: str | None = None
    confirm_area: bool = False
    edge_index: int | None = Field(None, ge=0)          # side whose real length is given
    edge_length_m: float | None = Field(None, gt=0, le=20000)


def _summary(parsed: dict) -> dict:
    """What the UI shows in the 'what we read on your plan' report (no raw texts)."""
    return {k: parsed.get(k) for k in ("method", "scale", "area", "edges", "perimeter_m", "vertex_labels",
                                       "water_points", "zones", "lines", "metadata", "north_detected",
                                       "warnings", "boundary_detection")}


def _location(parsed: dict, corr: Corrections) -> tuple[str | None, float | None, float | None, str]:
    meta = parsed.get("metadata") or {}
    gov = corr.governorate_code or (meta.get("governorate") or {}).get("code")
    if corr.latitude is not None and corr.longitude is not None:
        return gov or governorate_at(corr.latitude, corr.longitude), corr.latitude, corr.longitude, "user"
    if meta.get("gps"):
        g = meta["gps"]
        return gov or governorate_at(g["lat"], g["lon"]), g["lat"], g["lon"], "plan_gps"
    if gov:
        lat, lon = centroids()[gov]
        return gov, lat, lon, "governorate_centroid"
    return None, None, None, "missing"


def _apply_geometry(db: Session, farm: Farm, parsed: dict, lat: float, lon: float, quality: str,
                    corr: Corrections) -> None:
    geo = plan_parser.to_geo(parsed, lat, lon)
    farm.boundary_geojson = geo["boundary"]
    excl = [e["geometry"] for e in geo["exclusions"]]
    farm.exclusions_geojson = {"type": "GeometryCollection", "geometries": excl} if excl else None
    farm.latitude, farm.longitude = lat, lon
    area = parsed["area"]
    farm.measured_area_ha = round(area["measured_m2"] / 1e4, 4)
    farm.declared_area_ha = round((area["stated_m2"] or area["measured_m2"]) / 1e4, 4)
    scale_ok = parsed["scale"]["confidence"] >= 0.9 or parsed["scale"]["method"] == "printed_area"
    farm.area_validated = bool(corr.confirm_area or area["ok"] or (area["ok"] is None and scale_ok))
    pu = dict(farm.plan_upload or {})
    pu.update(kind="technical_plan", extraction=_summary(parsed), geo_exclusions=geo["exclusions"],
              geo_lines=geo["lines"], location={"lat": lat, "lon": lon, "quality": quality})
    farm.plan_upload = pu
    meta = parsed["metadata"]
    # water sources from the plan (replace previous plan-derived ones, keep farmer-entered ones)
    for s in list(farm.water_sources):
        if s.data_source == "plan":
            db.delete(s)
    wps = geo["water_points"]
    daily = corr.water_m3_day or meta.get("water_m3_day")
    flow = corr.flow_m3h or meta.get("flow_m3h")
    for w in wps:
        kind = {"borehole": "borehole", "well": "well", "network": "dam_network"}.get(w["kind"], "well")
        farm.water_sources.append(WaterSource(
            kind=kind, name=w["name"][:120], latitude=w["latitude"], longitude=w["longitude"],
            flow_m3h=flow, daily_volume_m3=(daily / len(wps)) if daily else None,
            pumping_depth_m=corr.depth_m if corr.depth_m is not None else (meta.get("depth_m") or 0.0),
            authorized=True, data_source="plan"))
    for e in list(farm.equipment):
        if (e.specs or {}).get("source") == "plan":
            db.delete(e)
    if meta.get("pump_kw"):
        farm.equipment.append(Equipment(kind="pump", specs={"power_kw": meta["pump_kw"], "source": "plan"}))
    if meta.get("solar_kwc"):
        farm.equipment.append(Equipment(kind="pv", specs={"kwp": meta["solar_kwc"], "source": "plan"}))
    if meta.get("battery_kwh"):
        farm.equipment.append(Equipment(kind="battery", specs={"kwh": meta["battery_kwh"], "source": "plan"}))
    for z in parsed["zones"]:
        if z["kind"] == "cold_storage":
            from shapely.geometry import Polygon
            farm.equipment.append(Equipment(kind="cold_room", specs={
                "floor_m2": round(Polygon(z["polygon_m"]).area, 1), "label": z["label"], "source": "plan"}))
    season = corr.season or meta.get("season")
    farm.season = season or "annual"
    soil = meta.get("soil")
    if soil:
        farm.soil = {**soil, "quality": "from_plan"}
    elif not (farm.soil or {}).get("sand_pct"):
        try:
            farm.soil = {**sources.fetch_soil(lat, lon), "location_quality": quality}
        except ConnectorError:
            farm.soil = {"source": "missing"}
    existing = [z for z in parsed["zones"] if z["kind"] == "orchard"]
    farm.existing_crops = [{"crop": "existing_orchard", "label": z["label"]} for z in existing]


def _plan_or_error(db: Session, farm: Farm) -> tuple[Plan | None, dict | None]:
    if not farm.area_validated:
        return None, {"code": "area_not_validated"}
    try:
        return agrobrain.generate_plan(db, farm), None
    except agrobrain.PlanningError as e:
        db.rollback()
        return None, {"code": e.code, **e.detail}
    except Exception:   # the terrain is imported even if the plan cannot be computed: never a 500 here
        log.exception("plan generation failed for farm %s", farm.id)
        db.rollback()
        return None, {"code": "plan_failed"}


@router.post("/api/farms/import", status_code=201)
async def import_plan(file: UploadFile = File(...), corrections: str = Form("{}"), page: int = Form(0),
                      user: User = Depends(current_user), db: Session = Depends(get_db)):
    if user.role != Role.farmer.value:
        raise HTTPException(403, "farmer_only")
    s = get_settings()
    data = await file.read(s.max_upload_mb * 1024 * 1024 + 1)
    if len(data) > s.max_upload_mb * 1024 * 1024:
        raise HTTPException(413, "file_too_large")
    name = file.filename or "plan"
    ext = Path(name).suffix.lower()
    if ext not in ALLOWED:
        raise HTTPException(415, "unsupported_format")
    try:
        corr = Corrections(**json.loads(corrections or "{}"))
    except (ValueError, TypeError):
        raise HTTPException(422, "invalid_corrections")
    if corr.governorate_code and corr.governorate_code not in GOVERNORATES:
        raise HTTPException(422, "unknown governorate")
    try:
        known = (corr.edge_index, corr.edge_length_m) if corr.edge_index is not None and corr.edge_length_m else None
        parsed = plan_parser.parse(data, name, page=page, known_edge=known)
    except ValueError as e:
        raise HTTPException(422, {"code": str(e)})
    if not parsed.get("ok") and any(w["code"] == "scale_not_found" for w in parsed.get("warnings", [])):
        # contour found but no scale: ask only for the real length of one side
        bu = parsed["boundary_units"]
        return Response(json.dumps({"status": "needs_input", "missing": ["edge_length"],
                                    "boundary_units": bu, "vertex_labels": parsed.get("vertex_labels") or [],
                                    "extraction": {"warnings": parsed["warnings"], "method": parsed["method"]}}),
                        status_code=200, media_type="application/json")
    if not parsed.get("ok"):
        raise HTTPException(422, {"code": "plan_not_understood", "extraction": parsed})
    gov, lat, lon, quality = _location(parsed, corr)
    if gov is None:
        # nothing invented: ask for the governorate (or a click on the map) and re-submit the same file
        return Response(json.dumps({"status": "needs_input", "missing": ["location"], "extraction": _summary(parsed)}),
                        status_code=200, media_type="application/json")
    stored = f"plan_{secrets.token_hex(8)}{ext}"
    (s.upload_dir / stored).write_bytes(data)
    farm = Farm(owner_id=user.id, name=f"Plan {GOVERNORATES[gov]['fr']} — {Path(name).stem[:40]}", governorate_code=gov,
                irrigation_method="drip", preferences={}, soil={}, plan_upload={"file": stored, "parsed": parsed})
    db.add(farm)
    db.flush()
    _apply_geometry(db, farm, parsed, lat, lon, quality, corr)
    db.commit()
    db.refresh(farm)
    plan, err = _plan_or_error(db, farm)
    audit(db, user, "plan.import", str(farm.id), {"file": stored, "method": parsed["method"]})
    db.refresh(farm)
    return {"status": "ok" if plan else "needs_input", "farm": farm_out(farm), "plan": plan_out(plan) if plan else None,
            "plan_error": err, "extraction": _summary(parsed), "location_quality": quality}


@router.post("/api/farms/{farm_id}/corrections")
def apply_corrections(farm_id: int, corr: Corrections, user: User = Depends(current_user),
                      db: Session = Depends(get_db)):
    farm = owned_farm(farm_id, db, user)
    if farm.owner_id != user.id:
        raise HTTPException(403, "owner_only")
    parsed = (farm.plan_upload or {}).get("parsed")
    if not parsed:
        raise HTTPException(400, "no_technical_plan")
    if corr.governorate_code:
        if corr.governorate_code not in GOVERNORATES:
            raise HTTPException(422, "unknown governorate")
        farm.governorate_code = corr.governorate_code
    loc = (farm.plan_upload or {}).get("location") or {}
    if corr.latitude is not None and corr.longitude is not None:
        lat, lon, quality = corr.latitude, corr.longitude, "user"
        g = governorate_at(lat, lon)
        if g:
            farm.governorate_code = g
    elif corr.governorate_code and loc.get("quality") == "governorate_centroid":
        lat, lon = centroids()[corr.governorate_code]
        quality = "governorate_centroid"
    else:
        lat, lon, quality = loc.get("lat", farm.latitude), loc.get("lon", farm.longitude), loc.get("quality", "user")
    _apply_geometry(db, farm, parsed, lat, lon, quality, corr)
    if corr.flow_m3h is not None:
        for w in farm.water_sources:
            w.flow_m3h = corr.flow_m3h
    db.commit()
    db.refresh(farm)
    plan, err = _plan_or_error(db, farm)
    audit(db, user, "plan.corrections", str(farm.id), corr.model_dump(exclude_none=True))
    db.refresh(farm)
    return {"farm": farm_out(farm), "plan": plan_out(plan) if plan else None, "plan_error": err,
            "extraction": (farm.plan_upload or {}).get("extraction"), "location_quality": quality}


def _names(lang: str) -> tuple[dict, dict]:
    colors = {c.code: c.color for c in CROPS.values()}
    names = {c.code: (c.name_ar if lang == "ar" else c.name_fr) for c in CROPS.values()}
    return colors, names


def _plan(farm_id: int, plan_id: int, db: Session, user: User) -> tuple[Farm, Plan]:
    farm = owned_farm(farm_id, db, user)
    plan = db.get(Plan, plan_id)
    if not plan or plan.farm_id != farm.id:
        raise HTTPException(404, "no_plan")
    return farm, plan


@router.get("/api/farms/{farm_id}/plans/{plan_id}/scene")
def get_scene(farm_id: int, plan_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    farm, plan = _plan(farm_id, plan_id, db, user)
    return scene_eng.build_scene(farm, plan)


@router.get("/api/farms/{farm_id}/plans/{plan_id}/export.{fmt}")
def export(farm_id: int, plan_id: int, fmt: str, lang: str = "fr", user: User = Depends(current_user),
           db: Session = Depends(get_db)):
    farm, plan = _plan(farm_id, plan_id, db, user)
    sc = scene_eng.build_scene(farm, plan)
    colors, names = _names(lang)
    svg = scene_eng.to_svg(sc, colors, names, f"{farm.name} — plan {plan.version}")
    if fmt == "svg":
        return Response(svg, media_type="image/svg+xml",
                        headers={"Content-Disposition": f"attachment; filename=plan_{plan.id}.svg"})
    if fmt == "pdf":
        return Response(scene_eng.svg_to_pdf(svg), media_type="application/pdf",
                        headers={"Content-Disposition": f"attachment; filename=plan_{plan.id}.pdf"})
    if fmt == "json":
        return Response(json.dumps(sc, ensure_ascii=False), media_type="application/json",
                        headers={"Content-Disposition": f"attachment; filename=plan_{plan.id}.agrosphere.json"})
    raise HTTPException(404, "unknown_format")


class RenderIn(BaseModel):
    scene: dict
    format: str = "svg"
    lang: str = "fr"


@router.post("/api/scenes/render")
def render_scene(body: RenderIn, user: User = Depends(current_user)):
    """Re-open a saved .agrosphere.json scene and render it (proves export -> re-open round trip)."""
    try:
        sc = scene_eng.validate(body.scene)
    except ValueError as e:
        raise HTTPException(422, str(e))
    colors, names = _names(body.lang)
    svg = scene_eng.to_svg(sc, colors, names, sc.get("meta", {}).get("farm", ""))
    if body.format == "pdf":
        return Response(scene_eng.svg_to_pdf(svg), media_type="application/pdf")
    return Response(svg, media_type="image/svg+xml")


@router.get("/api/farms/{farm_id}/scene")
def get_terrain_scene(farm_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Scene of the terrain alone (model input panel): contour, sides, zones, sources, entrance."""
    farm = owned_farm(farm_id, db, user)
    if not farm.boundary_geojson:
        raise HTTPException(404, "no_boundary")
    return scene_eng.build_scene(farm)
