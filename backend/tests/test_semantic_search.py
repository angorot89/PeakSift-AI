# ruff: noqa: F811 - pytest fixtures imported from test_semantic_lifecycle are parameters here
"""Semantic asset search: hybrid ranking (what the visual shows + its words), strength tiers
and thresholds, the best video scene, project isolation, fallbacks (not indexed, turned off,
model unavailable), query cleaning and bounds — and no vectors or scores in responses."""

import uuid

import numpy as np
import pytest

from app.core.config import get_settings
from app.models import VisualAsset
from app.services.semantic import search as search_module
from app.services.semantic.contract import EmbeddingUnavailable
from app.services.semantic.fake import FAKE_IDENTITY, FakeEmbeddingProvider
from app.services.semantic.registry import install_provider, reset_providers
from app.services.semantic.search import (
    MAX_QUERY_CHARS,
    QUERY_CACHE,
    AssetMatch,
    MatchMethod,
    QueryCache,
    Strength,
    Thresholds,
    VisualScore,
    clean_query,
    rank_assets,
    thresholds_for,
)
from tests.media_fixtures import requires_ffmpeg
from tests.test_semantic_lifecycle import jobs, upload  # noqa: F401 - fixtures
from tests.test_video_upload import create_project, sign_up
from tests.visual_fixtures import make_image, make_video

BLUE, RED, YELLOW = (45, 95, 190), (215, 70, 45), (240, 200, 40)  # bridge, rocket, kitchen


@pytest.fixture(autouse=True)
def fresh_cache():
    QUERY_CACHE.clear()
    yield
    QUERY_CACHE.clear()


# --- ranking (pure) -------------------------------------------------------------------------

T = Thresholds(strong=0.6, possible=0.4, prompt="{query}", version="t")


def asset(name="IMG_0001.jpg", tags=(), description="", kind="image", seconds=0):
    from datetime import UTC, datetime, timedelta

    return VisualAsset(
        id=uuid.uuid4(), display_name=name, tags=list(tags), description=description, kind=kind,
        created_at=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=seconds),
    )  # fmt: skip


def test_tiers_come_from_the_better_signal_and_weak_matches_are_left_out():
    strong_visual, possible_visual, weak = asset(), asset(), asset()
    tagged = asset("x.jpg", tags=["bridge"])
    named = asset("bridge-model.jpg")  # covers half of "bridge model joint"? see below
    visual = {
        strong_visual.id: VisualScore(0.7, None),
        possible_visual.id: VisualScore(0.45, None),
        weak.id: VisualScore(0.2, None),
    }
    found = rank_assets("bridge", [weak, possible_visual, tagged, named, strong_visual], visual, T)
    by_id = {m.asset.id: m for m in found}
    assert weak.id not in by_id  # below both cut-offs: never padded in
    assert by_id[strong_visual.id].strength == Strength.STRONG
    assert by_id[strong_visual.id].method == MatchMethod.VISUAL
    assert by_id[possible_visual.id].strength == Strength.POSSIBLE
    assert by_id[tagged.id].strength == Strength.STRONG
    assert by_id[tagged.id].method == MatchMethod.METADATA
    assert [m.strength for m in found] == sorted(
        (m.strength for m in found), key=lambda s: s != Strength.STRONG
    )  # strong before possible


def test_agreement_ranks_first_and_ties_prefer_the_newer_asset():
    both = asset("rocket.jpg", seconds=1)
    visual_only = asset(seconds=2)
    newer = asset(seconds=3)
    visual = {
        both.id: VisualScore(0.62, None),
        visual_only.id: VisualScore(0.62, None),
        newer.id: VisualScore(0.62, None),
    }
    found = rank_assets("rocket", [both, visual_only, newer], visual, T)
    assert found[0].asset is both and found[0].method == MatchMethod.BOTH
    assert [m.asset for m in found[1:]] == [newer, visual_only]


def test_without_thresholds_only_words_match():
    tagged, untagged = asset(tags=["rocket"]), asset()
    visual = {untagged.id: VisualScore(0.99, 1.0)}
    found = rank_assets("rocket launch", [tagged, untagged], visual, None)
    assert [m.asset for m in found] == [tagged] and found[0].similarity is None


def test_best_frame_time_only_for_visual_matches():
    video = asset(kind="video")
    found = rank_assets("bridge", [video], {video.id: VisualScore(0.65, 8.4)}, T)
    assert found[0].best_frame_time == 8.4
    by_words = asset("bridge.mp4", kind="video")
    found = rank_assets("bridge", [by_words], {by_words.id: VisualScore(0.1, 3.0)}, T)
    assert found[0].best_frame_time is None and found[0].method == MatchMethod.METADATA


def test_matches_are_ranking_signals_not_probabilities():
    a = asset(tags=["bridge"])
    match: AssetMatch = rank_assets("bridge", [a], {a.id: VisualScore(0.95, None)}, T)[0]
    assert 0 <= match.combined_score <= 1 + search_module.AGREEMENT_BONUS


@pytest.mark.parametrize(
    ("raw", "clean"),
    [
        ("  rocket   launch ", "rocket launch"),
        ("bridge\x00\x07joint", "bridge joint"),
        ("line\nbreak\ttab", "line break tab"),
        ("Brücke über den Fluss 🌉", "Brücke über den Fluss 🌉"),
        ("‮rocket", "rocket"),  # a bidi override is a control (format) character
        ("x" * 300, "x" * MAX_QUERY_CHARS),
        ("\x00\x01  ", ""),
    ],
)
def test_queries_are_cleaned_and_bounded(raw, clean):
    assert clean_query(raw) == clean


def test_the_query_cache_is_bounded_and_keyed_by_model():
    fake = FakeEmbeddingProvider()
    cache = QueryCache(size=2)
    first = cache.vector(fake, "bridge")
    assert cache.vector(fake, "bridge") is first and fake.text_calls == 1
    cache.vector(fake, "rocket")
    cache.vector(fake, "kitchen")
    cache.vector(fake, "bridge")  # evicted, embedded again
    assert fake.text_calls == 4


def test_every_known_model_has_its_own_versioned_thresholds():
    from app.services.semantic.clip_onnx import CLIP_IDENTITY

    clip, fake = thresholds_for(CLIP_IDENTITY), thresholds_for(FAKE_IDENTITY)
    assert clip and fake and clip.version != fake.version
    assert 0 < clip.possible < clip.strong < 1 and "{query}" in clip.prompt
    assert thresholds_for(None) is None


# --- the API --------------------------------------------------------------------------------


@pytest.fixture
def project(client):
    sign_up(client, f"seeker-{uuid.uuid4().hex[:8]}@example.com")
    return create_project(client)["id"]


def search(client, project_id, q, **params):
    return client.get(f"/projects/{project_id}/visual-assets/search", params={"q": q, **params})


@pytest.fixture
def library(client, project, jobs, tmp_path):  # noqa: F811
    """An untagged bridge photo, a named-and-tagged rocket photo, an untagged kitchen photo."""
    ids = {}
    ids["bridge"] = upload(client, project, make_image(tmp_path / "IMG_7834.jpg", color=BLUE)
                           ).json()["id"]  # fmt: skip
    rocket = upload(client, project, make_image(tmp_path / "launch-day.jpg", color=RED)).json()
    client.patch(f"/projects/{project}/visual-assets/{rocket['id']}", json={"tags": ["rocket"]})
    ids["rocket"] = rocket["id"]
    ids["kitchen"] = upload(client, project, make_image(tmp_path / "IMG_0002.jpg", color=YELLOW)
                            ).json()["id"]  # fmt: skip
    jobs.run()
    return ids


@requires_ffmpeg
def test_an_untagged_asset_is_found_by_what_it_shows(client, project, library):
    body = search(client, project, "bridge structure").json()
    assert body["visual_search_used"] is True and body["assets_preparing"] == 0
    assert body["query"] == "bridge structure"
    (hit,) = body["results"]
    assert (
        hit["asset"]["id"] == library["bridge"] and hit["asset"]["display_name"] == "IMG_7834.jpg"
    )
    assert hit["match"] == {"strength": "strong", "method": "visual", "best_frame_time": None}


@requires_ffmpeg
def test_words_and_pixels_agree_and_unrelated_queries_find_nothing(client, project, library):
    hits = search(client, project, "rocket launch").json()["results"]
    assert hits[0]["asset"]["id"] == library["rocket"]
    assert hits[0]["match"]["method"] == "visual_and_metadata"
    assert search(client, project, "weather forecast").json()["results"] == []


@requires_ffmpeg
def test_responses_carry_no_vectors_scores_or_internals(client, project, library):
    text = search(client, project, "bridge").text
    for internal in ("embedding", "similarity", "score", "palette", "model", "threshold"):
        assert internal not in text


@requires_ffmpeg
def test_kind_filter_and_result_bound(client, project, library):
    assert search(client, project, "bridge", kind="video").json()["results"] == []
    assert len(search(client, project, "rocket", limit=1).json()["results"]) == 1
    assert search(client, project, "rocket", limit=0).status_code == 422
    assert search(client, project, "rocket", limit=51).status_code == 422


@requires_ffmpeg
def test_other_projects_and_users_are_invisible(client, project, library, jobs, tmp_path):  # noqa: F811
    other = create_project(client)["id"]
    upload(client, other, make_image(tmp_path / "IMG_9999.jpg", color=BLUE))
    jobs.run()
    hits = search(client, project, "bridge").json()["results"]
    assert [h["asset"]["id"] for h in hits] == [library["bridge"]]
    client.post("/auth/logout")
    sign_up(client, f"intruder-{uuid.uuid4().hex[:8]}@example.com")
    assert search(client, project, "bridge").status_code == 404


def test_search_needs_a_session(client):
    assert search(client, uuid.uuid4(), "bridge").status_code == 401


@requires_ffmpeg
@pytest.mark.parametrize("q", ["", "   ", "\x00\x01", "x" * 201])
def test_empty_control_only_and_overlong_queries_are_refused(client, project, q):
    assert search(client, project, q).status_code == 422


@requires_ffmpeg
def test_unicode_queries_work(client, project, library):
    response = search(client, project, "Brücke 🌉")
    assert response.status_code == 200 and response.json()["query"] == "Brücke 🌉"


@requires_ffmpeg
def test_before_indexing_words_still_match_and_preparing_is_reported(
    client, project, jobs, tmp_path
):  # noqa: F811
    upload(client, project, make_image(tmp_path / "rocket.jpg", color=RED))
    upload(client, project, make_image(tmp_path / "IMG_1.jpg", color=BLUE))
    body = search(client, project, "rocket").json()  # nothing indexed yet
    assert body["visual_search_used"] is False and body["assets_preparing"] == 2
    assert [h["match"]["method"] for h in body["results"]] == ["metadata"]
    assert search(client, project, "bridge").json()["results"] == []  # needs the pixels
    jobs.run()
    body = search(client, project, "bridge").json()
    assert body["visual_search_used"] is True and body["results"][0]["match"]["method"] == "visual"


@requires_ffmpeg
def test_model_unavailable_falls_back_to_words(client, project, library, monkeypatch):
    class Broken(FakeEmbeddingProvider):
        def embed_text(self, text):
            raise EmbeddingUnavailable("The visual search model is not installed on this server")

    reset_providers()
    install_provider(get_settings(), Broken())
    body = search(client, project, "rocket").json()
    assert body["visual_search_used"] is False
    assert [h["asset"]["id"] for h in body["results"]] == [library["rocket"]]


@requires_ffmpeg
def test_turned_off_searches_words_only(client, project, library, monkeypatch):
    off = get_settings().model_copy(update={"semantic_provider": "disabled"})
    monkeypatch.setattr("app.api.visual_assets.get_settings", lambda: off)
    body = search(client, project, "bridge").json()
    assert body == {"query": "bridge", "visual_search_used": False, "assets_preparing": 0,
                    "results": []}  # fmt: skip


@requires_ffmpeg
def test_a_video_reports_its_best_scene(client, project, jobs, tmp_path):  # noqa: F811
    shot = "drawbox=x=40:y=40:w=80:h=60:color=white:t=fill,noise=alls=20:allf=t"
    video = make_video(
        tmp_path / "VID_1429.mp4", seconds=8.0, extra_filters=shot,
        source="color=c=0x2d5fbe:size=320x180:rate=30:duration=4[a];"
               "color=c=0xd7462d:size=320x180:rate=30:duration=4[b];[a][b]concat=n=2:v=1:a=0",
    )  # fmt: skip
    body = upload(client, project, video).json()
    jobs.run()
    (hit,) = search(client, project, "rocket launch").json()["results"]
    assert hit["asset"]["id"] == body["id"] and hit["match"]["method"] == "visual"
    assert 4.0 <= hit["match"]["best_frame_time"] < 8.0  # the rocket half
    (hit,) = search(client, project, "bridge").json()["results"]
    assert 0.0 <= hit["match"]["best_frame_time"] < 4.0


@requires_ffmpeg
def test_a_stale_index_is_never_compared(client, project, library, db_session):
    for row in db_session.get(VisualAsset, uuid.UUID(library["bridge"])).semantic_indexes:
        row.model_version = "old"
    db_session.flush()
    body = search(client, project, "bridge structure").json()
    assert body["results"] == [] and body["assets_preparing"] == 1


def test_query_vectors_are_cached_per_process(monkeypatch):
    fake = FakeEmbeddingProvider()
    thresholds = thresholds_for(FAKE_IDENTITY)
    a = search_module.query_vector(fake, thresholds, "bridge")
    b = search_module.query_vector(fake, thresholds, "bridge")
    assert a is b and fake.text_calls == 1 and np.isclose(np.linalg.norm(a), 1)
