from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.auth import router as auth_router
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
from app.core.config import get_settings
from app.core.errors import register_error_handlers

settings = get_settings()

app = FastAPI(title="PeakSift AI API", version="0.1.0")
register_error_handlers(app)  # before CORS, so error responses still get CORS headers

app.add_middleware(
    CORSMiddleware,
    # Explicit origin (never "*") because credentials are allowed.
    allow_origins=[settings.frontend_url.rstrip("/")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(auth_router)
app.include_router(projects_router)
app.include_router(videos_router)
app.include_router(video_content_router)
app.include_router(transcriptions_router)
app.include_router(clip_providers_router)
app.include_router(clip_detection_router)
app.include_router(clips_router)
app.include_router(video_clips_router)
app.include_router(clip_media_router)
app.include_router(clip_edits_router)
app.include_router(edit_media_router)
app.include_router(reframe_router)
