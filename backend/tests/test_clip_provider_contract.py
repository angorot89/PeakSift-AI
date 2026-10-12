import pytest
from pydantic import SecretStr

from app.core.config import Settings, get_settings
from app.services.clip_detection import factory
from app.services.clip_detection.contract import (
    SCORE_RANGE,
    TEXT_LIMITS,
    AnalysisWindow,
    ClipAnalysisProvider,
    ClipAnalysisRequest,
    ClipProviderConfigurationError,
    ClipProviderError,
    ClipProviderOutputError,
    ClipProviderRateLimitError,
    ClipProviderTimeoutError,
    ClipProviderUnavailableError,
    RawCandidate,
    TranscriptLine,
    analysis_output_json_schema,
    parse_analysis_output,
)
from app.services.clip_detection.factory import (
    PROVIDER_REGISTRY,
    get_clip_provider,
    provider_options,
    resolve_choice,
)
from app.services.clip_detection.prompt import SYSTEM_PROMPT, render_window, user_prompt
from tests.fakes import FakeClipProvider, raw_candidate


def window(*lines: tuple[float, float, str], index: int = 0) -> AnalysisWindow:
    items = tuple(TranscriptLine(start=s, end=e, text=t) for s, e, t in lines)
    return AnalysisWindow(index=index, start=items[0].start, end=items[-1].end, lines=items)


def request(**overrides) -> ClipAnalysisRequest:
    fields = {
        "window": window((600.0, 604.5, "So here is the thing."), (604.5, 611.0, "He said no.")),
        "video_duration": 3600.0,
        "min_clip_seconds": 15.0,
        "max_clip_seconds": 90.0,
        "max_candidates": 3,
        "language": "en",
    }
    fields.update(overrides)
    return ClipAnalysisRequest(**fields)


def settings_with(**overrides) -> Settings:
    base = get_settings().model_dump()
    base.update(overrides)
    return Settings(**base)


# --- types -----------------------------------------------------------------------------


def test_window_measures_itself():
    w = window((10.0, 12.0, "abc"), (12.0, 15.5, "defgh"))
    assert w.duration == 5.5
    assert w.char_count == 8


def test_fake_provider_satisfies_the_protocol():
    assert isinstance(FakeClipProvider(), ClipAnalysisProvider)


def test_documented_bounds_are_exposed():
    assert SCORE_RANGE == (0, 100)
    assert TEXT_LIMITS == {"title": 120, "hook": 300, "rationale": 1000}


# --- structured output -------------------------------------------------------------------


def test_json_schema_is_strict_and_lists_every_field():
    schema = analysis_output_json_schema()
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["candidates"]
    candidate = schema["$defs"]["CandidateOutput"]
    assert candidate["additionalProperties"] is False
    assert set(candidate["required"]) == {
        "start_seconds",
        "end_seconds",
        "title",
        "hook",
        "rationale",
        "category",
        "hook_score",
        "entertainment_score",
        "clarity_score",
        "payoff_score",
        "completeness_score",
    }


def test_parse_output_maps_fields_to_raw_candidates():
    data = {
        "candidates": [
            {
                "start_seconds": 600,
                "end_seconds": 640.5,
                "title": "The no",
                "hook": "He said no.",
                "rationale": "Clear payoff.",
                "category": "story",
                "hook_score": 80,
                "entertainment_score": "70",  # coerced
                "clarity_score": 60,
                "payoff_score": 90,
                "completeness_score": 75,
            }
        ]
    }
    (candidate,) = parse_analysis_output(data, provider="test")
    assert candidate == RawCandidate(
        start=600.0,
        end=640.5,
        title="The no",
        hook="He said no.",
        rationale="Clear payoff.",
        category="story",
        hook_score=80,
        entertainment_score=70,
        clarity_score=60,
        payoff_score=90,
        completeness_score=75,
    )


def test_parse_output_accepts_an_empty_candidate_list():
    assert parse_analysis_output({"candidates": []}, provider="test") == ()


@pytest.mark.parametrize(
    "data",
    [
        None,
        "not json",
        {},
        {"candidates": "nope"},
        {"candidates": [{"start_seconds": 1}]},  # missing fields
        {"candidates": [], "extra": 1},  # unknown key
        {
            "candidates": [
                {
                    "start_seconds": "soon",  # not a number
                    "end_seconds": 2,
                    "title": "t",
                    "hook": "h",
                    "rationale": "r",
                    "category": "story",
                    "hook_score": 1,
                    "entertainment_score": 1,
                    "clarity_score": 1,
                    "payoff_score": 1,
                    "completeness_score": 1,
                }
            ]
        },
    ],
)
def test_parse_output_rejects_malformed_responses(data):
    with pytest.raises(ClipProviderOutputError) as info:
        parse_analysis_output(data, provider="test")
    assert info.value.retryable is False
    assert "test" in info.value.message


def test_parse_output_does_not_judge_values_only_shape():
    """Out-of-range scores and inverted times are validation's job (it has the transcript)."""
    data = {
        "candidates": [
            {
                "start_seconds": 50,
                "end_seconds": 10,
                "title": "",
                "hook": "",
                "rationale": "",
                "category": "nonsense",
                "hook_score": 500,
                "entertainment_score": -1,
                "clarity_score": 0,
                "payoff_score": 0,
                "completeness_score": 0,
            }
        ]
    }
    (candidate,) = parse_analysis_output(data, provider="test")
    assert candidate.start == 50 and candidate.end == 10 and candidate.hook_score == 500


# --- errors ----------------------------------------------------------------------------


def test_error_retryability_is_explicit():
    assert ClipProviderConfigurationError("x").retryable is False
    assert ClipProviderConfigurationError("x").code == "provider_configuration"
    assert ClipProviderConfigurationError("x", code="missing_api_key").code == "missing_api_key"
    assert ClipProviderOutputError("x").retryable is False
    assert ClipProviderUnavailableError("x").retryable is True
    assert ClipProviderTimeoutError("x").retryable is True
    assert ClipProviderRateLimitError("x").retryable is True
    assert ClipProviderError("custom", "x").retryable is False
    for error in (ClipProviderUnavailableError("x"), ClipProviderTimeoutError("x")):
        assert isinstance(error, ClipProviderError)


# --- prompt -----------------------------------------------------------------------------


def test_render_window_uses_absolute_seconds_per_line():
    text = render_window(window((600.0, 604.5, "So here is the thing."), (604.5, 611.0, "No.")))
    assert text == "[600.0 → 604.5] So here is the thing.\n[604.5 → 611.0] No."


def test_user_prompt_carries_bounds_language_and_transcript():
    text = user_prompt(request(instructions="Prefer moments about cooking."))
    assert "Video duration: 3600.0 seconds." in text
    assert "600.0s to 611.0s" in text
    assert "between 15 and 90 seconds" in text
    assert "at most 3 clips" in text
    assert "language is 'en'" in text
    assert "Prefer moments about cooking." in text
    assert "[600.0 → 604.5] So here is the thing." in text
    assert "humor" in text and "other" in text  # allowed categories listed


def test_user_prompt_without_language_or_instructions():
    text = user_prompt(request(language=None, instructions=None))
    assert "language is" not in text
    assert text.endswith("[604.5 → 611.0] He said no.")


def test_system_prompt_forbids_invention_and_demands_alignment():
    assert "Never invent" in SYSTEM_PROMPT
    assert "absolute seconds" in SYSTEM_PROMPT
    assert "JSON only" in SYSTEM_PROMPT


# --- factory and allow-lists -----------------------------------------------------------------


def test_registry_names_both_milestone_4_providers():
    assert set(PROVIDER_REGISTRY) == {"ollama", "openai"}


def test_default_options_local_configured_hosted_not_without_key():
    settings = settings_with(openai_api_key=None)
    options = {o.name: o for o in provider_options(settings)}

    assert options["ollama"].configured is True
    assert options["ollama"].models == ("llama3.2:3b",)
    assert options["ollama"].default_model == "llama3.2:3b"
    assert options["ollama"].reason is None
    assert options["openai"].configured is False
    assert options["openai"].models == ()
    assert options["openai"].default_model is None
    assert options["openai"].reason == "OpenAI is not configured on this server"


def test_openai_option_appears_with_a_key_and_its_allow_list():
    settings = settings_with(
        openai_api_key=SecretStr("sk-test"), openai_clip_models=" gpt-5-mini, gpt-5 ,gpt-5-mini"
    )
    option = next(o for o in provider_options(settings) if o.name == "openai")

    assert option.configured is True
    assert option.models == ("gpt-5-mini", "gpt-5")  # trimmed, de-duplicated, ordered
    assert option.default_model == "gpt-5-mini"
    # The option never carries the key itself.
    assert "sk-test" not in repr(option)


def test_disabled_local_provider_is_reported_not_hidden():
    settings = settings_with(clip_detection_ollama_enabled=False)
    option = next(o for o in provider_options(settings) if o.name == "ollama")
    assert option.configured is False
    assert option.reason == "The local provider is disabled on this server"
    assert option.models == ()


def test_options_never_expose_the_endpoint_url():
    settings = settings_with(ollama_base_url="http://inference.internal:11434")
    assert "inference.internal" not in repr(provider_options(settings))


def test_resolve_choice_defaults_to_the_first_allowed_model():
    settings = settings_with(ollama_clip_models="qwen2.5:7b,llama3.2:3b")
    assert resolve_choice("ollama", None, settings) == ("ollama", "qwen2.5:7b")
    assert resolve_choice("ollama", "llama3.2:3b", settings) == ("ollama", "llama3.2:3b")


def test_resolve_choice_refuses_models_outside_the_allow_list():
    with pytest.raises(ClipProviderConfigurationError) as info:
        resolve_choice("ollama", "llama3.2:1b", settings_with())
    assert info.value.code == "model_not_allowed"
    assert "llama3.2:1b" not in info.value.message  # client input is not echoed


def test_resolve_choice_refuses_unknown_and_unconfigured_providers():
    with pytest.raises(ClipProviderConfigurationError) as info:
        resolve_choice("anthropic", None, settings_with())
    assert info.value.code == "unknown_provider"

    with pytest.raises(ClipProviderConfigurationError) as info:
        resolve_choice("openai", None, settings_with(openai_api_key=None))
    assert info.value.message == "OpenAI is not configured on this server"


def test_get_clip_provider_imports_lazily_and_passes_model(monkeypatch):
    built: dict = {}

    class Stub:
        def __init__(self, settings, model):
            built.update(model=model)
            self.name, self.model = "ollama", model

        def analyze(self, request):
            raise AssertionError

        def check_availability(self):
            raise AssertionError

    import types

    module = types.SimpleNamespace(OllamaClipProvider=Stub)
    monkeypatch.setitem(factory.PROVIDER_REGISTRY, "ollama", "stub.module:OllamaClipProvider")
    monkeypatch.setattr(factory.importlib, "import_module", lambda name: module)

    provider = get_clip_provider("ollama", None, settings_with())
    assert built == {"model": "llama3.2:3b"} and provider.model == "llama3.2:3b"


def test_get_clip_provider_reports_a_missing_sdk_as_configuration(monkeypatch):
    def failing_import(name):
        raise ImportError("No module named 'nothing'", name="nothing")

    monkeypatch.setattr(factory.importlib, "import_module", failing_import)
    with pytest.raises(ClipProviderConfigurationError) as info:
        get_clip_provider("ollama", None, settings_with())
    assert "not available" in info.value.message


# --- settings ---------------------------------------------------------------------------


def test_clip_bounds_must_be_ordered():
    with pytest.raises(ValueError):
        settings_with(clip_detection_min_clip_seconds=90, clip_detection_max_clip_seconds=30)


def test_default_clip_settings_are_sane():
    s = get_settings()
    assert s.clip_detection_window_seconds >= 60
    assert s.clip_detection_min_clip_seconds < s.clip_detection_max_clip_seconds
    assert 1 <= s.clip_detection_target_candidates <= 50
    assert s.clip_detection_candidates_per_window <= s.clip_detection_target_candidates
    assert 0 <= s.clip_detection_overlap_threshold <= 1


# --- fake provider -----------------------------------------------------------------------


def test_fake_provider_records_requests_and_supports_scripts():
    provider = FakeClipProvider(candidates=(raw_candidate(600.0, 640.0),))
    result = provider.analyze(request())
    assert result.candidates[0].start == 600.0 and result.provider == "fake"
    assert len(provider.requests) == 1

    scripted = FakeClipProvider(respond=lambda r: (raw_candidate(r.window.start, r.window.end),))
    assert scripted.analyze(request()).candidates[0].end == 611.0
    assert scripted.check_availability().available is True
