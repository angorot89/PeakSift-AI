"""Find Clips: search a video's transcript in plain language and keep what was found.

``GET`` answers with spans of the creator's own transcript where the request was heard (see
``services/find_clips.py``). ``POST /keep`` turns one span into a saved moment, so everything
that works on moments — creating a clip, Auto Edit, the editor — works on it unchanged.
Owner-scoped like every other video route: anything else is an indistinguishable 404.
"""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.api.clip_detection import _current_lines, _read_candidate
from app.api.deps import DbSession
from app.api.transcriptions import OwnedVideo
from app.core.config import get_settings
from app.core.rate_limit import per_user
from app.models import (
    CandidateDecision,
    CandidateOrigin,
    ClipCandidate,
    ClipDetectionRun,
    ClipDetectionStatus,
    Video,
)
from app.models.clip_detection import HOOK_MAX_LENGTH, RATIONALE_MAX_LENGTH, TITLE_MAX_LENGTH
from app.schemas.clip_detection import (
    ClipCandidateRead,
    FindClipsRead,
    FoundClip,
    FoundLine,
    KeepFoundClip,
)
from app.services import find_clips
from app.services.clip_detection.detection_config import DetectionConfig
from app.services.clip_detection.windowing import transcript_fingerprint
from app.services.find_clips_model import related_words

router = APIRouter(
    prefix="/projects/{project_id}/videos/{video_id}/find-clips", tags=["find-clips"]
)

BOUNDARY_TOLERANCE_SECONDS = 0.05
SEARCH_PROVIDER = "search"  # a run that holds kept search results when no analysis exists
SEARCH_MODEL = "transcript"


def _lines(db: DbSession, video: Video) -> list[find_clips.Line]:
    settings = get_settings()
    return [
        find_clips.Line(line.start, line.end, line.text)
        for line in _current_lines(db, video, settings)
    ]


def _kept(db: DbSession, video: Video) -> list[ClipCandidate]:
    """The video's kept search results on its current transcript."""
    return list(
        db.scalars(
            select(ClipCandidate)
            .join(ClipDetectionRun, ClipDetectionRun.id == ClipCandidate.run_id)
            .where(
                ClipCandidate.video_id == video.id,
                ClipCandidate.origin == CandidateOrigin.SEARCH,
                ClipDetectionRun.transcription_id == video.transcription.id,
            )
        )
    )


def _same_span(candidate: ClipCandidate, start: float, end: float) -> bool:
    return (
        abs(candidate.start_time - start) < BOUNDARY_TOLERANCE_SECONDS
        and abs(candidate.end_time - end) < BOUNDARY_TOLERANCE_SECONDS
    )


@router.get("", response_model=FindClipsRead, dependencies=[per_user("find_clips")])
def find(
    video: OwnedVideo,
    db: DbSession,
    q: Annotated[str, Query(min_length=2, max_length=find_clips.QUERY_MAX_CHARS)],
    limit: Annotated[int, Query(ge=1, le=20)] = find_clips.DEFAULT_LIMIT,
    related: Annotated[
        bool, Query(description="Also search for related words from the local model")
    ] = True,
) -> FindClipsRead:
    """Where in this video the request was said. 409 until the video is transcribed."""
    settings = get_settings()
    lines = _lines(db, video)
    query = " ".join(q.split())
    # Only ask the model when the request has something to search for at all.
    suggestions = (
        related_words(query, settings) if related and find_clips.spoken_terms(query) else []
    )
    understood, results = find_clips.search(
        lines,
        query,
        related=suggestions,
        min_seconds=settings.clip_detection_min_clip_seconds,
        max_seconds=settings.clip_detection_max_clip_seconds,
        limit=limit,
    )
    kept = _kept(db, video) if results else []
    return FindClipsRead(
        query=query,
        terms=list(understood.terms),
        related=list(understood.related),
        results=[
            FoundClip(
                start=found.start,
                end=found.end,
                duration=found.duration,
                excerpt=found.excerpt,
                lines=[FoundLine(start=x.start, end=x.end, text=x.text) for x in found.lines],
                matched=list(found.matched),
                related=list(found.related),
                score=found.score,
                candidate_id=next(
                    (c.id for c in kept if _same_span(c, found.start, found.end)), None
                ),
            )
            for found in results
        ],
    )


def _home_run(db: DbSession, video: Video, lines: list[find_clips.Line]) -> ClipDetectionRun:
    """Where a kept result lives: the newest completed analysis of the current transcript, so
    it sits with the detected moments; otherwise a completed run of its own."""
    run = db.scalar(
        select(ClipDetectionRun)
        .where(
            ClipDetectionRun.video_id == video.id,
            ClipDetectionRun.transcription_id == video.transcription.id,
            ClipDetectionRun.status == ClipDetectionStatus.COMPLETED,
        )
        .order_by(ClipDetectionRun.created_at.desc(), ClipDetectionRun.id.desc())
        .limit(1)
    )
    if run is not None:
        return run
    settings = get_settings()
    now = datetime.now(UTC)
    run = ClipDetectionRun(
        video=video,
        transcription=video.transcription,
        transcript_fingerprint=transcript_fingerprint(
            video.transcription.id, _current_lines(db, video, settings)
        ),
        provider=SEARCH_PROVIDER,
        model=SEARCH_MODEL,
        config=DetectionConfig.from_settings(settings).as_dict(),
        status=ClipDetectionStatus.COMPLETED,
        progress_percent=100,
        windows_total=0,
        started_at=now,
        completed_at=now,
    )
    db.add(run)
    db.flush()
    return run


def _title(query: str) -> str:
    text = " ".join(query.split())
    return (text[:1].upper() + text[1:])[:TITLE_MAX_LENGTH]


@router.post(
    "/keep",
    response_model=ClipCandidateRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[per_user("find_clips")],
)
def keep(
    body: KeepFoundClip, video: OwnedVideo, db: DbSession, response: Response
) -> ClipCandidateRead:
    """Keep a found span as a saved moment. Idempotent: the same span is the same moment.

    The span must be made of whole transcript lines and be a valid clip length — the server
    never trusts times from the client beyond picking lines it already has.
    """
    settings = get_settings()
    lines = _lines(db, video)
    lo = next(
        (i for i, x in enumerate(lines) if abs(x.start - body.start) < BOUNDARY_TOLERANCE_SECONDS),
        None,
    )
    hi = next(
        (i for i, x in enumerate(lines) if abs(x.end - body.end) < BOUNDARY_TOLERANCE_SECONDS),
        None,
    )
    if lo is None or hi is None or hi < lo:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="That span does not match the transcript. Search again.",
        )
    span = lines[lo : hi + 1]
    start, end = span[0].start, span[-1].end
    duration = end - start
    if not (
        settings.clip_detection_min_clip_seconds - BOUNDARY_TOLERANCE_SECONDS
        <= duration
        <= settings.clip_detection_max_clip_seconds + BOUNDARY_TOLERANCE_SECONDS
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="That span is not a valid clip length.",
        )

    existing = next((c for c in _kept(db, video) if _same_span(c, start, end)), None)
    if existing is not None:
        response.status_code = status.HTTP_200_OK
        return _read_candidate(existing)

    query = " ".join(body.query.split())
    own = find_clips.spoken_terms(query)
    heard = {find_clips.key(word) for line in span for word in find_clips.words(line.text)}
    matched = [word for term, word in own.items() if term in heard]
    rationale = f"You asked for “{query}”."
    if matched:
        rationale += f" Heard here: {', '.join(matched)}."

    run = _home_run(db, video, lines)
    excerpt = " ".join(line.text.strip() for line in span if line.text.strip())
    for _attempt in range(2):
        next_rank = (
            db.scalar(select(func.max(ClipCandidate.rank)).where(ClipCandidate.run_id == run.id))
            or 0
        ) + 1
        candidate = ClipCandidate(
            run=run,
            video_id=video.id,
            start_time=start,
            end_time=end,
            duration_seconds=duration,
            title=_title(query),
            hook=span[0].text.strip()[:HOOK_MAX_LENGTH],
            rationale=rationale[:RATIONALE_MAX_LENGTH],
            category="other",
            transcript_excerpt=excerpt,
            # A search match is not an editorial judgement: no scores are claimed.
            overall_score=0,
            hook_score=0,
            entertainment_score=0,
            clarity_score=0,
            payoff_score=0,
            completeness_score=0,
            rank=next_rank,
            decision=CandidateDecision.SAVED,
            decided_at=datetime.now(UTC),
            origin=CandidateOrigin.SEARCH,
            query=query,
        )
        db.add(candidate)
        try:
            db.commit()
            return _read_candidate(candidate)
        except IntegrityError:  # another keep took this rank at the same moment
            db.rollback()
            run = _home_run(db, video, lines)
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT, detail="Could not keep that moment. Try again."
    )
