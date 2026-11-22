"""Farmer inputs of the 2D planning module, automatic climate and result tables.

GET  /api/farms/{id}/inputs           what is known, where it comes from, and what is missing
PUT  /api/farms/{id}/inputs           terrain (location, side length, entrance), water sources, energy,
                                      equipment -> stored, then AgroBrain recomputes the whole plan
GET  /api/farms/{id}/climate          automatic climate profile (normals / statistics / recent / forecast / soil)
GET  /api/farms/{id}/plans/{pid}/report   tables A-E shown under the plan

The farmer never types weather, ET0, crop water needs, crops or areas: they are computed.
Unknown technical values stay empty and are reported as missing.
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import audit, current_user, owned_farm
from app.api.farms import farm_out, plan_out
from app.connectors import climate as climate_conn
from app.connectors import sources
from app.connectors.base import ConnectorError
from app.cv import plan_parser
from app.db.session import get_db
from app.engines import agrobrain, report as report_eng
from app.engines.scene import local_to_lonlat
from app.knowledge.governorates import GOVERNORATES, governorate_at
from app.models import Equipment, Farm, Plan, User, WaterSource

router = APIRouter(prefix="/api/farms", tags=["inputs"])

PRESSURE_FRICTION_M = 20.0   # drip emitter pressure (~10 m) + pipe/filter losses (~10 m): order of magnitude
PUMP_EFF = 0.5               # wire-to-water efficiency of small submersible pumps (same value as AgroBrain)
OVERSIZE_RATIO = 3.0         # flag a declared power more than 3x the hydraulic need (probable unit/typing error)

SourceKind = Literal["borehole", "well", "reservoir", "dam_network", "canal"]


class SourceIn(BaseModel):
    kind: SourceKind = "borehole"
    name: str | None = Field(None, max_length=120)
    x_m: float | None = None             # position in the plan (local metres)
    y_m: float | None = None
    latitude: float | None = Field(None, ge=30.0, le=37.6)
    longitude: float | None = Field(None, ge=7.4, le=11.7)
    flow_m3h: float | None = Field(None, gt=0, le=2000)
    depth_m: float | None = Field(None, ge=0, le=500)
    daily_volume_m3: float | None = Field(None, gt=0)
    annual_quota_m3: float | None = Field(None, gt=0)
    max_hours_per_day: float | None = Field(None, gt=0, le=24)
    salinity_ds_m: float | None = Field(None, ge=0, le=30)
    authorized: bool = True
    pump_kw: float | None = Field(None, gt=0, le=500)


class ColdRoomIn(BaseModel):
    volume_m3: float | None = Field(None, gt=0)
    floor_m2: float | None = Field(None, gt=0)
    label: str | None = None


class Point(BaseModel):
    x_m: float | None = None
    y_m: float | None = None
    latitude: float | None = None
    longitude: float | None = None


class InputsIn(BaseModel):
    name: str | None = Field(None, max_length=160)
    governorate_code: str | None = None
    delegation: str | None = Field(None, max_length=80)
    latitude: float | None = Field(None, ge=30.0, le=37.6)
    longitude: float | None = Field(None, ge=7.4, le=11.7)
    edge_index: int | None = Field(None, ge=0)
    edge_length_m: float | None = Field(None, gt=0, le=20000)
    confirm_area: bool = False
    entrance: Point | None = None
    sources: list[SourceIn] | None = None
    grid: Literal["yes", "no", "unknown"] | None = None
    grid_tariff_tnd_kwh: float | None = Field(None, gt=0, le=10)
    pv_kwc: float | None = Field(None, ge=0, le=10000)
    battery_kwh: float | None = Field(None, ge=0, le=100000)
    irrigation_method: Literal["drip", "sprinkler", "surface"] | None = None
    cold_rooms: list[ColdRoomIn] | None = None
    generate: bool = True


def _pt(farm: Farm, p) -> tuple[float, float] | None:
    """(lat, lon) of a point given in local plan metres or in WGS84."""
    if p.latitude is not None and p.longitude is not None:
        return p.latitude, p.longitude
    if p.x_m is not None and p.y_m is not None and farm.boundary_geojson:
        lon, lat = local_to_lonlat(farm, p.x_m, p.y_m)
        return lat, lon
    return None


def inputs_out(farm: Farm) -> dict:
    pu = farm.plan_upload or {}
    loc = pu.get("location") or {"quality": "user" if farm.latitude is not None else "missing"}
    prefs = farm.preferences or {}
    grid = next((e.specs for e in farm.equipment if e.kind == "grid"), None)
    missing = []
    if loc.get("quality") in ("governorate_centroid", "missing"):
        missing.append("gps")
    if not farm.boundary_geojson:
        missing.append("boundary")
    elif not farm.area_validated:
        missing.append("scale_or_side_length")
    if not farm.water_sources:
        missing.append("water_source")
    for i, s in enumerate(farm.water_sources):
        code = f"F{i + 1}"
        if s.flow_m3h is None and s.daily_volume_m3 is None:
            missing.append(f"flow:{code}")
        elif s.flow_m3h is None:
            missing.append(f"flow_for_schedule:{code}")
        if not s.pumping_depth_m and s.kind in ("borehole", "well"):
            missing.append(f"depth:{code}")
        if s.kind in ("borehole", "well") and not any(
                e.kind == "pump" and e.specs.get("source_id") == s.id for e in farm.equipment):
            missing.append(f"pump:{code}")
    if grid is None:
        missing.append("grid")
    if prefs.get("grid_tariff_tnd_kwh") is None:
        missing.append("grid_tariff")
    pumps = {e.specs.get("source_id"): e.specs.get("power_kw") for e in farm.equipment if e.kind == "pump"}
    # consistency: declared pump power vs the power needed to lift the declared flow (order of magnitude)
    warnings = []
    for i, w in enumerate(farm.water_sources):
        kw = pumps.get(w.id)
        if kw and w.flow_m3h:
            head = (w.pumping_depth_m or 0) + PRESSURE_FRICTION_M
            need = 9.81 * (w.flow_m3h / 3600) * head / PUMP_EFF
            if kw > OVERSIZE_RATIO * max(need, 0.37):
                warnings.append({"code": "pump_oversized", "source": f"F{i + 1}", "declared_kw": kw,
                                 "needed_kw": round(need, 1), "flow_m3h": w.flow_m3h, "head_m": round(head)})
    return {
        "terrain": {"name": farm.name, "governorate_code": farm.governorate_code, "delegation": farm.delegation,
                    "latitude": farm.latitude, "longitude": farm.longitude, "location_quality": loc.get("quality"),
                    "area_ha": farm.measured_area_ha, "declared_area_ha": farm.declared_area_ha,
                    "area_validated": farm.area_validated, "has_plan_file": bool(pu.get("parsed")),
                    "edges": (pu.get("extraction") or {}).get("edges"),
                    "entrance": prefs.get("entrance")},
        "water": [{"id": s.id, "code": f"F{i + 1}", "kind": s.kind, "name": s.name, "latitude": s.latitude,
                   "longitude": s.longitude, "flow_m3h": s.flow_m3h, "depth_m": s.pumping_depth_m or None,
                   "daily_volume_m3": s.daily_volume_m3, "annual_quota_m3": s.annual_quota_m3,
                   "max_hours_per_day": s.max_hours_per_day, "salinity_ds_m": s.salinity_ds_m,
                   "authorized": s.authorized, "pump_kw": pumps.get(s.id), "data_source": s.data_source}
                  for i, s in enumerate(farm.water_sources)],
        "energy": {"grid": "unknown" if grid is None else ("yes" if grid.get("available") else "no"),
                   "grid_tariff_tnd_kwh": prefs.get("grid_tariff_tnd_kwh"),
                   "pv_kwc": sum(float(e.specs.get("kwp", 0)) for e in farm.equipment if e.kind == "pv") or None,
                   "battery_kwh": sum(float(e.specs.get("kwh", 0)) for e in farm.equipment
                                      if e.kind == "battery") or None,
                   "irrigation_method": farm.irrigation_method,
                   "cold_rooms": [{"volume_m3": e.specs.get("volume_m3"), "floor_m2": e.specs.get("floor_m2"),
                                   "label": e.specs.get("label")} for e in farm.equipment if e.kind == "cold_room"]},
        "missing": missing, "warnings": warnings,
    }


def _replace_equipment(farm: Farm, db: Session, kind: str, specs_list: list[dict]) -> None:
    for e in list(farm.equipment):
        if e.kind == kind:
            farm.equipment.remove(e)
    for sp in specs_list:
        farm.equipment.append(Equipment(kind=kind, specs=sp))


@router.get("/{farm_id}/inputs")
def get_inputs(farm_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return inputs_out(owned_farm(farm_id, db, user))


@router.put("/{farm_id}/inputs")
def put_inputs(farm_id: int, body: InputsIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    from app.api.plan_import import Corrections, _apply_geometry
    farm = owned_farm(farm_id, db, user)
    if farm.owner_id != user.id:
        raise HTTPException(403, "owner_only")
    if body.governorate_code and body.governorate_code not in GOVERNORATES:
        raise HTTPException(422, "unknown governorate")
    if body.name:
        farm.name = body.name
    if body.delegation is not None:
        farm.delegation = body.delegation.strip() or None
    pu = dict(farm.plan_upload or {})
    parsed = pu.get("parsed")

    # --- terrain: scale from one side length, location ------------------------
    rescaled = False
    if body.edge_index is not None and body.edge_length_m:
        if not parsed:
            raise HTTPException(400, "side_length_needs_plan_file")
        edges = parsed.get("edges") or []
        if body.edge_index >= len(edges) or edges[body.edge_index]["length_m"] <= 0:
            raise HTTPException(422, "unknown_edge")
        f = body.edge_length_m / edges[body.edge_index]["length_m"]
        parsed = plan_parser.rescale(parsed, f)
        pu["parsed"] = parsed
        farm.plan_upload = pu
        rescaled = True
    loc = pu.get("location") or {}
    lat, lon, quality = loc.get("lat", farm.latitude), loc.get("lon", farm.longitude), loc.get("quality", "user")
    moved = False
    if body.latitude is not None and body.longitude is not None:
        lat, lon, quality, moved = body.latitude, body.longitude, "user", True
        g = governorate_at(lat, lon)
        if g:
            farm.governorate_code = g
    if body.governorate_code:
        farm.governorate_code = body.governorate_code
    if parsed and (rescaled or moved):
        _apply_geometry(db, farm, parsed, lat, lon, quality, Corrections(confirm_area=body.confirm_area or rescaled))
        if rescaled:
            farm.area_validated = True
    elif moved:
        farm.latitude, farm.longitude = lat, lon
    if body.confirm_area and farm.boundary_geojson:
        farm.area_validated = True
    db.flush()

    # --- entrance --------------------------------------------------------------
    prefs = dict(farm.preferences or {})
    if body.entrance is not None:
        ll = _pt(farm, body.entrance)
        prefs["entrance"] = {"lat": ll[0], "lon": ll[1]} if ll else None

    # --- water sources and their pumps ------------------------------------------
    if body.sources is not None:
        for s in list(farm.water_sources):
            farm.water_sources.remove(s)
        for e in list(farm.equipment):
            if e.kind == "pump":
                farm.equipment.remove(e)
        db.flush()
        for i, si in enumerate(body.sources):
            ll = _pt(farm, si)
            if ll is None:
                raise HTTPException(422, {"code": "source_position_missing", "index": i})
            ws = WaterSource(kind=si.kind, name=(si.name or f"F{i + 1}")[:120], latitude=ll[0], longitude=ll[1],
                             flow_m3h=si.flow_m3h, daily_volume_m3=si.daily_volume_m3,
                             annual_quota_m3=si.annual_quota_m3, pumping_depth_m=si.depth_m or 0.0,
                             max_hours_per_day=si.max_hours_per_day or 12.0, salinity_ds_m=si.salinity_ds_m,
                             authorized=si.authorized, data_source="farmer")
            farm.water_sources.append(ws)
            db.flush()
            if si.pump_kw:
                farm.equipment.append(Equipment(kind="pump", specs={"power_kw": si.pump_kw, "source_id": ws.id,
                                                                    "source": "farmer"}))

    # --- energy and equipment -----------------------------------------------------
    if body.grid is not None:
        _replace_equipment(farm, db, "grid", [] if body.grid == "unknown" else
                           [{"available": body.grid == "yes", "source": "farmer"}])
    if "grid_tariff_tnd_kwh" in body.model_fields_set:
        prefs["grid_tariff_tnd_kwh"] = body.grid_tariff_tnd_kwh
    if "pv_kwc" in body.model_fields_set:
        _replace_equipment(farm, db, "pv", [{"kwp": body.pv_kwc, "source": "farmer"}] if body.pv_kwc else [])
    if "battery_kwh" in body.model_fields_set:
        _replace_equipment(farm, db, "battery", [{"kwh": body.battery_kwh, "source": "farmer"}]
                           if body.battery_kwh else [])
    if body.irrigation_method:
        farm.irrigation_method = body.irrigation_method
    if body.cold_rooms is not None:
        _replace_equipment(farm, db, "cold_room", [{**c.model_dump(exclude_none=True), "source": "farmer"}
                                                   for c in body.cold_rooms])
    farm.preferences = prefs
    if farm.latitude is not None and not (farm.soil or {}).get("sand_pct") and not (farm.soil or {}).get("texture"):
        try:
            farm.soil = {**sources.fetch_soil(farm.latitude, farm.longitude), "location_quality": quality}
        except ConnectorError:
            pass
    db.commit()
    db.refresh(farm)
    audit(db, user, "farm.inputs", str(farm.id), body.model_dump(exclude_none=True, exclude={"sources"}))

    plan, err = None, None
    if body.generate:
        if not farm.area_validated:
            err = {"code": "area_not_validated"}
        else:
            try:
                plan = agrobrain.generate_plan(db, farm)
            except agrobrain.PlanningError as e:
                db.rollback()
                err = {"code": e.code, **e.detail}
        db.refresh(farm)
    return {"farm": farm_out(farm), "inputs": inputs_out(farm), "plan": plan_out(plan) if plan else None,
            "plan_error": err}


@router.get("/{farm_id}/climate")
def get_climate(farm_id: int, refresh: bool = False, user: User = Depends(current_user),
                db: Session = Depends(get_db)):
    farm = owned_farm(farm_id, db, user)
    lat, lon = agrobrain._centroid(farm)
    q = ((farm.plan_upload or {}).get("location") or {}).get("quality", "user")
    prof = climate_conn.climate_profile(db, lat, lon, refresh=refresh, soil=farm.soil or None)
    prof["location"]["quality"] = q
    return prof


@router.get("/{farm_id}/plans/{plan_id}/report")
def get_report(farm_id: int, plan_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    farm = owned_farm(farm_id, db, user)
    plan = db.get(Plan, plan_id)
    if plan is None or plan.farm_id != farm.id:
        raise HTTPException(404, "plan_not_found")
    return report_eng.build(farm, plan, (farm.preferences or {}).get("grid_tariff_tnd_kwh"))


class FromMapIn(BaseModel):
    boundary: dict
    name: str | None = Field(None, max_length=160)


@router.post("/from-map", status_code=201)
def create_from_map(body: FromMapIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Create a farm from an outline drawn on the satellite map. Location, governorate and area are
    computed from the geometry itself (true scale): the farmer types neither surface nor place."""
    from shapely.geometry import mapping, shape
    from app.cv import plan_reader
    from app.models import Role
    if user.role != Role.farmer.value:
        raise HTTPException(403, "farmer_only")
    try:
        g = shape(body.boundary)
    except Exception:
        raise HTTPException(422, "invalid_geojson")
    if g.geom_type != "Polygon" or not g.is_valid or g.is_empty:
        raise HTTPException(422, "invalid_polygon")
    c = g.representative_point()
    gov = governorate_at(c.y, c.x)
    if gov is None:
        raise HTTPException(422, "outside_tunisia")
    area_ha = plan_reader.area_check(mapping(g), None)["measured_ha"]
    if area_ha < 0.01:
        raise HTTPException(422, "boundary_too_small")
    lat, lon = round(c.y, 6), round(c.x, 6)
    farm = Farm(owner_id=user.id, name=(body.name or "").strip() or f"{GOVERNORATES[gov]['fr']} — {area_ha:.2f} ha",
                governorate_code=gov, latitude=lat, longitude=lon, boundary_geojson=mapping(g),
                measured_area_ha=round(area_ha, 4), declared_area_ha=round(area_ha, 4), area_validated=True,
                irrigation_method="drip", season="annual", soil={}, preferences={},
                plan_upload={"kind": "map", "location": {"lat": lat, "lon": lon, "quality": "user"}})
    db.add(farm)
    db.commit()
    db.refresh(farm)
    audit(db, user, "farm.from_map", str(farm.id), {"area_ha": area_ha, "governorate": gov})
    return {"farm": farm_out(farm), "inputs": inputs_out(farm)}
