"""Application settings (12-factor: everything configurable by environment)."""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="AGRO_", extra="ignore",
                                      protected_namespaces=("settings_",))

    app_name: str = "TuniNō"
    environment: str = "development"
    # SQLite is only for local development / tests. Production uses PostgreSQL + PostGIS.
    database_url: str = f"sqlite:///{(BASE_DIR / 'data' / 'agrosphere.db').as_posix()}"
    jwt_secret: str = "change-me-in-production-please-32+chars"
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 60 * 12
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    upload_dir: Path = BASE_DIR / "data" / "uploads"
    model_dir: Path = BASE_DIR / "data" / "models"
    reference_dir: Path = BASE_DIR / "data" / "reference"
    max_upload_mb: int = 25
    http_timeout_s: float = 45.0
    # Optional PyTorch segmentation weights (see app/cv/segmentation.py)
    segmentation_weights: Path | None = None
    # Contact string sent to public APIs that ask for one (generic on purpose)
    http_user_agent: str = "TuniNo/1.0 (+open-source agricultural planning tool)"

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    if s.environment == "production" and (s.jwt_secret.startswith("change-me") or len(s.jwt_secret) < 32):
        raise RuntimeError("AGRO_JWT_SECRET must be set to a random value of at least 32 characters in production")
    s.upload_dir.mkdir(parents=True, exist_ok=True)
    s.model_dir.mkdir(parents=True, exist_ok=True)
    return s
