"""Local assets (V1.8): creator-chosen origin (licensed needs its licence), market, category and
location (only from the market's list, only for local assets); local-first search that never
buries a better Global match; the Creator Kit lists only the creator's own local assets."""

from pathlib import Path

import pytest

from app.services import asset_labels
from tests.media_fixtures import requires_ffmpeg
from tests.test_audio_assets_api import make_audio
from tests.test_audio_assets_api import upload as upload_audio
from tests.test_clip_edit_api import sign_up
from tests.test_video_upload import create_project
from tests.test_visual_assets_api import clean_media_root, upload  # noqa: F401
from tests.visual_fixtures import make_image

pytestmark = requires_ffmpeg


def visual(client, project_id, tmp_path: Path, name: str, color=(120, 80, 40)) -> dict:
    path = make_image(tmp_path / name, size=(320, 180), color=color)
    response = upload(client, project_id, path)
    assert response.status_code == 201, response.text
    return response.json()


def label(client, project_id, asset_id, **changes):
    return client.patch(f"/projects/{project_id}/visual-assets/{asset_id}", json=changes)


def test_labels_are_the_creators_and_validated_together():
    clean = asset_labels.clean_labels
    base = asset_labels.read(type("A", (), dict.fromkeys(asset_labels.FIELDS))())
    assert clean("visual", base, {})["origin"] == "creator_upload"
    with pytest.raises(ValueError, match="licence"):
        clean("visual", base, {"origin": "licensed"})
    assert clean("visual", base, {"origin": "licensed", "license_note": "Envato, licence 123"})
    with pytest.raises(ValueError):
        clean("visual", base, {"origin": "internet"})  # no such origin
    with pytest.raises(ValueError):
        clean("visual", base, {"market": "ma", "location": "Paris"})  # not in Morocco's list
    local = clean("visual", base, {"market": "ma", "location": "Casablanca", "category": "cafe"})
    assert (local["market"], local["location"], local["category"]) == ("ma", "Casablanca", "cafe")
    assert clean("visual", local, {"market": "global"})["location"] is None  # Global: no place
    with pytest.raises(ValueError):
        clean("audio", base, {"category": "cafe"})  # a visual category on a sound
    assert clean("audio", base, {"category": "cafe_ambience"})["category"] == "cafe_ambience"


def test_search_puts_local_matches_first_without_burying_better_global_ones(client, tmp_path):
    sign_up(client, "local-search@example.com")
    project = create_project(client, "Casablanca café vlog")["id"]
    client.patch(f"/projects/{project}", json={"market": "ma"})
    generic = visual(client, project, tmp_path, "generic-cafe.jpg")
    label(client, project, generic["id"], tags=["café", "Casablanca"])  # strong, Global
    local = visual(client, project, tmp_path, "my-cafe.jpg", (60, 90, 120))
    label(client, project, local["id"], tags=["café", "Casablanca"], market="ma",
          location="Casablanca", category="cafe")  # fmt: skip
    weak_local = visual(client, project, tmp_path, "street.jpg", (20, 140, 60))
    label(client, project, weak_local["id"], tags=["Casablanca"], market="ma")  # possible only
    hits = client.get(f"/projects/{project}/visual-assets/search", params={"q": "café Casablanca"}
                      ).json()["results"]  # fmt: skip
    order = [(h["asset"]["id"], h["match"]["strength"], h["local"]) for h in hits]
    assert order[0] == (local["id"], "strong", True)  # same tier: local first
    assert order[1] == (generic["id"], "strong", False)  # a strong Global match stays above…
    assert order[2] == (weak_local["id"], "possible", True)  # …a weaker local one
    # A Global project ranks as before: no local flag, no local preference.
    client.patch(f"/projects/{project}", json={"market": "global"})
    hits = client.get(f"/projects/{project}/visual-assets/search", params={"q": "café Casablanca"}
                      ).json()["results"]  # fmt: skip
    assert not any(h["local"] for h in hits)


def test_unrelated_queries_never_pull_in_local_assets(client, tmp_path):
    sign_up(client, "dashboard@example.com")
    project = create_project(client, "SaaS demo")["id"]
    client.patch(f"/projects/{project}", json={"market": "ma"})
    dashboard = visual(client, project, tmp_path, "software-dashboard.png")
    local = visual(client, project, tmp_path, "medina.jpg", (200, 120, 40))
    label(client, project, local["id"], tags=["medina", "street"], market="ma", location="Fez")
    hits = client.get(f"/projects/{project}/visual-assets/search",
                      params={"q": "software dashboard"}).json()["results"]  # fmt: skip
    assert [h["asset"]["id"] for h in hits] == [dashboard["id"]]


def test_sounds_carry_labels_and_the_kit_lists_only_your_local_assets(client, tmp_path):
    sign_up(client, "sounds@example.com")
    project = create_project(client, "Market day")["id"]
    path = make_audio(tmp_path / "souk.wav", seconds=2.0)
    sound = upload_audio(client, project, path, kind="sfx").json()
    base = f"/projects/{project}/audio-assets/{sound['id']}"
    assert client.patch(base, json={"origin": "licensed"}).status_code == 422
    labelled = client.patch(base, json={"market": "ma", "category": "market_ambience",
                                        "origin": "cc0"}).json()  # fmt: skip
    assert (labelled["market"], labelled["category"], labelled["origin"]) == (
        "ma", "market_ambience", "cc0"
    )  # fmt: skip
    pic = visual(client, project, tmp_path, "atlas.jpg")
    label(client, project, pic["id"], market="ma", location="Atlas", category="mountains")
    kit = client.get("/markets/ma/assets", params={"kind": "visual"}).json()["assets"]
    assert [a["id"] for a in kit] == [pic["id"]] and kit[0]["location"] == "Atlas"
    sounds = client.get("/markets/ma/assets", params={"kind": "audio"}).json()["assets"]
    assert [a["id"] for a in sounds] == [sound["id"]]
    assert client.get("/markets/global/assets").json()["assets"] == []
    assert client.get("/markets/xx/assets").status_code == 404
    client.cookies.clear()
    sign_up(client, "not-sounds@example.com")
    assert client.get("/markets/ma/assets").json()["assets"] == []
    assert client.patch(base, json={"market": "global"}).status_code == 404


def test_labels_are_owner_scoped_and_errors_never_echo_what_was_sent(client, tmp_path):
    sign_up(client, "labels-owner@example.com")
    project = create_project(client, "Owner")["id"]
    pic = visual(client, project, tmp_path, "rabat.jpg")
    bad = label(client, project, pic["id"], market="ma", location="Paris-not-in-list")
    assert bad.status_code == 422 and "Paris-not-in-list" not in bad.text
    long_note = label(client, project, pic["id"], origin="licensed", license_note="x" * 301)
    assert long_note.status_code == 422 and "x" * 50 not in long_note.text
    assert label(client, project, pic["id"], storage_key="elsewhere").status_code == 422
    ok = label(client, project, pic["id"], origin="licensed", license_note="  Own   shoot, 2026 ")
    assert ok.json()["license_note"] == "Own shoot, 2026"  # whitespace tidied, words kept
    client.cookies.clear()
    sign_up(client, "labels-other@example.com")
    assert label(client, project, pic["id"], market="global").status_code == 404
    assert client.get("/markets/ma/assets", params={"kind": "visual"}).json()["assets"] == []


def test_the_creators_category_and_place_count_like_tags():
    """V1.8 journey: a photo labelled Café · Casablanca, named casa-cafe-morning.jpg with no
    tags, was not found by "Casablanca café". The creator's own labels now count like tags."""
    from types import SimpleNamespace

    from app.services.broll.matching import MIN_SCORE, AssetTerms, match_score

    def asset(**labels):
        return SimpleNamespace(id="a", display_name="casa-cafe-morning.jpg", tags=[],
                               description=None, **labels)  # fmt: skip

    labelled = AssetTerms.of(asset(category="cafe", location="Casablanca"))
    assert match_score("Casablanca café", labelled) >= MIN_SCORE
    plain = AssetTerms.of(asset(category=None, location=None))
    assert match_score("Casablanca café", plain) < MIN_SCORE  # unchanged without labels
    assert match_score("software dashboard", labelled) == 0
