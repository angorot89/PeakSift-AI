"""Validation, probing, waveform peaks and storage of user-supplied audio (music and SFX).

An upload is accepted only when it really is audio: the extension and declared type must be
allow-listed, and ffprobe must find an audio stream with a supported codec inside the
matching container and a positive duration within the kind's limit. A file with a real video
stream (other than embedded cover art) is refused. The upload is hashed while it is stored;
the same file uploaded again for the same purpose in the same project returns the existing
asset. Every refusal removes the stored file: nothing corrupt or rejected is kept.

Waveform peaks are computed by decoding with FFmpeg to 8 kHz mono through a pipe and folding
the samples into a bounded number of buckets as they stream in — PCM is never stored or
sent anywhere.
"""

import hashlib
import logging
import math
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO

import numpy as np
from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import AudioAsset, AudioAssetKind, Project
from app.services.ffprobe import ProbeError, run_ffprobe
from app.services.storage import FileTooLarge, LocalStorageProvider
from app.services.video_upload import (
    GENERIC_CONTENT_TYPES,
    UploadValidationError,
    sanitize_filename,
    too_large_message,
)

logger = logging.getLogger(__name__)

# Extension -> (container family reported by ffprobe, MIME types a browser may send). The
# first MIME type is stored, so the type on record is canonical rather than client-chosen.
ALLOWED_AUDIO_TYPES: dict[str, tuple[str, tuple[str, ...]]] = {
    ".mp3": ("mp3", ("audio/mpeg", "audio/mp3")),
    ".wav": ("wav", ("audio/wav", "audio/x-wav", "audio/wave", "audio/vnd.wave")),
    ".m4a": ("mp4", ("audio/mp4", "audio/x-m4a", "audio/m4a")),
    ".aac": ("aac", ("audio/aac", "audio/x-aac", "audio/aacp")),
    ".ogg": ("ogg", ("audio/ogg", "application/ogg")),
    ".opus": ("ogg", ("audio/ogg", "audio/opus")),
}
ACCEPTED_EXTENSIONS = tuple(sorted(ALLOWED_AUDIO_TYPES))
# Codecs PeakSift mixes. WAV may be any linear PCM (pcm_s16le, pcm_s24le, pcm_f32le, ...).
ALLOWED_CODECS = frozenset({"mp3", "aac", "alac", "vorbis", "opus", "flac"})

WAVEFORM_SAMPLE_RATE = 8000
WAVEFORM_MIN_BUCKETS = 200
WAVEFORM_MAX_BUCKETS = 1000
WAVEFORM_BUCKETS_PER_SECOND = 20
WAVEFORM_TIMEOUT_SECONDS = 120.0
READ_CHUNK = 64 * 1024


@dataclass(frozen=True)
class AudioProbe:
    container: str
    codec: str
    duration_seconds: float
    sample_rate: int
    channels: int


def validate_audio_upload(filename: str | None, content_type: str | None) -> tuple[str, str, str]:
    """Return (safe_display_name, extension, canonical_content_type) or raise 415."""
    safe_name = sanitize_filename(filename, fallback="audio")
    extension = PurePosixPath(safe_name).suffix.lower()
    if extension not in ALLOWED_AUDIO_TYPES:
        raise UploadValidationError(
            415, f"Unsupported audio type. Use one of: {', '.join(ACCEPTED_EXTENSIONS)}"
        )
    declared = (content_type or "").split(";", 1)[0].strip().lower()
    accepted = ALLOWED_AUDIO_TYPES[extension][1]
    if declared not in accepted and declared not in GENERIC_CONTENT_TYPES:
        raise UploadValidationError(415, "The file's content type does not match its extension")
    return safe_name, extension, accepted[0]


def _positive_float(value: object) -> float | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def _positive_int(value: object) -> int | None:
    try:
        number = int(value)  # type: ignore[call-overload]
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def parse_audio_probe(data: dict[str, Any], extension: str) -> AudioProbe:
    """Check ffprobe's view of the file against what an audio asset must be.

    Raises ``UploadValidationError`` (415/422) with a message that never echoes the file.
    """
    streams = [s for s in data.get("streams", []) if isinstance(s, dict)]
    container = data.get("format") if isinstance(data.get("format"), dict) else {}
    format_names = str(container.get("format_name") or "").split(",")
    family = ALLOWED_AUDIO_TYPES[extension][0]
    if family not in format_names:
        raise UploadValidationError(415, "The file's contents do not match its extension")
    pictures = {id(s) for s in streams if (s.get("disposition") or {}).get("attached_pic") == 1}
    if any(s.get("codec_type") == "video" and id(s) not in pictures for s in streams):
        raise UploadValidationError(415, "This file contains video. Upload an audio file")
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if audio is None:
        raise UploadValidationError(415, "The file does not contain an audio stream")
    codec = str(audio.get("codec_name") or "")
    if codec not in ALLOWED_CODECS and not codec.startswith("pcm_"):
        raise UploadValidationError(415, "This audio codec is not supported")
    duration = _positive_float(container.get("duration")) or _positive_float(audio.get("duration"))
    sample_rate = _positive_int(audio.get("sample_rate"))
    channels = _positive_int(audio.get("channels"))
    if duration is None or sample_rate is None or channels is None:
        raise UploadValidationError(422, "The audio could not be read (no duration or format)")
    return AudioProbe(
        container=family,
        codec=codec[:64],
        duration_seconds=round(duration, 3),
        sample_rate=sample_rate,
        channels=channels,
    )


def probe_audio_asset(path: Path, extension: str, *, ffprobe_path: str) -> AudioProbe:
    import json

    try:
        raw = run_ffprobe(path, ffprobe_path=ffprobe_path)
        data = json.loads(raw)
    except (ProbeError, ValueError):
        raise UploadValidationError(422, "The audio file could not be read") from None
    if not isinstance(data, dict):
        raise UploadValidationError(422, "The audio file could not be read")
    return parse_audio_probe(data, extension)


def waveform_bucket_count(duration_seconds: float) -> int:
    buckets = round(duration_seconds * WAVEFORM_BUCKETS_PER_SECOND)
    return max(WAVEFORM_MIN_BUCKETS, min(WAVEFORM_MAX_BUCKETS, buckets))


def compute_waveform(
    path: Path,
    duration_seconds: float,
    *,
    ffmpeg_path: str,
    timeout_seconds: float = WAVEFORM_TIMEOUT_SECONDS,
) -> list[int]:
    """Peak amplitude per bucket, 0-100 % of full scale, streamed from an FFmpeg pipe."""
    buckets = waveform_bucket_count(duration_seconds)
    expected = max(1, round(duration_seconds * WAVEFORM_SAMPLE_RATE))
    peaks = np.zeros(buckets, dtype=np.int32)
    command = [
        ffmpeg_path, "-v", "error", "-nostdin", "-i", str(path), "-vn", "-ac", "1",
        "-ar", str(WAVEFORM_SAMPLE_RATE), "-f", "s16le", "-",
    ]  # fmt: skip
    with tempfile.TemporaryFile() as stderr:
        try:
            process = subprocess.Popen(
                command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=stderr
            )
        except OSError:
            raise UploadValidationError(422, "The audio file could not be decoded") from None
        # A watchdog kills a stuck decoder at the deadline, which ends the blocking read below.
        expired = threading.Event()

        def expire() -> None:
            expired.set()
            process.kill()

        watchdog = threading.Timer(timeout_seconds, expire)
        watchdog.daemon = True
        watchdog.start()
        position, carry = 0, b""
        try:
            assert process.stdout is not None
            while chunk := process.stdout.read(READ_CHUNK):
                chunk = carry + chunk
                usable = len(chunk) - len(chunk) % 2
                carry = chunk[usable:]
                samples = np.abs(np.frombuffer(chunk[:usable], dtype="<i2").astype(np.int32))
                if samples.size == 0:
                    continue
                index = (np.arange(position, position + samples.size) * buckets) // expected
                np.maximum.at(peaks, np.minimum(index, buckets - 1), samples)
                position += samples.size
            process.wait()
        except BaseException:
            process.kill()
            process.wait()
            raise
        finally:
            watchdog.cancel()
        if expired.is_set():
            raise UploadValidationError(422, "Reading the audio took too long")
        if process.returncode != 0 or position == 0:
            raise UploadValidationError(422, "The audio file could not be decoded")
    return [min(100, round(int(p) * 100 / 32768)) for p in peaks]


class _HashingReader:
    """Wrap an upload stream so storing it also computes its sha256 (one pass)."""

    def __init__(self, stream: BinaryIO) -> None:
        self.stream = stream
        self.digest = hashlib.sha256()

    def read(self, size: int = -1) -> bytes:
        data = self.stream.read(size)
        self.digest.update(data)
        return data


def max_duration_for(kind: AudioAssetKind, settings: Settings) -> float:
    return (
        settings.audio_sfx_max_duration_seconds
        if kind == AudioAssetKind.SFX
        else settings.audio_upload_max_duration_seconds
    )


def _existing(
    db: Session, project: Project, kind: AudioAssetKind, digest: str
) -> AudioAsset | None:
    return db.scalar(
        select(AudioAsset).where(
            AudioAsset.project_id == project.id,
            AudioAsset.kind == kind.value,
            AudioAsset.sha256 == digest,
        )
    )


def store_audio_upload(
    db: Session,
    storage: LocalStorageProvider,
    project: Project,
    upload: UploadFile,
    kind: AudioAssetKind,
    settings: Settings,
) -> tuple[AudioAsset, bool]:
    """Validate, store, probe and index an upload. Returns (asset, created).

    Leaves no file behind on any refusal or failure, and returns the project's existing asset
    (``created`` False) when the same file was already uploaded for the same purpose.
    """
    safe_name, extension, content_type = validate_audio_upload(upload.filename, upload.content_type)
    key = storage.generate_key(extension, category="audio")
    reader = _HashingReader(upload.file)
    try:
        size = storage.save(reader, key, max_bytes=settings.audio_upload_max_bytes)  # type: ignore[arg-type]
    except FileTooLarge as error:
        raise UploadValidationError(413, too_large_message(error.limit)) from None
    keep = False
    try:
        if size == 0:
            raise UploadValidationError(400, "The uploaded file is empty")
        digest = reader.digest.hexdigest()
        existing = _existing(db, project, kind, digest)
        if existing is not None:
            return existing, False
        path = storage.path_for(key)
        probed = probe_audio_asset(path, extension, ffprobe_path=settings.ffprobe_path)
        limit = max_duration_for(kind, settings)
        if probed.duration_seconds > limit:
            label = "Sound effects" if kind == AudioAssetKind.SFX else "Audio files"
            raise UploadValidationError(
                413, f"{label} can be at most {_duration_label(limit)} long"
            )
        peaks = compute_waveform(path, probed.duration_seconds, ffmpeg_path=settings.ffmpeg_path)
        asset = AudioAsset(
            project_id=project.id,
            kind=kind.value,
            display_name=safe_name,
            storage_key=key,
            content_type=content_type,
            file_size=size,
            sha256=digest,
            container=probed.container,
            codec=probed.codec,
            duration_seconds=probed.duration_seconds,
            sample_rate=probed.sample_rate,
            channels=probed.channels,
            waveform_peaks=peaks,
        )
        db.add(asset)
        try:
            db.commit()
        except IntegrityError:  # the same file, uploaded concurrently, won the constraint
            db.rollback()
            winner = _existing(db, project, kind, digest)
            if winner is None:
                raise
            return winner, False
        keep = True
        return asset, True
    finally:
        if not keep:
            storage.delete(key)


def _duration_label(seconds: float) -> str:
    if seconds >= 60 and seconds % 60 == 0:
        minutes = int(seconds // 60)
        return f"{minutes} minute{'s' if minutes != 1 else ''}"
    return f"{seconds:g} seconds"
