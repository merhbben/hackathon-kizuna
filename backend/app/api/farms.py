"""Farmer endpoints: terrain, 2D plan import, resources, AgroBrain plan, re-planning."""
from __future__ import annotations

import secrets
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import audit, current_user, owned_farm
from app.connectors import sources
from app.connectors.base import ConnectorError
from app.core.config import get_settings
from app.cv import plan_reader, segmentation
from app.db.session import get_db
from app.engines import agrobrain, partition
from app.knowledge.governorates import governorate_at
from app.models import Equipment, Farm, Parcel, Plan, Role, User, WaterSource
from app.schemas import BoundaryIn, EquipmentIn, FarmIn, FarmPatch, GeorefIn, ReplanIn, WaterSourceIn

router = APIRouter(prefix="/api/farms", tags=["farms"])


def farm_out(f: Farm) -> dict:
    return {
        "id": f.id, "name": f.name, "governorate_code": f.governorate_code, "delegation": f.delegation,
        "latitude": f.latitude, "longitude": f.longitude, "declared_area_ha": f.declared_area_ha,
        "measured_area_ha": f.measured_area_ha, "area_validated": f.area_validated,
        "boundary": f.boundary_geojson, "exclusions": f.exclusions_geojson, "soil": f.soil,
        "budget_tnd": f.budget_tnd, "season": f.season, "existing_crops": f.existing_crops,
        "irrigation_method": f.irrigation_method, "preferences": f.preferences, "plan_upload": f.plan_upload,
        "water_sources": [{c: getattr(s, c) for c in ("id", "kind", "name", "latitude", "longitude", "flow_m3h",
                                                      "max_hours_per_day", "annual_quota_m3", "pumping_depth_m",
                                                      "elevation_m", "salinity_ds_m", "authorized")}
                          for s in f.water_sources],
        "equipment": [{"id": e.id, "kind": e.kind, "specs": e.specs} for e in f.equipment],
        "plans": [{"id": p.id, "version": p.version, "status": p.status, "created_at": p.created_at.isoformat()}
                  for p in f.plans],
    }


def plan_out(p: Plan) -> dict:
    return {"id": p.id, "farm_id": p.farm_id, "version": p.version, "status": p.status,
            "created_at": p.created_at.isoformat(), "summary": p.summary, "irrigation": p.irrigation,
            "energy": p.energy, "storage": p.storage, "contribution": p.contribution,
            "infrastructure": p.infrastructure_geojson, "inputs": p.inputs,
            "parcels": [{"id": x.id, "label": x.label, "crop": x.crop_code, "area_m2": x.area_m2,
                         "locked": x.locked, "water_source_id": x.water_source_id, "geometry": x.geometry_geojson,
                         "metrics": x.metrics} for x in p.parcels]}


@router.get("")
def list_farms(user: User = Depends(current_user), db: Session = Depends(get_db)):
    q = select(Farm) if user.role == Role.ministry.value else select(Farm).filter_by(owner_id=user.id)
    return [farm_out(f) for f in db.scalars(q.order_by(Farm.id))]


@router.post("", status_code=201)
def create_farm(body: FarmIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if user.role != Role.farmer.value:
        raise HTTPException(403, "farmer_only")
    f = Farm(owner_id=user.id, **body.model_dump(exclude={"soil"}), soil=body.soil.model_dump(exclude_none=True))
    db.add(f)
    db.commit()
    audit(db, user, "farm.create", str(f.id))
    return farm_out(f)


@router.get("/{farm_id}")
def get_farm(farm_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return farm_out(owned_farm(farm_id, db, user))


def _farmer_farm(farm_id, db, user) -> Farm:
    f = owned_farm(farm_id, db, user)
    if f.owner_id != user.id:
        raise HTTPException(403, "owner_only")
    return f


@router.patch("/{farm_id}")
def patch_farm(farm_id: int, body: FarmPatch, user: User = Depends(current_user), db: Session = Depends(get_db)):
    f = _farmer_farm(farm_id, db, user)
    data = body.model_dump(exclude_unset=True)
    if "soil" in data and data["soil"] is not None:
        f.soil = {**(f.soil or {}), **{k: v for k, v in data.pop("soil").items() if v is not None}}
    for k, v in data.items():
        setattr(f, k, v)
    if "declared_area_ha" in data:
        f.area_validated = False
    db.commit()
    return farm_out(f)


@router.delete("/{farm_id}", status_code=204)
def delete_farm(farm_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    f = _farmer_farm(farm_id, db, user)
    db.delete(f)
    db.commit()


@router.put("/{farm_id}/boundary")
def set_boundary(farm_id: int, body: BoundaryIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Boundary drawn on the map or corrected after plan recognition. Area must be confirmed before planning."""
    f = _farmer_farm(farm_id, db, user)
    from shapely.geometry import shape
    from shapely.validation import explain_validity
    try:
        g = shape(body.boundary)
    except Exception:
        raise HTTPException(422, "invalid_geojson")
    if g.geom_type not in ("Polygon", "MultiPolygon") or not g.is_valid:
        raise HTTPException(422, f"invalid_polygon: {explain_validity(g) if g.geom_type else ''}")
    check = plan_reader.area_check(body.boundary, f.declared_area_ha)
    f.boundary_geojson = body.boundary
    f.exclusions_geojson = body.exclusions
    f.measured_area_ha = check["measured_ha"]
    c = g.representative_point()
    f.latitude, f.longitude = round(c.y, 6), round(c.x, 6)
    gov = governorate_at(c.y, c.x)
    check["governorate_detected"] = gov
    check["governorate_matches"] = gov is None or gov == f.governorate_code
    if not check["governorate_matches"]:
        f.area_validated = False
    elif body.confirm_area:
        if not check["ok"]:
            # the farmer explicitly confirms the drawn/placed outline: measured area becomes the reference
            audit(db, user, "farm.area_override", str(f.id), {"declared": f.declared_area_ha, "measured": check["measured_ha"]})
            f.declared_area_ha = round(check["measured_ha"], 4)
            check["declared_updated"] = True
        f.area_validated = True
        # fill missing soil data automatically (SoilGrids estimate) so the farmer has less to type
        soil = f.soil or {}
        if soil.get("sand_pct") is None and soil.get("clay_pct") is None:
            try:
                auto = sources.fetch_soil(f.latitude, f.longitude)
                f.soil = {**auto, **{k: v for k, v in soil.items() if k in ("ece_ds_m", "slope_pct", "texture") and v}}
                check["soil_autofilled"] = True
            except ConnectorError:
                check["soil_autofilled"] = False
    else:
        f.area_validated = False
    db.commit()
    return {"farm": farm_out(f), "area_check": check}


@router.post("/{farm_id}/plan-upload")
async def upload_plan(farm_id: int, file: UploadFile = File(...), user: User = Depends(current_user),
                      db: Session = Depends(get_db)):
    f = _farmer_farm(farm_id, db, user)
    s = get_settings()
    data = await file.read(s.max_upload_mb * 1024 * 1024 + 1)
    if len(data) > s.max_upload_mb * 1024 * 1024:
        raise HTTPException(413, "file_too_large")
    name = file.filename or "plan"
    ext = Path(name).suffix.lower()
    if ext not in plan_reader.GEO_EXT | plan_reader.IMG_EXT | {".pdf"}:
        raise HTTPException(415, "unsupported_format")
    stored = f"{farm_id}_{secrets.token_hex(8)}{ext}"
    (s.upload_dir / stored).write_bytes(data)
    try:
        if ext in plan_reader.GEO_EXT:
            res = plan_reader.read_geofile(data, name)
            check = plan_reader.area_check(res["boundary"], f.declared_area_ha)
            f.plan_upload = {"file": stored, "kind": "geo", **res, "area_check": check}
        else:
            img = plan_reader.load_raster(data, name)
            det = plan_reader.detect(img)
            seg = segmentation.status()
            f.plan_upload = {"file": stored, "kind": "raster", "detection": det, "georeferenced": False,
                             "segmentation_model": seg}
    except plan_reader.PlanError as e:
        raise HTTPException(422, str(e))
    db.commit()
    audit(db, user, "plan.upload", str(farm_id), {"file": stored})
    return f.plan_upload


@router.get("/{farm_id}/plan-upload/image")
def plan_image(farm_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    from fastapi.responses import FileResponse
    f = owned_farm(farm_id, db, user)
    if not f.plan_upload or f.plan_upload.get("kind") != "raster":
        raise HTTPException(404, "no_raster_plan")
    path = get_settings().upload_dir / f.plan_upload["file"]
    import cv2
    from fastapi.responses import Response
    img = plan_reader.load_raster(path.read_bytes(), path.name)   # same scaling as detection
    ok, buf = cv2.imencode(".png", img)
    return Response(buf.tobytes(), media_type="image/png")


@router.post("/{farm_id}/georeference")
def georeference(farm_id: int, body: GeorefIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Turn the (corrected) pixel outline into a geographic polygon using control points or scale + anchor."""
    f = _farmer_farm(farm_id, db, user)
    if not f.plan_upload or f.plan_upload.get("kind") != "raster":
        raise HTTPException(400, "no_raster_plan")
    det = f.plan_upload["detection"]
    outline = body.boundary_px or det["boundary_px"]
    try:
        if body.control_points:
            M = plan_reader.fit_transform(body.control_points)
            resid = plan_reader.residuals_m(M, body.control_points)
        elif body.area_ha and body.anchor_lat is not None and body.anchor_lon is not None:
            # Simple mode: the farmer gives the real area and clicks the centre of the farm on the map.
            # Scale = sqrt(real area / outline area in px); anchor = centroid of the outline; north-up unless rotated.
            from shapely.geometry import Polygon as _P
            poly_px = _P(outline)
            if not poly_px.is_valid or poly_px.area <= 0:
                raise HTTPException(422, "invalid_outline")
            mpp = (body.area_ha * 10000 / poly_px.area) ** 0.5
            c = poly_px.centroid
            M = plan_reader.transform_from_scale(mpp, [c.x, c.y], body.anchor_lat, body.anchor_lon, body.rotation_deg)
            resid = []
        elif body.meters_per_px and body.anchor_px and body.anchor_lat is not None:
            M = plan_reader.transform_from_scale(body.meters_per_px, body.anchor_px, body.anchor_lat,
                                                 body.anchor_lon, body.rotation_deg)
            resid = []
        else:
            raise HTTPException(422, "need_control_points_or_scale")
    except plan_reader.PlanError as e:
        raise HTTPException(422, str(e))
    boundary = plan_reader.pixels_to_geojson(M, outline)
    check = plan_reader.area_check(boundary, f.declared_area_ha)
    excl = []
    for feat in det.get("features", []):
        if feat["type"] in ("building", "water") and "polygon" in feat and len(feat["polygon"]) >= 3:
            excl.append(plan_reader.pixels_to_geojson(M, feat["polygon"]))
    wells = []
    for w in (body.water_points_px or [{"px": x["point"], "kind": "well"} for x in det.get("features", [])
                                        if x["type"] == "well"]):
        lon, lat = plan_reader.point_px_to_lonlat(M, w["px"])
        wells.append({"kind": w.get("kind", "well"), "latitude": round(lat, 7), "longitude": round(lon, 7)})
    f.plan_upload = {**f.plan_upload, "georeferenced": True, "matrix": M.tolist(), "residuals_m": resid,
                     "boundary_px": outline, "boundary": boundary, "exclusions": excl, "wells": wells,
                     "area_check": check}
    db.commit()
    return f.plan_upload


@router.post("/{farm_id}/soil/autofill")
def soil_autofill(farm_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    f = _farmer_farm(farm_id, db, user)
    if f.latitude is None:
        raise HTTPException(400, "location_required")
    try:
        soil = sources.fetch_soil(f.latitude, f.longitude)
    except ConnectorError as e:
        raise HTTPException(502, f"soilgrids_unavailable: {e}")
    keep = {k: v for k, v in (f.soil or {}).items() if k in ("ece_ds_m", "slope_pct")}
    f.soil = {**soil, **keep}
    db.commit()
    return f.soil


@router.post("/{farm_id}/water-sources", status_code=201)
def add_source(farm_id: int, body: WaterSourceIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    f = _farmer_farm(farm_id, db, user)
    db.add(WaterSource(farm_id=f.id, **body.model_dump()))
    db.commit()
    db.refresh(f)
    return farm_out(f)


@router.delete("/{farm_id}/water-sources/{sid}", status_code=204)
def del_source(farm_id: int, sid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    f = _farmer_farm(farm_id, db, user)
    s = db.get(WaterSource, sid)
    if not s or s.farm_id != f.id:
        raise HTTPException(404, "not_found")
    db.delete(s)
    db.commit()


@router.post("/{farm_id}/equipment", status_code=201)
def add_equipment(farm_id: int, body: EquipmentIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    f = _farmer_farm(farm_id, db, user)
    db.add(Equipment(farm_id=f.id, kind=body.kind, specs=body.specs))
    db.commit()
    db.refresh(f)
    return farm_out(f)


@router.delete("/{farm_id}/equipment/{eid}", status_code=204)
def del_equipment(farm_id: int, eid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    f = _farmer_farm(farm_id, db, user)
    e = db.get(Equipment, eid)
    if not e or e.farm_id != f.id:
        raise HTTPException(404, "not_found")
    db.delete(e)
    db.commit()


def _run(db, f, locked=None):
    try:
        return agrobrain.generate_plan(db, f, locked)
    except agrobrain.PlanningError as e:
        db.rollback()
        raise HTTPException(422, {"code": e.code, **e.detail})


@router.post("/{farm_id}/plans", status_code=201)
def make_plan(farm_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    f = _farmer_farm(farm_id, db, user)
    plan = _run(db, f)
    audit(db, user, "plan.generate", str(plan.id))
    return plan_out(plan)


@router.get("/{farm_id}/plans/latest")
def latest_plan(farm_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    f = owned_farm(farm_id, db, user)
    if not f.plans:
        raise HTTPException(404, "no_plan")
    return plan_out(f.plans[-1])


@router.get("/{farm_id}/plans/{plan_id}")
def get_plan(farm_id: int, plan_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    f = owned_farm(farm_id, db, user)
    p = db.get(Plan, plan_id)
    if not p or p.farm_id != f.id:
        raise HTTPException(404, "no_plan")
    return plan_out(p)


@router.post("/{farm_id}/plans/{plan_id}/replan", status_code=201)
def replan(farm_id: int, plan_id: int, body: ReplanIn, user: User = Depends(current_user),
           db: Session = Depends(get_db)):
    """Farmer edits parcels (crop and/or geometry): edited parcels are locked, AgroBrain re-optimises the rest."""
    f = _farmer_farm(farm_id, db, user)
    p = db.get(Plan, plan_id)
    if not p or p.farm_id != f.id:
        raise HTTPException(404, "no_plan")
    by_id = {x.id: x for x in p.parcels}
    locked = []
    if body.keep_locked:
        locked += [{"crop": x.crop_code, "geometry": x.geometry_geojson} for x in p.parcels
                   if x.locked and x.id not in {e.parcel_id for e in body.edits}]
    for e in body.edits:
        x = by_id.get(e.parcel_id)
        if not x:
            raise HTTPException(404, f"parcel {e.parcel_id}")
        geom = e.geometry or x.geometry_geojson
        from shapely.geometry import shape
        if not shape(geom).is_valid:
            raise HTTPException(422, "invalid_parcel_geometry")
        locked.append({"crop": e.crop_code or x.crop_code, "geometry": geom})
    plan = _run(db, f, locked)
    audit(db, user, "plan.replan", str(plan.id), {"edits": len(body.edits)})
    return plan_out(plan)


@router.post("/{farm_id}/plans/{plan_id}/accept")
def accept_plan(farm_id: int, plan_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    f = _farmer_farm(farm_id, db, user)
    p = db.get(Plan, plan_id)
    if not p or p.farm_id != f.id:
        raise HTTPException(404, "no_plan")
    for other in f.plans:
        if other.status == "accepted":
            other.status = "proposed"
    p.status = "accepted"
    db.commit()
    return {"ok": True}


@router.get("/{farm_id}/plans/{plan_id}/geojson")
def plan_geojson(farm_id: int, plan_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    f = owned_farm(farm_id, db, user)
    p = db.get(Plan, plan_id)
    if not p or p.farm_id != f.id:
        raise HTTPException(404, "no_plan")
    feats = [{"type": "Feature", "geometry": x.geometry_geojson,
              "properties": {"label": x.label, "crop": x.crop_code, "area_m2": x.area_m2, **{
                  k: v for k, v in x.metrics.items() if isinstance(v, (int, float, str))}}} for x in p.parcels]
    if p.infrastructure_geojson:
        feats.append({"type": "Feature", "geometry": p.infrastructure_geojson, "properties": {"label": "infra"}})
    return {"type": "FeatureCollection", "features": feats}


@router.get("/{farm_id}/satellite")
def satellite(farm_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    f = owned_farm(farm_id, db, user)
    if not f.boundary_geojson:
        raise HTTPException(400, "no_boundary")
    try:
        scenes = sources.search_sentinel2(sources.bbox_of(f.boundary_geojson))
    except ConnectorError as e:
        raise HTTPException(502, str(e))
    return {"scenes": scenes, "status": "scene_discovery", "ndvi": "requires_cog_reader (rasterio) — not installed"}


@router.get("/{farm_id}/parcels/{parcel_id}/area")
def parcel_area(farm_id: int, parcel_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    f = owned_farm(farm_id, db, user)
    x = db.get(Parcel, parcel_id)
    if not x or x.plan.farm_id != f.id:
        raise HTTPException(404, "not_found")
    return {"area_m2": partition.area_m2(x.geometry_geojson)}
