"""Semantic B-roll matching: suggestion queries against the project's visuals by what they show
and by their words, strong / possible tiers, the best video scene and a safe playback offset,
project isolation, stale vectors, fallbacks — and the B-roll API's match details."""

import pytest
from PIL import Image, ImageDraw

from app.core.config import get_settings
from app.services.semantic.fake import FAKE_IDENTITY, FakeEmbeddingProvider
from app.services.semantic.matching import MAX_SUGGESTION_MATCHES, asset_offset, match_queries
from app.services.semantic.registry import install_provider, reset_providers
from app.services.semantic.search import QUERY_CACHE, MatchMethod, Strength
from tests.test_broll_api import clip_ctx, complete, fake_queue  # noqa: F401 - fixture
from tests.test_clip_edit_api import sign_up
from tests.test_semantic_domain import make_ready
from tests.test_visual_asset_model import image_fields, make_asset, make_project, video_fields

BLUE, RED, YELLOW = (45, 95, 190), (215, 70, 45), (240, 200, 40)  # bridge, rocket, kitchen
FAKE = {
    "provider": FAKE_IDENTITY.provider,
    "model": FAKE_IDENTITY.model,
    "model_version": FAKE_IDENTITY.model_version,
    "embedding_version": FAKE_IDENTITY.embedding_version,
}


@pytest.fixture(autouse=True)
def fake_model():
    QUERY_CACHE.clear()
    reset_providers()
    fake = FakeEmbeddingProvider()
    install_provider(get_settings(), fake)
    yield fake
    reset_providers()
    QUERY_CACHE.clear()


def picture(colour) -> Image.Image:
    image = Image.new("RGB", (96, 64), colour)
    ImageDraw.Draw(image).rectangle((10, 10, 30, 30), fill=(250, 250, 250))
    return image


def indexed(db, project, *colours, video=False, **fields):
    fake = FakeEmbeddingProvider()
    vectors = [v.tolist() for v in fake.embed_images([picture(c) for c in colours])]
    asset = make_asset(db, (video_fields if video else image_fields)(project, **fields))
    make_ready(db, asset, vectors, **FAKE)
    return asset


# --- the playback offset ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("best", "element", "video", "offset"),
    [
        (8.4, 2.5, 20.0, 7.15),  # centred on the scene
        (0.3, 2.5, 20.0, 0.0),  # never before the start
        (19.5, 2.5, 20.0, 17.5),  # never past the end: no black tail
        (12.0, 2.5, 12.495, 9.99),  # rounded down, never up past the end
        (None, 2.5, 20.0, 0.0),  # an image, or a match by words
        (4.0, 3.0, 3.0, 0.0),  # the video is not longer than the element
        (4.0, 3.0, 2.0, 0.0),
        (float("nan"), 2.5, 20.0, 0.0),
        (4.0, float("inf"), 20.0, 0.0),
        (4.0, 0.0, 20.0, 0.0),
        (4.0, 2.5, None, 0.0),
    ],
)
def test_asset_offset_is_centred_and_always_inside_the_video(best, element, video, offset):
    value = asset_offset(best, element, video)
    assert value == offset
    if video and element and value:
        assert 0 <= value and value + element <= video


# --- matching ------------------------------------------------------------------------------


def test_an_untagged_visual_matches_by_what_it_shows(db_session):
    project = make_project(db_session)
    bridge = indexed(db_session, project, BLUE, display_name="IMG_7834.jpg")
    rocket = indexed(db_session, project, RED, display_name="launch.jpg", tags=["rocket"])
    kitchen = indexed(db_session, project, YELLOW, display_name="IMG_0002.jpg")
    assets = [bridge, rocket, kitchen]
    found = match_queries(
        db_session, project.id, ["bridge joint", "rocket launch", "weather map"], assets,
        get_settings(),
    )  # fmt: skip
    assert found.visual_used
    (match,) = found.get("bridge joint")
    assert match.asset is bridge and match.strength == Strength.STRONG
    assert match.method == MatchMethod.VISUAL and match.similarity is not None
    first = found.get("rocket launch")[0]
    assert first.asset is rocket and first.method == MatchMethod.BOTH
    assert found.get("weather map") == []  # an unrelated query matches nothing


def test_a_partial_word_match_is_only_possible(db_session):
    project = make_project(db_session)
    # A tag covering half of the query's subject words: a possible match, never strong.
    notes = indexed(db_session, project, YELLOW, display_name="notes.png", tags=["bridge"])
    (match,) = match_queries(db_session, project.id, ["bridge joint"], [notes], get_settings()).get(
        "bridge joint"
    )
    assert match.strength == Strength.POSSIBLE and match.method == MatchMethod.METADATA


def test_matches_are_bounded_and_strongest_first(db_session):
    project = make_project(db_session)
    assets = [indexed(db_session, project, BLUE, display_name=f"IMG_{n}.jpg") for n in range(5)]
    assets.append(indexed(db_session, project, YELLOW, display_name="bridge.jpg"))
    found = match_queries(db_session, project.id, ["bridge"], assets, get_settings()).get("bridge")
    assert len(found) == MAX_SUGGESTION_MATCHES
    assert all(m.strength == Strength.STRONG for m in found)


def test_a_video_matches_by_its_best_scene(db_session):
    project = make_project(db_session)
    video = indexed(db_session, project, BLUE, RED, video=True, display_name="VID_1429.mp4")
    found = match_queries(
        db_session, project.id, ["rocket launch", "bridge"], [video], get_settings()
    )
    assert found.get("rocket launch")[0].best_frame_time == 1.5  # the second (red) frame
    assert found.get("bridge")[0].best_frame_time == 0.5


def test_other_projects_and_stale_vectors_never_match(db_session):
    project, other = make_project(db_session), make_project(db_session)
    mine = indexed(db_session, project, YELLOW, display_name="IMG_1.jpg")
    indexed(db_session, other, BLUE, display_name="IMG_2.jpg")  # another project's bridge
    old = make_asset(db_session, image_fields(project, display_name="IMG_3.jpg"))
    make_ready(db_session, old, [FakeEmbeddingProvider().embed_images([picture(BLUE)])[0].tolist()],
               **{**FAKE, "model_version": "0"})  # fmt: skip
    found = match_queries(db_session, project.id, ["bridge"], [mine, old], get_settings())
    assert found.get("bridge") == []


def test_without_the_model_words_still_match(db_session, monkeypatch):
    project = make_project(db_session)
    tagged = indexed(db_session, project, YELLOW, display_name="x.jpg", tags=["bridge"])
    untagged = indexed(db_session, project, BLUE, display_name="IMG_7.jpg")

    class Broken(FakeEmbeddingProvider):
        def embed_text(self, text):
            from app.services.semantic.contract import EmbeddingFailure

            raise EmbeddingFailure("The visual search model failed on the query")

    reset_providers()
    install_provider(get_settings(), Broken())
    found = match_queries(db_session, project.id, ["bridge"], [tagged, untagged], get_settings())
    assert not found.visual_used
    assert [m.asset for m in found.get("bridge")] == [tagged]
    off = get_settings().model_copy(update={"semantic_provider": "disabled"})
    found = match_queries(db_session, project.id, ["bridge"], [tagged, untagged], off)
    assert not found.visual_used and [m.asset for m in found.get("bridge")] == [tagged]


def test_each_query_is_embedded_once(db_session, fake_model):
    project = make_project(db_session)
    asset = indexed(db_session, project, BLUE)
    match_queries(db_session, project.id, ["bridge", "bridge", "rocket"], [asset], get_settings())
    match_queries(db_session, project.id, ["bridge"], [asset], get_settings())
    assert fake_model.text_calls == 2  # deduplicated, then cached


def test_no_assets_or_queries_is_quietly_empty(db_session, fake_model):
    project = make_project(db_session)
    assert match_queries(db_session, project.id, ["bridge"], [], get_settings()).get("bridge") == []
    assert match_queries(db_session, project.id, [], [], get_settings()).by_query == {}
    assert fake_model.text_calls == 0


# --- the B-roll API ----------------------------------------------------------------------------


def test_suggestions_carry_tiered_match_details(client, db_session):
    sign_up(client)
    ctx = clip_ctx(db_session)
    project = ctx["video"].project
    rocket = indexed(db_session, project, RED, display_name="IMG_5521.jpg")
    video = indexed(db_session, project, BLUE, RED, video=True, display_name="VID_1429.mp4")
    analysis_id = client.post(f"{ctx['base']}/analyses").json()["id"]
    complete(db_session, analysis_id)  # suggestions: "rocket", "Moon / spacecraft"
    state = client.get(ctx["base"]).json()
    by_query = {s["query"]: s for s in state["suggestions"]}
    rocket_suggestion = by_query["rocket"]
    assert set(rocket_suggestion["matches"]) == {str(rocket.id), str(video.id)}
    details = {d["asset_id"]: d for d in rocket_suggestion["match_details"]}
    assert details[str(rocket.id)] == {"asset_id": str(rocket.id), "strength": "strong",
                                       "method": "visual", "best_frame_time": None}  # fmt: skip
    assert details[str(video.id)]["best_frame_time"] == 1.5
    assert rocket_suggestion["matches"] == [
        d["asset_id"] for d in rocket_suggestion["match_details"]
    ]
    text = client.get(ctx["base"]).text
    for internal in ("similarity", "score", "embedding", "palette"):
        assert internal not in text
