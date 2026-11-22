"""Ministry endpoints: national overview, crop planning, reserves & energy, alerts & management."""
from __future__ import annotations

import csv
import io
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import audit, ministry_user
from app.connectors import sources
from app.connectors.base import ConnectorError, mark_status, upsert_records
from app.db.session import get_db
from app.engines import forecast, national, policy
from app.knowledge.crops import CROPS
from app.knowledge.governorates import GOVERNORATES
from app.models import (Alert, ContributionRequest, DataQuality, DataRecord, DataSourceStatus, Farm, ModelRun, Plan,
                        User)
from app.schemas import DecisionIn, PolicyIn, SimulationIn

router = APIRouter(prefix="/api/ministry", tags=["ministry"])

EXPECTED_MANUAL = [
    {"indicator": "irrigated_area_ha", "entity": "governorate", "source": "ONAGRI / CRDA", "unit": "ha"},
    {"indicator": "water_allocation_mm3", "entity": "governorate", "source": "DGBGTH / CRDA", "unit": "Mm3"},
    {"indicator": "dam_storage_mm3", "entity": "governorate + item=dam", "source": "ONAGRI (situation des barrages)",
     "unit": "Mm3"},
    {"indicator": "dam_capacity_mm3", "entity": "governorate + item=dam", "source": "ONAGRI", "unit": "Mm3"},
    {"indicator": "population", "entity": "governorate", "source": "INS (RGPH 2024)", "unit": "persons"},
    {"indicator": "yield_kg_ha", "entity": "governorate + item=crop", "source": "ONAGRI / CRDA", "unit": "kg/ha"},
    {"indicator": "reserve_stock_kt", "entity": "TN + item=crop", "source": "Office des Céréales / OCT", "unit": "kt"},
    {"indicator": "cold_storage_capacity_t", "entity": "governorate", "source": "Ministère / APIA", "unit": "t"},
]


def _alerts(db: Session, limit: int = 50) -> list[dict]:
    rows = db.scalars(select(Alert).where(Alert.active.is_(True)).order_by(Alert.created_at.desc()).limit(limit))
    order = {"critical": 0, "warning": 1, "info": 2}
    out = [{"id": a.id, "kind": a.kind, "severity": a.severity, "entity": a.entity, "item": a.item, "title": a.title,
            "evidence": a.evidence, "created_at": a.created_at.isoformat()} for a in rows]
    return sorted(out, key=lambda a: order.get(a["severity"], 3))


def _missing(db: Session) -> list[dict]:
    out = []
    for m in EXPECTED_MANUAL:
        n = db.scalar(select(func.count(DataRecord.id)).where(DataRecord.dataset == "MANUAL",
                                                             DataRecord.indicator == m["indicator"]))
        out.append({**m, "records": n, "status": "available" if n else "missing"})
    return out


@router.get("/overview")
def overview(db: Session = Depends(get_db), _: User = Depends(ministry_user)):
    bal = national.national_balance(db)
    caps = national.capacities(db)
    per_gov = []
    pop_rows = {r.entity: r for r in db.scalars(select(DataRecord).where(DataRecord.dataset == "MANUAL",
                                                                         DataRecord.indicator == "population"))}
    dams = national.dams(db)
    alerts = _alerts(db)
    for g, names in GOVERNORATES.items():
        per_gov.append({"code": g, "name": names, "registered_farms": caps[g].get("registered_farms", 0),
                        "registered_area_ha": caps[g].get("registered_area_ha", 0),
                        "population": pop_rows[g].value if g in pop_rows else None,
                        "population_source": pop_rows[g].source_url if g in pop_rows else None,
                        "alerts": sum(1 for a in alerts if a["entity"] == g),
                        "dam_fill_pct": _gov_fill(dams, g)})
    items = bal.get("items", [])
    return {"balance": bal, "governorates": per_gov, "alerts": alerts[:10], "dams": dams,
            "totals": {"demand_kt": round(sum(i["demand_kt"] for i in items), 0),
                       "expected_kt": round(sum(i["expected_production_kt"] or 0 for i in items), 0),
                       "deficit_crops": sum(1 for i in items if (i["gap_kt"] or 0) < 0),
                       "surplus_crops": sum(1 for i in items if (i["gap_kt"] or 0) > 0)},
            "platform": national.platform_production(db), "missing_data": _missing(db)}


def _gov_fill(dams, g):
    ds = [d for d in dams if d["governorate"] == g and d.get("capacity_mm3")]
    if not ds:
        return None
    return round(100 * sum(d["storage_mm3"] for d in ds) / sum(d["capacity_mm3"] for d in ds), 1)


@router.get("/plan")
def crop_plan(year: int | None = None, db: Session = Depends(get_db), _: User = Depends(ministry_user)):
    bal = national.national_balance(db, year)
    return {"balance": bal, "allocation": national.allocate(db, bal) if bal.get("items") else None,
            "guidance": national.governorate_guidance(db)}


@router.post("/simulate")
def simulate(body: SimulationIn, db: Session = Depends(get_db), _: User = Depends(ministry_user)):
    ov = body.model_dump(exclude_none=True, exclude={"year"})
    base = national.national_balance(db, body.year)
    sim = national.national_balance(db, body.year, ov)
    diff = []
    bi = {i["crop"]: i for i in base.get("items", [])}
    for i in sim.get("items", []):
        b = bi.get(i["crop"], {})
        diff.append({"crop": i["crop"], "gap_base_kt": b.get("gap_kt"), "gap_sim_kt": i["gap_kt"],
                     "required_base_kt": b.get("required_kt"), "required_sim_kt": i["required_kt"],
                     "water_sim_mm3": i["water_mm3_if_irrigated"], "price_pressure": i["price_pressure"]})
    return {"scenario": ov, "year": sim.get("year"), "items": diff, "population": sim.get("population")}


@router.get("/reserves-energy")
def reserves_energy(db: Session = Depends(get_db), _: User = Depends(ministry_user)):
    latest = select(Plan.farm_id, func.max(Plan.version).label("v")).group_by(Plan.farm_id).subquery()
    plans = db.scalars(select(Plan).join(latest, (latest.c.farm_id == Plan.farm_id) & (latest.c.v == Plan.version)))
    farms, cold_t, cold_kw, pv_kwp, batt = [], 0.0, 0.0, 0.0, 0.0
    for p in plans:
        e = p.energy or {}
        rooms = (p.storage or {}).get("rooms", [])
        cold_t += sum(r["mass_t"] for r in rooms)
        cold_kw += sum(r["refrigeration_capacity_kw"] for r in rooms)
        pv_kwp += e.get("kwp_needed") or 0
        batt += e.get("battery_kwh_needed") or 0
        farms.append({"farm_id": p.farm_id, "name": p.farm.name, "governorate": p.farm.governorate_code,
                      "large": (p.summary or {}).get("large_farm"), "area_ha": (p.summary or {}).get("field_area_ha"),
                      "production_t": (p.summary or {}).get("production_t"), "water_m3": (p.summary or {}).get(
                          "water_m3"), "cold_rooms": len(rooms), "cold_t": round(sum(r["mass_t"] for r in rooms), 1),
                      "kwp": e.get("kwp_needed"), "battery_kwh": e.get("battery_kwh_needed"),
                      "autonomy_hours": e.get("autonomy_hours"),
                      "export_within_cap_kwh": ((e.get("simulation") or {}).get("export") or {}).get(
                          "within_cap_kwh"), "plan_status": p.status})
    reserve_stock = [{"crop": r.item, "kt": r.value, "period": r.period, "source": r.source_url}
                     for r in db.scalars(select(DataRecord).where(DataRecord.dataset == "MANUAL",
                                                                  DataRecord.indicator == "reserve_stock_kt"))]
    bal = national.national_balance(db)
    return {"farms": farms, "totals": {"cold_storage_t": round(cold_t, 1), "cold_capacity_kw": round(cold_kw, 1),
                                       "pv_kwp": round(pv_kwp, 1), "battery_kwh": round(batt, 1)},
            "reserve_targets": [{"crop": i["crop"], "reserve_target_kt": i["reserve_target_kt"]}
                                for i in bal.get("items", []) if i["reserve_target_kt"]],
            "reserve_stocks": reserve_stock, "dams": national.dams(db),
            "contributions": _contributions(db)}


def _contributions(db: Session) -> list[dict]:
    out = []
    for c in db.scalars(select(ContributionRequest).order_by(ContributionRequest.created_at.desc()).limit(200)):
        farm = db.get(Farm, c.farm_id)
        out.append({"id": c.id, "farm_id": c.farm_id, "farm": farm.name if farm else None,
                    "governorate": farm.governorate_code if farm else None, "plan_id": c.plan_id,
                    "status": c.status, "proposal": c.proposal, "decision_note": c.decision_note,
                    "created_at": c.created_at.isoformat()})
    return out


@router.post("/contributions/{cid}/decision")
def decide(cid: int, body: DecisionIn, db: Session = Depends(get_db), user: User = Depends(ministry_user)):
    c = db.get(ContributionRequest, cid)
    if not c:
        raise HTTPException(404, "not_found")
    c.status, c.decision_note, c.decided_by = body.decision, body.note, user.id
    c.decided_at = datetime.now(timezone.utc)
    db.commit()
    audit(db, user, "contribution.decision", str(cid), body.model_dump())
    return {"ok": True}


@router.get("/alerts")
def alerts(db: Session = Depends(get_db), _: User = Depends(ministry_user)):
    return _alerts(db, 200)


@router.post("/alerts/refresh")
def alerts_refresh(with_rain: bool = True, db: Session = Depends(get_db), user: User = Depends(ministry_user)):
    national.governorate_climates(db, fetch=True)
    new = national.refresh_alerts(db, with_rain)
    audit(db, user, "alerts.refresh", payload={"count": len(new)})
    return _alerts(db, 200)


@router.get("/policy")
def get_policy(db: Session = Depends(get_db), _: User = Depends(ministry_user)):
    return policy.all_settings(db)


@router.put("/policy/{key}")
def put_policy(key: str, body: PolicyIn, db: Session = Depends(get_db), user: User = Depends(ministry_user)):
    try:
        policy.set_value(db, key, body.value, user.id, body.validate_setting, body.source)
    except KeyError:
        raise HTTPException(404, "unknown_policy_key")
    audit(db, user, "policy.set", key, {"value": body.value, "validated": body.validate_setting})
    return policy.all_settings(db)


@router.get("/models")
def models(db: Session = Depends(get_db), _: User = Depends(ministry_user)):
    rows = db.scalars(select(ModelRun).order_by(ModelRun.task, ModelRun.item, ModelRun.model_name))
    return [{"task": r.task, "item": r.item, "model": r.model_name, "version": r.version, "selected": r.selected,
             "mape_pct": r.metrics.get("mape_pct"), "mae": r.metrics.get("mae"), "n_test": r.metrics.get("n_test"),
             "data_signature": r.data_signature, "created_at": r.created_at.isoformat(),
             "libs": r.params.get("libs")} for r in rows]


@router.post("/models/retrain")
def retrain(db: Session = Depends(get_db), user: User = Depends(ministry_user)):
    out = {t: forecast.train_and_select(db, t) for t in ("demand_per_capita", "yield")}
    audit(db, user, "models.retrain")
    return out


@router.get("/data-sources")
def data_sources(db: Session = Depends(get_db), _: User = Depends(ministry_user)):
    st = [{"key": s.key, "last_attempt": s.last_attempt and s.last_attempt.isoformat(),
           "last_success": s.last_success and s.last_success.isoformat(), "records": s.records, "message": s.message}
          for s in db.scalars(select(DataSourceStatus))]
    counts = db.execute(select(DataRecord.dataset, DataRecord.quality, func.count(DataRecord.id))
                        .group_by(DataRecord.dataset, DataRecord.quality)).all()
    return {"status": st, "datasets": [{"dataset": d, "quality": q, "records": n} for d, q, n in counts],
            "missing": _missing(db),
            "not_integrated": [
                {"source": "INM", "reason": "no public API; import station data as CSV (MANUAL)"},
                {"source": "FAO WaPOR", "reason": "v3 raster API; 250 m/100 m coverage of Tunisia — planned, "
                                                  "requires raster stack (rasterio)"},
                {"source": "data.gov.tn / ONAGRI", "reason": "published as PDF/XLS bulletins; use CSV import"},
                {"source": "Sentinel-2 NDVI", "reason": "scene discovery implemented; NDVI needs COG reader"}]}


@router.post("/data-sources/{key}/refresh")
def refresh_source(key: str, db: Session = Depends(get_db), user: User = Depends(ministry_user)):
    try:
        if key == "faostat":
            n = sources.load_faostat(db, refresh=True)
        elif key == "worldbank":
            n = sources.fetch_population(db)
        elif key == "nasa_power":
            n = len(national.governorate_climates(db, fetch=True))
        else:
            raise HTTPException(404, "unknown_source")
    except ConnectorError as e:
        mark_status(db, key, False, message=str(e)[:500])
        raise HTTPException(502, str(e))
    audit(db, user, "data.refresh", key)
    return {"key": key, "records": n}


@router.post("/data-import")
async def data_import(file: UploadFile = File(...), db: Session = Depends(get_db), user: User = Depends(ministry_user)):
    """CSV columns: indicator,entity,item,period,value,unit,quality,source_url,note.
    entity = 'TN' or governorate ISO code (TN-11...). quality in official|measured|estimated|manual."""
    raw = (await file.read(10 * 1024 * 1024)).decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(raw))
    need = {"indicator", "entity", "period", "value", "unit", "source_url"}
    if not reader.fieldnames or not need.issubset(set(reader.fieldnames)):
        raise HTTPException(422, f"columns_required: {sorted(need)}")
    rows, errors = [], []
    allowed_q = {q.value for q in DataQuality} - {"forecast"}
    for i, r in enumerate(reader, start=2):
        ent = r["entity"].strip()
        if ent != "TN" and ent not in GOVERNORATES:
            errors.append({"line": i, "error": "entity"})
            continue
        try:
            val = float(r["value"]) if r["value"].strip() != "" else None
        except ValueError:
            errors.append({"line": i, "error": "value"})
            continue
        q = (r.get("quality") or "manual").strip()
        if q not in allowed_q:
            errors.append({"line": i, "error": "quality"})
            continue
        if not r["source_url"].strip():
            errors.append({"line": i, "error": "source_url_required"})
            continue
        rows.append(dict(source="manual import", dataset="MANUAL", indicator=r["indicator"].strip(), entity=ent,
                         item=(r.get("item") or "").strip(), period=r["period"].strip(), value=val,
                         unit=r["unit"].strip(), quality=q, source_url=r["source_url"].strip(),
                         note=(r.get("note") or "")[:500]))
    n = upsert_records(db, rows) if rows else 0
    audit(db, user, "data.import", file.filename or "", {"rows": n, "errors": len(errors)})
    return {"imported": n, "errors": errors[:100]}


@router.get("/reports/balance.csv")
def report_csv(year: int | None = None, db: Session = Depends(get_db), _: User = Depends(ministry_user)):
    bal = national.national_balance(db, year)
    buf = io.StringIO()
    cols = ["crop", "season", "demand_kt", "required_kt", "expected_production_kt", "gap_kt", "hectares_needed",
            "water_mm3_if_irrigated", "imports_kt", "exports_kt", "reserve_target_kt", "demand_model",
            "demand_mape_pct", "per_capita_quality"]
    w = csv.writer(buf)
    w.writerow(["# AgroSphere AI national balance", f"year={bal.get('year')}",
                f"population={bal.get('population')} ({bal.get('population_quality')})",
                f"margin={bal.get('safety_margin_pct')}%", "sources=FAOSTAT FBS/QCL, World Bank, NASA POWER"])
    w.writerow(["crop_name"] + cols)
    for i in bal.get("items", []):
        w.writerow([CROPS[i["crop"]].name_fr] + [i.get(c) for c in cols])
    buf.seek(0)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": f"attachment; filename=bilan_{bal.get('year')}.csv"})
