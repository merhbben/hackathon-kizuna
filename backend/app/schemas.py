from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.knowledge.crops import CROPS
from app.knowledge.governorates import GOVERNORATES


class RegisterIn(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=200)
    password: str = Field(min_length=8, max_length=128)
    governorate_code: str | None = None
    language: Literal["fr", "ar"] = "fr"

    @field_validator("governorate_code")
    @classmethod
    def _gov(cls, v):
        if v is not None and v not in GOVERNORATES:
            raise ValueError("unknown governorate")
        return v


class UserOut(BaseModel):
    id: int
    email: str
    full_name: str
    role: str
    governorate_code: str | None
    language: str

    model_config = {"from_attributes": True}


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class SoilIn(BaseModel):
    texture: str | None = None
    sand_pct: float | None = Field(None, ge=0, le=100)
    clay_pct: float | None = Field(None, ge=0, le=100)
    organic_matter_pct: float | None = Field(None, ge=0, le=30)
    ph: float | None = Field(None, ge=3, le=11)
    ece_ds_m: float | None = Field(None, ge=0, le=40)
    slope_pct: float | None = Field(None, ge=0, le=60)
    source: str | None = "farmer"


class FarmIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    governorate_code: str
    delegation: str | None = None
    latitude: float | None = Field(None, ge=30.0, le=37.6)
    longitude: float | None = Field(None, ge=7.4, le=11.7)
    declared_area_ha: float | None = Field(None, gt=0, le=100000)
    soil: SoilIn = SoilIn()
    budget_tnd: float | None = Field(None, ge=0)
    season: Literal["autumn_winter", "spring_summer", "annual"] | None = "annual"
    existing_crops: list[Any] = []
    irrigation_method: Literal["drip", "sprinkler", "surface"] = "drip"
    preferences: dict = {}

    @field_validator("governorate_code")
    @classmethod
    def _gov(cls, v):
        if v not in GOVERNORATES:
            raise ValueError("unknown governorate")
        return v


class FarmPatch(BaseModel):
    name: str | None = None
    governorate_code: str | None = None
    delegation: str | None = None
    latitude: float | None = Field(None, ge=30.0, le=37.6)
    longitude: float | None = Field(None, ge=7.4, le=11.7)
    declared_area_ha: float | None = Field(None, gt=0)
    soil: SoilIn | None = None
    budget_tnd: float | None = None
    season: Literal["autumn_winter", "spring_summer", "annual"] | None = None
    existing_crops: list[Any] | None = None
    irrigation_method: Literal["drip", "sprinkler", "surface"] | None = None
    preferences: dict | None = None

    @field_validator("governorate_code")
    @classmethod
    def _gov(cls, v):
        if v is not None and v not in GOVERNORATES:
            raise ValueError("unknown governorate")
        return v


class BoundaryIn(BaseModel):
    boundary: dict
    exclusions: dict | None = None
    confirm_area: bool = False


class WaterSourceIn(BaseModel):
    kind: Literal["well", "borehole", "reservoir", "dam_network", "canal"]
    name: str | None = None
    latitude: float
    longitude: float
    flow_m3h: float = Field(gt=0, le=2000)
    max_hours_per_day: float = Field(12, gt=0, le=24)
    annual_quota_m3: float | None = Field(None, ge=0)
    pumping_depth_m: float = Field(0, ge=0, le=500)
    elevation_m: float | None = None
    salinity_ds_m: float | None = Field(None, ge=0, le=30)
    authorized: bool = True


class EquipmentIn(BaseModel):
    kind: Literal["pump", "pv", "battery", "grid", "cold_room"]
    specs: dict


class GeorefIn(BaseModel):
    control_points: list[dict] | None = None     # [{'px':[x,y],'lat':..,'lon':..}]
    meters_per_px: float | None = Field(None, gt=0)
    anchor_px: list[float] | None = None
    anchor_lat: float | None = None
    anchor_lon: float | None = None
    rotation_deg: float = 0.0
    area_ha: float | None = Field(None, gt=0, le=100000)   # simple mode: real area + one click at the centre
    boundary_px: list[list[float]] | None = None  # corrected outline from the editor
    water_points_px: list[dict] | None = None     # [{'px':[x,y], 'kind':'well'}]


class ParcelEdit(BaseModel):
    parcel_id: int
    crop_code: str | None = None
    geometry: dict | None = None

    @field_validator("crop_code")
    @classmethod
    def _crop(cls, v):
        if v is not None and v not in CROPS:
            raise ValueError("unknown crop")
        return v


class ReplanIn(BaseModel):
    edits: list[ParcelEdit] = []
    keep_locked: bool = True


class PolicyIn(BaseModel):
    value: Any
    validate_setting: bool = Field(False, alias="validate")
    source: str | None = None

    model_config = {"populate_by_name": True}


class SimulationIn(BaseModel):
    year: int | None = None
    population_pct: float = Field(0, ge=-30, le=30)
    yield_pct: float = Field(0, ge=-80, le=80)
    rain_pct: float = Field(0, ge=-90, le=100)
    import_cut_pct: float = Field(0, ge=0, le=100)
    margin_pct: float | None = Field(None, ge=0, le=50)


class DecisionIn(BaseModel):
    decision: Literal["approved", "rejected"]
    note: str | None = Field(None, max_length=2000)
