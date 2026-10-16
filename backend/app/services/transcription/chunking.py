"""Split normalized audio into fixed-duration chunks and map chunk times back to video time.

Chunks are deterministic, non-overlapping slices of ``transcription/<id>/normalized.mp3``
written to ``transcription/<id>/chunks/NNNN.mp3``. Each chunk records its absolute start,
so a provider segment at ``12.4 → 18.9`` inside the chunk starting at ``600`` is stored as
``612.4 → 618.9``. Boundaries are plain time cuts (no silence detection); a word spoken
across a boundary may be split between two segments — documented limitation for V0.3.
"""

import logging
import math
import os
import shutil
import subprocess
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from app.services.audio_extraction import AUDIO_BITRATE, AUDIO_CHANNELS, AUDIO_SAMPLE_RATE
from app.services.ffprobe import ProbeError, probe_audio
from app.services.storage import LocalStorageProvider
from app.services.transcription.contract import ProviderSegment

logger = logging.getLogger(__name__)

# A final remainder shorter than this is folded into the previous chunk instead of
# becoming its own near-empty chunk.
MIN_LAST_CHUNK_SECONDS = 1.0


@dataclass(frozen=True)
class ChunkPlan:
    index: int
    start_seconds: float
    duration_seconds: float


@dataclass(frozen=True)
class AudioChunk:
    index: int
    storage_key: str
    start_seconds: float
    duration_seconds: float


class ChunkingError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def chunks_prefix(transcription_id: uuid.UUID | str) -> str:
    return f"transcription/{transcription_id}/chunks"


def chunk_key(transcription_id: uuid.UUID | str, index: int) -> str:
    return f"{chunks_prefix(transcription_id)}/{index:04d}.mp3"


def plan_chunks(total_seconds: float, chunk_seconds: float) -> list[ChunkPlan]:
    """Deterministic, contiguous, non-overlapping chunks covering [0, total_seconds]."""
    if not total_seconds or total_seconds <= 0:
        raise ChunkingError("invalid_duration", "The audio has no usable duration")
    if chunk_seconds <= 0:
        raise ChunkingError("invalid_chunk_size", "Chunk duration must be positive")

    count = max(1, math.ceil(total_seconds / chunk_seconds))
    plans: list[ChunkPlan] = []
    for index in range(count):
        start = index * chunk_seconds
        duration = min(chunk_seconds, total_seconds - start)
        plans.append(ChunkPlan(index=index, start_seconds=start, duration_seconds=duration))

    if len(plans) > 1 and plans[-1].duration_seconds < MIN_LAST_CHUNK_SECONDS:
        tail = plans.pop()
        previous = plans[-1]
        plans[-1] = ChunkPlan(
            index=previous.index,
            start_seconds=previous.start_seconds,
            duration_seconds=previous.duration_seconds + tail.duration_seconds,
        )
    return plans


def build_chunk_command(
    ffmpeg_path: str, source: Path, target: Path, start: float, duration: float
) -> list[str]:
    # The normalized MP3 is constant-bitrate, so input seeking (-ss before -i) lands
    # within one MP3 frame (~26 ms) of the requested time and stays fast on long files.
    return [
        ffmpeg_path,
        "-v",
        "error",
        "-nostdin",
        "-y",
        "-ss",
        f"{start:.3f}",
        "-i",
        str(source),
        "-t",
        f"{duration:.3f}",
        "-vn",
        "-ac",
        str(AUDIO_CHANNELS),
        "-ar",
        str(AUDIO_SAMPLE_RATE),
        "-b:a",
        AUDIO_BITRATE,
        "-codec:a",
        "libmp3lame",
        "-f",
        "mp3",
        str(target),
    ]


def split_audio(
    source: Path,
    storage: LocalStorageProvider,
    transcription_id: uuid.UUID | str,
    *,
    total_seconds: float,
    chunk_seconds: float,
    ffmpeg_path: str = "ffmpeg",
    ffprobe_path: str = "ffprobe",
    timeout_seconds: float = 600,
) -> list[AudioChunk]:
    """Write every chunk to storage. On any failure, no chunk files are left behind."""
    if not source.is_file():
        raise ChunkingError("source_missing", "The normalized audio file is missing")
    plans = plan_chunks(total_seconds, chunk_seconds)
    chunks: list[AudioChunk] = []
    try:
        for plan in plans:
            key = chunk_key(transcription_id, plan.index)
            target = storage.path_for(key)
            target.parent.mkdir(parents=True, exist_ok=True)
            partial = target.with_name(f".{target.name}.part")
            command = build_chunk_command(
                ffmpeg_path, source, partial, plan.start_seconds, plan.duration_seconds
            )
            try:
                result = subprocess.run(
                    command, capture_output=True, timeout=timeout_seconds, check=False
                )
            except FileNotFoundError:
                raise ChunkingError(
                    "ffmpeg_missing", "ffmpeg is not installed on the server"
                ) from None
            except subprocess.TimeoutExpired:
                partial.unlink(missing_ok=True)
                raise ChunkingError(
                    "ffmpeg_timeout", f"Splitting audio timed out after {timeout_seconds:g} seconds"
                ) from None
            if result.returncode != 0 or not partial.is_file() or partial.stat().st_size == 0:
                logger.warning(
                    "chunk %s failed (exit %s): %s",
                    plan.index,
                    result.returncode,
                    result.stderr.decode(errors="replace")[-300:],
                )
                partial.unlink(missing_ok=True)
                raise ChunkingError(
                    "chunk_failed",
                    f"Could not create audio chunk {plan.index} (ffmpeg exit {result.returncode})",
                )
            os.replace(partial, target)

            duration = plan.duration_seconds
            try:
                probed = probe_audio(target, ffprobe_path=ffprobe_path).duration_seconds
                if probed:
                    duration = probed
            except ProbeError:
                pass
            chunks.append(
                AudioChunk(
                    index=plan.index,
                    storage_key=key,
                    start_seconds=plan.start_seconds,
                    duration_seconds=duration,
                )
            )
    except BaseException:
        cleanup_chunks(storage, transcription_id)
        raise
    return chunks


def attempt_workspace(transcription_id: uuid.UUID | str, task_id: str | None) -> str:
    """``<transcription-id>/<attempt-tag>``: where one attempt keeps its normalized audio and
    chunks. Passed wherever a transcription id names a storage location, so a stalled worker
    of an older attempt can only ever touch its own files."""
    tag = "".join(ch for ch in (task_id or "inline") if ch.isalnum())[:16] or "inline"
    return f"{uuid.UUID(str(transcription_id))}/{tag}"


def cleanup_other_workspaces(
    storage: LocalStorageProvider, transcription_id: uuid.UUID | str, keep: str
) -> None:
    """Remove derived files of earlier attempts (and the pre-V0.6 flat layout), keeping
    ``keep`` (a workspace from ``attempt_workspace``)."""
    root = storage.path_for(f"transcription/{uuid.UUID(str(transcription_id))}")
    if not root.is_dir():
        return
    keep_name = keep.rsplit("/", 1)[-1]
    for entry in root.iterdir():
        if entry.name == keep_name:
            continue
        if entry.is_dir() and not entry.is_symlink():
            shutil.rmtree(entry, ignore_errors=True)
        else:
            entry.unlink(missing_ok=True)


def cleanup_chunks(storage: LocalStorageProvider, transcription_id: uuid.UUID | str) -> None:
    """Delete the chunk directory; the normalized audio next to it is kept."""
    directory = storage.path_for(chunks_prefix(transcription_id))
    if directory.is_dir():
        shutil.rmtree(directory, ignore_errors=True)


def shift_segments(
    segments: Iterable[ProviderSegment], offset_seconds: float
) -> tuple[ProviderSegment, ...]:
    """Move chunk-relative segment times into absolute time by adding the chunk start."""
    if offset_seconds < 0:
        raise ChunkingError("invalid_offset", "Chunk offset cannot be negative")
    return tuple(
        ProviderSegment(
            start=round(segment.start + offset_seconds, 3),
            end=round(segment.end + offset_seconds, 3),
            text=segment.text,
            speaker=segment.speaker,
        )
        for segment in segments
    )
