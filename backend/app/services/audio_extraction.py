"""Extract speech-ready audio from a source video with FFmpeg.

Output is MP3, mono, 16 kHz, 64 kbps: compact enough for multi-hour streams, accepted
by local and hosted transcription providers, and sufficient for speech.
"""

import logging
import os
import re
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path

from app.services.ffprobe import ProbeError, probe_audio
from app.services.storage import LocalStorageProvider

logger = logging.getLogger(__name__)

AUDIO_SAMPLE_RATE = 16_000
AUDIO_CHANNELS = 1
AUDIO_BITRATE = "64k"

_NO_STREAM_PATTERN = re.compile(
    r"does not contain any stream|Stream map .* matches no streams", re.I
)


@dataclass(frozen=True)
class ExtractedAudio:
    storage_key: str
    size_bytes: int
    duration_seconds: float | None


class AudioExtractionError(Exception):
    """Extraction failed. ``code`` is stable for callers; ``message`` is safe to store/show."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def normalized_audio_key(transcription_id: uuid.UUID | str) -> str:
    """Where a transcription's normalized audio lives, relative to the media root."""
    return f"transcription/{transcription_id}/normalized.mp3"


def build_ffmpeg_command(ffmpeg_path: str, source: Path, target: Path) -> list[str]:
    """ffmpeg argument list. Paths come from storage keys the application generated."""
    return [
        ffmpeg_path,
        "-v",
        "error",
        "-nostdin",
        "-y",
        "-i",
        str(source),
        "-vn",
        "-ac",
        str(AUDIO_CHANNELS),
        "-ar",
        str(AUDIO_SAMPLE_RATE),
        "-b:a",
        AUDIO_BITRATE,
        "-codec:a",
        "libmp3lame",
        # Explicit container: the output is written to a ".part" temp name first, from
        # which ffmpeg could not infer the format.
        "-f",
        "mp3",
        str(target),
    ]


def extract_normalized_audio(
    source: Path,
    storage: LocalStorageProvider,
    key: str,
    *,
    ffmpeg_path: str = "ffmpeg",
    ffprobe_path: str = "ffprobe",
    timeout_seconds: float = 3600,
) -> ExtractedAudio:
    """Write normalized audio for ``source`` to ``key``. Leaves nothing behind on failure."""
    target = storage.path_for(key)  # validates the key before anything else happens
    if not source.is_file() or source.stat().st_size == 0:
        raise AudioExtractionError("source_missing", "The source video file is missing")

    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(f".{target.name}.part")
    command = build_ffmpeg_command(ffmpeg_path, source, partial)

    try:
        try:
            result = subprocess.run(
                command, capture_output=True, timeout=timeout_seconds, check=False
            )
        except FileNotFoundError:
            raise AudioExtractionError(
                "ffmpeg_missing", "ffmpeg is not installed on the server"
            ) from None
        except subprocess.TimeoutExpired:
            raise AudioExtractionError(
                "ffmpeg_timeout", f"Audio extraction timed out after {timeout_seconds:g} seconds"
            ) from None

        if result.returncode != 0:
            stderr = result.stderr.decode(errors="replace")
            # Logged for operators only; it may contain local paths.
            logger.warning("ffmpeg failed (exit %s): %s", result.returncode, stderr[-500:])
            if _NO_STREAM_PATTERN.search(stderr):
                raise AudioExtractionError("no_audio_stream", "The video has no audio track")
            raise AudioExtractionError(
                "ffmpeg_failed", f"Audio extraction failed (ffmpeg exit code {result.returncode})"
            )

        if not partial.is_file() or partial.stat().st_size == 0:
            raise AudioExtractionError("empty_output", "Audio extraction produced no audio")

        os.replace(partial, target)
    except BaseException:
        partial.unlink(missing_ok=True)
        target.unlink(missing_ok=True)
        raise

    try:
        duration = probe_audio(target, ffprobe_path=ffprobe_path).duration_seconds
    except ProbeError:
        duration = None
    return ExtractedAudio(
        storage_key=key, size_bytes=target.stat().st_size, duration_seconds=duration
    )
