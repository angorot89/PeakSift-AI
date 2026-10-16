"""Shared test fixtures.

Tests run against a dedicated PostgreSQL database (``TEST_DATABASE_URL``), never the
developer's ``DATABASE_URL``. The schema is created with the real Alembic migrations once
per session, and every test runs inside a transaction that is rolled back afterwards.
"""

import os
import tempfile
from collections.abc import Generator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://localhost:5432/peaksift_test"
)

# Must happen before anything imports `app.*`: settings are read at import time.
# Test-only values take priority over a developer's `.env`.
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["SECRET_KEY"] = "test-only-secret-key-not-for-production-0123456789"
os.environ["APP_ENV"] = "test"
# Uploaded test media goes to a throwaway directory, never the developer's MEDIA_ROOT.
os.environ["MEDIA_ROOT"] = tempfile.mkdtemp(prefix="peaksift-test-media-")
# Job scratch space (inputs, intermediates, renders in validation), equally throwaway.
os.environ["WORK_ROOT"] = tempfile.mkdtemp(prefix="peaksift-test-work-")
# Background tasks run inline during tests; no broker or worker is required.
os.environ["CELERY_TASK_ALWAYS_EAGER"] = "1"

BACKEND_DIR = Path(__file__).resolve().parents[1]


def _alembic_config() -> Config:
    config = Config(BACKEND_DIR / "alembic.ini")
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    return config


@pytest.fixture(scope="session", autouse=True)
def migrated_database() -> Generator[None, None, None]:
    """Apply all migrations before the session and roll them back afterwards."""
    config = _alembic_config()
    command.upgrade(config, "head")
    yield
    command.downgrade(config, "base")


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    """A session whose work is discarded when the test ends.

    `create_savepoint` turns the application's `commit()` calls into savepoints, so the
    outer transaction can still be rolled back.
    """
    from app.core.database import engine

    with engine.connect() as connection:
        transaction = connection.begin()
        session = Session(bind=connection, join_transaction_mode="create_savepoint")
        try:
            yield session
        finally:
            session.close()
            transaction.rollback()


@pytest.fixture
def client(db_session: Session) -> Generator[TestClient, None, None]:
    """FastAPI test client wired to the rolled-back test session."""
    from app.core.database import get_db
    from app.main import app

    app.dependency_overrides[get_db] = lambda: db_session
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
