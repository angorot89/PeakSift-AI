from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app.api.audio_assets import limits_router as audio_limits_router
from app.api.audio_assets import router as audio_assets_router
from app.api.auth import router as auth_router
from app.api.caption_styles import router as caption_styles_router
from app.api.caption_tracks import router as caption_tracks_router
from app.api.clip_detection import providers_router as clip_providers_router
from app.api.clip_detection import router as clip_detection_router
from app.api.clip_edits import media_router as edit_media_router
from app.api.clip_edits import router as clip_edits_router
from app.api.clip_media import router as clip_media_router
from app.api.clips import router as clips_router
from app.api.clips import video_clips_router
from app.api.health import router as health_router
from app.api.projects import router as projects_router
from app.api.reframe import router as reframe_router
from app.api.transcriptions import router as transcriptions_router
from app.api.video_content import router as video_content_router
from app.api.videos import router as videos_router
from app.core.config import Settings, get_settings
from app.core.errors import register_error_handlers
from app.core.observability import RequestContextMiddleware, configure_logging

ROUTERS = (
    health_router,
    auth_router,
    projects_router,
    videos_router,
    video_content_router,
    transcriptions_router,
    clip_providers_router,
    clip_detection_router,
    clips_router,
    video_clips_router,
    clip_media_router,
    clip_edits_router,
    edit_media_router,
    reframe_router,
    caption_tracks_router,
    caption_styles_router,
    audio_assets_router,
    audio_limits_router,
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
    # Outermost: every response (errors and rejected hosts included) carries a request id.
    application.add_middleware(RequestContextMiddleware)
    return application


app = create_app(get_settings())
