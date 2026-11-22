"""ORM models.

Geometries are stored as GeoJSON (EPSG:4326) in JSON columns so the ORM stays
portable (SQLite for tests). On PostgreSQL the migration additionally creates
PostGIS `geom` columns populated by triggers, with GIST indexes, used for
spatial queries (see alembic/versions/0001_initial.py).
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Role(str, Enum):
    ministry = "ministry"
    farmer = "farmer"


class DataQuality(str, Enum):
    """Provenance class shown everywhere in the UI."""
    official = "official"      # published by an institution (INS, FAOSTAT, ONAGRI...)
    measured = "measured"      # sensor / farmer measurement
    estimated = "estimated"    # model or reanalysis estimate (SoilGrids, NASA POWER, PVGIS...)
    forecast = "forecast"      # output of a forecasting model
    manual = "manual"          # manually imported, source declared by the importer


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(255))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default=Role.farmer.value)
    governorate_code: Mapped[str | None] = mapped_column(String(8), nullable=True)
    language: Mapped[str] = mapped_column(String(5), default="fr")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    farms: Mapped[list[Farm]] = relationship(back_populates="owner", cascade="all, delete-orphan")


class Farm(Base):
    __tablename__ = "farms"
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    governorate_code: Mapped[str] = mapped_column(String(8), index=True)
    delegation: Mapped[str | None] = mapped_column(String(120), nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    declared_area_ha: Mapped[float | None] = mapped_column(Float, nullable=True)
    boundary_geojson: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Non-cultivable zones (buildings, obstacles, existing paths) in GeoJSON
    exclusions_geojson: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    measured_area_ha: Mapped[float | None] = mapped_column(Float, nullable=True)
    area_validated: Mapped[bool] = mapped_column(Boolean, default=False)
    soil: Mapped[dict] = mapped_column(JSON, default=dict)            # texture, fractions, pH, EC, slope, source
    budget_tnd: Mapped[float | None] = mapped_column(Float, nullable=True)
    season: Mapped[str | None] = mapped_column(String(20), nullable=True)
    existing_crops: Mapped[list] = mapped_column(JSON, default=list)
    irrigation_method: Mapped[str] = mapped_column(String(20), default="drip")
    preferences: Mapped[dict] = mapped_column(JSON, default=dict)     # crop prices/costs entered by farmer etc.
    plan_upload: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # CV detection result + georef
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    owner: Mapped[User] = relationship(back_populates="farms")
    water_sources: Mapped[list[WaterSource]] = relationship(back_populates="farm", cascade="all, delete-orphan")
    equipment: Mapped[list[Equipment]] = relationship(back_populates="farm", cascade="all, delete-orphan")
    plans: Mapped[list[Plan]] = relationship(back_populates="farm", cascade="all, delete-orphan",
                                             order_by="Plan.version")


class WaterSource(Base):
    __tablename__ = "water_sources"
    id: Mapped[int] = mapped_column(primary_key=True)
    farm_id: Mapped[int] = mapped_column(ForeignKey("farms.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20))  # well | borehole | reservoir | dam_network | canal
    name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    flow_m3h: Mapped[float | None] = mapped_column(Float, nullable=True)       # None = not on the plan
    daily_volume_m3: Mapped[float | None] = mapped_column(Float, nullable=True)  # declared m3/day (plan)
    data_source: Mapped[str] = mapped_column(String(20), default="farmer")      # farmer | plan | measured
    max_hours_per_day: Mapped[float] = mapped_column(Float, default=12.0)
    annual_quota_m3: Mapped[float | None] = mapped_column(Float, nullable=True)
    pumping_depth_m: Mapped[float] = mapped_column(Float, default=0.0)   # dynamic water level
    elevation_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    salinity_ds_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    authorized: Mapped[bool] = mapped_column(Boolean, default=True)
    farm: Mapped[Farm] = relationship(back_populates="water_sources")


class Equipment(Base):
    __tablename__ = "equipment"
    id: Mapped[int] = mapped_column(primary_key=True)
    farm_id: Mapped[int] = mapped_column(ForeignKey("farms.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20))  # pump | pv | battery | grid | cold_room
    specs: Mapped[dict] = mapped_column(JSON, default=dict)
    farm: Mapped[Farm] = relationship(back_populates="equipment")


class Plan(Base):
    __tablename__ = "plans"
    id: Mapped[int] = mapped_column(primary_key=True)
    farm_id: Mapped[int] = mapped_column(ForeignKey("farms.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(20), default="proposed")  # proposed | accepted
    inputs: Mapped[dict] = mapped_column(JSON, default=dict)
    summary: Mapped[dict] = mapped_column(JSON, default=dict)
    irrigation: Mapped[dict] = mapped_column(JSON, default=dict)
    energy: Mapped[dict] = mapped_column(JSON, default=dict)
    storage: Mapped[dict] = mapped_column(JSON, default=dict)
    contribution: Mapped[dict] = mapped_column(JSON, default=dict)
    infrastructure_geojson: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    farm: Mapped[Farm] = relationship(back_populates="plans")
    parcels: Mapped[list[Parcel]] = relationship(back_populates="plan", cascade="all, delete-orphan")


class Parcel(Base):
    __tablename__ = "parcels"
    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("plans.id", ondelete="CASCADE"), index=True)
    label: Mapped[str] = mapped_column(String(20))
    crop_code: Mapped[str] = mapped_column(String(40))
    geometry_geojson: Mapped[dict] = mapped_column(JSON)
    area_m2: Mapped[float] = mapped_column(Float)
    locked: Mapped[bool] = mapped_column(Boolean, default=False)
    water_source_id: Mapped[int | None] = mapped_column(ForeignKey("water_sources.id", ondelete="SET NULL"),
                                                        nullable=True)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    plan: Mapped[Plan] = relationship(back_populates="parcels")


class DataRecord(Base):
    """Every number from an external or imported source, with provenance."""
    __tablename__ = "data_records"
    __table_args__ = (UniqueConstraint("dataset", "indicator", "entity", "item", "period",
                                       name="uq_data_record"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(60))      # FAOSTAT, WorldBank, NASA_POWER, ONAGRI ...
    dataset: Mapped[str] = mapped_column(String(60), index=True)  # e.g. FAOSTAT_FBS
    indicator: Mapped[str] = mapped_column(String(80), index=True)
    entity: Mapped[str] = mapped_column(String(20), index=True)   # 'TN' national or governorate ISO code
    item: Mapped[str] = mapped_column(String(80), default="", index=True)  # crop code or ''
    period: Mapped[str] = mapped_column(String(20), index=True)   # '2022', '2022-07', '2022-07-03'
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit: Mapped[str] = mapped_column(String(40))
    quality: Mapped[str] = mapped_column(String(20), default=DataQuality.official.value)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DataSourceStatus(Base):
    __tablename__ = "data_source_status"
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(60), unique=True)
    last_attempt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_success: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    records: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)


class PolicySetting(Base):
    """Ministry-configurable parameters. Nothing here is presented as law."""
    __tablename__ = "policy_settings"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[dict | list | float | str | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft | validated
    source: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ModelRun(Base):
    """Registry of trained/evaluated models (versions + metrics)."""
    __tablename__ = "model_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    task: Mapped[str] = mapped_column(String(60), index=True)    # demand_per_capita, yield ...
    item: Mapped[str] = mapped_column(String(80), default="")
    model_name: Mapped[str] = mapped_column(String(60))
    version: Mapped[str] = mapped_column(String(40))
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    data_signature: Mapped[str] = mapped_column(String(64))
    selected: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ContributionRequest(Base):
    """Reserve-contribution proposal for a large farm. Requires ministry validation."""
    __tablename__ = "contribution_requests"
    id: Mapped[int] = mapped_column(primary_key=True)
    farm_id: Mapped[int] = mapped_column(ForeignKey("farms.id", ondelete="CASCADE"), index=True)
    plan_id: Mapped[int | None] = mapped_column(ForeignKey("plans.id", ondelete="SET NULL"), nullable=True)
    proposal: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending | approved | rejected
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Alert(Base):
    __tablename__ = "alerts"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(30))       # drought | shortage | surplus | power | water | data
    severity: Mapped[str] = mapped_column(String(10))   # info | warning | critical
    entity: Mapped[str] = mapped_column(String(20), default="TN")
    item: Mapped[str] = mapped_column(String(80), default="")
    title: Mapped[dict] = mapped_column(JSON)           # {"fr": ..., "ar": ...}
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    action: Mapped[str] = mapped_column(String(80))
    target: Mapped[str] = mapped_column(String(120), default="")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
