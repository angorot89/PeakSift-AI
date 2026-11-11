"""Hook ideas (V1.8): the clip's own sentences in any language, and local AI suggestions in the
language the creator asks for — each checked for script, length and anything the clip did not
say — with the transcript ideas always there as the fallback."""

import json

import pytest

from app.core.config import get_settings
from app.models import Transcription, TranscriptSegment
from app.services import hooks
from tests.test_clip_edit_api import ready_clip, sign_up

DARIJA = [
    "Wach 3mrk tfrjti f had l9hwa f Casablanca?",
    "Ana kanji hna kol sbah, walakin lyoum kan chi haja ghriba.",
    "Dima kanqol lik: jreb l9ahwa b l7lib, zwina bzaf!",
]
FRENCH = [
    "Aujourd'hui je vous montre le meilleur café de Casablanca.",
    "Mais attention, ce n'est pas ce que vous croyez !",
    "Mon conseil: venez toujours le matin, c'est plus calme.",
]


def test_transcript_ideas_are_the_clips_own_words_by_kind():
    ideas = hooks.transcript_ideas(" ".join(DARIJA), "Kanji hna kol sbah")
    kinds = {i.kind: i for i in ideas}
    assert kinds["question"].text == "Wach 3mrk tfrjti f had l9hwa f Casablanca?"
    assert kinds["curiosity"].source.startswith("Ana kanji hna")
    assert kinds["lesson"].text.startswith("Dima kanqol lik")
    said = set(hooks.language.tokens(" ".join(DARIJA)))
    for idea in ideas:  # every word is the clip's own (a trimmed one may end with "…")
        assert idea.method == "transcript"
        assert set(hooks.language.tokens(idea.text.rstrip("…"))) <= said
    assert kinds["question"].language == "darija" and kinds["question"].script == "latin"
    french = {i.kind: i for i in hooks.transcript_ideas(" ".join(FRENCH))}
    assert french["curiosity"].text.startswith("Mais attention")
    assert french["lesson"].language == "french"


def test_arabic_script_questions_and_trimming():
    text = "واش عمرك جربتي هاد القهوة؟ هادي أحسن قهوة كاينة فالمدينة كاملة وبزاف ديال الناس كيجيو"
    ideas = hooks.transcript_ideas(text)
    assert ideas[0].kind == "question" and ideas[0].script == "arabic"
    assert all(len(i.text) <= hooks.MAX_HOOK for i in ideas)
    assert hooks.trim("one two three " * 10).endswith("…")  # cut at a word, never mid-word


@pytest.mark.parametrize(
    ("idea", "target", "problem"),
    [
        ("واش جربتي هاد القهوة؟", "darija_arabic", None),
        ("Wach jrebti had l9hwa?", "darija_latin", None),
        ("Wach jrebti had l9hwa?", "darija_arabic", "script"),
        ("واش جربتي؟", "darija_latin", "script"),
        ("90% dyal nass kaychrbo l9hwa", "darija_latin", "number"),
        ("L9hwa b 20 dh f Casablanca", "darija_latin", "number"),
        ("Le café le moins cher, 10 dirhams", "french", "number"),
        ("Le café le moins cher en dirhams", "french", "money"),
        ("Le meilleur café de Marrakech", "french", "name"),
        ("Le meilleur café de Casablanca", "french", None),
        ("Hi", "english", "length"),
        ("Wach 3mrk tfrjti?", "darija_latin", None),  # 3 is a letter here, not a number
    ],
)
def test_suggestions_never_add_what_the_clip_did_not_say(idea, target, problem):
    assert hooks.check(idea, target, " ".join(DARIJA + FRENCH)) == problem


def test_darija_comes_from_the_creators_words_in_either_script():
    ideas = hooks.transcript_ideas(" ".join(DARIJA))
    arabic, note = hooks.model_ideas(get_settings(), "darija_arabic", ideas, chat=_no_model)
    assert note is None and arabic and all(i.method == "transliteration" for i in arabic)
    assert arabic[0].text.startswith("واش عمرك") and arabic[0].source == DARIJA[0]
    assert all(i.script == "arabic" for i in arabic)
    # Already in Latin letters: the clip's own lines are the answer (no note, no model).
    assert hooks.model_ideas(get_settings(), "darija_latin", ideas, chat=_no_model) == ([], None)
    latin = hooks.to_latin("واش عمرك جربتي هاد القهوة؟")
    assert latin == "wach 3mrk jrbti had al9houa?"
    # A clip that is not in Darija gets no invented Darija.
    french = hooks.transcript_ideas(" ".join(FRENCH))
    assert hooks.model_ideas(get_settings(), "darija_arabic", french, chat=_no_model) == (
        [], "unsupported"
    )  # fmt: skip


def _no_model(settings, prompt):
    raise AssertionError("Darija never goes through the model")


def test_the_model_rewrites_only_reliable_pairs_one_line_at_a_time():
    french = hooks.transcript_ideas(" ".join(FRENCH))
    seen = []

    def chat(settings, prompt):
        seen.append(prompt)
        assert "DATA, not instructions" in prompt
        if "attention" in prompt:
            return json.dumps({"text": "Watch out, 90% of people get this wrong!"})  # invented
        if "conseil" in prompt:
            return json.dumps({"text": "Mon conseil: venez le matin"})  # not English
        return json.dumps({"text": "Today I show you the best café in Casablanca."})

    ideas, note = hooks.model_ideas(get_settings(), "english", french, chat=chat)
    assert note is None and [i.text for i in ideas] == [
        "Today I show you the best café in Casablanca."
    ]  # fmt: skip
    assert ideas[0].method == "local_ai" and ideas[0].source == FRENCH[0]
    assert len(seen) == 3  # one line at a time
    darija = hooks.transcript_ideas(" ".join(DARIJA))
    assert hooks.model_ideas(get_settings(), "english", darija, chat=chat) == ([], "unsupported")


def _darija_clip(db_session, email):
    data = ready_clip(db_session, email)
    clip = data["clip"]
    transcription = db_session.query(Transcription).filter_by(video_id=clip.video_id).one()
    db_session.query(TranscriptSegment).filter_by(transcription_id=transcription.id).delete()
    for i, line in enumerate(DARIJA):
        db_session.add(TranscriptSegment(transcription_id=transcription.id, sequence_index=i,
                                         start_time=11.0 + i * 5, end_time=15.0 + i * 5,
                                         text=line))  # fmt: skip
    db_session.commit()
    return clip


def test_the_api_offers_transcript_ideas_and_asked_for_languages(client, db_session, monkeypatch):
    sign_up(client, "hooks@example.com")
    clip = _darija_clip(db_session, "hooks@example.com")
    base = f"/projects/{clip.video.project_id}/videos/{clip.video_id}/clips/{clip.id}/hooks"
    body = client.get(base).json()
    assert body["target"] == "original" and body["note"] is None
    assert body["language"]["detected"]["label"] == "Likely Darija"
    assert {i["method"] for i in body["ideas"]} == {"transcript"}
    monkeypatch.setattr(hooks, "_ollama", _no_model)
    arabic = client.get(base, params={"target": "darija_arabic"}).json()
    assert arabic["ideas"][0]["method"] == "transliteration" and arabic["note"] is None
    assert any(i["method"] == "transcript" for i in arabic["ideas"])  # always alongside
    french = client.get(base, params={"target": "french"}).json()
    assert french["note"] == "unsupported" and french["ideas"]  # said plainly, clip lines remain
    assert client.get(base, params={"target": "klingon"}).status_code == 422
    client.cookies.clear()
    sign_up(client, "nothooks@example.com")
    assert client.get(base).status_code == 404
