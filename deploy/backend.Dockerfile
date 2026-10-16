# syntax=docker/dockerfile:1.7
# PeakSift backend images, built from backend/ (the build context):
#
#   docker build -f deploy/backend.Dockerfile --target api    -t peaksift-api    backend
#   docker build -f deploy/backend.Dockerfile --target worker -t peaksift-worker backend
#
# One base: Python 3.12 on Debian bookworm with FFmpeg (built with libass), fontconfig and
# the caption fonts (Noto Sans, Noto Sans Arabic via fonts-noto-core, Symbola for emoji),
# the package installed system-wide, running as an unprivileged user. No secrets, media
# or model weights are baked in: configuration comes from the environment, media from
# the storage backend, models from the /models volume.

FROM python:3.12-slim-bookworm AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg fontconfig fonts-noto-core fonts-symbola \
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
# Scratch for jobs and model caches live on volumes owned by the service user.
RUN mkdir -p /work /models && chown peaksift:peaksift /work /models
ENV WORK_ROOT=/work \
    HF_HOME=/models/huggingface \
    REFRAME_MODEL_PATH=/models/face_detection_yunet_2023mar.onnx
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
