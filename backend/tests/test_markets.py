"""Markets (V1.8): a creator's default market, a project's market and content language (two
separate choices), and the market frozen into a Short's provenance."""

from sqlalchemy import select

from app.models import Project, User
from app.services import markets
from tests.test_clip_edit_api import ready_clip, sign_up
from tests.test_video_upload import create_project


def test_markets_are_profiles_not_code_paths():
    assert set(markets.MARKETS) == {"global", "ma"}
    morocco = markets.market("ma")
    assert morocco.is_local and morocco.local_label == "Moroccan"
    assert morocco.hook_languages[0] == "darija" and "french" in morocco.hook_languages
    assert not markets.market(None).is_local  # Global is the default
    for bad in ("MA", "morocco", "xx", ""):
        if bad:
            try:
                markets.market(bad)
            except ValueError:
                continue
            raise AssertionError(bad)
    assert markets.snapshot("global", "english") is None  # Global Shorts keep their provenance
    assert markets.snapshot("ma", "french") == {
        "code": "ma", "name": "Morocco", "content_language": "french", "version": "market_v1",
    }  # fmt: skip


def test_the_market_list_is_public_to_creators(client):
    sign_up(client, "markets@example.com")
    body = client.get("/markets").json()
    assert [m["code"] for m in body["markets"]] == ["global", "ma"]
    assert [lang["code"] for lang in body["content_languages"]] == [
        "auto", "darija", "arabic", "french", "english", "mixed",
    ]  # fmt: skip
    client.cookies.clear()
    assert client.get("/markets").status_code == 401


def test_old_projects_are_global_and_new_ones_follow_the_creators_default(client, db_session):
    sign_up(client, "default@example.com")
    old = create_project(client, "Before markets")
    assert (old["market"], old["content_language"]) == ("global", "auto")
    assert client.get("/auth/me").json()["default_market"] == "global"
    assert client.patch("/auth/me", json={"default_market": "ma"}).json()["default_market"] == "ma"
    new = create_project(client, "Made in Morocco Mode")
    assert new["market"] == "ma"
    # The preference never touched the earlier project.
    assert client.get(f"/projects/{old['id']}").json()["market"] == "global"
    # An explicit choice wins over the default.
    chosen = client.post("/projects", json={"name": "Global one", "market": "global",
                                            "content_language": "french"}).json()  # fmt: skip
    assert (chosen["market"], chosen["content_language"]) == ("global", "french")
    assert client.patch("/auth/me", json={"default_market": "fr"}).status_code == 422


def test_market_and_language_are_separate_and_validated(client):
    sign_up(client, "language@example.com")
    project = create_project(client, "Casablanca vlog")
    updated = client.patch(f"/projects/{project['id']}",
                           json={"market": "ma", "content_language": "english"}).json()  # fmt: skip
    assert (updated["market"], updated["content_language"]) == ("ma", "english")
    assert client.patch(f"/projects/{project['id']}", json={"content_language": "klingon"}
                        ).status_code == 422  # fmt: skip
    assert client.patch(f"/projects/{project['id']}", json={"market": "xx"}).status_code == 422
    client.cookies.clear()
    sign_up(client, "stranger@example.com")
    assert client.patch(f"/projects/{project['id']}", json={"market": "global"}).status_code == 404


def test_a_short_freezes_the_market_it_was_made_in(client, db_session):
    sign_up(client, "frozen@example.com")
    data = ready_clip(db_session, "frozen@example.com")
    project = db_session.get(Project, data["clip"].video.project_id)
    project.market, project.content_language = "ma", "darija"
    db_session.commit()
    base = f"/projects/{project.id}/videos/{data['clip'].video_id}/clips/{data['clip'].id}/edits"
    edit = client.post(base, json={"layout": "center_crop", "captions_enabled": False}).json()
    assert edit["origin"]["market"] == markets.snapshot("ma", "darija")
    # Changing the project later never rewrites the Short.
    client.patch(f"/projects/{project.id}", json={"market": "global"})
    assert client.get(f"{base}/{edit['id']}").json()["origin"]["market"]["code"] == "ma"
    # A Global Short keeps exactly the provenance it had before markets (none).
    other = client.post(base, json={"layout": "fit", "captions_enabled": False}).json()
    assert other["origin"] is None
    user = db_session.scalar(select(User).where(User.email == "frozen@example.com"))
    assert user.default_market == "global"
