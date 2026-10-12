from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, model_validator
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

    # Long audio is transcribed in fixed-duration chunks (seconds). 10 minutes at 64 kbps is
    # ~4.8 MB, comfortably under hosted upload limits.
    transcription_chunk_seconds: int = Field(default=600, ge=30)

    # Pipeline behaviour. Transient provider errors are retried in-task with exponential
    # backoff; a job whose heartbeat is older than the stale threshold is considered dead.
    transcription_provider_max_attempts: int = Field(default=3, ge=1)
    transcription_retry_backoff_seconds: float = Field(default=2.0, ge=0)
    # Must exceed the worst-case time for one chunk on the slowest worker, or a live
    # job could be mistaken for a dead one.
    transcription_stale_after_seconds: int = Field(default=30 * 60, gt=0)
    transcription_prompt_tail_chars: int = Field(default=200, ge=0)
    # Provider segments may overrun a chunk by this much (encoder padding) before rejection.
    transcription_timestamp_tolerance_seconds: float = Field(default=1.5, ge=0)

    # Which speech-to-text provider the pipeline uses: "faster_whisper" (local) or "openai".
    # Server configuration only; API clients never choose a provider.
    transcription_provider: str = "faster_whisper"

    # faster-whisper (local provider). The model is loaded lazily inside the worker only.
    faster_whisper_model: str = "small"
    faster_whisper_device: str = "cpu"
    faster_whisper_compute_type: str = "int8"
    faster_whisper_beam_size: int = Field(default=5, gt=0)

    # OpenAI (hosted provider). The key is only required when TRANSCRIPTION_PROVIDER=openai
    # and is never validated at startup, logged, returned or sent to the frontend.
    openai_api_key: SecretStr | None = None
    openai_transcription_model: str = "gpt-4o-mini-transcribe"  # hosted text option
    openai_high_accuracy_model: str = "gpt-4o-transcribe"  # higher-accuracy text option
    openai_timestamp_model: str = "whisper-1"  # the model that returns segment timestamps
    openai_timeout_seconds: float = Field(default=600, gt=0)
    # Hosted uploads are limited to 25 MB; keep a safety margin below it.
    openai_max_upload_bytes: int = Field(default=20 * 1024 * 1024, gt=0)

    # --- AI clip detection (Milestone 4) ---------------------------------------------
    # The transcript is analysed in bounded windows; each window is one model request.
    clip_detection_window_seconds: int = Field(default=300, ge=60)
    clip_detection_window_overlap_seconds: int = Field(default=20, ge=0)
    clip_detection_window_max_chars: int = Field(default=8000, ge=1000)
    clip_detection_max_windows: int = Field(default=500, ge=1)
    # Accepted clip length and how many ranked candidates a run keeps.
    clip_detection_min_clip_seconds: float = Field(default=15, gt=0)
    clip_detection_max_clip_seconds: float = Field(default=90, gt=0)
    clip_detection_target_candidates: int = Field(default=10, ge=1, le=50)
    clip_detection_candidates_per_window: int = Field(default=3, ge=1, le=10)
    # Candidates overlapping more than this fraction (intersection / union) are duplicates.
    clip_detection_overlap_threshold: float = Field(default=0.5, ge=0, le=1)
    clip_detection_timestamp_tolerance_seconds: float = Field(default=1.0, ge=0)
    # Pipeline behaviour (same semantics as transcription).
    clip_detection_provider_max_attempts: int = Field(default=3, ge=1)
    clip_detection_retry_backoff_seconds: float = Field(default=2.0, ge=0)
    clip_detection_stale_after_seconds: int = Field(default=15 * 60, gt=0)

    # Local provider: an Ollama-compatible endpoint. The operator controls the endpoint and
    # the comma-separated allow-list of models (first = default); clients only pick from it.
    clip_detection_ollama_enabled: bool = True
    ollama_base_url: str = "http://localhost:11434"
    ollama_clip_models: str = "llama3.2:3b"
    ollama_connect_timeout_seconds: float = Field(default=5, gt=0)
    ollama_timeout_seconds: float = Field(default=300, gt=0)
    # Context window requested per call; must hold the system prompt plus one analysis window.
    ollama_num_ctx: int = Field(default=8192, ge=2048)

    # Hosted provider: OpenAI structured outputs. Uses OPENAI_API_KEY (shared with
    # transcription). Comma-separated allow-list of models (first = default).
    openai_clip_models: str = "gpt-5-mini,gpt-5"
    openai_clip_timeout_seconds: float = Field(default=120, gt=0)

    # Background jobs. Redis is the Celery broker; the database stays the source of truth.
    redis_url: str = "redis://localhost:6379/0"
    # Run tasks inline in the calling process (tests only). Never enable in production.
    celery_task_always_eager: bool = False
    # Limits for one transcription job: a 4-hour stream on CPU can legitimately take hours.
    celery_task_soft_time_limit_seconds: int = Field(default=6 * 3600, gt=0)
    celery_task_time_limit_seconds: int = Field(default=6 * 3600 + 600, gt=0)

    @model_validator(mode="after")
    def _clip_bounds_are_ordered(self) -> "Settings":
        if self.clip_detection_min_clip_seconds >= self.clip_detection_max_clip_seconds:
            raise ValueError(
                "CLIP_DETECTION_MIN_CLIP_SECONDS must be smaller than "
                "CLIP_DETECTION_MAX_CLIP_SECONDS"
            )
        return self

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
