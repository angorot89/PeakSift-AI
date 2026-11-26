"""Driving a resumable upload to completion, safely.

- **Resume, never restart:** the loop first asks the provider how many bytes it has
  (``query_upload``) and always sends the next chunk from the provider's confirmed offset —
  after a crash, a timeout or a partial acceptance alike. Bytes are never sent twice and a
  second video is never created for the same session.
- **Monotonic, real progress:** ``on_progress`` receives only provider-confirmed byte counts,
  and never a smaller one than before (a provider answer that goes backwards is an error).
- **Attempt ownership:** ``still_owner`` runs before every chunk; a fenced-out attempt raises
  there and stops without touching the session further.
- **Bounded retries:** retryable failures (network, rate limiting, provider errors) are
  retried with exponential backoff, at most ``max_retries`` times in a row; anything else —
  and an expired session, which needs a new session — is raised to the caller.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass

from app.services.publishing.provider import (
    ProviderAuth,
    PublishErrorCode,
    PublishingProvider,
    PublishProviderError,
    UploadProgress,
)


@dataclass(frozen=True)
class UploadSource:
    size: int
    read: Callable[[int, int], bytes]  # (offset, length) -> exactly that many bytes


def run_upload(
    provider: PublishingProvider,
    auth: ProviderAuth,
    session_uri: str,
    source: UploadSource,
    *,
    chunk_bytes: int,
    on_progress: Callable[[int], None],
    still_owner: Callable[[], None],
    max_retries: int = 5,
    backoff_seconds: float = 2.0,
    sleep: Callable[[float], None] = time.sleep,
) -> UploadProgress:
    failures = 0
    reported = -1
    progress: UploadProgress | None = None

    def report(confirmed: int) -> None:
        nonlocal reported
        if confirmed < reported:
            raise PublishProviderError(PublishErrorCode.PROVIDER_ERROR)
        if confirmed > reported:
            reported = confirmed
            on_progress(confirmed)

    while progress is None or not progress.complete:
        still_owner()
        try:
            if progress is None:  # first step, or after a failure: where does the upload stand?
                progress = provider.query_upload(auth, session_uri, source.size)
            else:
                offset = progress.confirmed_bytes
                planned = getattr(provider, "chunk_length", None)
                length = (
                    planned(session_uri, offset, source.size)  # the platform's declared plan
                    if planned is not None
                    else min(chunk_bytes, source.size - offset)
                )
                data = source.read(offset, length)
                if len(data) != length:
                    raise OSError("the source returned fewer bytes than requested")
                answer = provider.upload_chunk(auth, session_uri, data, offset, source.size)
                if answer.confirmed_bytes < offset:
                    raise PublishProviderError(PublishErrorCode.PROVIDER_ERROR)
                stalled = answer.confirmed_bytes == offset and not answer.complete
                failures = failures + 1 if stalled else 0
                if failures > max_retries:
                    raise PublishProviderError(PublishErrorCode.PROVIDER_ERROR)
                progress = answer
            report(progress.confirmed_bytes)
        except PublishProviderError as error:
            if (
                not error.retryable
                or error.code == PublishErrorCode.UPLOAD_SESSION_EXPIRED
                or failures >= max_retries
            ):
                raise
            failures += 1
            sleep(backoff_seconds * 2 ** (failures - 1))
            progress = None  # ask the provider again before sending anything
    return progress
