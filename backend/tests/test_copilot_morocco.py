"""Ask PeakSift in Morocco Mode (V1.8): what PeakSift knows exactly — local assets, templates,
the project's language, the clip's own Darija lines, the Global library — is answered without
the model; Global projects get no market facts; another creator's assets never count."""

from app.models import AudioAsset, Project, Transcription, TranscriptSegment, VisualAsset
from app.services.copilot.prompt import SYSTEM_PROMPT
from tests.test_clip_edit_api import ready_clip, sign_up
from tests.test_copilot_acceptance import ask, use

DARIJA = ["Wach 3mrk tfrjti f had l9hwa f Casablanca?",
          "Dima kanqol lik: jreb l9ahwa b l7lib, zwina bzaf!"]  # fmt: skip


def project_with(db, email, *, market="ma", language="auto", lines=DARIJA, local=True):
    data = ready_clip(db, email)
    clip = data["clip"]
    project = db.get(Project, clip.video.project_id)
    project.market, project.content_language = market, language
    transcription = db.query(Transcription).filter_by(video_id=clip.video_id).one()
    db.query(TranscriptSegment).filter_by(transcription_id=transcription.id).delete()
    for i, line in enumerate(lines):
        db.add(TranscriptSegment(transcription_id=transcription.id, sequence_index=i,
                                 start_time=11.0 + i * 5, end_time=15.0 + i * 5,
                                 text=line))  # fmt: skip
    for name, mkt in (("casa-cafe.jpg", "ma" if local else "global"), ("dashboard.png", "global")):
        db.add(VisualAsset(
            project_id=project.id, kind="image", display_name=name, storage_key=f"v/{name}{email}",
            content_type="image/jpeg", file_size=1, sha256=name[0] * 64, width=640, height=360,
            codec="jpeg", container="jpeg", market=mkt,
        ))  # fmt: skip
    db.add(AudioAsset(
        project_id=project.id, kind="sfx", display_name="souk.wav", storage_key=f"a/souk{email}",
        content_type="audio/wav", file_size=1, sha256="b" * 64, container="wav", codec="pcm",
        duration_seconds=2.0, sample_rate=44100, channels=2, waveform_peaks=[],
        market="ma" if local else "global", category="market_ambience",
    ))  # fmt: skip
    db.commit()
    return project, clip


def test_local_assets_are_a_database_fact_not_a_model_answer(client, db_session, monkeypatch):
    sign_up(client, "copilot-ma@example.com")
    project, _ = project_with(db_session, "copilot-ma@example.com")
    fake = use(monkeypatch)
    answer = ask(client, "Do I have any Moroccan visuals?", "assets", project_id=project.id)
    assert answer["content"] == (
        "Yes: 1 Moroccan visual (“casa-cafe.jpg”) and 1 Moroccan sound (market ambience) in this "
        "project."
    )
    global_lib = ask(client, "What can I use from the global library?", "assets",
                     project_id=project.id)["content"]  # fmt: skip
    assert "1 Global visual (“dashboard.png”)" in global_lib and "Clean, Punchy" in global_lib
    assert not fake.calls


def test_language_and_darija_hooks_come_from_the_project_and_the_clip(client, db_session,
                                                                      monkeypatch):  # fmt: skip
    sign_up(client, "copilot-lang@example.com")
    project, clip = project_with(db_session, "copilot-lang@example.com", language="french")
    fake = use(monkeypatch)
    ids = {"project_id": project.id, "clip_id": clip.id}
    keep = ask(client, "Can I keep this Short in French?", "editor", **ids)["content"]
    assert keep.startswith("Yes. Morocco Mode never changes your language") and "French" in keep
    hooks = ask(client, "Give me 3 Darija hooks", "editor", **ids)["content"]
    assert "“Wach 3mrk tfrjti f had l9hwa f Casablanca?”" in hooks  # the creator's own words
    fit = ask(client, "Which Morocco template fits this clip?", "editor", **ids)["content"]
    assert "“Local Storytime”" in fit and "not a prediction" in fit  # a story moment
    assert "Morocco Vox Pop" in fit and "Global templates stay available" in fit
    assert not fake.calls


def test_no_darija_is_written_for_a_clip_that_isnt_in_darija(client, db_session, monkeypatch):
    sign_up(client, "copilot-en@example.com")
    project, clip = project_with(db_session, "copilot-en@example.com", lines=[
        "Today I tried to beat my record on the lava level and it went wrong.",
        "Here is the tip nobody tells you about that jump.",
    ])  # fmt: skip
    use(monkeypatch)
    hooks = ask(client, "Give me 3 Darija hooks", "editor", project_id=project.id,
                clip_id=clip.id)["content"]  # fmt: skip
    assert hooks.startswith("Your clip isn't in Darija") and "never written for you" in hooks


def test_global_projects_get_no_market_facts_unless_asked(client, db_session, monkeypatch):
    sign_up(client, "copilot-global@example.com")
    project, _ = project_with(db_session, "copilot-global@example.com", market="global",
                              local=False)  # fmt: skip
    use(monkeypatch, {"message": "Here is your project."})
    from app.core.config import get_settings
    from app.models import User
    from app.services.copilot.context import build_context

    user = db_session.query(User).filter_by(email="copilot-global@example.com").one()
    plain = build_context(db_session, user, get_settings(), page="assets", project_id=project.id,
                          question="What is this video about?")  # fmt: skip
    assert "market" not in plain.view
    asked = build_context(db_session, user, get_settings(), page="assets", project_id=project.id,
                          question="Do I have any Moroccan visuals?")  # fmt: skip
    assert asked.view["market"]["local_visual_total"] == 0
    answer = ask(client, "Do I have any Moroccan visuals?", "assets", project_id=project.id)
    assert answer["content"].startswith("Not yet: no visual or sound in this project is marked")


def test_another_creators_assets_never_count(client, db_session, monkeypatch):
    sign_up(client, "owner-ma@example.com")
    project_with(db_session, "owner-ma@example.com")
    client.cookies.clear()
    sign_up(client, "other-ma@example.com")
    mine, _ = project_with(db_session, "other-ma@example.com", local=False)
    use(monkeypatch)
    answer = ask(client, "Do I have any Moroccan visuals?", "assets", project_id=mine.id)
    assert answer["content"].startswith("Not yet")


def test_the_model_is_told_never_to_stereotype():
    assert "Never generalize about people, places, a country, a culture or a religion" in (
        SYSTEM_PROMPT
    )  # fmt: skip


GENERALIZATIONS = [
    "Moroccans love café content.", "Moroccan audiences always watch at night.",
    "Most Moroccans speak Darija.", "Arab viewers tend to like long intros.",
    "Les Marocains préfèrent le français.", "المغاربة كيحبو القهوة",
    "كل المغاربة دايما فالقهوة", "العرب يفضلون الفيديوهات الطويلة",
]  # fmt: skip
FACTS = [
    "Your Moroccan visuals come first.", "You have 1 Moroccan visual (“casa-cafe.jpg”).",
    "Morocco Mode never changes your language.", "The people in your clip are laughing.",
    "هاد الفيديو على القهوة ف كازا",
]  # fmt: skip


def test_generalizations_about_people_are_screened_out_facts_stay():
    from app.services.copilot.safety import drop_generalizations, generalizes

    assert all(generalizes(s) for s in GENERALIZATIONS)
    assert not any(generalizes(s) for s in FACTS)
    text = "Moroccans love café content. Your clip opens with a question."
    assert drop_generalizations(text) == "Your clip opens with a question."


def test_a_model_answer_never_reaches_the_creator_with_a_stereotype(client, db_session,
                                                                    monkeypatch):  # fmt: skip
    sign_up(client, "copilot-stereo@example.com")
    project, _ = project_with(db_session, "copilot-stereo@example.com")
    use(monkeypatch, {"message": "Moroccans always love café stories. Your video asks people "
                                 "about their favourite café."})  # fmt: skip
    answer = ask(client, "What is this video about?", "assets", project_id=project.id)
    assert answer["content"] == "Your video asks people about their favourite café."
