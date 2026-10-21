"""What PeakSift knows about a clip, gathered for Auto Edit: plain facts and a planner context.

Auto Edit **consumes completed analyses; it never starts them**. One click never launches
word timing, framing analysis and B-roll suggestions behind the creator's back — the editor
offers those separately, and a plan uses whatever is ready:

- the clip's timed transcript (word timing when it exists, else transcript segments) and the
  candidate's title and hook;
- the completed word-timing track and framing analysis made with the server's *current*
  settings (the same ones the editor shows), and the framing confidence;
- the current completed B-roll analysis — dismissed suggestions are never planned — with the
  project's assets that match each suggestion by what they show and by their words
  (``semantic/matching.py``), as strong or possible matches, and a matched video's best scene;
- the music track the creator explicitly chose for this plan, and the project's sound effects
  whose names mark them as transition sounds ("whoosh", "swoosh", "transition", …);
- what this server can draw (text overlays, visuals) and the source's orientation.

Every asset handed to a planner exists in this project and in storage. The same gathering
feeds the source fingerprint (``PlanSources``), so a plan is reused exactly while these facts
are unchanged.
"""

import hashlib
import re
import uuid
from dataclasses import dataclass
from pathlib import PurePosixPath

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import Settings
from app.models import (
    AudioAsset,
    AudioAssetKind,
    BrollAnalysis,
    BrollAnalysisStatus,
    BrollSuggestion,
    BrollSuggestionStatus,
    CaptionTrack,
    CaptionTrackStatus,
    Clip,
    ReframeAnalysis,
    ReframeStatus,
    TranscriptionStatus,
    VisualAsset,
)
from app.services.auto_edit.config import AutoEditRequest
from app.services.auto_edit.contract import (
    MUSIC_HANDLE,
    AudioOption,
    AutoEditContext,
    BrollOption,
    Capabilities,
    TimedLine,
    VisualOption,
    orientation,
)
from app.services.auto_edit.fingerprint import (
    AudioAssetFacts,
    PlanSources,
    SuggestionFacts,
    VisualAssetFacts,
)
from app.services.auto_edit.recipes import recipe_version
from app.services.broll.config import BrollConfig
from app.services.broll.pipeline import PipelineFailure, clip_lines
from app.services.caption_timing.config import CaptionTimingConfig
from app.services.clip_edit.composition import supports_captions, supports_visuals
from app.services.reframe.config import ReframeConfig
from app.services.semantic.matching import match_queries
from app.services.semantic.registry import configured_identity
from app.services.semantic.search import MatchMethod, Strength, thresholds_for
from app.services.semantic.state import current_index
from app.services.storage import InvalidStorageKey, StorageProvider

TRANSITION_SOUND = re.compile(
    r"(whoosh|woosh|swoosh|swish|swipe|whip|transition|riser)", re.IGNORECASE
)


class SourcesUnavailable(Exception):
    """The clip cannot be planned (not ready); ``code``/``message`` are safe to show."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Gathered:
    sources: PlanSources
    context: AutoEditContext
    broll_method: str | None  # local_ai / keyword / keyword_fallback, when suggestions exist
    music_missing: bool  # the creator chose a track that is no longer available


def _present(storage: StorageProvider, key: str | None) -> bool:
    if not key:
        return False
    try:
        return storage.exists(key)  # StorageUnavailable propagates: an outage is not "missing"
    except InvalidStorageKey:
        return False


def current_reframe(db: Session, clip: Clip, settings: Settings) -> ReframeAnalysis | None:
    fingerprint = ReframeConfig.from_settings(settings).fingerprint()
    return db.scalar(
        select(ReframeAnalysis).where(
            ReframeAnalysis.clip_id == clip.id,
            ReframeAnalysis.config_fingerprint == fingerprint,
            ReframeAnalysis.status == ReframeStatus.COMPLETED,
        )
    )


def current_caption_track(db: Session, clip: Clip, settings: Settings) -> CaptionTrack | None:
    transcription = clip.video.transcription
    hint = (
        transcription.language or None
        if transcription is not None and transcription.status == TranscriptionStatus.COMPLETED
        else None
    )
    fingerprint = CaptionTimingConfig.from_settings(settings, language_hint=hint).fingerprint()
    return db.scalar(
        select(CaptionTrack).where(
            CaptionTrack.clip_id == clip.id,
            CaptionTrack.config_fingerprint == fingerprint,
            CaptionTrack.status == CaptionTrackStatus.COMPLETED,
        )
    )


def current_broll(db: Session, clip: Clip, settings: Settings) -> BrollAnalysis | None:
    """The newest completed analysis made with today's settings (any generation)."""

    def base(snapshot: dict | None) -> dict:
        return {k: v for k, v in (snapshot or {}).items() if k != "generation"}

    wanted = base(BrollConfig.from_settings(settings).snapshot())
    rows = db.scalars(
        select(BrollAnalysis)
        .where(BrollAnalysis.clip_id == clip.id)
        .order_by(BrollAnalysis.generation.desc(), BrollAnalysis.created_at.desc())
    )
    current = next((row for row in rows if base(row.config) == wanted), None)
    return current if current and current.status == BrollAnalysisStatus.COMPLETED else None


def broll_method(analysis: BrollAnalysis) -> str:
    if analysis.provider == "keyword":
        return "keyword_fallback" if analysis.fallback_reason else "keyword"
    return "local_ai"


def _lines(clip: Clip, db: Session) -> tuple[TimedLine, ...]:
    try:
        lines = clip_lines(clip, db)
    except PipelineFailure:  # no transcript: a plan can still frame and finish the clip
        return ()
    return tuple(TimedLine(line.start, line.end, line.text) for line in lines)


def _transcript_fingerprint(lines: tuple[TimedLine, ...]) -> str | None:
    if not lines:
        return None
    canonical = "\n".join(f"{line.start:.2f}|{line.end:.2f}|{line.text}" for line in lines)
    return hashlib.sha256(canonical.encode()).hexdigest()


def gather(
    clip: Clip,
    db: Session,
    settings: Settings,
    storage: StorageProvider,
    request: AutoEditRequest,
) -> Gathered:
    if not clip.duration_seconds or clip.status != "ready":
        raise SourcesUnavailable("clip_not_ready", "Generate the clip before using Auto Edit")
    if not _present(storage, clip.storage_key):
        raise SourcesUnavailable(
            "clip_missing", "The clip file is missing; generate the clip again"
        )
    recipe = recipe_version(request.recipe_version)
    duration = float(clip.duration_seconds)
    project_id = clip.video.project_id
    lines = _lines(clip, db)
    track = current_caption_track(db, clip, settings)
    framing = current_reframe(db, clip, settings)
    analysis = current_broll(db, clip, settings)
    transcription = clip.video.transcription
    phrase = (
        transcription is not None
        and transcription.status == TranscriptionStatus.COMPLETED
        and bool(lines)
    )

    # Visual assets: every one counts for the fingerprint; only matches reach the planner.
    library = list(
        db.scalars(
            select(VisualAsset)
            .options(selectinload(VisualAsset.semantic_indexes))
            .where(VisualAsset.project_id == project_id)
            .order_by(VisualAsset.created_at, VisualAsset.id)
        )
    )
    by_id = {str(asset.id): asset for asset in library}
    suggestions = (
        list(
            db.scalars(
                select(BrollSuggestion)
                .where(
                    BrollSuggestion.analysis_id == analysis.id,
                    BrollSuggestion.status != BrollSuggestionStatus.DISMISSED,
                )
                .order_by(BrollSuggestion.start_time, BrollSuggestion.sequence_index)
            )
        )
        if analysis is not None
        else []
    )
    visual_handles: dict[str, str] = {}  # asset id → handle
    present: dict[str, bool] = {}
    options: list[BrollOption] = []
    suggestion_ids: dict[str, str] = {}
    found = match_queries(db, project_id, [s.query for s in suggestions], library, settings)
    for index, suggestion in enumerate(suggestions, start=1):
        handle = f"suggestion_{index}"
        suggestion_ids[handle] = str(suggestion.id)
        matched: list[str] = []
        strong: list[str] = []
        visual: list[str] = []
        scenes: list[tuple[str, float]] = []
        for match in found.get(suggestion.query):
            asset_id = str(match.asset.id)
            if asset_id not in present:
                present[asset_id] = _present(storage, match.asset.storage_key)
            if not present[asset_id]:
                continue
            asset_handle = visual_handles.setdefault(
                asset_id, f"visual_asset_{len(visual_handles) + 1}"
            )
            matched.append(asset_handle)
            if match.strength == Strength.STRONG:
                strong.append(asset_handle)
            if match.method in (MatchMethod.VISUAL, MatchMethod.BOTH):
                visual.append(asset_handle)
            if match.best_frame_time is not None and match.asset.kind == "video":
                scenes.append((asset_handle, float(match.best_frame_time)))
        options.append(
            BrollOption(
                handle=handle,
                start=float(suggestion.start_time),
                end=float(suggestion.end_time),
                query=suggestion.query,
                reason=suggestion.reason,
                matches=tuple(matched),
                strong_matches=tuple(strong),
                visual_matches=tuple(visual),
                best_scenes=tuple(scenes),
            )
        )
    visual_options = tuple(
        VisualOption(
            handle=handle,
            kind=by_id[asset_id].kind,
            name=by_id[asset_id].display_name,
            description=by_id[asset_id].description or "",
            tags=tuple(by_id[asset_id].tags or ()),
            orientation=orientation(by_id[asset_id].width, by_id[asset_id].height),
            duration=by_id[asset_id].duration_seconds,
        )
        for asset_id, handle in visual_handles.items()
    )

    # Audio: the explicitly chosen music track, and transition sound effects.
    audio_ids: dict[str, str] = {}
    music: AudioOption | None = None
    music_missing = False
    audio_facts: list[AudioAssetFacts] = []
    if request.music_asset_id:
        chosen = db.scalar(
            select(AudioAsset).where(
                AudioAsset.id == uuid.UUID(request.music_asset_id),
                AudioAsset.project_id == project_id,
                AudioAsset.kind == AudioAssetKind.MUSIC,
            )
        )
        if chosen is not None and _present(storage, chosen.storage_key):
            music = AudioOption(MUSIC_HANDLE, chosen.display_name, float(chosen.duration_seconds))
            audio_ids[MUSIC_HANDLE] = str(chosen.id)
            audio_facts.append(
                AudioAssetFacts(str(chosen.id), chosen.kind, chosen.display_name,
                                float(chosen.duration_seconds))
            )  # fmt: skip
        else:
            music_missing = True
    effects: list[AudioOption] = []
    if recipe.max_sfx:
        rows = db.scalars(
            select(AudioAsset)
            .where(AudioAsset.project_id == project_id, AudioAsset.kind == AudioAssetKind.SFX)
            .order_by(AudioAsset.created_at, AudioAsset.id)
        )
        for row in rows:
            if not TRANSITION_SOUND.search(PurePosixPath(row.display_name).stem):
                continue
            if not _present(storage, row.storage_key):
                continue
            handle = f"sfx_{len(effects) + 1}"
            effects.append(
                AudioOption(handle, row.display_name, float(row.duration_seconds), transition=True)
            )
            audio_ids[handle] = str(row.id)
            audio_facts.append(
                AudioAssetFacts(str(row.id), row.kind, row.display_name,
                                float(row.duration_seconds))
            )  # fmt: skip

    capabilities = Capabilities(
        smart_reframe=framing is not None,
        reframe_confidence=framing.confidence_level if framing is not None else None,
        word_timing=track is not None,
        phrase_timing=phrase,
        text_overlays=supports_captions(settings.ffmpeg_path),
        visuals=supports_visuals(settings.ffmpeg_path),
    )
    candidate = clip.candidate
    context = AutoEditContext(
        clip_duration=duration,
        lines=lines,
        capabilities=capabilities,
        recipe=recipe.summary(),
        source_orientation=orientation(clip.width, clip.height),
        title=candidate.title if candidate else None,
        candidate_hook=candidate.hook if candidate else None,
        broll=tuple(options),
        visual_assets=visual_options,
        music=music,
        sound_effects=tuple(effects),
        reframe_analysis_id=str(framing.id) if framing is not None else None,
        caption_track_id=str(track.id) if track is not None else None,
        visual_ids={handle: asset_id for asset_id, handle in visual_handles.items()},
        suggestion_ids=suggestion_ids,
        audio_ids=audio_ids,
    )
    identity = configured_identity(settings)
    thresholds = thresholds_for(identity)

    def semantic_fact(asset: VisualAsset) -> str | None:
        index = current_index(asset.semantic_indexes, identity)
        return f"{index.status}:{index.id}" if index is not None else None

    sources = PlanSources(
        clip_id=str(clip.id),
        matching=(
            f"{identity.provider}:{identity.model}:{identity.model_version}:{thresholds.version}"
            if identity is not None and thresholds is not None
            else None
        ),
        clip_artifact=clip.storage_key,
        clip_duration=duration,
        transcript_fingerprint=_transcript_fingerprint(lines),
        caption_track_id=context.caption_track_id,
        reframe_analysis_id=context.reframe_analysis_id,
        reframe_confidence=capabilities.reframe_confidence,
        broll_analysis_id=str(analysis.id) if analysis is not None else None,
        suggestions=tuple(
            SuggestionFacts(str(s.id), float(s.start_time), float(s.end_time), s.query, s.status)
            for s in suggestions
        ),
        visual_assets=tuple(
            VisualAssetFacts(
                id=str(asset.id),
                kind=asset.kind,
                name=asset.display_name,
                description=asset.description or "",
                tags=tuple(asset.tags or ()),
                width=asset.width,
                height=asset.height,
                duration=asset.duration_seconds,
                has_alpha=bool(asset.has_alpha),
                semantic=semantic_fact(asset),
            )
            for asset in library
        ),
        audio_assets=tuple(audio_facts),
    )
    return Gathered(
        sources=sources,
        context=context,
        broll_method=broll_method(analysis) if analysis is not None else None,
        music_missing=music_missing,
    )
