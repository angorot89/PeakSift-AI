"""Storage providers for the contract tests: local, in-process S3 (moto) and a live
S3-compatible service when one is configured.

The live backend runs only when ``TEST_S3_ENDPOINT_URL``, ``TEST_S3_ACCESS_KEY_ID`` and
``TEST_S3_SECRET_ACCESS_KEY`` are set (CI points them at a MinIO service; locally, any
disposable MinIO). Each use gets a fresh bucket that is emptied and removed afterwards.
"""

import os
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import boto3
from moto import mock_aws

from app.core.config import Settings
from app.services.storage import LocalStorageProvider, S3StorageProvider, StorageProvider

BACKENDS = ["local", "s3-moto", "s3-live"]
LIVE_ENV = ("TEST_S3_ENDPOINT_URL", "TEST_S3_ACCESS_KEY_ID", "TEST_S3_SECRET_ACCESS_KEY")


def live_available() -> bool:
    return all(os.environ.get(name) for name in LIVE_ENV)


def skip_unless_live() -> None:
    """Skip a live-S3 case locally; in CI (``REQUIRE_LIVE_S3=1``) a missing service fails."""
    if live_available():
        return
    import pytest

    if os.environ.get("REQUIRE_LIVE_S3"):
        pytest.fail("REQUIRE_LIVE_S3 is set but TEST_S3_* is not configured")
    pytest.skip("TEST_S3_ENDPOINT_URL / credentials are not set")


def live_settings(bucket: str) -> Settings:
    """Settings for the live service, built without validation (S3 is not selectable as
    the application backend yet; the provider itself is what is under test)."""
    endpoint = os.environ["TEST_S3_ENDPOINT_URL"]
    return Settings.model_construct(
        storage_backend="s3",
        s3_endpoint_url=endpoint,
        s3_region=os.environ.get("TEST_S3_REGION", "us-east-1"),
        s3_bucket=bucket,
        s3_access_key_id=_secret(os.environ["TEST_S3_ACCESS_KEY_ID"]),
        s3_secret_access_key=_secret(os.environ["TEST_S3_SECRET_ACCESS_KEY"]),
        s3_path_style=True,
        s3_secure=endpoint.startswith("https://"),
        s3_connect_timeout_seconds=5,
        s3_read_timeout_seconds=30,
    )


def _secret(value: str):
    from pydantic import SecretStr

    return SecretStr(value)


def _empty_and_remove(client, bucket: str) -> None:
    for page in client.get_paginator("list_objects_v2").paginate(Bucket=bucket):
        for item in page.get("Contents", []):
            client.delete_object(Bucket=bucket, Key=item["Key"])
    client.delete_bucket(Bucket=bucket)


@contextmanager
def provider(kind: str, tmp_path: Path, monkeypatch) -> Iterator[StorageProvider]:
    if kind == "local":
        yield LocalStorageProvider(tmp_path / "media")
        return
    if kind == "s3-moto":
        for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"):
            monkeypatch.setenv(name, "testing")
        monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
        with mock_aws():
            client = boto3.client("s3", region_name="us-east-1")
            client.create_bucket(Bucket="peaksift-contract")
            yield S3StorageProvider(client, "peaksift-contract")
        return
    assert kind == "s3-live" and live_available()
    bucket = f"peaksift-test-{uuid.uuid4().hex[:16]}"
    storage = S3StorageProvider.from_settings(live_settings(bucket))
    client = storage._client
    client.create_bucket(Bucket=bucket)
    try:
        yield storage
    finally:
        _empty_and_remove(client, bucket)
