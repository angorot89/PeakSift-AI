"""B-roll suggestion providers: the local Ollama provider (fake HTTP transport — no server, no
model), the deterministic keyword fallback, grounding in what was said, the combined review and
the honest fallback rules."""

import json

import httpx
import pytest

from app.core.config import Settings, get_settings
from app.services.broll.contract import (
    BrollProviderConfigurationError,
    BrollProviderError,
    BrollProviderOutputError,
    BrollProviderTimeoutError,
    BrollProviderUnavailableError,
    BrollRequest,
    BrollResult,
    TranscriptLine,
)
from app.services.broll.grounding import ground, invented_names, is_vague, stems
from app.services.broll.keyword import KeywordBrollProvider, name_mentions
from app.services.broll.ollama import SYSTEM_PROMPT, OllamaBrollProvider, user_prompt
from app.services.broll.suggest import broll_model, get_broll_provider, review, suggest
from app.services.broll.validation import RawSuggestion, Suggestion

LINES = (
    TranscriptLine(0.0, 3.0, "NASA plans to return humans to the Moon."),
    TranscriptLine(3.0, 7.0, "The new rocket launched from Florida last spring."),
    TranscriptLine(7.0, 11.0, "I think that's a huge success for everyone."),
    TranscriptLine(11.0, 15.0, "Next they want a base near the south pole of the Moon."),
)


def request(lines=LINES, duration=15.0, cap=2) -> BrollRequest:
    return BrollRequest(
        lines=lines, clip_duration=duration, max_suggestions=cap, min_seconds=1.0, max_seconds=6.0,
        title="Back to the Moon", hook="NASA is going back.",
    )  # fmt: skip


def settings_with(**overrides) -> Settings:
    return Settings(**{**get_settings().model_dump(), **overrides})


# --- Ollama ------------------------------------------------------------------------------------

GOOD = {
    "suggestions": [
        {
            "start_seconds": 0.5,
            "end_seconds": 3.0,
            "query": "Moon surface",
            "reason": "The Moon line",
            "score": 85,
        }
    ]
}


def provider_with(handler) -> tuple[OllamaBrollProvider, list]:
    seen: list = []

    def record(req: httpx.Request) -> httpx.Response:
        seen.append(json.loads(req.content))
        return handler(req)

    client = httpx.Client(base_url="http://ollama.test", transport=httpx.MockTransport(record))
    return OllamaBrollProvider(get_settings(), "llama3.2:3b", client=client), seen


def reply(content, *, done_reason="stop", status=200) -> httpx.Response:
    text = content if isinstance(content, str) else json.dumps(content)
    return httpx.Response(status, json={"message": {"content": text}, "done_reason": done_reason})


def test_ollama_returns_raw_suggestions_with_a_constrained_request():
    provider, seen = provider_with(lambda req: reply(GOOD))
    result = provider.suggest(request())
    assert result.provider == "ollama" and result.model == "llama3.2:3b"
    assert result.suggestions == (RawSuggestion(0.5, 3.0, "Moon surface", "The Moon line", 85),)
    payload = seen[0]
    assert payload["options"]["temperature"] == 0 and payload["stream"] is False
    assert payload["format"]["properties"]["suggestions"]["type"] == "array"
    assert payload["messages"][0]["content"] == SYSTEM_PROMPT
    assert (
        "[3.0-7.0] The new rocket launched from Florida last spring."
        in payload["messages"][1]["content"]
    )
    assert "at most 2 visuals" in payload["messages"][1]["content"]


def test_the_prompt_forbids_invention_and_asks_for_restraint():
    assert "Never add names, brands, people, places" in SYSTEM_PROMPT
    assert "Do not suggest a visual for every sentence" in SYSTEM_PROMPT
    assert "Clip title: Back to the Moon" in user_prompt(request())


@pytest.mark.parametrize(
    ("handler", "error", "code"),
    [
        (
            lambda r: (_ for _ in ()).throw(httpx.ConnectError("x")),
            BrollProviderUnavailableError,
            "provider_unavailable",
        ),
        (
            lambda r: (_ for _ in ()).throw(httpx.ReadTimeout("x")),
            BrollProviderTimeoutError,
            "provider_timeout",
        ),
        (lambda r: httpx.Response(404), BrollProviderUnavailableError, "model_not_installed"),
        (lambda r: httpx.Response(503), BrollProviderUnavailableError, "provider_server_error"),
        (lambda r: httpx.Response(400), BrollProviderError, "provider_request_rejected"),
        (
            lambda r: httpx.Response(200, text="not json"),
            BrollProviderOutputError,
            "provider_output",
        ),
        (lambda r: reply("{not json"), BrollProviderOutputError, "provider_output"),
        (lambda r: reply({"items": []}), BrollProviderOutputError, "provider_output"),
        (lambda r: reply(GOOD, done_reason="length"), BrollProviderOutputError, "provider_output"),
    ],
)
def test_ollama_failures_are_normalized(handler, error, code):
    provider, _ = provider_with(handler)
    with pytest.raises(error) as raised:
        provider.suggest(request())
    assert raised.value.code == code and raised.value.fallback_ok


# --- the keyword fallback ------------------------------------------------------------------------


def test_name_mentions_skip_grammar_and_keep_names():
    text = (
        "NASA flew. Rockets are loud. I saw the Statue of Liberty and the Eiffel Tower, okay? Paris"
    )
    assert [name for name, _ in name_mentions(text)] == [
        "NASA", "Statue of Liberty", "Eiffel Tower"
    ]  # fmt: skip


def test_keyword_suggestions_start_near_the_name_and_are_deterministic():
    result = KeywordBrollProvider().suggest(request())
    assert result.provider == "keyword"
    names = [(s.query, s.start, s.end) for s in result.suggestions]
    assert names[0] == ("NASA", 0.0, 3.0)
    moon = next(s for s in result.suggestions if s.query == "Moon")
    assert 1.8 < moon.start < 2.9 and moon.end - moon.start == pytest.approx(3.0)  # once only
    assert [s.query for s in result.suggestions].count("Moon") == 1
    assert "Florida" in [s.query for s in result.suggestions]
    assert all(s.reason.startswith("Mentioned in “") for s in result.suggestions)
    assert KeywordBrollProvider().suggest(request()) == result


def test_keyword_windows_slide_back_at_the_end_of_the_clip():
    lines = (TranscriptLine(0.0, 4.0, "We ended the trip in Tokyo"),)
    (only,) = KeywordBrollProvider().suggest(request(lines, duration=4.0)).suggestions
    assert only.query == "Tokyo" and (only.start, only.end) == (1.0, 4.0)


# --- grounding --------------------------------------------------------------------------------


def s(start, end, query, score=70) -> Suggestion:
    return Suggestion(start=start, end=end, query=query, reason="r", score=score)


def test_grounding_keeps_what_was_said_here_and_refuses_the_rest():
    kept, refused = ground(
        [
            s(0.5, 3.0, "Moon surface"),  # said here
            s(3.0, 6.0, "rocket launch footage"),  # "launched" → launch
            s(7.0, 10.0, "success"),  # vague
            s(5.0, 7.0, "Moon base"),  # the Moon is mentioned, but not near 5-7 s
            s(3.0, 6.0, "rocket with Elon Musk"),  # a name nobody said
            s(0.0, 3.0, "SpaceX Moon lander"),  # sentence case: SpaceX invented
        ],
        LINES,
    )
    assert [k.query for k in kept] == ["Moon surface", "rocket launch footage"]
    assert refused == {"vague": 1, "not_said_here": 1, "invented_name": 2}


def test_title_case_queries_need_half_their_words_from_the_transcript():
    clip = stems(" ".join(line.text for line in LINES))
    assert not invented_names("Moon South Pole", clip)
    assert invented_names("Mars Colony Habitat", clip)
    assert invented_names("ESA Moon base", clip)  # an acronym first is a name
    assert not invented_names("NASA Moon base", clip)


def test_vague_queries():
    assert is_vague("Success") and is_vague("an important thing") and is_vague("the footage")
    assert not is_vague("rocket launch")


# --- review: checks, grounding, then density ---------------------------------------------------


def test_review_grounds_before_capping_density():
    raw = [
        RawSuggestion(7.0, 9.0, "success", "vague", 99),  # strongest, but refused
        RawSuggestion(0.5, 3.0, "Moon", "said", 60),
        RawSuggestion(3.5, 6.0, "rocket", "said", 55),
        RawSuggestion(11.0, 14.0, "Moon base", "said", 40),
        RawSuggestion(8.0, 14.5, "pole", "too long", 90),
    ]
    report = review(raw, LINES, 15.0)  # 15 s → at most 2
    assert [k.query for k in report.kept] == ["Moon", "rocket"]
    assert report.rejected == {"bad_length": 1, "vague": 1, "density": 1}


# --- provider choice and the honest fallback -----------------------------------------------------


class Failing:
    name = "ollama"
    model = "m"

    def __init__(self, error: BrollProviderError) -> None:
        self.error = error

    def suggest(self, request):
        raise self.error


def test_an_unavailable_model_falls_back_and_says_why():
    outcome = suggest(
        request(), Failing(BrollProviderUnavailableError("down")), fallback_enabled=True
    )
    assert outcome.fallback_reason == "provider_unavailable"
    assert outcome.result.provider == "keyword" and outcome.result.suggestions


def test_no_fallback_when_disabled_or_misconfigured():
    with pytest.raises(BrollProviderUnavailableError):
        suggest(request(), Failing(BrollProviderUnavailableError("down")), fallback_enabled=False)
    with pytest.raises(BrollProviderConfigurationError):
        suggest(request(), Failing(BrollProviderConfigurationError("bad")), fallback_enabled=True)


def test_a_working_provider_is_used_as_is():
    class Fine:
        name, model = "ollama", "m"

        def suggest(self, request):
            return BrollResult((), "ollama", "m")

    assert suggest(request(), Fine(), fallback_enabled=True).fallback_reason is None


def test_provider_choice_is_server_configuration():
    assert isinstance(get_broll_provider(get_settings(), "keyword", ""), KeywordBrollProvider)
    assert isinstance(
        get_broll_provider(get_settings(), "ollama", "llama3.2:3b"), OllamaBrollProvider
    )
    with pytest.raises(BrollProviderConfigurationError):
        get_broll_provider(get_settings(), "openai", "gpt")
    with pytest.raises(BrollProviderConfigurationError):
        get_broll_provider(get_settings(), "ollama", "")
    assert broll_model(settings_with(broll_ollama_model="", ollama_clip_models="a:1, b:2")) == "a:1"
    assert broll_model(settings_with(broll_ollama_model="qwen2.5:7b")) == "qwen2.5:7b"
