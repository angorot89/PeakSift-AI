"""The short-form edit job: ClipEdit row → captions file → FFmpeg composition → validated
render → atomic finalize → ready.

Runs inside a Celery worker. The ``clip_edits`` row is the source of truth:

- **Claiming:** a ready edit is never re-rendered; a live edit (fresh heartbeat) is never
  rendered twice; a failed edit only re-runs after the retry endpoint resets it; a row
  whose task id belongs to a newer attempt is ignored.
- **Ownership:** the task id committed on the row before enqueueing is the attempt token.
  Every commit and the failure path re-read it, so a stalled worker that a retry took over
  cannot change the row; it only ever touches its own ``work-<attempt>`` directory.
- **Order of operations:** render into the attempt's workspace, validate with ffprobe,
  rename atomically to ``edited.mp4``, then one commit sets ``storage_key`` + metadata +
  ``ready`` — so ``ready`` always means a validated file exists.
- **Captions** come only from the persisted transcript (see ``captions.py``); the V0.5 clip
  file is the read-only video source and is never modified.

Progress is honest stage progress: 5 claimed, 15 captions prepared, 85 rendered,
90 validating, 100 ready.
"""

import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy import inspect as sa_inspect
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models import (
    AudioAsset,
    AudioAssetKind,
    ClipEdit,
    ClipEditStatus,
    ClipStatus,
    ReframeAnalysis,
    ReframeKeyframe,
    ReframeStatus,
    TranscriptionStatus,
    TranscriptSegment,
)
from app.services.audio_mix.loudness import measure_loudness
from app.services.audio_mix.mixer import prepare_track
from app.services.audio_mix.plan import SAMPLE_RATE as MIX_SAMPLE_RATE
from app.services.audio_mix.plan import mix_request
from app.services.clip_edit.brand import logo_plan
from app.services.clip_edit.brand_render import BrandLayers, end_card_ass
from app.services.clip_edit.caption_styles import build_ass_document
from app.services.clip_edit.caption_v2 import build_dynamic_ass
from app.services.clip_edit.captions import Cue, SourceSegment, build_cues
from app.services.clip_edit.composition import ComposedShort, compose_short
from app.services.clip_edit.config import (
    CAPTION_RENDERER_V2,
    CaptionPosition,
    CaptionStyle,
    EditConfig,
    Layout,
)
from app.services.clip_edit.cuts import remap_crop_points
from app.services.clip_edit.dynamic_text import DynamicCaptionError, dynamic_cues
from app.services.clip_edit.emoji import emoji_font
from app.services.clip_edit.hook import hook_ass
from app.services.clip_edit.safe_area import caption_placement
from app.services.clip_edit.smart_crop import CropPoint, crop_points_from
from app.services.clip_edit.storage import EditArtifactStore
from app.services.clip_edit.tighten import tighten_clip
from app.services.clip_render.pipeline import render_options_from
from app.services.clip_render.renderer import RenderError
from app.services.ffprobe import ProbeError, probe, probe_audio
from app.services.storage import (
    InvalidStorageKey,
    ObjectNotFound,
    StorageError,
    StorageProvider,
    media_storage,
)
from app.services.visuals.assets import (
    VisualsProblem,
    brand_logo,
    check_visuals,
    load_visual_assets,
)
from app.services.visuals.compositor import VisualLayer

logger = logging.getLogger(__name__)

CLAIMED_PROGRESS = 5
CAPTIONS_READY_PROGRESS = 15
AUDIO_READY_PROGRESS = 25
# A finished track measuring above this true peak (dBTP) is treated as clipped and refused.
CLIPPING_TRUE_PEAK_DBTP = 0.0
RENDER_DONE_PROGRESS = 85
VALIDATING_PROGRESS = 90
MAX_ERROR_LENGTH = 500

Composer = Callable[..., ComposedShort]


class PipelineSuperseded(Exception):
    """A newer attempt owns this edit; stop without writing."""


class PipelineFailure(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _now() -> datetime:
    return datetime.now(UTC)


def is_stale(edit: ClipEdit, settings: Settings, *, now: datetime | None = None) -> bool:
    if edit.status not in (ClipEditStatus.RENDERING, ClipEditStatus.VALIDATING):
        return False
    last = edit.heartbeat_at or edit.started_at or edit.created_at
    return ((now or _now()) - last).total_seconds() > settings.clip_render_stale_after_seconds


def run_clip_edit(
    edit_id: uuid.UUID,
    db: Session,
    *,
    settings: Settings | None = None,
    storage: StorageProvider | None = None,
    composer: Composer | None = None,
    task_id: str | None = None,
) -> ClipEdit | None:
    """Execute the render for a ``ClipEdit`` row. Problems are recorded, never raised."""
    settings = settings or get_settings()
    store = EditArtifactStore(storage or media_storage(settings))
    composer = composer or compose_short  # resolved at call time (tests patch the module)

    edit = db.get(ClipEdit, edit_id)
    if edit is None:
        logger.warning("Clip edit %s no longer exists; nothing to render", edit_id)
        return None
    if not _claim(edit, db, settings, store, task_id):
        return edit
    attempt = edit.attempt

    def fail(code: str, message: str) -> None:
        try:
            _fail(edit, db, store, code, message, task_id=task_id, attempt=attempt)
        except Exception:
            # The database itself is failing. Leave the row as it is: it goes stale and the
            # retry endpoint recovers it. Only this attempt's own files are removed.
            logger.exception("Could not record the failure of clip edit %s", edit_id)
            db.rollback()
            store.discard_workspace(edit_id, attempt)

    try:
        _execute(edit, db, settings, store, composer, task_id, attempt)
    except PipelineSuperseded:
        if _row_exists(edit_id, db):
            store.discard_workspace(edit_id, attempt)
        else:
            store.discard(edit_id)  # the edit is gone: none of its files are needed
        logger.info("Clip edit %s was taken over or removed; stopping", edit_id)
    except (PipelineFailure, RenderError) as error:
        fail(error.code, error.message)
    except (StorageError, OSError):  # disk full, permissions, a vanished directory
        logger.exception("Storage failure while rendering clip edit %s", edit_id)
        fail("storage_failure", "The edited short could not be stored")
    except SoftTimeLimitExceeded:
        fail("time_limit", "Rendering ran longer than the worker allows; retry the edit")
    except Exception:
        logger.exception("Unexpected error rendering clip edit %s", edit_id)
        fail("internal_error", "Unexpected error while rendering the short")
    return edit


# --- claiming -----------------------------------------------------------------------


def _claim(
    edit: ClipEdit, db: Session, settings: Settings, store: EditArtifactStore, task_id: str | None
) -> bool:
    if task_id and edit.celery_task_id and edit.celery_task_id != task_id:
        logger.info("Clip edit %s belongs to a newer attempt; ignoring", edit.id)
        return False
    if edit.status == ClipEditStatus.READY:
        logger.info("Clip edit %s is already ready; ignoring duplicate task", edit.id)
        return False
    if edit.status == ClipEditStatus.FAILED:
        logger.info("Clip edit %s is failed; a retry must reset it first", edit.id)
        return False
    if edit.status != ClipEditStatus.QUEUED and not is_stale(edit, settings):
        logger.info("Clip edit %s is already rendering elsewhere", edit.id)
        return False

    store.discard(edit.id)  # nothing from an earlier attempt survives (stale temp, orphans)
    now = _now()
    edit.status = ClipEditStatus.RENDERING
    edit.started_at = now
    edit.heartbeat_at = now
    edit.completed_at = None
    edit.progress_percent = CLAIMED_PROGRESS
    edit.error_code = None
    edit.error_message = None
    edit.storage_key = None
    edit.file_size = None
    edit.duration_seconds = None
    edit.width = edit.height = None
    edit.fps = None
    edit.video_codec = edit.audio_codec = None
    edit.caption_cue_count = None
    db.commit()
    return True


# --- the work -------------------------------------------------------------------------


def _execute(
    edit: ClipEdit,
    db: Session,
    settings: Settings,
    store: EditArtifactStore,
    composer: Composer,
    task_id: str | None,
    attempt: int,
) -> None:
    config = EditConfig.from_snapshot(edit.config)  # the stored snapshot, not current defaults
    clip = edit.clip
    if clip.status != ClipStatus.READY or not clip.storage_key:
        raise PipelineFailure("clip_not_ready", "The source clip is not ready")
    crop_points = _crop_path(edit, db, config) if config.layout == Layout.SMART_REFRAME else None
    clip_seconds = float(clip.duration_seconds)
    if config.cuts is not None:
        try:
            config.cuts.check(clip_seconds)
        except ValueError as error:
            raise PipelineFailure("invalid_cuts", str(error)) from None
        if crop_points is not None:
            crop_points = remap_crop_points(config.cuts, crop_points, clip_seconds)
    short_seconds = config.output_seconds(clip_seconds)  # the Short's own timeline

    workspace = store.workspace(edit.id, attempt)
    # Inputs are read locally: the stored file itself, or a copy fetched into the workspace.
    inputs = workspace / "inputs"
    inputs.mkdir()
    try:
        source = store.storage.fetch(clip.storage_key, inputs)
    except (ObjectNotFound, InvalidStorageKey):
        raise PipelineFailure("clip_missing", "The source clip file is missing") from None
    if config.cuts is not None:
        # Tighten first: everything after this works on the kept parts, back to back.
        source = tighten_clip(
            source,
            workspace,
            config.cuts.kept(clip_seconds),
            render_options_from(settings),
            heartbeat=lambda: _heartbeat(edit, db, task_id),
        )
    dynamic = config.caption_renderer == CAPTION_RENDERER_V2
    cues: list = []
    if config.captions_enabled and dynamic:
        cues = _dynamic_cues(edit, db, settings, config)
        edit.caption_cue_count = len(cues)
    elif config.captions_enabled:
        cues = build_cues(
            _transcript_segments(edit, db),
            clip_start=clip.start_time,
            clip_end=clip.end_time,
            max_words=settings.caption_max_words,
            max_chars=settings.caption_max_chars,
        )
        if config.cuts is not None:
            cues = [
                Cue(*span, cue.text)
                for cue in cues
                if (span := config.cuts.span(cue.start, cue.end)) is not None
            ]
        edit.caption_cue_count = len(cues)
    emoji_family = emoji_font(settings.ffmpeg_path) if dynamic or config.hook else None
    # The hook overlay shares the subtitle file (output-frame coordinates, safe area).
    brand = config.brand
    hook = (
        hook_ass(
            config.hook,
            font_family=settings.caption_font_family,
            emoji_family=emoji_family,
            accent=brand.hook_accent if brand else None,
        )
        if config.hook
        else None
    )
    extra_styles = [hook[0]] if hook else []
    extra_events = [hook[1]] if hook else []
    if brand is not None and brand.end_card is not None:
        # The end card's name and line live in the same subtitle file, after the clip.
        card_styles, card_events = end_card_ass(
            brand.end_card,
            name=brand.name,
            start=short_seconds,
            font_family=settings.caption_font_family,
        )
        extra_styles += card_styles
        extra_events += card_events
    # No speech in this range, no hook and no end card: render without a text layer, honestly.
    captions = bool(cues) or bool(extra_events)
    if captions and dynamic:
        placement = caption_placement(config.caption_position)
        store.captions_path(edit.id, attempt).write_text(
            build_dynamic_ass(
                cues,
                preset=config.caption_style,
                alignment=placement.alignment,
                margin_v=placement.margin_v,
                margin_h=placement.margin_h,
                font_family=settings.caption_font_family,
                extra_styles=extra_styles,
                extra_events=extra_events,
                emoji_family=emoji_family,
                active_colour=brand.caption_emphasis if brand else None,
            ),
            encoding="utf-8",
        )
    elif captions:
        store.captions_path(edit.id, attempt).write_text(
            build_ass_document(
                cues,
                style=config.caption_style or CaptionStyle.BOLD,
                position=config.caption_position or CaptionPosition.BOTTOM,
                font_family=settings.caption_font_family,
                extra_styles=extra_styles,
                extra_events=extra_events,
            ),
            encoding="utf-8",
        )
    edit.progress_percent = CAPTIONS_READY_PROGRESS
    _heartbeat(edit, db, task_id)

    extra: dict = {}
    if config.audio is not None:
        track = _prepare_audio(
            edit, db, settings, store, workspace, config, source, task_id, inputs
        )
        if track is not None:
            extra["audio"] = track
        edit.progress_percent = AUDIO_READY_PROGRESS
        _heartbeat(edit, db, task_id)

    if config.visuals is not None:
        extra["visuals"] = _prepare_visuals(edit, db, store, inputs, config, short_seconds)
        _heartbeat(edit, db, task_id)

    if brand is not None:
        extra["brand"] = _prepare_brand(edit, db, store, inputs, config, short_seconds)

    composed = composer(
        source,
        store.render_path(edit.id, attempt),
        layout=config.layout,
        options=render_options_from(settings),
        workspace=workspace,
        captions=captions,
        caption_font=settings.caption_font_family,
        heartbeat=lambda: _heartbeat(edit, db, task_id),
        crop_points=crop_points,
        focus=((config.focus_x, config.focus_y) if config.layout == Layout.MANUAL_CROP else None),
        **extra,
    )
    if "audio" in extra:
        _check_final_audio(edit, store.render_path(edit.id, attempt), settings)
    edit.progress_percent = RENDER_DONE_PROGRESS
    _heartbeat(edit, db, task_id)

    edit.status = ClipEditStatus.VALIDATING
    edit.progress_percent = VALIDATING_PROGRESS
    _heartbeat(edit, db, task_id)

    _ensure_still_owner(edit, db, task_id)
    key = store.finalize(edit.id, attempt)  # file first, then the row
    store.discard_workspace(edit.id, attempt)  # the caption file is no longer needed
    edit.storage_key = key
    edit.file_size = composed.size_bytes
    edit.duration_seconds = composed.duration_seconds
    edit.width, edit.height = composed.width, composed.height
    edit.fps = composed.fps
    edit.video_codec, edit.audio_codec = composed.video_codec, composed.audio_codec
    edit.status = ClipEditStatus.READY
    edit.progress_percent = 100
    edit.completed_at = _now()
    _heartbeat(edit, db, task_id)
    logger.info(
        "Clip edit %s ready: %s, captions %s (%s cues), hook %s, %s visuals, %.2fs, %s bytes",
        edit.id,
        config.layout.value,
        "on" if config.captions_enabled else "off",
        edit.caption_cue_count,
        "on" if config.hook else "off",
        len(config.visuals.elements) if config.visuals else 0,
        composed.duration_seconds,
        composed.size_bytes,
    )


def _prepare_visuals(
    edit: ClipEdit,
    db: Session,
    store: EditArtifactStore,
    inputs: Path,
    config: EditConfig,
    short_seconds: float,
) -> list[VisualLayer]:
    """The snapshot's visuals, re-checked against today's assets and the clip, with each asset
    fetched into this attempt's workspace (the stored file itself on local storage)."""
    assets = load_visual_assets(db, edit.clip.video.project_id, config.visuals.asset_ids)
    try:
        check_visuals(config.visuals, assets, short_seconds)
    except VisualsProblem as problem:
        raise PipelineFailure(problem.code, problem.message) from None
    paths: dict[str, Path] = {}
    for asset_id in config.visuals.asset_ids:
        try:
            paths[asset_id] = store.storage.fetch(assets[asset_id].storage_key, inputs)
        except (ObjectNotFound, InvalidStorageKey):
            raise PipelineFailure(
                "visual_asset_unavailable", "A selected visual is no longer available"
            ) from None
    return [
        VisualLayer(
            element=element,
            path=paths[element.asset_id],
            kind=assets[element.asset_id].kind,
            has_alpha=assets[element.asset_id].has_alpha,
            width=assets[element.asset_id].width,
            height=assets[element.asset_id].height,
        )
        for element in config.visuals.elements
    ]


def _prepare_brand(
    edit: ClipEdit,
    db: Session,
    store: EditArtifactStore,
    inputs: Path,
    config: EditConfig,
    short_seconds: float,
) -> BrandLayers:
    """The snapshot's brand, with its logo re-checked (still one of the creator's images) and
    fetched into this attempt's workspace, and where/when the corner logo shows."""
    brand = config.brand
    path, plan = None, None
    if brand.logo is not None:
        owner = edit.clip.video.project.user_id
        asset = brand_logo(db, owner, brand.logo.asset_id)
        if asset is None:
            raise PipelineFailure("brand_logo_unavailable", "The brand logo is no longer available")
        try:
            path = store.storage.fetch(asset.storage_key, inputs)
        except (ObjectNotFound, InvalidStorageKey):
            raise PipelineFailure(
                "brand_logo_unavailable", "The brand logo is no longer available"
            ) from None
        insets = [
            (element.position.value, element.start, element.end)
            for element in (config.visuals.elements if config.visuals else ())
            if element.is_inset and element.position is not None
        ]
        plan = logo_plan(
            brand.logo,
            captions_position=(
                config.caption_position.value
                if config.captions_enabled and config.caption_position
                else None
            ),
            hook_position=config.hook.position.value if config.hook else None,
            hook_seconds=config.hook.duration if config.hook else 0.0,
            insets=insets,
        )
    return BrandLayers(short_seconds, path, plan, brand.end_card)


def _prepare_audio(
    edit: ClipEdit,
    db: Session,
    settings: Settings,
    store: EditArtifactStore,
    workspace: Path,
    config: EditConfig,
    source: Path,
    task_id: str | None,
    inputs: Path,
) -> Path | None:
    """Mix and finish the edit's audio section into the attempt workspace.

    The referenced assets are re-checked here (the snapshot names them; they must still be
    this project's, of the right kind, with their file present). Returns None when nothing
    would be heard (a silent clip without music or effects stays without an audio stream).
    """
    mix = config.audio
    try:
        meta = probe(source, ffprobe_path=settings.ffprobe_path)
    except ProbeError:
        raise PipelineFailure("clip_missing", "The source clip could not be read") from None
    if not meta.duration_seconds:
        raise PipelineFailure("clip_missing", "The source clip has no duration")
    project_id = edit.clip.video.project_id
    wanted = {uuid.UUID(asset_id) for asset_id in mix.asset_ids}
    rows = {
        str(asset.id): asset
        for asset in db.scalars(
            select(AudioAsset).where(AudioAsset.id.in_(wanted), AudioAsset.project_id == project_id)
        )
    } if wanted else {}  # fmt: skip
    kinds = {cue.asset_id: AudioAssetKind.SFX for cue in mix.sfx}
    if mix.music is not None:
        kinds[mix.music.asset_id] = AudioAssetKind.MUSIC
    assets: dict[str, tuple[Path, float]] = {}
    for asset_id, kind in kinds.items():
        asset = rows.get(asset_id)
        path = None
        if asset is not None and asset.kind == kind:
            try:
                path = store.storage.fetch(asset.storage_key, inputs)
            except (ObjectNotFound, InvalidStorageKey):
                path = None
        if asset is None or path is None:
            raise PipelineFailure(
                "audio_asset_unavailable",
                "A selected music track or sound effect is no longer available",
            )
        assets[asset_id] = (path, float(asset.duration_seconds))
    request = mix_request(
        mix,
        duration=float(meta.duration_seconds),
        source=source if meta.audio_codec is not None else None,
        assets=assets,
    )
    if request is None:
        return None
    track, loudness = prepare_track(
        request,
        workspace,
        normalize=mix.normalize,
        options=render_options_from(settings),
        heartbeat=lambda: _heartbeat(edit, db, task_id),
    )
    logger.info(
        "Clip edit %s audio: music %s, %s effects, mix loudness %s",
        edit.id,
        "on" if mix.music else "off",
        len(mix.sfx),
        f"{loudness.integrated:.1f} LUFS" if loudness else "n/a",
    )
    return track


def _check_final_audio(edit: ClipEdit, rendered: Path, settings: Settings) -> None:
    """Validate and measure the encoded short's mixed audio.

    The audio stream must be the mix's format (stereo, 48 kHz) and as long as the video;
    the loudness and true peak are recorded, and an obviously clipped result is refused.
    """
    try:
        info = probe_audio(rendered, ffprobe_path=settings.ffprobe_path)
        video = probe(rendered, ffprobe_path=settings.ffprobe_path)
    except ProbeError:
        raise RenderError(
            "invalid_output", "The rendered short's audio could not be read"
        ) from None
    tolerance = render_options_from(settings).duration_tolerance_seconds
    if (
        info.channels != 2
        or info.sample_rate != MIX_SAMPLE_RATE
        or not info.duration_seconds
        or not video.duration_seconds
        or abs(info.duration_seconds - video.duration_seconds) > tolerance
    ):
        raise RenderError("invalid_output", "The rendered short's audio track is not valid")
    measured = measure_loudness(rendered, render_options_from(settings))
    edit.audio_loudness_lufs = round(measured.integrated, 2) if measured else None
    edit.audio_true_peak_dbtp = round(measured.true_peak, 2) if measured else None
    if measured is not None and measured.true_peak > CLIPPING_TRUE_PEAK_DBTP:
        raise RenderError(
            "audio_clipped",
            "The finished audio clips; lower the music or effect volume, or turn on normalization",
        )


def _crop_path(edit: ClipEdit, db: Session, config: EditConfig) -> list[CropPoint]:
    """The completed analysis' crop path for this clip, re-validated before rendering."""
    analysis = db.get(ReframeAnalysis, uuid.UUID(str(config.reframe_analysis_id)))
    if (
        analysis is None
        or analysis.clip_id != edit.clip_id
        or analysis.status != ReframeStatus.COMPLETED
    ):
        raise PipelineFailure(
            "reframe_unavailable",
            "The framing analysis is not available; analyze the framing again",
        )
    keyframes = db.scalars(
        select(ReframeKeyframe)
        .where(ReframeKeyframe.reframe_analysis_id == analysis.id)
        .order_by(ReframeKeyframe.sequence_index)
    ).all()
    try:
        return crop_points_from(keyframes)
    except ValueError:
        raise PipelineFailure("invalid_path", "The framing path is not valid") from None


def _dynamic_cues(edit: ClipEdit, db: Session, settings: Settings, config: EditConfig) -> list:
    """Word-aware cues for the dynamic renderer (see ``dynamic_text.py``)."""
    try:
        return dynamic_cues(
            edit.clip,
            db,
            settings,
            preset=config.caption_style,
            position=config.caption_position,
            timing=config.caption_timing,
            track_id=config.caption_track_id,
            cuts=config.cuts,
        )
    except DynamicCaptionError as error:
        raise PipelineFailure(error.code, error.message) from None


def _transcript_segments(edit: ClipEdit, db: Session) -> list[SourceSegment]:
    transcription = edit.clip.video.transcription
    if transcription is None or transcription.status != TranscriptionStatus.COMPLETED:
        raise PipelineFailure(
            "transcript_unavailable", "Captions need a completed transcript for this video"
        )
    rows = db.scalars(
        select(TranscriptSegment)
        .where(TranscriptSegment.transcription_id == transcription.id)
        .order_by(TranscriptSegment.sequence_index)
    )
    return [SourceSegment(start=r.start_time, end=r.end_time, text=r.text) for r in rows]


# --- state helpers ----------------------------------------------------------------------


def _still_owner(edit: ClipEdit, db: Session, task_id: str | None) -> bool:
    """True while this attempt may write the row. A row deleted mid-render (its project,
    video or clip was removed) has no owner: the worker stops and writes nothing."""
    with db.no_autoflush:  # read the committed token; never flush our pending progress first
        row = db.execute(select(ClipEdit.celery_task_id).where(ClipEdit.id == _key(edit))).first()
    if row is None:
        return False
    if task_id is None:
        return True
    return not row.celery_task_id or row.celery_task_id == task_id


def _key(edit: ClipEdit) -> uuid.UUID:
    """The primary key without touching the database: reading ``edit.id`` on an expired
    instance whose row was deleted raises instead of answering."""
    return sa_inspect(edit).identity[0]


def _row_exists(edit_id: uuid.UUID, db: Session) -> bool:
    db.rollback()
    return db.scalar(select(ClipEdit.id).where(ClipEdit.id == edit_id)) is not None


def _ensure_still_owner(edit: ClipEdit, db: Session, task_id: str | None) -> None:
    if not _still_owner(edit, db, task_id):
        db.rollback()
        raise PipelineSuperseded()


def _heartbeat(edit: ClipEdit, db: Session, task_id: str | None = None) -> None:
    """Commit progress — but only while this attempt still owns the edit."""
    _ensure_still_owner(edit, db, task_id)
    edit.heartbeat_at = _now()
    db.commit()


def _fail(
    edit: ClipEdit,
    db: Session,
    store: EditArtifactStore,
    code: str,
    message: str,
    *,
    task_id: str | None = None,
    attempt: int = 1,
) -> None:
    db.rollback()
    edit_id = _key(edit)
    if not _still_owner(edit, db, task_id):
        if _row_exists(edit_id, db):
            store.discard_workspace(edit_id, attempt)  # our own files only
        else:
            store.discard(edit_id)
        logger.info(
            "Clip edit %s failed (%s) after being taken over; newer attempt untouched",
            edit_id,
            code,
        )
        return
    store.discard(edit_id)  # no partial render, caption file or orphaned artifact survives
    edit.status = ClipEditStatus.FAILED
    edit.error_code = code[:64]
    edit.error_message = message[:MAX_ERROR_LENGTH]
    edit.storage_key = None
    edit.completed_at = _now()
    edit.heartbeat_at = edit.completed_at
    db.commit()
    logger.warning("Clip edit %s failed: %s — %s", edit_id, code, message)
