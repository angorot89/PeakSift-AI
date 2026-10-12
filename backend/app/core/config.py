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
    # Largest accepted source video. Default 2 GiB.
    max_video_upload_bytes: int = Field(default=2 * 1024**3, gt=0)

    # ffprobe binary used to read video metadata, and how long one probe may take.
    ffprobe_path: str = "ffprobe"
    ffprobe_timeout_seconds: float = Field(default=30, gt=0)

    # ffmpeg binary used to extract normalized audio for transcription, and its time limit.
    ffmpeg_path: str = "ffmpeg"
    audio_extraction_timeout_seconds: float = Field(default=3600, gt=0)

    # Which speech-to-text provider the pipeline uses: "faster_whisper" (local) or "openai".
    # Server configuration only; API clients never choose a provider.
    transcription_provider: str = "faster_whisper"

    # Background jobs. Redis is the Celery broker; the database stays the source of truth.
    redis_url: str = "redis://localhost:6379/0"
    # Run tasks inline in the calling process (tests only). Never enable in production.
    celery_task_always_eager: bool = False
    # Limits for one transcription job: a 4-hour stream on CPU can legitimately take hours.
    celery_task_soft_time_limit_seconds: int = Field(default=6 * 3600, gt=0)
    celery_task_time_limit_seconds: int = Field(default=6 * 3600 + 600, gt=0)

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
