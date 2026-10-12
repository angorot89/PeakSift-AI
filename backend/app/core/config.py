from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings, read from environment variables (and `.env` if present)."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    frontend_url: str = "http://localhost:3000"

    # SQLAlchemy URL, e.g. postgresql+psycopg://user:password@localhost:5432/peaksift
    database_url: str

    # Signs auth tokens. Required and deliberately has no default; see .env.example.
    secret_key: SecretStr = Field(min_length=32)
    access_token_expire_minutes: int = Field(default=7 * 24 * 60, gt=0)
    auth_cookie_name: str = "peaksift_access_token"

    # Local directory for uploaded media (development storage). Never committed.
    media_root: Path = Path("./media")

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
