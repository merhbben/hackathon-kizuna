from fastapi import APIRouter

from app.knowledge.crops import CROPS, IRRIGATION_EFFICIENCY
from app.knowledge.governorates import GOVERNORATES, boundaries

router = APIRouter(prefix="/api/reference", tags=["reference"])


@router.get("/crops")
def crops():
    return [{"code": c.code, "name": {"fr": c.name_fr, "ar": c.name_ar}, "category": c.category, "color": c.color,
             "perennial": c.perennial, "cycle_days": c.cycle_days, "stages": c.stages, "kc": c.kc,
             "root_depth_m": c.root_depth_m, "p": c.p, "ky": c.ky, "ece_threshold": c.ece_threshold,
             "planting_months": c.planting_months, "rainfed_possible": c.rainfed_possible,
             "storage": c.storage.__dict__, "faostat_qcl": c.faostat_qcl, "faostat_fbs": c.faostat_fbs,
             "refs": c.refs, "calibrate": c.calibrate} for c in CROPS.values()]


@router.get("/governorates")
def governorates():
    return {"names": GOVERNORATES, "geojson": boundaries(),
            "source": "geoBoundaries gbOpen TUN ADM1 (OpenStreetMap contributors, ODbL)"}


@router.get("/irrigation")
def irrigation():
    return {"efficiency": IRRIGATION_EFFICIENCY, "source": "FAO-56 Table 20 / FAO Irrigation Water Management "
                                                           "Training Manual 4"}
