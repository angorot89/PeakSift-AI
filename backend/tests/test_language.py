"""Language intelligence (V1.8): conservative detection of Darija (Arabic script and Arabizi),
Arabic, French, English and code-switching; a matching-only normalization that never rewrites
what a creator said; the project's language endpoint where the creator's choice wins; Darija
captions rendered with their own spelling."""

from pathlib import Path

import numpy as np
import pytest

from app.core.config import get_settings
from app.models import Transcription, TranscriptSegment
from app.services import language
from app.services.broll.matching import AssetTerms, match_score
from app.services.clip_edit.emoji import emoji_font
from tests.media_fixtures import requires_ffmpeg, requires_libass
from tests.test_caption_languages import MARGIN_H, cues_for, document, ink
from tests.test_caption_v2 import render_frames
from tests.test_clip_edit_api import ready_clip, sign_up


@pytest.mark.parametrize(
    ("text", "expected", "label"),
    [
        ("واش حتى نتا كتشوف هادشي؟ بزاف ديال الناس كيقولو هاد الكلام دابا", "darija",
         "Likely Darija"),
        ("Wash 7ta nta katchouf hadchi? bzaf dyal nass kay9olo had lkalam daba", "darija",
         "Likely Darija"),
        ("Wach nta mzyan? c'est vraiment pas normal, bzaf dyal les gens kay9olo ça", "mixed",
         "Likely mixed (Darija, French)"),
        ("Aujourd'hui je vais vous montrer le meilleur café de la ville, c'est très bon",
         "french", "Likely French"),
        ("Today I tried to beat my record and it went horribly wrong, this is the story",
         "english", "Likely English"),
        ("هذا هو المقهى الذي زرته في المدينة وكان رائعا جدا لكن الأسعار مرتفعة", "arabic",
         "Likely Arabic"),
        ("واش هادشي زوين بزاف 😂🔥 صافي", "darija", "Likely Darija"),
        ("wach?", "unknown", "Not enough speech to tell"),
    ],
)  # fmt: skip
def test_detection_is_a_hedged_guess(text, expected, label):
    guess = language.detect(text)
    assert guess.language == expected
    assert language.label(guess) == label
    assert guess.confidence in ("likely", "possible")  # never "certain"


def test_darija_with_english_is_mixed_not_malformed():
    guess = language.detect("Wach had chi is really good? bzaf dyal people like this so much daba")
    assert guess.language == "mixed" and set(guess.languages) == {"darija", "english"}
    assert guess.scripts == ("latin",)


def test_arabizi_digits_are_letters_and_folding_is_for_matching_only():
    # 3, 7 and 9 stay: they are letters in Arabizi.
    assert language.tokens("Wash 7ta nta 3lach?") == ["wash", "7ta", "nta", "3lach"]
    # Emphasis, accents and Arabic letter variants compare equal…
    assert language.fold("Bzzzaf") == "bzaf"
    assert language.fold("café") == "cafe"
    assert language.fold("أحمد إبراهيم") == language.fold("احمد ابراهيم")
    assert language.fold("مُحَمَّد") == "محمد"
    # …but the original text is never changed by the module (it returns new strings only).
    original = "واش حتى نتا؟ Wash 7ta nta?"
    language.detect(original)
    assert original == "واش حتى نتا؟ Wash 7ta nta?"


def test_search_matches_accents_and_arabic_variants():
    class Asset:
        id = "a1"
        display_name = "casablanca-cafe.jpg"
        description = "مقهى في الدار البيضاء"
        tags = ["café", "Casablanca"]

    terms = AssetTerms.of(Asset())
    assert match_score("café Casablanca", terms) == 1.0
    assert match_score("cafe casablanca", terms) == 1.0
    assert match_score("مقهى", terms) > 0


def test_the_projects_language_is_the_creators_choice_first(client, db_session):
    sign_up(client, "darija@example.com")
    data = ready_clip(db_session, "darija@example.com")
    project_id = data["clip"].video.project_id
    transcription = db_session.query(Transcription).filter_by(video_id=data["clip"].video_id).one()
    db_session.query(TranscriptSegment).filter_by(transcription_id=transcription.id).delete()
    for i, line in enumerate(
        [
            "Wash 7ta nta katchouf hadchi?",
            "bzaf dyal nass kay9olo had lkalam daba",
        ]
    ):
        db_session.add(
            TranscriptSegment(
                transcription_id=transcription.id,
                sequence_index=i,
                start_time=i * 3.0,
                end_time=i * 3.0 + 2.5,
                text=line,
            )
        )
    db_session.commit()  # fmt: skip
    body = client.get(f"/projects/{project_id}/language").json()
    assert body["chosen"] == "auto" and body["effective"] == "darija"
    assert body["detected"]["label"] == "Likely Darija"
    client.patch(f"/projects/{project_id}", json={"content_language": "french"})
    body = client.get(f"/projects/{project_id}/language").json()
    assert body["effective"] == "french"  # the creator's choice wins over detection
    client.cookies.clear()
    sign_up(client, "other@example.com")
    assert client.get(f"/projects/{project_id}/language").status_code == 404


@requires_ffmpeg
@requires_libass
@pytest.mark.parametrize(
    "text",
    [
        "Wash 7ta nta? 3lach la",  # Arabizi with digits as letters
        "واش حتى نتا؟ 😂",  # Darija in Arabic script with an emoji
        "C'est bzaf, wallah — vraiment",  # Darija and French
        "Salam 👋 هادشي is crazy",  # three scripts and an emoji
    ],
)
def test_darija_captions_render_inside_the_frame_with_their_own_spelling(tmp_path: Path, text):
    cue = cues_for(text)[0]
    spelled = "".join(("" if w.attached else " ") + w.text for w in cue.words).strip()
    assert text.startswith(spelled)  # the creator's own spelling, nothing rewritten
    frame = render_frames(
        document([cue], emoji_font(get_settings().ffmpeg_path)), [cue.end - 0.05], tmp_path
    )[0]
    cols = np.nonzero(ink(frame))[1]
    assert len(cols) > 500 and cols.min() >= MARGIN_H - 30 and cols.max() <= 1080 - MARGIN_H + 30


def test_the_darija_quality_set_holds():
    """scripts/darija_quality.py: every line of the manual set is detected as expected and only
    sentences open a Short, with the line's own words."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("darija_quality", "scripts/darija_quality.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for line, expected, offered in module.LINES:
        result = module.row(line)
        assert result["guess"].language == expected, line
        assert bool(result["ideas"]) == offered, line


@pytest.mark.parametrize("text", [
    "Katherine and I went to the park with the kids today.",
    "Le kayak est un sport que je pratique avec mes amis.",
])  # fmt: skip
def test_darija_verb_markers_do_not_claim_english_or_french(text):
    assert language.detect(text).language in ("english", "french")
