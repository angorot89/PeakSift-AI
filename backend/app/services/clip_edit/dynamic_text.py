"""The dynamic caption text of a clip, exactly as the renderer will draw it.

One function for both the render pipeline and the editor preview (``GET …/caption-preview``),
so the preview shows the same cues, line breaks and word timing as the burned-in short:

- **aligned_word:** the words of a completed ``CaptionTrack`` of this clip, re-validated
  (finite, ordered, inside the clip) before use, grouped by the word-aware cue builder;
- **phrase_fallback:** the transcript's phrase cues (approximate timing, emoji kept), in the
  same shape but never highlighted per word.

Lines are fitted to the preset's real rendered width inside the General Social Safe Area.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import (
    CaptionTrack,
    CaptionTrackStatus,
    CaptionWord,
    Clip,
    TranscriptionStatus,
    TranscriptSegment,
)
from app.services.caption_timing.contract import TimedWord, TimingOutputError, validate_words
from app.services.clip_edit.caption_v2 import rules_for
from app.services.clip_edit.captions import SourceSegment, build_cues
from app.services.clip_edit.config import CaptionPosition, CaptionTiming, DynamicPreset
from app.services.clip_edit.cuts import CutsConfig, remap_words
from app.services.clip_edit.dynamic_cues import (
    SourceWord,
    WordCue,
    build_word_cues,
    phrase_cues,
)
from app.services.clip_edit.safe_area import caption_placement


class DynamicCaptionError(Exception):
    """The text cannot be built. ``code`` is stable; ``message`` is safe to show."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def transcript_segments(clip: Clip, db: Session) -> list[SourceSegment]:
    transcription = clip.video.transcription
    if transcription is None or transcription.status != TranscriptionStatus.COMPLETED:
        raise DynamicCaptionError(
            "transcript_unavailable", "Captions need a completed transcript for this video"
        )
    rows = db.scalars(
        select(TranscriptSegment)
        .where(TranscriptSegment.transcription_id == transcription.id)
        .order_by(TranscriptSegment.sequence_index)
    )
    return [SourceSegment(start=r.start_time, end=r.end_time, text=r.text) for r in rows]


def dynamic_cues(
    clip: Clip,
    db: Session,
    settings: Settings,
    *,
    preset: DynamicPreset,
    position: CaptionPosition,
    timing: CaptionTiming,
    track_id: str | uuid.UUID | None,
    cuts: CutsConfig | None = None,
) -> list[WordCue]:
    """Cues on the Short's timeline: with ``cuts``, words and phrases are moved past the
    removed parts *before* they are grouped, so a cue never spans a join's old pause."""
    clip_seconds = float(clip.duration_seconds)
    duration = cuts.output_duration(clip_seconds) if cuts else clip_seconds
    rules = rules_for(preset, caption_placement(position).margin_h)
    if timing != CaptionTiming.ALIGNED_WORD:
        phrases = build_cues(
            transcript_segments(clip, db),
            clip_start=clip.start_time,
            clip_end=clip.end_time,
            max_words=settings.caption_max_words,
            max_chars=settings.caption_max_chars,
            keep_emoji=True,
        )
        spans = [(c.start, c.end, c.text) for c in phrases]
        if cuts is not None:
            spans = [(*span, text) for s, e, text in spans if (span := cuts.span(s, e)) is not None]
        return phrase_cues(spans, clip_duration=duration, rules=rules)
    track = db.get(CaptionTrack, uuid.UUID(str(track_id))) if track_id else None
    usable = track is not None and track.status == CaptionTrackStatus.COMPLETED
    if not usable or track.clip_id != clip.id:
        raise DynamicCaptionError(
            "caption_track_unavailable",
            "The word timing for these captions is not available; generate it again",
        )
    rows = db.scalars(
        select(CaptionWord)
        .where(CaptionWord.caption_track_id == track.id)
        .order_by(CaptionWord.sequence_index)
    ).all()
    try:  # persisted words are re-validated before use
        words, _ = validate_words(
            [TimedWord(r.start_time, r.end_time, r.text, r.confidence) for r in rows],
            audio_duration=clip_seconds,
            tolerance=settings.caption_timing_tolerance_seconds,
        )
    except TimingOutputError:
        raise DynamicCaptionError(
            "caption_track_invalid", "The word timing for these captions is not valid"
        ) from None
    source = [SourceWord(w.text, w.start, w.end) for w in words]
    if cuts is not None:
        source = remap_words(cuts, source, lambda w, start, end: SourceWord(w.text, start, end))
    return build_word_cues(source, clip_duration=duration, rules=rules)
