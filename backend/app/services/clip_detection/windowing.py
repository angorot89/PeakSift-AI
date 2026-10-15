"""Stage A: prepare a transcript for analysis.

- normalise text safely (control characters out, whitespace collapsed, per-line cap)
- validate the timeline (absolute, ordered, inside the video) — refuse rather than repair
- fingerprint the transcript so candidates stay traceable to the exact snapshot
- group lines into bounded, overlapping analysis windows so a multi-hour transcript is
  analysed in many small requests, never one unbounded prompt
"""

import hashlib
import re
import unicodedata
from collections.abc import Iterable, Sequence

from app.services.clip_detection.contract import AnalysisWindow, TranscriptLine
from app.services.media_timing import MediaTimingError, fit_to_media

# A single transcript segment longer than this is cut; real speech segments are far shorter.
MAX_LINE_CHARS = 2000

_WHITESPACE = re.compile(r"\s+")


class TranscriptError(Exception):
    """The transcript cannot be analysed. ``code`` is stable; ``message`` is safe to show."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# --- text ------------------------------------------------------------------------------------


def normalize_text(text: str) -> str:
    """Printable text only, single spaces, trimmed, capped. Unicode letters are kept."""
    cleaned = "".join(
        ch for ch in text if ch in ("\n", "\t", " ") or not unicodedata.category(ch).startswith("C")
    )
    cleaned = _WHITESPACE.sub(" ", cleaned).strip()
    return cleaned[:MAX_LINE_CHARS]


# --- timeline --------------------------------------------------------------------------------


def prepare_lines(
    lines: Iterable[TranscriptLine], *, video_duration: float, tolerance_seconds: float
) -> tuple[TranscriptLine, ...]:
    """Normalise and validate transcript lines against the video.

    A small overshoot past the video's end (within ``tolerance_seconds``) is normalized to the
    end, exactly as at transcription; anything else invalid is refused, never "fixed".
    """
    prepared: list[TranscriptLine] = []
    previous_start = -1.0
    for index, line in enumerate(lines):
        start, end = float(line.start), float(line.end)
        try:  # the same media-bounds rule as at transcription (see media_timing.py)
            start, end = fit_to_media(start, end, video_duration, tolerance=tolerance_seconds)
        except MediaTimingError as error:
            raise TranscriptError(
                "transcript_invalid", f"Transcript line {index}: {error}"
            ) from None
        if start < previous_start:
            raise TranscriptError("transcript_invalid", f"Transcript line {index} is out of order")
        previous_start = start
        text = normalize_text(line.text)
        if not text:
            continue  # silence markers or empty segments carry no editorial content
        prepared.append(TranscriptLine(start=start, end=end, text=text))
    if not prepared:
        raise TranscriptError("transcript_empty", "The transcript contains no spoken words")
    return tuple(prepared)


def transcript_fingerprint(transcription_id: object, lines: Iterable[TranscriptLine]) -> str:
    """sha256 over the transcription id and every (start, end, text); stable across runs."""
    digest = hashlib.sha256(str(transcription_id).encode())
    for line in lines:
        digest.update(f"\x1f{line.start:.3f}\x1f{line.end:.3f}\x1f{line.text}\x1e".encode())
    return digest.hexdigest()


# --- windows ---------------------------------------------------------------------------------


def build_windows(
    lines: Sequence[TranscriptLine],
    *,
    window_seconds: float,
    overlap_seconds: float,
    max_chars: int,
    max_windows: int,
) -> tuple[AnalysisWindow, ...]:
    """Greedy, deterministic windows over prepared lines.

    A window takes consecutive lines while it stays within ``window_seconds`` of its first
    line's start and within ``max_chars`` of text; it always holds at least one line. The
    next window starts at the first line beginning at or after ``last.end - overlap`` so a
    moment straddling a boundary is seen whole by at least one window, but it always
    starts after the previous first line so progress is guaranteed. Every line belongs to
    at least one window.
    """
    if not lines:
        return ()
    if window_seconds <= 0 or max_chars <= 0:
        raise ValueError("window_seconds and max_chars must be positive")

    windows: list[AnalysisWindow] = []
    first = 0
    while first < len(lines):
        start_time = lines[first].start
        chars = 0
        last = first
        for index in range(first, len(lines)):
            line = lines[index]
            fits_time = line.end - start_time <= window_seconds
            fits_chars = chars + len(line.text) <= max_chars
            if index > first and not (fits_time and fits_chars):
                break
            chars += len(line.text)
            last = index
        window_lines = tuple(lines[first : last + 1])
        windows.append(
            AnalysisWindow(
                index=len(windows),
                start=window_lines[0].start,
                end=window_lines[-1].end,
                lines=window_lines,
            )
        )
        if len(windows) > max_windows:
            raise TranscriptError(
                "transcript_too_long",
                f"The transcript needs more than {max_windows} analysis windows",
            )
        if last + 1 >= len(lines):
            break
        # Rewind into the overlap, but never back to (or before) this window's first line.
        resume_from = window_lines[-1].end - overlap_seconds
        next_first = last + 1
        for index in range(last, first, -1):
            if lines[index].start >= resume_from:
                next_first = index
            else:
                break
        first = max(next_first, first + 1)
    return tuple(windows)


def excerpt(lines: Sequence[TranscriptLine], start: float, end: float) -> str:
    """The transcript text spoken inside [start, end] — our words, never the model's."""
    return " ".join(line.text for line in lines if line.end > start and line.start < end)
