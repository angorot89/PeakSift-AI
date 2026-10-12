from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings, read from environment variables (and `.env` if present)."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    frontend_url: str = "http://localhost:3000"

    # SQLAlchemy URL, e.g. postgresql+psycopg://user:password@localhost:5432/peaksift
    database_url: str

    # Not used yet; reserved for upcoming milestones.
    secret_key: SecretStr | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
