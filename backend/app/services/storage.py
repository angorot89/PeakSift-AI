"""Private media storage: a local directory or an S3-compatible bucket.

Objects are addressed by *storage keys* that the application generates
(``videos/<uuid>.<ext>``); browser-supplied names never become keys or paths. Two providers
implement one small contract, :class:`StorageProvider`:

- :class:`LocalStorageProvider` — files under ``MEDIA_ROOT`` (development, single host);
- :class:`S3StorageProvider` — a private bucket on an S3-compatible service (AWS S3, MinIO,
  Cloudflare R2, ...). Objects are written without ACLs, so they inherit the bucket's
  private default; nothing here creates a public or presigned URL.

``STORAGE_BACKEND`` selects one (:func:`storage_from_settings`). The contract is what the
API and workers need: stream a byte range, store a stream or a local file, download an
object to a local workspace (FFmpeg reads local files), check presence and size, delete.
"Missing" (:class:`ObjectNotFound`) and "storage broken" (:class:`StorageUnavailable`) stay
distinct, so an outage is never mistaken for a deleted artifact.
"""

import mimetypes
import os
import re
import shutil
import tempfile
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Any, BinaryIO, Protocol

if TYPE_CHECKING:
    from app.core.config import Settings

CHUNK_SIZE = 1024 * 1024  # 1 MiB

# Keys are relative, slash-separated, and made only of safe characters.
_KEY_PATTERN = re.compile(r"^[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*(?:\.[A-Za-z0-9]{1,16})?$")
_EXTENSION_PATTERN = re.compile(r"^[A-Za-z0-9]{1,16}$")


class StorageError(Exception):
    """Base class for storage failures."""


class InvalidStorageKey(StorageError):
    """The key is malformed or would resolve outside the media root."""


class FileTooLarge(StorageError):
    def __init__(self, limit: int) -> None:
        super().__init__(f"File exceeds the maximum size of {limit} bytes")
        self.limit = limit


class ObjectNotFound(StorageError):
    """No object is stored under the key."""


class ObjectExists(StorageError):
    """An object is already stored under the key; keys are never overwritten."""


class StorageUnavailable(StorageError):
    """The storage backend could not be reached or refused the request."""


def generate_key(extension: str, category: str = "videos") -> str:
    """A unique key such as ``videos/3f2c...9a.mp4``. The extension must be plain."""
    extension = extension.lower().lstrip(".")
    if not _EXTENSION_PATTERN.fullmatch(extension):
        raise InvalidStorageKey(f"Unsafe file extension: {extension!r}")
    return f"{category}/{uuid.uuid4().hex}.{extension}"


def validate_key(key: str) -> str:
    if not isinstance(key, str) or not _KEY_PATTERN.fullmatch(key) or ".." in key.split("/"):
        raise InvalidStorageKey("Invalid storage key")
    return key


class StorageProvider(Protocol):
    """What the application needs from media storage, whatever the backend."""

    backend: str

    def exists(self, key: str) -> bool: ...

    def size(self, key: str) -> int: ...

    def save(self, stream: BinaryIO, key: str, *, max_bytes: int | None = None) -> int: ...

    def put_file(self, source: Path, key: str) -> int: ...

    def download_file(self, key: str, destination: Path) -> int: ...

    def fetch(self, key: str, directory: Path) -> Path: ...

    def iter_range(self, key: str, start: int, end: int) -> Iterator[bytes]: ...

    def delete(self, key: str) -> None: ...

    def check(self) -> None: ...


def copy_limited(stream: BinaryIO, target: BinaryIO, max_bytes: int | None) -> int:
    """Copy in 1 MiB chunks; raise ``FileTooLarge`` past ``max_bytes``. Returns the count."""
    written = 0
    while chunk := stream.read(CHUNK_SIZE):
        written += len(chunk)
        if max_bytes is not None and written > max_bytes:
            raise FileTooLarge(max_bytes)
        target.write(chunk)
    return written


def _open_new(path: Path) -> BinaryIO:
    """Open ``path`` for writing, creating its directory. A concurrent delete may prune that
    directory between the two steps (it removes directories it leaves empty), so retry."""
    for _ in range(5):
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            return path.open("wb")
        except FileNotFoundError:
            continue
    raise StorageError("Could not create the storage directory")


def _partial_for(destination: Path) -> Path:
    return destination.with_name(f".{destination.name}.part")


class LocalStorageProvider:
    """Files under a root directory; keys resolve only through :meth:`path_for`."""

    backend = "local"
    generate_key = staticmethod(generate_key)

    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()

    def path_for(self, key: str) -> Path:
        """Absolute path for a key, guaranteed to be inside the media root."""
        validate_key(key)
        path = (self.root / key).resolve()
        if self.root not in path.parents:
            raise InvalidStorageKey("Storage key escapes the media root")
        return path

    def exists(self, key: str) -> bool:
        return self.path_for(key).is_file()

    def size(self, key: str) -> int:
        path = self.path_for(key)
        if not path.is_file():
            raise ObjectNotFound("Object not found")
        return path.stat().st_size

    def save(self, stream: BinaryIO, key: str, *, max_bytes: int | None = None) -> int:
        """Copy ``stream`` to ``key`` in chunks and return the byte count.

        The data goes to a temporary sibling first and is renamed into place at the end, so
        a reader never sees a half-written file and a failure (including exceeding
        ``max_bytes``) leaves nothing behind. Existing keys are never overwritten.
        """
        path = self.path_for(key)
        if path.exists():
            raise ObjectExists("Storage key already exists")
        partial = _partial_for(path)
        try:
            with _open_new(partial) as target:
                written = copy_limited(stream, target, max_bytes)
            os.replace(partial, path)
        except BaseException:
            partial.unlink(missing_ok=True)
            raise
        return written

    def put_file(self, source: Path, key: str) -> int:
        """Copy a local file in under ``key`` (never overwriting). On the same filesystem
        the file is hard-linked rather than copied; callers never modify a stored source."""
        path = self.path_for(key)
        if path.exists():
            raise ObjectExists("Storage key already exists")
        partial = _partial_for(path)
        for _ in range(5):
            path.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.link(source, partial)
            except FileNotFoundError:
                if not Path(source).is_file():
                    raise
                continue  # the directory was pruned by a concurrent delete: retry
            except OSError:
                break  # another filesystem (or links unsupported): copy instead
            os.replace(partial, path)
            return path.stat().st_size
        with Path(source).open("rb") as stream:
            return self.save(stream, key)

    def download_file(self, key: str, destination: Path) -> int:
        """Copy the object to ``destination`` (whose directory must exist)."""
        path = self.path_for(key)
        if not path.is_file():
            raise ObjectNotFound("Object not found")
        destination = Path(destination)
        partial = _partial_for(destination)
        try:
            shutil.copyfile(path, partial)
            os.replace(partial, destination)
        except BaseException:
            partial.unlink(missing_ok=True)
            raise
        return destination.stat().st_size

    def fetch(self, key: str, directory: Path) -> Path:
        """A local path to read the object from: the stored file itself (no copy). Callers
        only ever read it; ``directory`` is unused here."""
        path = self.path_for(key)
        if not path.is_file():
            raise ObjectNotFound("Object not found")
        return path

    def iter_range(self, key: str, start: int, end: int) -> Iterator[bytes]:
        """Bytes ``[start, end]`` in chunks; the file opens now and closes with the iterator."""
        path = self.path_for(key)
        try:
            handle = path.open("rb")
        except FileNotFoundError:
            raise ObjectNotFound("Object not found") from None
        return _iter_file(handle, start, end)

    def delete(self, key: str) -> None:
        """Remove the file if present, and directories it leaves empty. Deleting a missing
        key is not an error."""
        path = self.path_for(key)
        path.unlink(missing_ok=True)
        for parent in path.parents:
            if parent == self.root:
                break
            try:
                parent.rmdir()
            except OSError:
                break  # not empty (or already gone)

    def check(self) -> None:
        try:
            self.root.mkdir(parents=True, exist_ok=True)
        except OSError:
            raise StorageUnavailable("The media directory is not usable") from None
        if not self.root.is_dir() or not os.access(self.root, os.R_OK | os.W_OK | os.X_OK):
            raise StorageUnavailable("The media directory is not usable")


def _iter_file(handle: BinaryIO, start: int, end: int) -> Iterator[bytes]:
    with handle:
        handle.seek(start)
        remaining = end - start + 1
        while remaining > 0:
            chunk = handle.read(min(CHUNK_SIZE, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


# NoSuchBucket is deliberately absent: a missing bucket means storage is broken.
_MISSING_CODES = frozenset({"404", "NoSuchKey", "NotFound"})


class S3StorageProvider:
    """A private bucket on an S3-compatible service, through a boto3 S3 client."""

    backend = "s3"
    generate_key = staticmethod(generate_key)

    def __init__(self, client: Any, bucket: str) -> None:
        self._client = client
        self.bucket = bucket

    @classmethod
    def from_settings(cls, settings: "Settings") -> "S3StorageProvider":
        import boto3
        from botocore.config import Config

        access_key = settings.s3_access_key_id
        secret_key = settings.s3_secret_access_key
        client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url or None,
            region_name=settings.s3_region,
            use_ssl=settings.s3_secure,
            # Without explicit keys boto3 uses its standard chain (e.g. an instance role).
            aws_access_key_id=access_key.get_secret_value() if access_key else None,
            aws_secret_access_key=secret_key.get_secret_value() if secret_key else None,
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": "path" if settings.s3_path_style else "auto"},
                connect_timeout=settings.s3_connect_timeout_seconds,
                read_timeout=settings.s3_read_timeout_seconds,
                retries={"mode": "standard", "max_attempts": 3},
            ),
        )
        return cls(client, settings.s3_bucket)

    # -- errors: botocore exceptions never leave this class --------------------------------

    def _call(self, operation: str, **kwargs: Any) -> Any:
        from botocore.exceptions import BotoCoreError, ClientError

        try:
            return getattr(self._client, operation)(Bucket=self.bucket, **kwargs)
        except ClientError as exc:
            raise self._translate(exc) from None
        except BotoCoreError:
            raise StorageUnavailable("Object storage request failed") from None

    @staticmethod
    def _translate(exc: Exception) -> StorageError:
        code = str(getattr(exc, "response", {}).get("Error", {}).get("Code", ""))
        if code in _MISSING_CODES:
            return ObjectNotFound("Object not found")
        return StorageUnavailable("Object storage request failed")

    # -- contract --------------------------------------------------------------------------

    def _head(self, key: str) -> dict[str, Any]:
        try:
            return self._call("head_object", Key=validate_key(key))
        except ObjectNotFound:
            # A HEAD response has no error body, so a missing *bucket* is also a bare 404.
            # Confirm the bucket is there before calling the object missing: an outage or
            # misconfiguration must never look like a deleted artifact.
            self.check()
            raise

    def exists(self, key: str) -> bool:
        try:
            self._head(key)
        except ObjectNotFound:
            return False
        return True

    def size(self, key: str) -> int:
        return int(self._head(key)["ContentLength"])

    def save(self, stream: BinaryIO, key: str, *, max_bytes: int | None = None) -> int:
        """Spool ``stream`` to a temporary file (enforcing ``max_bytes``), then upload it."""
        validate_key(key)
        with tempfile.TemporaryFile() as spool:
            written = copy_limited(stream, spool, max_bytes)
            spool.seek(0)
            self._upload(spool, key)
        return written

    def put_file(self, source: Path, key: str) -> int:
        validate_key(key)
        with Path(source).open("rb") as stream:
            size = os.fstat(stream.fileno()).st_size
            self._upload(stream, key)
        return size

    def _upload(self, stream: BinaryIO, key: str) -> None:
        # Keys are fresh UUIDs, so a check-then-write race needs two writers on one new key;
        # the check still stops a caller from replacing an artifact by mistake.
        if self.exists(key):
            raise ObjectExists("Storage key already exists")
        content_type = mimetypes.guess_type(key)[0] or "application/octet-stream"
        from boto3.exceptions import S3UploadFailedError
        from botocore.exceptions import BotoCoreError, ClientError

        # upload_fileobj switches to a multipart upload for large files (and aborts it on
        # failure); no ACL is sent, so the object stays as private as the bucket.
        try:
            self._client.upload_fileobj(
                stream, self.bucket, key, ExtraArgs={"ContentType": content_type}
            )
        except (ClientError, BotoCoreError, S3UploadFailedError):
            raise StorageUnavailable("Object storage upload failed") from None

    def download_file(self, key: str, destination: Path) -> int:
        destination = Path(destination)
        partial = _partial_for(destination)
        body = self._call("get_object", Key=validate_key(key))["Body"]
        try:
            with partial.open("wb") as target:
                for chunk in _read_body(body):
                    target.write(chunk)
            os.replace(partial, destination)
        except BaseException:
            partial.unlink(missing_ok=True)
            raise
        return destination.stat().st_size

    def fetch(self, key: str, directory: Path) -> Path:
        """Download the object into ``directory`` (a job's workspace) and return the copy."""
        destination = Path(directory) / validate_key(key).rsplit("/", 1)[-1]
        self.download_file(key, destination)
        return destination

    def iter_range(self, key: str, start: int, end: int) -> Iterator[bytes]:
        """Request ``bytes=start-end`` now (so a missing object fails before any response
        starts) and stream the body in chunks; the connection closes with the iterator."""
        body = self._call("get_object", Key=validate_key(key), Range=f"bytes={start}-{end}")["Body"]
        return _read_body(body)

    def delete(self, key: str) -> None:
        self._call("delete_object", Key=validate_key(key))  # absent keys are not an error

    def check(self) -> None:
        try:
            self._call("head_bucket")
        except ObjectNotFound:
            raise StorageUnavailable("The media bucket does not exist") from None


def _read_body(body: Any) -> Iterator[bytes]:
    from botocore.exceptions import BotoCoreError

    try:
        while chunk := body.read(CHUNK_SIZE):
            yield chunk
    except BotoCoreError:
        raise StorageUnavailable("Object storage read failed") from None
    finally:
        body.close()


def storage_from_settings(settings: "Settings") -> StorageProvider:
    if settings.storage_backend == "s3":
        return S3StorageProvider.from_settings(settings)
    return LocalStorageProvider(settings.media_root)


_cached: "tuple[Settings, StorageProvider] | None" = None


def media_storage(settings: "Settings") -> StorageProvider:
    """The configured provider, built once per settings object (an S3 client is
    thread-safe and costly to create). Used by the API and the workers alike."""
    global _cached
    if _cached is None or _cached[0] is not settings:
        _cached = (settings, storage_from_settings(settings))
    return _cached[1]
