"""Test configuration: isolated SQLite DB, no network.

Network connectors are replaced by deterministic fixtures. These fixture values are
TEST DATA ONLY (clearly synthetic, used to exercise the engines) and never reach the
application database.
"""
import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="agrosphere-test-")
os.environ["AGRO_DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["AGRO_UPLOAD_DIR"] = f"{_tmp}/uploads"
os.environ["AGRO_ENVIRONMENT"] = "test"

import math  # noqa: E402

import pytest  # noqa: E402

import app.models  # noqa: E402,F401
from app.db.session import Base, SessionLocal, engine  # noqa: E402
from app.engines.fao56 import MonthlyClimate  # noqa: E402

TEST_CLIMATE = MonthlyClimate(
    et0_mm_day=[1.8, 2.4, 3.4, 4.5, 5.8, 7.0, 7.6, 7.0, 5.2, 3.6, 2.4, 1.8],
    rain_mm=[35, 30, 30, 25, 15, 5, 2, 8, 30, 35, 30, 35],
    tmax_c=[16, 17, 20, 23, 28, 33, 36, 36, 31, 26, 21, 17],
    tmin_c=[6, 6, 8, 11, 14, 18, 21, 22, 19, 15, 10, 7], source="TEST FIXTURE")


def _pv_profile():
    prof = []
    for m in range(12):
        peak = 0.55 + 0.25 * math.sin(math.pi * m / 11)
        prof.append([max(0.0, peak * math.sin(math.pi * (h - 6) / 13)) if 6 <= h <= 19 else 0.0 for h in range(24)])
    return prof


@pytest.fixture(scope="session", autouse=True)
def _db():
    Base.metadata.create_all(engine)
    db = SessionLocal()
    from app.connectors import sources
    sources.load_faostat(db)          # real cached FAOSTAT extract shipped in data/reference
    db.close()
    yield


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    from app.connectors import sources
    from app.connectors.base import ConnectorError

    def no_net(*a, **k):
        raise ConnectorError("offline test")

    monkeypatch.setattr(sources, "fetch_climate_normals", lambda db, lat, lon, entity=None: TEST_CLIMATE)
    monkeypatch.setattr(sources, "fetch_pv_profile", lambda db, lat, lon, **k: {
        "profile_kwh_per_kwp": _pv_profile(), "source": "TEST", "years": "-", "radiation_db": "-", "tilt_deg": 30,
        "annual_kwh_per_kwp": 1700, "quality": "estimated"})
    monkeypatch.setattr(sources, "fetch_forecast", no_net)
    monkeypatch.setattr(sources, "fetch_soil", no_net)
    monkeypatch.setattr(sources, "fetch_population", no_net)
    monkeypatch.setattr(sources, "fetch_recent_rain_anomaly", no_net)
    yield


@pytest.fixture
def db():
    s = SessionLocal()
    yield s
    s.close()
