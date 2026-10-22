"""Auto Edit for a generated clip: recipes, create a plan (idempotent per inputs), list,
status, retry, regenerate ("try another plan") and apply.

Ownership chain: User → Project → Video → Clip → AutoEditPlan; anything else is a 404 (401
without a session). A request can only name a recipe (an allow-list) and, optionally, one of
the project's music tracks; the planner, its model and every rule are server configuration.
Responses never carry prompts, model output, model server addresses, task ids, fingerprints,
storage keys or paths.

Applying a ready plan creates (or reuses) a **normal edit** through exactly the same checks as
the edit endpoint — every asset is re-checked for ownership and kind at this moment — and the
plan becomes ``applied`` with a reference to that edit. It is never changed again; applying it
twice returns the same edit. "Try another plan" makes a new plan (the next generation) and
keeps the old one.
"""

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.api.clip_edits import OwnedClip, create_or_reuse_edit, read_edit
from app.api.deps import CurrentUser, DbSession, Storage
from app.api.media_streaming import object_present
from app.api.transcriptions import OwnedVideo
from app.core.config import get_settings
from app.core.rate_limit import per_user
from app.models import (
    ACTIVE_AUTO_EDIT_STATUSES,
    AudioAsset,
    AudioAssetKind,
    AutoEditPlan,
    AutoEditStatus,
    BrollSuggestion,
    BrollSuggestionStatus,
    Clip,
    ClipStatus,
    Video,
)
from app.schemas.auto_edit import (
    AutoEditApplyRead,
    AutoEditConfidence,
    AutoEditCreate,
    AutoEditPlanPage,
    AutoEditPlanRead,
    AutoEditRecipeRead,
    PerformanceContextRead,
)
from app.services.auto_edit import state
from app.services.auto_edit.config import AutoEditRequest
from app.services.auto_edit.fingerprint import source_fingerprint
from app.services.auto_edit.recipes import RECIPE_ORDER, current_recipe, recipe_version
from app.services.auto_edit.sources import SourcesUnavailable, gather
from app.services.clip_edit.config import EditConfig
from app.services.performance.profile import creator_profile
from app.services.storage import StorageProvider, StorageUnavailable
from app.workers.dispatch import JobQueueUnavailable, enqueue_auto_edit_plan, new_task_id

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/projects/{project_id}/videos/{video_id}/clips/{clip_id}/auto-edits",
    tags=["auto-edit"],
)
recipes_router = APIRouter(tags=["auto-edit"])

MAX_LIST = 20


def get_owned_plan(plan_id: uuid.UUID, clip: OwnedClip, db: DbSession) -> AutoEditPlan:
    plan = db.scalar(
        select(AutoEditPlan).where(AutoEditPlan.id == plan_id, AutoEditPlan.clip_id == clip.id)
    )
    if plan is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plan not found")
    return plan


OwnedPlan = Annotated[AutoEditPlan, Depends(get_owned_plan)]


def _confidence(plan: AutoEditPlan) -> AutoEditConfidence | None:
    summary = plan.confidence_summary
    if not summary:
        return None
    return AutoEditConfidence(
        planner=summary.get("planner", "rules"),
        fallback=bool(summary.get("fallback_reason")),
        framing=summary.get("framing"),
        word_timing=bool(summary.get("word_timing")),
        phrase_timing=bool(summary.get("phrase_timing")),
        broll_method=summary.get("broll_method"),
        broll_suggestions=int(summary.get("broll_suggestions") or 0),
        matched_assets=int(summary.get("matched_assets") or 0),
    )


def read_plan(plan: AutoEditPlan) -> AutoEditPlanRead:
    try:
        label = recipe_version(plan.recipe_version).label
    except ValueError:
        label = plan.recipe.title()
    music = (plan.config or {}).get("music_asset_id")
    explanations = plan.explanation_snapshot
    if explanations is not None:  # internal bookkeeping stays internal
        explanations = {k: v for k, v in explanations.items() if k != "used_suggestions"}
    return AutoEditPlanRead(
        id=plan.id,
        clip_id=plan.clip_id,
        status=plan.status,
        progress_percent=plan.progress_percent,
        attempt=plan.attempt,
        is_stale=state.is_stale(plan, get_settings()),
        generation=plan.generation,
        recipe=plan.recipe,
        recipe_version=plan.recipe_version,
        recipe_label=label,
        music_asset_id=uuid.UUID(music) if music else None,
        configuration=plan.configuration_snapshot,
        explanations=explanations,
        confidence=_confidence(plan),
        clip_edit_id=plan.clip_edit_id,
        error_code=plan.error_code,
        error_message=plan.error_message,
        created_at=plan.created_at,
        started_at=plan.started_at,
        completed_at=plan.completed_at,
        applied_at=plan.applied_at,
        performance_hints=_hint_texts((plan.config or {}).get("performance_context")),
    )


def _hint_texts(profile: dict | None) -> list[str] | None:
    return [hint["text"] for hint in profile["hints"]] if profile else None


def _performance_source() -> str:
    return "fake" if get_settings().performance_provider == "fake" else "youtube"


def _profile_for(db, user_id: uuid.UUID, wanted: bool) -> dict | None:
    """The creator's profile snapshot when they asked for it (None: none to use)."""
    return creator_profile(db, user_id, _performance_source()) if wanted else None


def _require_plannable(clip: Clip, storage: StorageProvider) -> None:
    if clip.status != ClipStatus.READY or not clip.duration_seconds:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Generate the clip before using Auto Edit",
        )
    try:
        present = object_present(storage, clip.storage_key)
    except StorageUnavailable:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Media storage is unavailable. Try again in a moment.",
        ) from None
    if not present:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The clip file is missing; generate the clip again",
        )


def _owned_music(db: DbSession, video: Video, music_asset_id: uuid.UUID | None) -> str | None:
    if music_asset_id is None:
        return None
    music = db.scalar(
        select(AudioAsset).where(
            AudioAsset.id == music_asset_id,
            AudioAsset.project_id == video.project_id,
            AudioAsset.kind == AudioAssetKind.MUSIC,
        )
    )
    # Another project's track is indistinguishable from a missing one (no existence leak).
    if music is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Choose music from this project's audio",
        )
    return str(music.id)


def _enqueue_or_503(db: DbSession, plan: AutoEditPlan, *, created: bool) -> None:
    """The attempt token is already committed on the row; hand the job to the broker."""
    try:
        enqueue_auto_edit_plan(plan.id, task_id=plan.celery_task_id)
    except JobQueueUnavailable:
        if created:
            db.delete(plan)  # never leave a queued row that no worker will pick up
        else:
            plan.status = AutoEditStatus.FAILED
            plan.error_code = "queue_unavailable"
            plan.error_message = "The job queue was unavailable; retry in a moment"
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The planning queue is unavailable. Try again in a moment.",
        ) from None


def _existing(db: DbSession, clip: Clip, fingerprint: str) -> AutoEditPlan | None:
    return db.scalar(
        select(AutoEditPlan).where(
            AutoEditPlan.clip_id == clip.id, AutoEditPlan.source_fingerprint == fingerprint
        )
    )


def _start(
    db: DbSession,
    clip: Clip,
    storage: StorageProvider,
    request: AutoEditRequest,
    response: Response,
) -> AutoEditPlanRead:
    """The plan for these inputs: the existing one, or a new queued one."""
    try:
        gathered = gather(clip, db, get_settings(), storage, request)
    except SourcesUnavailable as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=error.message) from None
    except StorageUnavailable:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Media storage is unavailable. Try again in a moment.",
        ) from None
    fingerprint = source_fingerprint(gathered.sources, request.snapshot())
    existing = _existing(db, clip, fingerprint)
    if existing is not None:
        if existing.status == AutoEditStatus.FAILED:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The last plan for these inputs failed; use the retry endpoint",
            )
        response.status_code = status.HTTP_200_OK
        return read_plan(existing)
    plan = AutoEditPlan(
        clip_id=clip.id,
        video_id=clip.video_id,
        recipe=request.recipe,
        recipe_version=request.recipe_version,
        planner_version=request.planner_version,
        planner_provider=request.provider,
        planner_model=request.model,
        generation=request.generation,
        config=request.snapshot(),
        source_fingerprint=fingerprint,
        celery_task_id=new_task_id(),  # attempt token committed before the job exists
    )
    db.add(plan)
    try:
        db.commit()
    except IntegrityError:  # a concurrent identical request won the unique constraint
        db.rollback()
        winner = _existing(db, clip, fingerprint)
        if winner is None:  # pragma: no cover - the other transaction vanished
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Try again") from None
        response.status_code = status.HTTP_200_OK
        return read_plan(winner)
    _enqueue_or_503(db, plan, created=True)
    return read_plan(plan)


# --- recipes ------------------------------------------------------------------------------------


@recipes_router.get("/auto-edit/recipes", response_model=list[AutoEditRecipeRead])
def list_recipes(_: CurrentUser) -> list[AutoEditRecipeRead]:
    """The creator recipes, in display order (today's versions)."""
    return [
        AutoEditRecipeRead(
            name=recipe.name,
            version=recipe.version,
            label=recipe.label,
            description=recipe.description,
        )  # fmt: skip
        for recipe in (current_recipe(name) for name in RECIPE_ORDER)
    ]


@recipes_router.get("/auto-edit/performance-context", response_model=PerformanceContextRead)
def performance_context(current_user: CurrentUser, db: DbSession) -> PerformanceContextRead:
    """The patterns from the creator's own shorts Auto Edit could consider (if they ask)."""
    source = _performance_source()
    profile = creator_profile(db, current_user.id, source)
    return PerformanceContextRead(
        available=profile is not None,
        simulated=source == "fake",
        sample_size=profile["sample_size"] if profile else 0,
        hints=_hint_texts(profile) or [],
    )


# --- plans --------------------------------------------------------------------------------------


@router.post(
    "",
    response_model=AutoEditPlanRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[per_user("auto_edit")],
)
def create_plan(
    body: AutoEditCreate,
    clip: OwnedClip,
    video: OwnedVideo,
    db: DbSession,
    storage: Storage,
    response: Response,
    current_user: CurrentUser,
) -> AutoEditPlanRead:
    """Plan an edit with this recipe. The same recipe and inputs return the existing plan
    (200); changed inputs (a new caption track, a tagged asset…) make a new one."""
    _require_plannable(clip, storage)
    music = _owned_music(db, video, body.music_asset_id)
    request = AutoEditRequest.from_settings(
        get_settings(), recipe=body.recipe.value, music_asset_id=music,
        performance_context=_profile_for(db, current_user.id, body.use_performance_context),
    )  # fmt: skip
    return _start(db, clip, storage, request, response)


@router.get("", response_model=AutoEditPlanPage)
def list_plans(clip: OwnedClip, db: DbSession) -> AutoEditPlanPage:
    """The clip's plans, newest first (earlier ones are kept)."""
    rows = db.scalars(
        select(AutoEditPlan)
        .where(AutoEditPlan.clip_id == clip.id)
        .order_by(
            AutoEditPlan.created_at.desc(), AutoEditPlan.generation.desc(), AutoEditPlan.id.desc()
        )
        .limit(MAX_LIST)
    ).all()
    return AutoEditPlanPage(plans=[read_plan(row) for row in rows])


@router.get("/{plan_id}", response_model=AutoEditPlanRead)
def get_plan(plan: OwnedPlan) -> AutoEditPlanRead:
    return read_plan(plan)


@router.post(
    "/{plan_id}/retry", response_model=AutoEditPlanRead, dependencies=[per_user("auto_edit")]
)
def retry_plan(
    plan: OwnedPlan, clip: OwnedClip, db: DbSession, storage: Storage
) -> AutoEditPlanRead:
    """Re-queue a failed or stalled plan on the same row with a fresh attempt token."""
    settings = get_settings()
    db.refresh(plan, with_for_update=True)  # concurrent retries serialize
    if plan.status != AutoEditStatus.FAILED and not state.is_stale(plan, settings):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only a failed or stalled plan can be retried",
        )
    if plan.attempt >= settings.auto_edit_max_attempts:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="This plan has been retried too many times"
        )
    _require_plannable(clip, storage)
    plan.status = AutoEditStatus.QUEUED
    plan.progress_percent = 0
    plan.attempt += 1
    plan.error_code = plan.error_message = None
    plan.started_at = plan.completed_at = plan.heartbeat_at = None
    plan.celery_task_id = new_task_id()  # fences out a stalled worker of the old attempt
    db.commit()
    _enqueue_or_503(db, plan, created=False)
    return read_plan(plan)


@router.post(
    "/{plan_id}/regenerate",
    response_model=AutoEditPlanRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[per_user("auto_edit")],
)
def regenerate_plan(
    plan: OwnedPlan,
    clip: OwnedClip,
    db: DbSession,
    storage: Storage,
    response: Response,
    current_user: CurrentUser,
) -> AutoEditPlanRead:
    """Try another plan with the same recipe and music: a new generation; this one is kept."""
    if plan.status in ACTIVE_AUTO_EDIT_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This plan is still being made; wait for it before trying another",
        )
    _require_plannable(clip, storage)
    previous = AutoEditRequest.from_snapshot(plan.config)
    newest = db.scalar(
        select(func.max(AutoEditPlan.generation)).where(
            AutoEditPlan.clip_id == clip.id, AutoEditPlan.recipe == plan.recipe
        )
    )
    request = AutoEditRequest.from_settings(
        get_settings(),
        recipe=plan.recipe,
        music_asset_id=previous.music_asset_id,
        generation=(newest or plan.generation) + 1,
        # Same choice as before, with the creator's current patterns.
        performance_context=_profile_for(
            db, current_user.id, previous.performance_context is not None
        ),
    )
    return _start(db, clip, storage, request, response)


@router.post(
    "/{plan_id}/apply", response_model=AutoEditApplyRead, dependencies=[per_user("edit_render")]
)
def apply_plan(
    plan: OwnedPlan,
    clip: OwnedClip,
    video: OwnedVideo,
    db: DbSession,
    storage: Storage,
) -> AutoEditApplyRead:
    """Turn a ready plan into a normal edit (rendered like any other); applying an applied plan
    returns its edit. Every asset is checked again now, exactly as for a manual edit."""
    if plan.status == AutoEditStatus.APPLIED:
        if plan.clip_edit is not None:
            return AutoEditApplyRead(plan=read_plan(plan), edit=read_edit(plan.clip_edit))
        # Its version was deleted. An applied plan never changes, so it is not re-linked; the
        # creator can open its settings in the editor ("Edit choices") or try another plan.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This plan's version was deleted; open its settings in the editor instead",
        )
    if plan.status != AutoEditStatus.READY:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Only a ready plan can be applied"
        )
    try:
        config = EditConfig.from_snapshot(plan.configuration_snapshot)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This plan can no longer be applied; try another plan",
        ) from None
    edit, _ = create_or_reuse_edit(db, clip, video, storage, config)
    try:
        state.mark_applied(plan, db, edit.id)
    except state.PlanNotReady:  # pragma: no cover - changed concurrently
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Only a ready plan can be applied"
        ) from None
    _accept_suggestions(db, plan)
    db.refresh(plan)
    return AutoEditApplyRead(plan=read_plan(plan), edit=read_edit(edit))


def _accept_suggestions(db: DbSession, plan: AutoEditPlan) -> None:
    """The creator accepted the plan's visuals: record it on their suggestions (history)."""
    used = (plan.explanation_snapshot or {}).get("used_suggestions") or []
    ids = []
    for value in used:
        try:
            ids.append(uuid.UUID(str(value)))
        except ValueError:
            continue
    if not ids:
        return
    rows = db.scalars(
        select(BrollSuggestion).where(
            BrollSuggestion.id.in_(ids),
            BrollSuggestion.clip_id == plan.clip_id,
            BrollSuggestion.status == BrollSuggestionStatus.SUGGESTED,
        )
    )
    for row in rows:
        row.status = BrollSuggestionStatus.ACCEPTED
    db.commit()
