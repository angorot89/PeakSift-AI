from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app.api.audio_assets import limits_router as audio_limits_router
from app.api.audio_assets import router as audio_assets_router
from app.api.auth import router as auth_router
from app.api.auto_edit import recipes_router as auto_edit_recipes_router
from app.api.auto_edit import router as auto_edit_router
from app.api.brand import router as brand_router
from app.api.broll import router as broll_router
from app.api.caption_styles import router as caption_styles_router
from app.api.caption_tracks import router as caption_tracks_router
from app.api.clip_detection import providers_router as clip_providers_router
from app.api.clip_detection import router as clip_detection_router
from app.api.clip_edits import media_router as edit_media_router
from app.api.clip_edits import router as clip_edits_router
from app.api.clip_media import router as clip_media_router
from app.api.clips import router as clips_router
from app.api.clips import video_clips_router
from app.api.copilot import router as copilot_router
from app.api.find_clips import router as find_clips_router
from app.api.health import router as health_router
from app.api.hooks import router as hooks_router
from app.api.library import router as library_router
from app.api.markets import router as markets_router
from app.api.performance import router as performance_router
from app.api.projects import router as projects_router
from app.api.publish_jobs import edit_router as publish_edit_router
from app.api.publish_jobs import job_router as publish_job_router
from app.api.publish_jobs import slots_router as posting_slots_router
from app.api.publishing import platforms_router as publishing_platforms_router
from app.api.publishing import router as publishing_router
from app.api.publishing_instagram import router as publishing_instagram_router
from app.api.publishing_tiktok import router as publishing_tiktok_router
from app.api.quick_start import router as quick_start_router
from app.api.reframe import router as reframe_router
from app.api.shorts import router as shorts_router
from app.api.transcriptions import router as transcriptions_router
from app.api.video_content import router as video_content_router
from app.api.videos import router as videos_router
from app.api.visual_assets import limits_router as visual_limits_router
from app.api.visual_assets import router as visual_assets_router
from app.api.workspace import router as workspace_router
from app.core.config import Settings, get_settings
from app.core.errors import register_error_handlers
from app.core.observability import RequestContextMiddleware, configure_logging
from app.core.security_headers import SecurityHeadersMiddleware

ROUTERS = (
    health_router,
    auth_router,
    projects_router,
    videos_router,
    quick_start_router,
    video_content_router,
    transcriptions_router,
    clip_providers_router,
    clip_detection_router,
    find_clips_router,
    clips_router,
    video_clips_router,
    clip_media_router,
    clip_edits_router,
    edit_media_router,
    reframe_router,
    caption_tracks_router,
    caption_styles_router,
    audio_assets_router,
    broll_router,
    auto_edit_router,
    auto_edit_recipes_router,
    audio_limits_router,
    visual_assets_router,
    visual_limits_router,
    library_router,
    publishing_router,
    publishing_platforms_router,
    publishing_tiktok_router,
    publishing_instagram_router,
    publish_edit_router,
    publish_job_router,
    posting_slots_router,
    performance_router,
    workspace_router,
    shorts_router,
    markets_router,
    hooks_router,
    brand_router,
    copilot_router,
)


def create_app(settings: Settings) -> FastAPI:
    """The API application for these settings (servers use ``app`` below)."""
    # Interactive API docs are a development aid; production does not publish them.
    docs = (
        {"docs_url": None, "redoc_url": None, "openapi_url": None} if settings.is_production else {}
    )
    configure_logging(settings)
    application = FastAPI(title="PeakSift AI API", version="1.0.0", **docs)
    register_error_handlers(application)  # before CORS, so error responses get CORS headers
    application.add_middleware(
        CORSMiddleware,
        # Explicit origin (never "*") because credentials are allowed.
        allow_origins=[settings.frontend_url.rstrip("/")],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID", "Retry-After"],
    )
    if settings.allowed_host_list:
        # Requests for any other Host are refused (required in production; see config.py).
        application.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_host_list)
    if settings.trusted_proxy_list:
        # Only these proxies may set the client address and scheme (X-Forwarded-For /
        # -Proto); anyone else's forwarded headers are ignored.
        application.add_middleware(
            ProxyHeadersMiddleware, trusted_hosts=settings.trusted_proxy_list
        )
    for router in ROUTERS:
        application.include_router(router)
    application.add_middleware(SecurityHeadersMiddleware, hsts=settings.is_production)
    # Outermost: every response (errors and rejected hosts included) carries a request id.
    application.add_middleware(RequestContextMiddleware)
    return application


app = create_app(get_settings())
