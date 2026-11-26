"""Find Clips: plain-language search of a transcript, and keeping what was found."""

import uuid
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api import find_clips as api
from app.core.config import Settings, get_settings
from app.models import ClipCandidate, ClipDetectionRun, Transcription, TranscriptSegment, Video
from app.services import find_clips, find_clips_model
from app.services.find_clips import Line, key, related_terms, search, spoken_terms

PASSWORD = "correct horse battery"
MP4_BYTES = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 1024

# A small "episode": ten-second lines, three topics.
TALK = [
    "Welcome back to the show everybody.",
    "Today is about my first year as a creator.",
    "I spent three months building a studio.",
    "I bought lights and a camera and painted a wall.",
    "Let me tell you about pricing because people lose money here.",
    "My first course cost nineteen dollars.",
    "I thought a low price would bring more buyers.",
    "When I raised the price to ninety nine dollars sales doubled.",
    "The price is part of the message.",
    "Something funny happened last week on stream.",
    "My cat walked across the keyboard and ended the stream.",
    "Four thousand people watched me lose an argument with a cat.",
    "So start before you are ready.",
    "Thanks for watching and see you next week.",
]


def talk(texts=TALK, seconds: float = 10.0) -> list[Line]:
    return [Line(i * seconds, (i + 1) * seconds, text) for i, text in enumerate(texts)]


def find(query: str, lines=None, **options):
    options = {"min_seconds": 15, "max_seconds": 60, **options}
    return search(lines if lines is not None else talk(), query, **options)


# --- understanding the request ----------------------------------------------------------


def test_only_the_spoken_words_of_a_request_are_searched():
    assert list(spoken_terms("the part where I talk about pricing").values()) == ["pricing"]
    assert list(spoken_terms("Show me the moment with the CAT").values()) == ["cat"]
    assert spoken_terms("the part where I talk about it") == {}


@pytest.mark.parametrize(
    ("one", "other"),
    [
        ("pricing", "price"),
        ("prices", "price"),
        ("funniest", "funny"),
        ("stories", "story"),
        ("charged", "charge"),
        ("mistakes", "mistake"),
        ("Café", "cafe"),
        ("vidéos", "video"),
        ("أحمد", "احمد"),
        ("مدرسة", "مدرسه"),
    ],
)
def test_two_spellings_of_a_word_meet(one, other):
    assert key(one) == key(other)


def test_short_and_different_words_stay_apart():
    assert key("cat") != key("car")
    assert key("price") != key("prize")


def test_related_words_are_single_new_content_words():
    own = spoken_terms("pricing")
    related = related_terms(["cost", "price", "how much", "the", "dollars", 7, "x", "COST"], own)
    assert list(related.values()) == ["cost", "dollars"]


# --- the search -------------------------------------------------------------------------


def test_finds_the_span_where_the_words_were_said():
    understood, results = find("the part where I explain pricing")

    assert understood.terms == ("pricing",)
    best = results[0]
    assert best.matched == ("pricing",)
    assert "nineteen dollars" in best.excerpt and "raised the price" in best.excerpt
    assert (best.start, best.end) == (40.0, 90.0)  # the whole pricing story, pulled together
    assert best.score == 100
    assert "studio" not in best.excerpt and "cat" not in best.excerpt


def test_results_are_whole_lines_within_clip_length():
    lines = talk()
    starts, ends = {x.start for x in lines}, {x.end for x in lines}
    for query in ("pricing", "cat", "studio", "creator", "stream"):
        for result in find(query)[1]:
            assert result.start in starts and result.end in ends
            assert 15 <= result.duration <= 60
            assert result.lines and result.excerpt


def test_a_single_hit_gets_context_to_be_a_clip():
    _, results = find("studio")

    assert len(results) == 1
    assert results[0].duration >= 15
    assert "three months building a studio" in results[0].excerpt


def test_more_of_the_request_ranks_higher():
    _, results = find("cat on the keyboard during the stream")

    assert results[0].matched == ("cat", "keyboard", "stream")
    assert results[0].score == 100
    assert all(r.score <= results[0].score for r in results)


def test_spans_never_overlap():
    _, results = find("price stream cat studio creator")
    spans = sorted((r.start, r.end) for r in results)
    assert all(a_end <= b_start for (_, a_end), (b_start, _) in zip(spans, spans[1:], strict=False))


def test_related_words_widen_the_search_and_are_reported_apart():
    assert find("the hilarious bit")[1] == []  # "hilarious" was never said…
    funniest = find("the funniest moment")[1][0]  # …but "funny" was, and what follows it is kept
    assert funniest.matched == ("funniest",) and "My cat walked" in funniest.excerpt

    understood, results = find("the hilarious bit", related=["funny", "laugh", "cat"])

    assert understood.terms == ("hilarious",) and understood.related == ("funny", "laugh", "cat")
    assert results and results[0].matched == () and set(results[0].related) == {"funny", "cat"}
    assert results[0].score == 50  # related words are weaker evidence than the creator's own


def test_nothing_is_found_when_nothing_was_said():
    assert find("quantum physics")[1] == []
    assert find("the part where I talk about it")[1] == []
    assert find("pricing", lines=[])[1] == []


def test_a_recording_too_short_for_a_clip_returns_nothing():
    assert find("pricing", lines=talk(["Pricing matters."], seconds=5))[1] == []


def test_other_languages_and_scripts():
    lines = talk(
        [
            "مرحبا بكم في الحلقة",
            "اليوم غادي نهضرو على الثمن ديال المنتوج",
            "الثمن كان رخيص بزاف",
            "Le prix était trop bas au début",
            "et après les ventes ont doublé",
            "شكرا على المتابعة",
        ]
    )
    arabic = find("الثمن", lines=lines)[1]
    french = find("le moment où je parle du prix", lines=lines)[1]

    assert arabic and "الثمن" in arabic[0].excerpt
    assert french and "prix" in french[0].excerpt and french[0].matched == ("prix",)


def test_search_is_deterministic_and_bounded():
    first = find("price stream cat", limit=2)
    assert first == find("price stream cat", limit=2)
    assert len(first[1]) <= 2


# --- related words from the local model -----------------------------------------------------


def model_settings(**overrides) -> Settings:
    base = get_settings().model_dump()
    base.update(copilot_enabled=True, copilot_provider="ollama")
    base.update(overrides)
    return Settings(**base)


def ollama(handler) -> httpx.Client:
    return httpx.Client(base_url="http://ollama.test", transport=httpx.MockTransport(handler))


def test_related_words_come_from_the_model_answer(monkeypatch):
    monkeypatch.setattr(find_clips_model, "assistant_available", lambda settings: True)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/chat"
        content = '{"words": ["funny", "laugh", 3, "joke"]}'
        return httpx.Response(200, json={"message": {"content": content}})

    words = find_clips_model.related_words(
        "the funniest moment", model_settings(), client=ollama(handler)
    )
    assert words == ["funny", "laugh", "joke"]


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(500),
        httpx.Response(200, json={"message": {"content": "not json"}}),
        httpx.Response(200, json={"message": {"content": '{"words": "funny"}'}}),
        httpx.Response(200, json={"unexpected": True}),
    ],
)
def test_a_bad_model_answer_means_no_related_words(monkeypatch, response):
    monkeypatch.setattr(find_clips_model, "assistant_available", lambda settings: True)
    words = find_clips_model.related_words(
        "funny", model_settings(), client=ollama(lambda request: response)
    )
    assert words == []


def test_no_model_means_no_related_words(monkeypatch):
    def unreachable(request):
        raise AssertionError("the model must not be called")

    monkeypatch.setattr(find_clips_model, "assistant_available", lambda settings: False)
    assert (
        find_clips_model.related_words("funny", model_settings(), client=ollama(unreachable)) == []
    )

    def refused(request):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(find_clips_model, "assistant_available", lambda settings: True)
    assert find_clips_model.related_words("funny", model_settings(), client=ollama(refused)) == []


# --- the API ------------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def no_model(monkeypatch):
    """The API tests search on the creator's own words; the model step is tested above."""
    monkeypatch.setattr(api, "related_words", lambda query, settings: [])


@pytest.fixture(autouse=True)
def clean_media_root():
    yield
    for path in Path(get_settings().media_root).rglob("*"):
        if path.is_file():
            path.unlink()


def sign_up(client: TestClient, email: str = "owner@example.com") -> None:
    response = client.post("/auth/register", json={"email": email, "password": PASSWORD})
    assert response.status_code == 201


def transcribed(client: TestClient, db_session: Session, *, status: str = "completed") -> str:
    """A ready video with the TALK transcript; returns its find-clips URL."""
    project_id = client.post("/projects", json={"name": "Show"}).json()["id"]
    video_id = client.post(
        f"/projects/{project_id}/videos", files={"file": ("s.mp4", MP4_BYTES, "video/mp4")}
    ).json()["id"]
    video = db_session.get(Video, uuid.UUID(video_id))
    video.status, video.error_message, video.duration_seconds = "ready", None, len(TALK) * 10.0
    transcription = Transcription(
        video=video, provider="faster_whisper", model="small", status=status, progress_percent=100
    )
    for i, text in enumerate(TALK):
        transcription.segments.append(
            TranscriptSegment(
                sequence_index=i, start_time=i * 10.0, end_time=(i + 1) * 10.0, text=text
            )
        )
    db_session.add(transcription)
    db_session.commit()
    return f"/projects/{project_id}/videos/{video_id}/find-clips"


def count(db_session: Session, model) -> int:
    return db_session.scalar(select(func.count()).select_from(model)) or 0


def test_requires_authentication_and_ownership(client, db_session):
    assert (
        client.get(f"/projects/{uuid.uuid4()}/videos/{uuid.uuid4()}/find-clips?q=cat").status_code
        == 401
    )
    sign_up(client)
    url = transcribed(client, db_session)
    client.post("/auth/logout")
    sign_up(client, "other@example.com")
    assert client.get(url, params={"q": "cat"}).status_code == 404
    assert (
        client.post(f"{url}/keep", json={"query": "cat", "start": 90, "end": 120}).status_code
        == 404
    )


def test_search_returns_grounded_spans(client, db_session):
    sign_up(client)
    url = transcribed(client, db_session)

    body = client.get(url, params={"q": "the part where I talk about pricing"}).json()

    assert body["terms"] == ["pricing"] and body["related"] == []
    best = body["results"][0]
    assert (best["start"], best["end"], best["duration"]) == (40.0, 90.0, 50.0)
    assert best["matched"] == ["pricing"] and best["candidate_id"] is None
    assert [line["text"] for line in best["lines"]] == TALK[4:9]


def test_search_uses_related_words_when_the_model_offers_them(client, db_session, monkeypatch):
    sign_up(client)
    url = transcribed(client, db_session)
    monkeypatch.setattr(api, "related_words", lambda query, settings: ["funny", "cat"])

    body = client.get(url, params={"q": "the hilarious bit"}).json()
    assert body["related"] == ["funny", "cat"] and body["results"][0]["related"] == ["funny", "cat"]

    # related=false never asks the model
    monkeypatch.setattr(api, "related_words", lambda query, settings: 1 / 0)
    assert (
        client.get(url, params={"q": "the hilarious bit", "related": "false"}).json()["results"]
        == []
    )


def test_search_needs_a_completed_transcript_and_a_real_query(client, db_session):
    sign_up(client)
    assert (
        client.get(
            transcribed(client, db_session, status="transcribing"), params={"q": "cat"}
        ).status_code
        == 409
    )
    url = transcribed(client, db_session)
    assert client.get(url, params={"q": "c"}).status_code == 422
    assert client.get(url, params={"q": "x" * 201}).status_code == 422
    assert client.get(url, params={"q": "the part where I talk"}).json()["results"] == []


def test_keeping_a_result_makes_a_saved_moment(client, db_session):
    sign_up(client)
    url = transcribed(client, db_session)
    found = client.get(url, params={"q": "my cat on the keyboard"}).json()["results"][0]

    response = client.post(
        f"{url}/keep",
        json={"query": "my cat on the keyboard", "start": found["start"], "end": found["end"]},
    )

    assert response.status_code == 201
    moment = response.json()
    assert moment["origin"] == "search" and moment["query"] == "my cat on the keyboard"
    assert moment["decision"] == "saved" and moment["title"] == "My cat on the keyboard"
    assert (moment["start"], moment["end"]) == (found["start"], found["end"])
    assert moment["transcript_excerpt"] == found["excerpt"]
    assert "You asked for “my cat on the keyboard”" in moment["rationale"]
    assert "cat, keyboard" in moment["rationale"]
    assert moment["overall_score"] == 0 and set(moment["scores"].values()) == {
        0
    }  # no rating claimed

    # It was asked for, not ranked: never counted as a top pick.
    counts = client.get(
        f"{url.removesuffix('/find-clips')}/clip-detection/{moment['run_id']}/candidates"
    ).json()["counts"]
    assert counts == {"active": 1, "top": 0, "saved": 1, "dismissed": 0}

    # With no analysis yet, the moment lives in a completed run of its own…
    run = db_session.get(ClipDetectionRun, uuid.UUID(moment["run_id"]))
    assert (run.provider, run.status) == ("search", "completed")
    # …keeping it again is the same moment, and the search now points at it.
    again = client.post(
        f"{url}/keep", json={"query": "cat", "start": found["start"], "end": found["end"]}
    )
    assert again.status_code == 200 and again.json()["id"] == moment["id"]
    assert count(db_session, ClipCandidate) == 1
    listed = client.get(url, params={"q": "my cat on the keyboard"}).json()["results"][0]
    assert listed["candidate_id"] == moment["id"]


def test_a_kept_result_joins_the_detected_moments(client, db_session):
    sign_up(client)
    url = transcribed(client, db_session)
    video_id = uuid.UUID(url.split("/")[4])
    video = db_session.get(Video, video_id)
    run = ClipDetectionRun(
        video=video, transcription=video.transcription, transcript_fingerprint="f" * 64,
        provider="ollama", model="llama3.2:3b", status="completed", progress_percent=100,
    )  # fmt: skip
    run.candidates.append(
        ClipCandidate(
            video_id=video.id,
            start_time=20,
            end_time=40,
            duration_seconds=20,
            title="Studio",
            hook="h",
            rationale="r",
            overall_score=80,
            hook_score=80,
            entertainment_score=80,
            clarity_score=80,
            payoff_score=80,
            completeness_score=80,
            rank=1,
        )  # fmt: skip
    )
    db_session.add(run)
    db_session.commit()

    moment = client.post(f"{url}/keep", json={"query": "pricing", "start": 40, "end": 90}).json()

    assert moment["run_id"] == str(run.id) and moment["rank"] == 2
    assert count(db_session, ClipDetectionRun) == 1
    page = client.get(
        f"{url.removesuffix('/find-clips')}/clip-detection/{run.id}/candidates",
        params={"decision": "saved"},
    ).json()
    assert [c["origin"] for c in page["candidates"]] == ["search"]


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (41.7, 90),
        (40, 93.3),
        (90, 40),
        (40, 50),
        (0, 140),
    ],  # off the lines, reversed, too short, too long
)
def test_keep_refuses_spans_that_are_not_valid_clips_of_whole_lines(client, db_session, start, end):
    sign_up(client)
    url = transcribed(client, db_session)

    response = client.post(f"{url}/keep", json={"query": "pricing", "start": start, "end": end})

    assert response.status_code == 422
    assert count(db_session, ClipCandidate) == 0 and count(db_session, ClipDetectionRun) == 0


def test_keep_needs_a_completed_transcript(client, db_session):
    sign_up(client)
    url = transcribed(client, db_session, status="transcribing")
    assert (
        client.post(f"{url}/keep", json={"query": "cat", "start": 90, "end": 120}).status_code
        == 409
    )


def test_module_constants_are_sane():
    assert find_clips.MAX_RELATED <= find_clips_model.MAX_WORDS
