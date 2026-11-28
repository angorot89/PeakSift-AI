# syntax=docker/dockerfile:1.7
# PeakSift backend images, built from backend/ (the build context):
#
#   docker build -f deploy/backend.Dockerfile --target api    -t peaksift-api    backend
#   docker build -f deploy/backend.Dockerfile --target worker -t peaksift-worker backend
#
# One base: Python 3.12 on Debian bookworm with FFmpeg (built with libass), the PostgreSQL 16
# client tools (backups), fontconfig and the caption fonts (Noto Sans, Noto Sans Arabic via fonts-noto-core, Symbola for emoji),
# the package installed system-wide, running as an unprivileged user. No secrets, media
# or model weights are baked in: configuration comes from the environment, media from
# the storage backend, models from the /models volume.

FROM python:3.12-slim-bookworm AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
# PostgreSQL 16 client tools from the official PGDG repository: pg_dump must be at least the
# server's major version (Debian bookworm ships 15), for python -m app.cli.backup.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl gnupg \
 && install -d /usr/share/postgresql-common/pgdg \
 && curl -fsSL -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
      https://www.postgresql.org/media/keys/ACCC4CF8.asc \
 && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" \
      > /etc/apt/sources.list.d/pgdg.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg fontconfig fonts-noto-core fonts-symbola \
      postgresql-client-16 \
 && apt-get purge -y --auto-remove curl gnupg \
 && rm -rf /var/lib/apt/lists/* \
 && fc-cache -f \
 && groupadd --system --gid 10001 peaksift \
 && useradd --system --uid 10001 --gid peaksift --home-dir /app --shell /usr/sbin/nologin peaksift
WORKDIR /app
COPY pyproject.toml ./
COPY app ./app
RUN pip install ".[production]" && rm -rf build *.egg-info
COPY alembic.ini ./
COPY alembic ./alembic
COPY scripts ./scripts
# The caption style fonts (open-licence display fonts): exactly the pinned google/fonts files,
# sha256-verified by the script, with their licence files, read-only for the service user.
RUN python scripts/fetch_caption_fonts.py --dir /app/fonts
# The starter library (CC0 sounds and music, MIT stickers): the pinned GitHub release archive,
# sha256-verified as a whole and file by file.
RUN python scripts/fetch_library.py --dir /app/library
# Scratch for jobs and model caches live on volumes owned by the service user.
RUN mkdir -p /work /models && chown peaksift:peaksift /work /models
ENV WORK_ROOT=/work \
    CAPTION_FONTS_DIR=/app/fonts \
    LIBRARY_DIR=/app/library \
    HF_HOME=/models/huggingface \
    REFRAME_MODEL_PATH=/models/face_detection_yunet_2023mar.onnx \
    SEMANTIC_MODEL_DIR=/models/clip-vit-b-32
USER peaksift

# The API: gunicorn managing uvicorn workers. Access lines come from the application
# (path without query strings); gunicorn's own access log stays off.
FROM base AS api
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=8s --start-period=20s --retries=3 \
  CMD ["python", "-c", "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=5).status == 200 else 1)"]
CMD ["sh", "-c", "exec gunicorn app.main:app --worker-class uvicorn_worker.UvicornWorker --workers ${WEB_CONCURRENCY:-2} --bind 0.0.0.0:8000 --timeout 120 --graceful-timeout 30 --keep-alive 5"]

# The background worker: one job at a time per process (database state is the truth).
FROM base AS worker
HEALTHCHECK --interval=30s --timeout=20s --start-period=30s --retries=3 \
  CMD ["python", "-m", "app.cli.health"]
CMD ["sh", "-c", "exec celery -A app.workers.celery_app worker --loglevel=INFO --concurrency=${CELERY_CONCURRENCY:-1} --without-gossip --without-mingle"]
