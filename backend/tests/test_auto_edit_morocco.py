"""Morocco-aware Auto Edit (V1.8): in a Moroccan project a strong local visual is preferred over an
equally strong Global one — a weak hint inside the existing rules, never a forced or weaker match —
the plan says so in plain words, freezes the market, and Global projects are exactly as before."""

from datetime import UTC, datetime, timedelta

import pytest

from app.api.auto_edit import _origin
from app.models import VisualAsset
from app.services.auto_edit.config import AutoEditRequest
from app.services.auto_edit.fallback import FallbackAutoEditPlanner
from app.services.auto_edit.fingerprint import source_fingerprint
from app.services.auto_edit.sources import gather
from app.services.storage import LocalStorageProvider
from tests.test_auto_edit_pipeline import build_world, make_plan, pipeline_settings, run, stored


@pytest.fixture
def settings():
    return pipeline_settings()


@pytest.fixture
def storage(tmp_path):
    return LocalStorageProvider(tmp_path / "media")


@pytest.fixture
def world(db_session, settings, storage, tmp_path):
    return build_world(db_session, settings, storage, tmp_path)


def local_asset(db, world, storage, tmp_path, *, tags, name="medina-bridge.jpg"):
    """A Moroccan visual added *before* the Global one (so date order alone would not pick it)."""
    asset = VisualAsset(
        project_id=world["clip"].video.project_id, kind="image", display_name=name,
        storage_key=stored(storage, tmp_path, "jpg", "visuals"), content_type="image/jpeg",
        file_size=1, sha256="d" * 64, width=1600, height=900, codec="jpeg", container="jpeg",
        description="", tags=tags, market="ma", location="Fez", category="architecture",
        created_at=datetime.now(UTC) - timedelta(days=30),
    )  # fmt: skip
    db.add(asset)
    db.commit()
    return asset


def set_market(db, world, market):
    project = world["clip"].video.project
    project.market, project.content_language = market, "darija"
    db.commit()


def placed(plan) -> list[str]:
    return [
        e["asset_id"]
        for e in (plan.configuration_snapshot.get("visuals") or {}).get("elements", [])
    ]


def test_morocco_mode_places_an_equally_strong_local_visual_first(
    db_session, world, settings, storage, tmp_path
):
    local = local_asset(db_session, world, storage, tmp_path, tags=["bridge", "joint"])
    set_market(db_session, world, "ma")
    row = make_plan(db_session, world["clip"], settings, storage)
    plan = run(db_session, row, settings, storage, FallbackAutoEditPlanner())
    assert plan.status == "ready" and placed(plan) == [str(local.id)]
    notes = plan.explanation_snapshot["notes"]
    assert "Morocco Mode put your Moroccan visuals first for this Short." in notes
    assert plan.explanation_snapshot["market"]["code"] == "ma"
    # The market is frozen into the Short made from this plan.
    assert _origin(plan)["market"] == plan.explanation_snapshot["market"]


def test_without_a_strong_local_match_the_global_one_is_used_and_said_plainly(
    db_session, world, settings, storage, tmp_path
):
    local_asset(db_session, world, storage, tmp_path, tags=["medina", "street"])
    set_market(db_session, world, "ma")
    plan = run(db_session, make_plan(db_session, world["clip"], settings, storage), settings,
               storage, FallbackAutoEditPlanner())  # fmt: skip
    assert placed(plan) == [
        str(world["bridge"].id)
    ]  # the relevant Global visual, not a forced local
    assert (
        "No strong Moroccan visual matched these moments, so PeakSift used one from your Global "
        "library." in plan.explanation_snapshot["notes"]
    )


def test_a_global_project_plans_exactly_as_before(db_session, world, settings, storage, tmp_path):
    request = AutoEditRequest.from_settings(settings, recipe="punchy")
    before = source_fingerprint(gather(world["clip"], db_session, settings, storage, request)
                                .sources, request.snapshot())  # fmt: skip
    local_asset(db_session, world, storage, tmp_path, tags=["bridge", "joint"])
    plan = run(db_session, make_plan(db_session, world["clip"], settings, storage), settings,
               storage, FallbackAutoEditPlanner())  # fmt: skip
    # Newest equally strong match first, as before markets; no market note or snapshot.
    assert placed(plan) == [str(world["bridge"].id)]
    assert "market" not in plan.explanation_snapshot
    assert not any("Mode" in note for note in plan.explanation_snapshot["notes"])
    assert "market" not in _origin(plan)
    # A Global project's fingerprint carries no market fact (earlier plans keep theirs).
    sources = gather(world["clip"], db_session, settings, storage, request).sources
    assert "market" not in sources.canonical()
    assert before != source_fingerprint(sources, request.snapshot())  # a new asset is a new fact


def test_relabelling_an_asset_local_makes_a_new_plan(
    db_session, world, settings, storage, tmp_path
):
    set_market(db_session, world, "ma")
    request = AutoEditRequest.from_settings(settings, recipe="punchy")
    first = source_fingerprint(gather(world["clip"], db_session, settings, storage, request)
                               .sources, request.snapshot())  # fmt: skip
    world["bridge"].market = "ma"
    db_session.commit()
    second = source_fingerprint(gather(world["clip"], db_session, settings, storage, request)
                                .sources, request.snapshot())  # fmt: skip
    assert first != second
