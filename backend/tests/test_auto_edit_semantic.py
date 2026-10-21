# ruff: noqa: F811 - pytest fixtures imported from test_auto_edit_pipeline are parameters here
"""Auto Edit with semantic asset matches: planners see strong / possible categories and a video's
best scene (never scores), only strong matches are placed, a video starts at its matched scene,
the explanation says how the visual was matched, unrelated suggestions get no visual, and the
plan's fingerprint follows the assets' visual-search state."""

from dataclasses import replace

import pytest
from PIL import Image, ImageDraw

from app.core.config import get_settings
from app.models import VisualAsset
from app.services.auto_edit.config import AutoEditRequest
from app.services.auto_edit.contract import BrollOption, VisualOption
from app.services.auto_edit.fallback import FallbackAutoEditPlanner
from app.services.auto_edit.fingerprint import source_fingerprint
from app.services.auto_edit.ollama import constraints
from app.services.auto_edit.recipes import current_recipe
from app.services.auto_edit.sources import gather
from app.services.auto_edit.validation import validate_plan
from app.services.semantic.fake import FAKE_IDENTITY, FakeEmbeddingProvider
from app.services.semantic.registry import reset_providers
from app.services.semantic.search import QUERY_CACHE
from tests.test_auto_edit_pipeline import (  # noqa: F401 - fixtures
    build_world,
    make_plan,
    run,
    settings,
    storage,
    stored,
    world,
)
from tests.test_auto_edit_validation import BRIDGE, BRIDGE_ID, JOINT, LAUNCH, ctx, proposal
from tests.test_semantic_domain import make_ready

BLUE, RED, YELLOW = (45, 95, 190), (215, 70, 45), (240, 200, 40)  # bridge, rocket, kitchen
FAKE = {
    "provider": FAKE_IDENTITY.provider,
    "model": FAKE_IDENTITY.model,
    "model_version": FAKE_IDENTITY.model_version,
    "embedding_version": FAKE_IDENTITY.embedding_version,
}


@pytest.fixture(autouse=True)
def fresh_model():
    QUERY_CACHE.clear()
    reset_providers()
    yield
    reset_providers()
    QUERY_CACHE.clear()


def picture(colour) -> Image.Image:
    image = Image.new("RGB", (96, 64), colour)
    ImageDraw.Draw(image).rectangle((10, 10, 30, 30), fill=(250, 250, 250))
    return image


def untagged(db, storage, tmp_path, project_id, *colours, kind="image", duration=None):
    """A visual with a camera-style name, no description, no tags — only its pixels."""
    extension = "mp4" if kind == "video" else "jpg"
    asset = VisualAsset(
        project_id=project_id, kind=kind,
        display_name=f"IMG_{len(colours)}{colours[0][0]}.{extension}",
        storage_key=stored(storage, tmp_path, extension, "visuals"),
        content_type="video/mp4" if kind == "video" else "image/jpeg", file_size=1,
        sha256=f"{abs(hash(colours)):064d}"[:64], width=1280, height=720,
        codec="h264" if kind == "video" else "jpeg", container="mp4" if kind == "video" else "jpeg",
        duration_seconds=duration, fps=30.0 if kind == "video" else None,
    )  # fmt: skip
    db.add(asset)
    db.flush()
    vectors = [
        v.tolist() for v in FakeEmbeddingProvider().embed_images([picture(c) for c in colours])
    ]
    make_ready(db, asset, vectors, **FAKE)
    db.commit()
    return asset


def without_tagged_bridge(db, world):
    db.delete(world["bridge"])
    db.commit()


# --- the planner's view and the prompt ----------------------------------------------------------

OFFERED = BrollOption(
    "suggestion_1", 10.2, 12.7, "bridge joint", "Shows the weak joint",
    ("visual_asset_1", "visual_asset_2"), ("visual_asset_1",), ("visual_asset_1", "visual_asset_2"),
    (("visual_asset_2", 4.2),),
)  # fmt: skip


def test_planners_see_categories_and_scenes_never_scores():
    view = ctx(broll=(OFFERED,)).planner_view()
    assert view["broll_suggestions"][0]["matching_assets"] == [
        {"asset": "visual_asset_1", "strength": "strong"},
        {"asset": "visual_asset_2", "strength": "possible", "best_scene_start": 4.2},
    ]


def test_the_prompt_allows_strong_pairs_only():
    rules = "\n".join(constraints(ctx(broll=(OFFERED,))))
    assert "suggestion_1 with visual_asset_1." in rules and "visual_asset_2" not in rules
    only_possible = replace(OFFERED, strong_matches=())
    rules = "\n".join(constraints(ctx(broll=(only_possible,))))
    assert "No B-roll suggestion has a strong matching asset: visuals must be []." in rules


# --- the validator -------------------------------------------------------------------------------


def test_a_possible_match_is_never_placed():
    possible = replace(JOINT, strong_matches=())
    plan = validate_plan(proposal(), ctx(broll=(possible,)), current_recipe("punchy"))
    assert "visuals" not in plan.configuration.snapshot()
    assert plan.report.possible_matches == 1
    assert any("only a possible match" in note for note in plan.explanations["notes"])


def test_a_video_starts_at_its_matched_scene():
    video = replace(LAUNCH, handle="visual_asset_1", duration=20.0)
    option = replace(JOINT, best_scenes=(("visual_asset_1", 8.4),),
                     visual_matches=("visual_asset_1",))  # fmt: skip
    plan = validate_plan(
        proposal(), ctx(broll=(option,), visual_assets=(video,)), current_recipe("punchy")
    )
    (element,) = plan.configuration.snapshot()["visuals"]["elements"]
    assert element["asset_offset_seconds"] == 7.15  # 8.4 centred in the 2.5 s moment
    item = plan.explanations["sections"]["visuals"]["items"][0]
    assert item["kind"] == "video" and item["matched"] == "visual"


def test_a_scene_near_the_end_never_leaves_a_black_tail():
    video = replace(LAUNCH, handle="visual_asset_1", duration=9.0)
    option = replace(JOINT, best_scenes=(("visual_asset_1", 8.9),))
    plan = validate_plan(
        proposal(), ctx(broll=(option,), visual_assets=(video,)), current_recipe("punchy")
    )
    (element,) = plan.configuration.snapshot()["visuals"]["elements"]
    assert element["asset_offset_seconds"] + 2.5 <= 9.0


def test_images_and_word_matches_keep_the_default_start():
    plan = validate_plan(proposal(), ctx(broll=(JOINT,)), current_recipe("punchy"))
    (element,) = plan.configuration.snapshot()["visuals"]["elements"]
    assert element["asset_offset_seconds"] == 0.0 and element["asset_id"] == BRIDGE_ID


def test_the_explanation_says_the_visual_was_matched_by_what_it_shows():
    option = replace(JOINT, visual_matches=("visual_asset_1",))
    plan = validate_plan(
        proposal(explanations__visuals="Adds visual_asset_1."),  # refused: names a handle
        ctx(broll=(option,), visual_assets=(BRIDGE,)), current_recipe("punchy"),
    )  # fmt: skip
    reason = plan.explanations["sections"]["visuals"]["reason"]
    assert reason == "Matched this image to “bridge joint” by what it shows."
    for internal in ("0.", "%", "similarity", "score", "cosine"):
        assert internal not in reason


# --- end to end with real gathering (fake embeddings) -------------------------------------------


def test_an_untagged_visual_is_placed_by_what_it_shows(db_session, world, settings, storage,
                                                      tmp_path):  # fmt: skip
    without_tagged_bridge(db_session, world)
    project_id = world["clip"].video.project_id
    photo = untagged(db_session, storage, tmp_path, project_id, BLUE)
    request = AutoEditRequest.from_settings(settings, recipe="punchy")
    context = gather(world["clip"], db_session, settings, storage, request).context
    (option,) = context.broll
    assert option.matches == option.strong_matches == option.visual_matches == ("visual_asset_1",)
    assert context.visual_ids["visual_asset_1"] == str(photo.id)
    row = make_plan(db_session, world["clip"], settings, storage)
    plan = run(db_session, row, settings, storage, FallbackAutoEditPlanner())
    (element,) = plan.configuration_snapshot["visuals"]["elements"]
    assert element["asset_id"] == str(photo.id)
    assert plan.explanation_snapshot["sections"]["visuals"]["items"][0]["matched"] == "visual"


def test_a_matched_video_scene_reaches_the_edit(db_session, world, settings, storage, tmp_path):
    without_tagged_bridge(db_session, world)
    project_id = world["clip"].video.project_id
    video = untagged(
        db_session, storage, tmp_path, project_id, RED, YELLOW, BLUE, kind="video", duration=20.0
    )  # fmt: skip  (frames at 0.5, 1.5 and 2.5 s)
    row = make_plan(db_session, world["clip"], settings, storage)
    plan = run(db_session, row, settings, storage, FallbackAutoEditPlanner())
    (element,) = plan.configuration_snapshot["visuals"]["elements"]
    assert element["asset_id"] == str(video.id)
    assert element["asset_offset_seconds"] == 1.25  # the bridge scene (2.5 s) centred


def test_unrelated_visuals_are_never_placed(db_session, world, settings, storage, tmp_path):
    without_tagged_bridge(db_session, world)
    project_id = world["clip"].video.project_id
    untagged(db_session, storage, tmp_path, project_id, RED)  # a rocket, for a bridge moment
    untagged(db_session, storage, tmp_path, project_id, YELLOW)
    row = make_plan(db_session, world["clip"], settings, storage)
    plan = run(db_session, row, settings, storage, FallbackAutoEditPlanner())
    assert "visuals" not in plan.configuration_snapshot
    assert plan.explanation_snapshot["sections"]["visuals"]["choice"] == "No visuals"


def test_a_possible_word_match_is_offered_but_not_placed(db_session, world, settings, storage,
                                                        tmp_path):  # fmt: skip
    world["bridge"].tags = ["bridge"]  # covers half of "bridge joint": possible
    world["bridge"].description = ""
    world["bridge"].display_name = "notes.jpg"
    db_session.commit()
    request = AutoEditRequest.from_settings(settings, recipe="punchy")
    context = gather(world["clip"], db_session, settings, storage, request).context
    (option,) = context.broll
    assert option.matches == ("visual_asset_1",) and option.strong_matches == ()
    row = make_plan(db_session, world["clip"], settings, storage)
    plan = run(db_session, row, settings, storage, FallbackAutoEditPlanner())
    assert "visuals" not in plan.configuration_snapshot


def test_the_fingerprint_follows_visual_search(db_session, world, settings, storage, tmp_path):
    project_id = world["clip"].video.project_id
    request = AutoEditRequest.from_settings(settings, recipe="punchy")
    before = gather(world["clip"], db_session, settings, storage, request).sources
    canonical = before.canonical()
    assert canonical["matching"].startswith("fake:")
    assert all("semantic" not in a for a in canonical["visual_assets"])  # nothing indexed yet
    untagged(db_session, storage, tmp_path, project_id, BLUE)
    after = gather(world["clip"], db_session, settings, storage, request).sources
    assert source_fingerprint(after, request.snapshot()) != source_fingerprint(
        before, request.snapshot()
    )
    assert any(
        a.get("semantic", "").startswith("ready:") for a in after.canonical()["visual_assets"]
    )
    off = get_settings().model_copy(update={"semantic_provider": "disabled"})
    plain = gather(world["clip"], db_session, off, storage, request).sources.canonical()
    assert "matching" not in plain  # V1.2-shaped facts when visual search is off


def test_existing_visual_option_shape_is_unchanged():
    # VisualOption gains nothing: planners still see the name, kind, words and orientation.
    assert set(VisualOption.__dataclass_fields__) == {
        "handle",
        "kind",
        "name",
        "description",
        "tags",
        "orientation",
        "duration",
    }


def test_the_reason_never_says_no_match_when_a_possible_match_was_offered():
    possible = replace(JOINT, strong_matches=())
    plan = validate_plan(proposal(), ctx(broll=(possible,)), current_recipe("punchy"))
    reason = plan.explanations["sections"]["visuals"]["reason"]
    assert reason == (
        "No project visual strongly matched a B-roll suggestion; possible matches are "
        "offered in the editor."
    )
    unmatched = replace(JOINT, matches=(), strong_matches=())
    plan = validate_plan(proposal(visuals=[]), ctx(broll=(unmatched,)), current_recipe("punchy"))
    assert plan.explanations["sections"]["visuals"]["reason"] in (
        "No project asset matched a B-roll suggestion.",
        "Shows the joint.",  # the planner's own sentence, accepted when nothing changed
    )
