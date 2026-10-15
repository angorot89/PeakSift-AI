"""Storage backend settings: validated by name (never value) and turned into a provider."""

import pytest
from pydantic import ValidationError

from app.core import config
from app.core.config import Settings, storage_problems
from app.services.storage import LocalStorageProvider, S3StorageProvider, storage_from_settings

SECRET = "pK3x9QzR7mVw2LtYb8NcJ4hF6sDgA1eU5oIqWr0ZyXv"
S3_SECRET = "minio-secret-value-never-printed"


def s3(**overrides) -> dict:
    values = {
        "secret_key": SECRET,
        "database_url": "postgresql+psycopg://app@db:5432/peaksift",
        "storage_backend": "s3",
        "s3_endpoint_url": "https://storage.peaksift.example",
        "s3_bucket": "peaksift-media",
        "s3_access_key_id": "peaksift-app",
        "s3_secret_access_key": S3_SECRET,
    }
    values.update(overrides)
    return values


@pytest.fixture
def pipelines_ready(monkeypatch):
    monkeypatch.setattr(config, "S3_MEDIA_PIPELINES_READY", True)


def test_local_is_the_default_and_needs_nothing_else():
    settings = Settings(secret_key=SECRET, database_url="postgresql+psycopg://localhost/x")
    assert settings.storage_backend == "local"
    assert storage_problems(settings) == []
    assert isinstance(storage_from_settings(settings), LocalStorageProvider)


def test_s3_is_refused_until_the_media_pipelines_use_it():
    with pytest.raises(ValidationError) as excinfo:
        Settings(**s3())
    assert "not available until the media pipelines use it" in str(excinfo.value)


def test_a_complete_s3_configuration_builds_a_private_bucket_provider(pipelines_ready):
    settings = Settings(**s3(s3_path_style=True))
    storage = storage_from_settings(settings)

    assert isinstance(storage, S3StorageProvider) and storage.bucket == "peaksift-media"
    client_config = storage._client.meta.config
    assert storage._client.meta.endpoint_url == "https://storage.peaksift.example"
    assert client_config.s3["addressing_style"] == "path"
    assert client_config.signature_version == "s3v4"


@pytest.mark.parametrize(
    ("overrides", "problem"),
    [
        ({"s3_bucket": ""}, "S3_BUCKET"),
        ({"s3_bucket": "Bad_Bucket"}, "S3_BUCKET"),
        ({"s3_secret_access_key": None}, "set together"),
        ({"s3_endpoint_url": "ftp://storage.example"}, "S3_ENDPOINT_URL"),
        ({"s3_endpoint_url": "https://user:pw@storage.example"}, "S3_ENDPOINT_URL"),
        ({"s3_endpoint_url": "https://storage.example/some/path"}, "S3_ENDPOINT_URL"),
        ({"s3_endpoint_url": "http://minio:9000"}, "S3_SECURE"),
    ],
)
def test_incomplete_s3_settings_fail_fast_without_values(overrides, problem, pipelines_ready):
    with pytest.raises(ValidationError) as excinfo:
        Settings(**s3(**overrides))
    message = str(excinfo.value)
    assert problem in message
    assert S3_SECRET not in message and "user:pw" not in message


def test_plain_http_is_allowed_only_when_explicitly_insecure(pipelines_ready):
    settings = Settings(**s3(s3_endpoint_url="http://minio:9000", s3_secure=False))
    assert storage_problems(settings) == []


def test_s3_without_keys_uses_the_standard_credential_chain(pipelines_ready):
    settings = Settings(**s3(s3_access_key_id=None, s3_secret_access_key=None))
    assert storage_problems(settings) == []


def test_secrets_never_appear_in_the_settings_repr(pipelines_ready):
    settings = Settings(**s3())
    assert S3_SECRET not in repr(settings) and S3_SECRET not in str(settings.model_dump())
