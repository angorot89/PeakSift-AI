from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.auth import router as auth_router
from app.api.health import router as health_router
from app.api.projects import router as projects_router
from app.core.config import get_settings

settings = get_settings()

app = FastAPI(title="PeakSift AI API", version="0.1.0")

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
