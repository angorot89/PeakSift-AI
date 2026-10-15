"""One rule for transcript timing against the media it describes.

Speech models can place the end of the final segment a little past the end of the audio
(decoder drift, encoder padding). Within a small documented tolerance —
``TRANSCRIPTION_TIMESTAMP_TOLERANCE_SECONDS`` — that end is normalized to the media's
duration; anything further is invalid provider output and is refused, never clamped. Used
when transcripts are persisted and again by clip detection, so consumers never apply
different boundary rules to the same transcript.
"""

import math


class MediaTimingError(ValueError):
    """A segment's times cannot belong to the media. The message is safe to store."""


def fit_to_media(
    start: float, end: float, duration: float | None, *, tolerance: float
) -> tuple[float, float]:
    """Return (start, end) inside ``[0, duration]``, or raise ``MediaTimingError``.

    ``duration`` None or 0 means unknown: only the basic ordering rules apply.
    """
    if not (math.isfinite(start) and math.isfinite(end)):
        raise MediaTimingError("A segment has a non-finite time")
    if start < 0:
        raise MediaTimingError(f"A segment starts before 0 ({start:.2f}s)")
    if end <= start:
        raise MediaTimingError(f"A segment ends before it starts ({start:.2f}s -> {end:.2f}s)")
    if not duration or duration <= 0:
        return start, end
    if start >= duration:
        raise MediaTimingError(
            f"A segment starts after the media ends ({start:.2f}s >= {duration:.2f}s)"
        )
    if end > duration + tolerance:
        raise MediaTimingError(f"A segment ends after the media ({end:.2f}s > {duration:.2f}s)")
    return start, min(end, duration)


def media_duration(*durations: float | None) -> float | None:
    """The authoritative duration: the shortest known positive duration of the media."""
    known = [d for d in durations if d and math.isfinite(d) and d > 0]
    return min(known) if known else None
