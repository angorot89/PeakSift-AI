import ipaddress
import re
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings, read from environment variables (and `.env` if present)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        # An empty variable means "not set" (deployment tools pass unset options as "").
        env_ignore_empty=True,
        # Validation errors must never echo the configuration (it holds secrets).
        hide_input_in_errors=True,
    )

    # development | test | production. Production refuses to start on unsafe or incomplete
    # configuration (see `_production_is_safe`); it is never inferred from a debug flag.
    app_env: Literal["development", "test", "production"] = "development"
    frontend_url: str = "http://localhost:3000"
    # Host names this API answers to (comma-separated; required in production, no wildcards).
    allowed_hosts: str = ""
    # Reverse proxies whose X-Forwarded-For / X-Forwarded-Proto are trusted (comma-separated
    # IPs or CIDRs). Empty: forwarded headers are ignored and the socket peer is the client.
    trusted_proxies: str = ""

    # SQLAlchemy URL, e.g. postgresql+psycopg://user:password@localhost:5432/peaksift
    database_url: str

    # Signs auth tokens. Required and deliberately has no default; see .env.example.
    secret_key: SecretStr = Field(min_length=32)
    access_token_expire_minutes: int = Field(default=7 * 24 * 60, gt=0)
    auth_cookie_name: str = "peaksift_access_token"

    # Local directory for uploaded media (development storage). Never committed.
    media_root: Path = Path("./media")

    # Local scratch directory for media jobs (FFmpeg inputs, intermediates, renders being
    # validated). Each attempt gets its own subdirectory, removed when it ends. Empty: a
    # "peaksift-work" directory in the system temp dir. Never served, never backed up.
    work_root: str = ""

    # Where persistent media lives: `local` (MEDIA_ROOT) or `s3` (a private bucket on any
    # S3-compatible service). The HTTP API behaves identically with either.
    storage_backend: Literal["local", "s3"] = "local"
    # Empty endpoint: AWS S3 itself. MinIO/R2/...: the service URL (scheme://host[:port]).
    s3_endpoint_url: str = ""
    s3_region: str = "us-east-1"
    s3_bucket: str = ""
    # Both or neither; without them boto3's standard chain applies (e.g. an instance role).
    s3_access_key_id: SecretStr | None = None
    s3_secret_access_key: SecretStr | None = None
    # Path-style addressing (http://host/bucket/key), usually needed for MinIO.
    s3_path_style: bool = False
    # TLS to the storage endpoint. When true an http:// endpoint is refused.
    s3_secure: bool = True
    # Optional secondary storage for backups (python -m app.cli.backup create --upload): a
    # separate private bucket, ideally another account or region. Same rules as S3_*.
    backup_s3_endpoint_url: str = ""
    backup_s3_region: str = "us-east-1"
    backup_s3_bucket: str = ""
    backup_s3_access_key_id: SecretStr | None = None
    backup_s3_secret_access_key: SecretStr | None = None
    backup_s3_path_style: bool = False
    backup_s3_secure: bool = True
    # pg_dump / pg_restore (their major version must be at least the server's).
    pg_dump_path: str = "pg_dump"
    pg_restore_path: str = "pg_restore"
    # pg_dump gives up (instead of waiting indefinitely) when another session holds a lock
    # that blocks reading a table.
    backup_lock_wait_timeout_seconds: int = Field(default=60, ge=1)
    s3_connect_timeout_seconds: float = Field(default=5, gt=0)
    s3_read_timeout_seconds: float = Field(default=60, gt=0)
    # Largest accepted source video. Default 2 GiB.
    max_video_upload_bytes: int = Field(default=2 * 1024**3, gt=0)
    # User-supplied audio (music and sound effects): largest file, longest music track and
    # longest sound effect. Default 100 MiB, 20 minutes, 30 seconds.
    audio_upload_max_bytes: int = Field(default=100 * 1024**2, gt=0)
    audio_upload_max_duration_seconds: float = Field(default=20 * 60, gt=0)
    audio_sfx_max_duration_seconds: float = Field(default=30, gt=0)
    # Visual assets (images and B-roll videos): bytes per upload, video length, and pixel
    # budgets checked before anything is decoded (images) or rendered (videos).
    visual_asset_max_bytes: int = Field(default=500 * 1024**2, gt=0)
    visual_asset_max_video_duration_seconds: float = Field(default=10 * 60, gt=0)
    visual_asset_max_pixel_count: int = Field(default=40_000_000, gt=0)
    visual_asset_max_video_pixel_count: int = Field(default=4096 * 2304, gt=0)

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
    # Must exceed the worst-case time for one analysis window on the slowest worker, or a
    # live run could be mistaken for a dead one (a retry would then fence it out).
    clip_detection_stale_after_seconds: int = Field(default=15 * 60, gt=0)
    # How many times one run may be retried before the user must start a new detection.
    clip_detection_max_attempts: int = Field(default=5, ge=1)

    # Local provider: an Ollama-compatible endpoint. The operator controls the endpoint and
    # the comma-separated allow-list of models (first = default); clients only pick from it.
    clip_detection_ollama_enabled: bool = True
    ollama_base_url: str = "http://localhost:11434"
    ollama_clip_models: str = "llama3.2:3b"
    ollama_connect_timeout_seconds: float = Field(default=5, gt=0)
    ollama_timeout_seconds: float = Field(default=300, gt=0)
    # Context window requested per call; must hold the system prompt plus one analysis window.
    ollama_num_ctx: int = Field(default=8192, ge=2048)
    # B-roll suggestions: "ollama" (a local model) or "keyword" (deterministic, name-based).
    # With the fallback on, the keyword provider answers when the model cannot, and says so.
    broll_suggestion_provider: Literal["ollama", "keyword"] = "ollama"
    broll_ollama_model: str = ""  # empty: the first OLLAMA_CLIP_MODELS entry
    broll_fallback_enabled: bool = True
    broll_stale_after_seconds: int = Field(default=15 * 60, gt=0)
    broll_max_attempts: int = Field(default=5, ge=1)
    # Auto Edit planning jobs: when a running one counts as stalled, and how often it may be
    # retried.
    auto_edit_stale_after_seconds: int = Field(default=15 * 60, gt=0)
    auto_edit_max_attempts: int = Field(default=5, ge=1)

    # Hosted provider: OpenAI structured outputs. Uses OPENAI_API_KEY (shared with
    # transcription). Comma-separated allow-list of models (first = default).
    openai_clip_models: str = "gpt-5-mini,gpt-5"
    openai_clip_timeout_seconds: float = Field(default=120, gt=0)
    openai_clip_max_output_tokens: int = Field(default=4000, ge=256)

    # --- Clip rendering (Milestone 5) ------------------------------------------------
    # Output is always a fast-start MP4 with H.264 (libx264, yuv420p) and AAC when the source
    # has audio, at the source's resolution and orientation. CPU encoding; no GPU required.
    clip_render_preset: str = Field(default="veryfast", pattern=r"^[a-z]+$")
    clip_render_crf: int = Field(default=20, ge=0, le=51)
    clip_audio_bitrate: str = Field(default="128k", pattern=r"^\d{2,4}k$")
    clip_render_timeout_seconds: float = Field(default=1800, gt=0)
    # Rendered duration may differ from the request by this much (frame/container rounding).
    clip_render_duration_tolerance_seconds: float = Field(default=1.0, ge=0)
    # A clip may end this far past the probed source duration (encoder padding).
    clip_render_source_tolerance_seconds: float = Field(default=1.0, ge=0)
    clip_render_heartbeat_seconds: float = Field(default=15, gt=0)
    clip_render_stale_after_seconds: int = Field(default=15 * 60, gt=0)
    clip_render_max_attempts: int = Field(default=5, ge=1)

    # --- Short-form editing (Milestone 6) ------------------------------------------------
    # Burned-in captions need an FFmpeg built with libass (the `subtitles` filter) and an
    # installed open font. The family is looked up through fontconfig; Arabic and other
    # scripts fall back to installed fonts that have the glyphs (e.g. Noto Sans Arabic).
    caption_font_family: str = Field(default="Noto Sans", pattern=r"^[A-Za-z0-9 _-]{1,64}$")
    caption_max_words: int = Field(default=7, ge=1, le=20)
    caption_max_chars: int = Field(default=32, ge=8, le=80)

    # --- Smart reframing (Milestone 7) -------------------------------------------------
    # Server configuration only: users never choose a detector, model file or tuning value.
    # Geometry is normalized to the display-oriented source frame (0..1 in x and y).
    reframe_detector: str = Field(default="yunet_face", pattern=r"^[a-z0-9_]{1,32}$")
    # Where the detector's model file lives. It is never committed and never downloaded
    # automatically: run `python scripts/fetch_reframe_model.py` once (pinned URL + sha256).
    reframe_model_path: str = "./models/face_detection_yunet_2023mar.onnx"
    # Frames analysed per second of clip, and the width they are downscaled to for detection.
    reframe_sample_fps: float = Field(default=2.0, gt=0, le=10)
    reframe_analysis_width: int = Field(default=640, ge=160, le=1920)
    reframe_min_detection_confidence: float = Field(default=0.5, ge=0.05, le=0.99)
    # Keep at least this fraction of the crop width between a framed face and the crop edge.
    reframe_face_margin: float = Field(default=0.12, ge=0, le=0.4)
    # The subject may drift this fraction of the crop width from the crop centre before the
    # crop starts to follow (prevents constant micro-panning).
    reframe_dead_zone: float = Field(default=0.10, ge=0, le=0.4)
    # Exponential smoothing time constant of the crop centre, in seconds.
    reframe_smoothing_seconds: float = Field(default=0.5, ge=0, le=5)
    # Speed limit of the crop centre, in fractions of the panned axis per second (source widths
    # for landscape footage).
    reframe_max_pan_per_second: float = Field(default=0.35, gt=0, le=5)
    # A track missing for longer than this stops steering the crop (then fall back to centre).
    reframe_max_gap_seconds: float = Field(default=1.5, gt=0, le=10)
    reframe_sampling_timeout_seconds: float = Field(default=600, gt=0)
    reframe_heartbeat_seconds: float = Field(default=15, gt=0)
    reframe_stale_after_seconds: int = Field(default=15 * 60, gt=0)
    reframe_max_attempts: int = Field(default=5, ge=1)

    # --- Word-timed captions (Milestone 8) ------------------------------------------------
    # The speech-timing provider is server configuration (allow-listed). It reuses the
    # FASTER_WHISPER_* model settings, so captions and transcripts share one loaded model.
    caption_timing_provider: Literal["faster_whisper"] = "faster_whisper"
    # A word may end this far past the decoded clip audio (encoder padding) before the
    # provider output is refused; within it the end is clamped to the audio duration.
    caption_timing_tolerance_seconds: float = Field(default=0.25, ge=0, le=2)
    caption_timing_stale_after_seconds: int = Field(default=15 * 60, gt=0)
    caption_timing_max_attempts: int = Field(default=5, ge=1)

    # --- Publishing (V1.0: YouTube) --------------------------------------------------------
    # Off unless explicitly enabled; when on, every setting it needs is validated at startup.
    youtube_publishing_enabled: bool = False
    # Encrypts stored OAuth refresh tokens (AES-256-GCM): 32 random bytes, base64. From the
    # environment or a secret manager only — never the database, Git or logs.
    publishing_token_encryption_key: SecretStr | None = None
    publishing_token_key_version: int = Field(default=1, ge=1)
    # Older keys still accepted for decryption during rotation: "1:<base64>,2:<base64>".
    publishing_token_previous_keys: SecretStr | None = None
    # Which publishing provider jobs use: "youtube", or "fake" — an in-memory simulation for
    # tests and non-production stacks (refused in production).
    publishing_provider: Literal["youtube", "fake"] = "youtube"
    # Bytes per resumable-upload request; Google requires multiples of 256 KiB. Default 8 MiB.
    youtube_upload_chunk_bytes: int = Field(default=8 * 1024 * 1024, ge=256 * 1024)
    # A publish whose heartbeat is older than this is stalled (retryable).
    publish_stale_after_seconds: int = Field(default=15 * 60, gt=0)
    publish_max_attempts: int = Field(default=5, ge=1)
    # After the upload: how often, and how many times, to ask YouTube about processing.
    publish_status_poll_seconds: int = Field(default=30, ge=5)
    publish_status_max_polls: int = Field(default=20, ge=1)
    # A Google Cloud "Web application" OAuth client. The redirect URI is the API's
    # /publishing/youtube/callback and must be registered on the client exactly.
    google_client_id: str = ""
    google_client_secret: SecretStr | None = None
    google_oauth_redirect_uri: str = ""

    # Rate limits (Redis). Off only in tests. RATE_LIMITS overrides individual budgets:
    # "login_ip=20/60,edit_render=200/3600" (see app/core/rate_limit.py for the names).
    rate_limit_enabled: bool = True
    rate_limits: str = ""

    # Logging: one JSON object per line in production by default, readable text otherwise.
    log_format: Literal["json", "text"] | None = None
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

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

    @model_validator(mode="after")
    def _storage_is_complete(self) -> "Settings":
        problems = storage_problems(self)
        if problems:
            raise ValueError("Invalid storage configuration: " + "; ".join(problems))
        return self

    @model_validator(mode="after")
    def _publishing_is_complete(self) -> "Settings":
        problems = publishing_problems(self)
        if problems:
            raise ValueError("Invalid publishing configuration: " + "; ".join(problems))
        return self

    @model_validator(mode="after")
    def _rate_limits_are_valid(self) -> "Settings":
        from app.core.rate_limit import parse_overrides

        parse_overrides(self.rate_limits)  # raises with a message naming the setting only
        return self

    @model_validator(mode="after")
    def _production_is_safe(self) -> "Settings":
        if self.app_env != "production":
            return self
        problems = production_problems(self)
        if problems:
            raise ValueError("Unsafe production configuration: " + "; ".join(problems))
        return self

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def cookie_secure(self) -> bool:
        """Auth cookies are Secure in production (HTTPS is required there)."""
        return self.is_production

    @property
    def allowed_host_list(self) -> list[str]:
        return [h.strip().lower() for h in self.allowed_hosts.split(",") if h.strip()]

    @property
    def trusted_proxy_list(self) -> list[str]:
        return [p.strip() for p in self.trusted_proxies.split(",") if p.strip()]


def publishing_problems(settings: "Settings") -> list[str]:
    """Why the publishing settings cannot work (names only, never values)."""
    from app.services.publishing.tokens import TokenKeyError, decode_key, parse_previous_keys

    problems: list[str] = []
    key = settings.publishing_token_encryption_key
    if key is not None:
        try:
            decode_key(key.get_secret_value())
        except TokenKeyError as error:
            problems.append(f"PUBLISHING_TOKEN_ENCRYPTION_KEY {error}")
    previous = settings.publishing_token_previous_keys
    if previous is not None:
        try:
            versions = parse_previous_keys(previous.get_secret_value())
        except TokenKeyError as error:
            problems.append(f"PUBLISHING_TOKEN_PREVIOUS_KEYS {error}")
        else:
            if settings.publishing_token_key_version in versions:
                problems.append(
                    "PUBLISHING_TOKEN_KEY_VERSION must differ from every previous key version"
                )
    if settings.youtube_upload_chunk_bytes % (256 * 1024):
        problems.append("YOUTUBE_UPLOAD_CHUNK_BYTES must be a multiple of 262144 (256 KiB)")
    if not settings.youtube_publishing_enabled:
        return problems
    if key is None:
        problems.append("PUBLISHING_TOKEN_ENCRYPTION_KEY is required when publishing is enabled")
    if not settings.google_client_id.endswith(".apps.googleusercontent.com"):
        problems.append("GOOGLE_CLIENT_ID must be a Google OAuth web client id")
    if (
        settings.google_client_secret is None
        or not settings.google_client_secret.get_secret_value()
    ):
        problems.append("GOOGLE_CLIENT_SECRET is required when publishing is enabled")
    redirect = urlsplit(settings.google_oauth_redirect_uri)
    local = redirect.hostname in ("localhost", "127.0.0.1")
    if (
        not redirect.hostname
        or redirect.query
        or redirect.fragment
        or redirect.username
        or not redirect.path.endswith("/publishing/youtube/callback")
    ):
        problems.append(
            "GOOGLE_OAUTH_REDIRECT_URI must be the API's /publishing/youtube/callback URL"
        )
    elif redirect.scheme != "https" and not (redirect.scheme == "http" and local):
        problems.append("GOOGLE_OAUTH_REDIRECT_URI must use https:// (http only for localhost)")
    elif settings.is_production and redirect.scheme != "https":
        problems.append("GOOGLE_OAUTH_REDIRECT_URI must use https:// in production")
    return problems


# S3 bucket names: 3-63 lowercase letters, digits, dots and hyphens.
_BUCKET_PATTERN = re.compile(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")


def storage_problems(settings: Settings) -> list[str]:
    """Why the S3 storage settings cannot work (names only, never values)."""
    if settings.storage_backend != "s3":
        return []
    problems: list[str] = []
    if not _BUCKET_PATTERN.fullmatch(settings.s3_bucket):
        problems.append("S3_BUCKET must be a valid bucket name")
    if (settings.s3_access_key_id is None) != (settings.s3_secret_access_key is None):
        problems.append("S3_ACCESS_KEY_ID and S3_SECRET_ACCESS_KEY must be set together")
    if settings.s3_endpoint_url:
        endpoint = urlsplit(settings.s3_endpoint_url)
        if (
            endpoint.scheme not in ("http", "https")
            or not endpoint.hostname
            or endpoint.username
            or endpoint.password
            or endpoint.path not in ("", "/")
            or endpoint.query
            or endpoint.fragment
        ):
            problems.append("S3_ENDPOINT_URL must be scheme://host[:port] without credentials")
        elif settings.s3_secure and endpoint.scheme != "https":
            problems.append("S3_ENDPOINT_URL must use https:// while S3_SECURE is true")
    return problems


# Values that must never sign production tokens (placeholders from docs and examples).
_PLACEHOLDER_SECRETS = {"change-me", "changeme", "secret", "replace-me", "your-secret-key"}


def production_problems(settings: Settings) -> list[str]:
    """Every reason this configuration must not run in production (names only, no values)."""
    problems: list[str] = []
    explicit = settings.model_fields_set
    secret = settings.secret_key.get_secret_value()
    if (
        secret.lower().strip("-_ ") in _PLACEHOLDER_SECRETS
        or "change" in secret.lower()
        or len(set(secret)) < 10
    ):
        problems.append("SECRET_KEY is a placeholder or has too little variety")
    frontend = urlsplit(settings.frontend_url)
    if frontend.scheme != "https" or not frontend.hostname or "*" in settings.frontend_url:
        problems.append("FRONTEND_URL must be an explicit https:// origin")
    hosts = settings.allowed_host_list
    if not hosts:
        problems.append("ALLOWED_HOSTS is required")
    elif any("*" in host for host in hosts):
        problems.append("ALLOWED_HOSTS must not contain wildcards")
    for proxy in settings.trusted_proxy_list:
        try:
            ipaddress.ip_network(proxy, strict=False)
        except ValueError:
            problems.append("TRUSTED_PROXIES must be IP addresses or CIDR ranges")
            break
    if "*" in settings.trusted_proxy_list:
        problems.append("TRUSTED_PROXIES must not trust every address")
    for name in ("database_url", "redis_url"):
        if name not in explicit:
            problems.append(f"{name.upper()} must be set explicitly")
    if settings.celery_task_always_eager:
        problems.append("CELERY_TASK_ALWAYS_EAGER must be off")
    if not settings.rate_limit_enabled:
        problems.append("RATE_LIMIT_ENABLED must be on")
    if settings.publishing_provider != "youtube":
        problems.append("PUBLISHING_PROVIDER must be youtube")
    if settings.storage_backend == "local" and (
        "media_root" not in explicit or not settings.media_root.is_absolute()
    ):
        problems.append("MEDIA_ROOT must be set to an absolute path (STORAGE_BACKEND=local)")
    if settings.storage_backend == "s3" and "storage_backend" not in explicit:
        problems.append("STORAGE_BACKEND must be set explicitly")
    if settings.work_root and not Path(settings.work_root).is_absolute():
        problems.append("WORK_ROOT must be an absolute path")
    return problems


@lru_cache
def get_settings() -> Settings:
    return Settings()
