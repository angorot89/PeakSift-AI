"""Opening hook ideas for a clip (V1.8): ``GET …/clips/{clip_id}/hooks?target=``.

``target`` is ``original`` (the clip's own sentences, always available) or a language the creator
asks for — ``darija_arabic``, ``darija_latin``, ``arabic``, ``french``, ``english`` — which adds
checked local AI suggestions (``services/hooks.py``). Owner-scoped (``404`` otherwise); the
creator's project language is reported alongside so the editor can offer the right choices.
Nothing is applied: the creator picks a hook and can edit it.
"""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from app.api.clip_edits import OwnedClip
from app.api.deps import DbSession
from app.core.config import get_settings
from app.core.rate_limit import per_user
from app.models import Transcription, TranscriptSegment
from app.services import hooks, language

router = APIRouter(
    prefix="/projects/{project_id}/videos/{video_id}/clips/{clip_id}/hooks", tags=["hooks"]
)


def clip_lines(db, clip) -> list[str]:
    """The transcript lines inside the clip (the newest completed transcript)."""
    transcription = db.scalar(
        select(Transcription)
        .where(Transcription.video_id == clip.video_id, Transcription.status == "completed")
        .order_by(Transcription.created_at.desc())
        .limit(1)
    )
    if transcription is None:
        return []
    return list(
        db.scalars(
            select(TranscriptSegment.text)
            .where(
                TranscriptSegment.transcription_id == transcription.id,
                TranscriptSegment.end_time > clip.start_time,
                TranscriptSegment.start_time < clip.end_time,
            )
            .order_by(TranscriptSegment.start_time)
        )
    )


@router.get("", dependencies=[per_user("hook_ideas")])
def hook_ideas(
    clip: OwnedClip, db: DbSession, target: Annotated[str, Query()] = "original"
) -> dict:
    if target not in hooks.TARGETS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Unknown hook language"
        )
    lines = [" ".join(line.split()) for line in clip_lines(db, clip) if line.strip()]
    text = " ".join(lines)
    project = clip.video.project
    guess = language.detect(text)
    ideas = hooks.transcript_ideas(text, clip.candidate.hook)
    note = None
    if target != "original" and lines:
        extra, note = hooks.model_ideas(get_settings(), target, ideas)
        ideas = extra + ideas
    return {
        "target": target,
        "language": {
            "chosen": project.content_language,
            "detected": {**guess.read(), "label": language.label(guess)},
        },
        "market": project.market,
        "ideas": [idea.read() for idea in ideas],
        # unavailable: the local model could not be reached; none_grounded: nothing it proposed
        # passed the checks. The transcript ideas are always there.
        "note": note,
    }
