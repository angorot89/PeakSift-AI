"""OpenAI clip provider tests with a fake SDK client. No network, no key, no billing."""

import logging
from types import SimpleNamespace

import httpx
import openai
import pytest
from pydantic import SecretStr

from app.core.config import Settings, get_settings
from app.services.clip_detection import openai_provider as module
from app.services.clip_detection.contract import (
    AnalysisOutput,
    AnalysisWindow,
    ClipAnalysisRequest,
    ClipProviderConfigurationError,
    ClipProviderError,
    ClipProviderOutputError,
    ClipProviderRateLimitError,
    ClipProviderTimeoutError,
    ClipProviderUnavailableError,
    TranscriptLine,
)
from app.services.clip_detection.openai_provider import OpenAIClipProvider

MODEL = "gpt-5-mini"
REQUEST = httpx.Request("POST", "https://api.openai.com/v1/responses")

GOOD = {
    "start_seconds": 600.0,
    "end_seconds": 640.0,
    "title": "The reveal",
    "hook": "He finally says it.",
    "rationale": "Builds and pays off inside the window.",
    "category": "story",
    "hook_score": 82,
    "entertainment_score": 75,
    "clarity_score": 70,
    "payoff_score": 88,
    "completeness_score": 80,
}


def status_error(cls, status: int):
    return cls("error", response=httpx.Response(status, request=REQUEST), body=None)


def parsed_response(candidates, *, status="completed", reason=None):
    return SimpleNamespace(
        status=status,
        incomplete_details=SimpleNamespace(reason=reason) if reason else None,
        output_parsed=AnalysisOutput.model_validate({"candidates": candidates}),
        output=[],
    )


class FakeResponses:
    def __init__(self):
        self.calls: list[dict] = []
        self.result = parsed_response([GOOD])
        self.error: Exception | None = None

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.result


class FakeModels:
    def __init__(self):
        self.error: Exception | None = None
        self.retrieved: list[str] = []

    def retrieve(self, model):
        self.retrieved.append(model)
        if self.error:
            raise self.error
        return SimpleNamespace(id=model)


class FakeClient:
    def __init__(self):
        self.responses = FakeResponses()
        self.models = FakeModels()


def settings_with(**overrides) -> Settings:
    base = get_settings().model_dump()
    base.setdefault("openai_api_key", None)
    base["openai_api_key"] = SecretStr("sk-test-not-real")
    base.update(overrides)
    return Settings(**base)


def request() -> ClipAnalysisRequest:
    lines = tuple(
        TranscriptLine(start=600.0 + 5 * i, end=605.0 + 5 * i, text=f"line {i}") for i in range(4)
    )
    return ClipAnalysisRequest(
        window=AnalysisWindow(index=1, start=600.0, end=620.0, lines=lines),
        video_duration=3600.0,
        min_clip_seconds=15,
        max_clip_seconds=90,
        max_candidates=3,
        language="en",
    )


@pytest.fixture
def client() -> FakeClient:
    return FakeClient()


@pytest.fixture
def provider(client: FakeClient) -> OpenAIClipProvider:
    return OpenAIClipProvider(settings_with(), MODEL, client=client)


# --- configuration ---------------------------------------------------------------------------


def test_missing_key_is_a_configuration_error_before_any_request():
    with pytest.raises(ClipProviderConfigurationError) as info:
        OpenAIClipProvider(settings_with(openai_api_key=None), MODEL)
    assert info.value.code == "missing_api_key"
    with pytest.raises(ClipProviderConfigurationError):
        OpenAIClipProvider(settings_with(openai_api_key=SecretStr("")), MODEL)


def test_real_client_is_built_with_key_timeout_and_minimal_retries(monkeypatch):
    built: dict = {}

    class StubOpenAI:
        def __init__(self, *, api_key, timeout, max_retries):
            built.update(api_key=api_key, timeout=timeout, max_retries=max_retries)

    monkeypatch.setattr(module.openai, "OpenAI", StubOpenAI)
    OpenAIClipProvider(settings_with(openai_clip_timeout_seconds=42), MODEL)
    assert built == {"api_key": "sk-test-not-real", "timeout": 42, "max_retries": 1}


def test_key_never_appears_in_provider_state_errors_or_logs(
    provider: OpenAIClipProvider, client, caplog
):
    client.responses.error = status_error(openai.AuthenticationError, 401)
    with pytest.raises(ClipProviderError) as info:
        provider.analyze(request())
    assert "sk-test" not in info.value.message
    assert "sk-test" not in repr(vars(provider))

    # Even an SDK error whose message echoes the key must not reach the logs.
    client.responses.error = openai.OpenAIError("boom sk-test-not-real")
    with caplog.at_level(logging.DEBUG), pytest.raises(ClipProviderError) as info:
        provider.analyze(request())
    assert "sk-test" not in info.value.message
    assert "sk-test" not in caplog.text
    assert "OpenAIError" in caplog.text  # the type is still logged for operators


# --- request shape ---------------------------------------------------------------------------


def test_uses_structured_outputs_with_the_shared_prompt(provider, client):
    result = provider.analyze(request())

    (call,) = client.responses.calls
    assert call["model"] == MODEL
    assert call["text_format"] is AnalysisOutput
    assert call["max_output_tokens"] == 4000
    assert "Never invent" in call["instructions"]
    (message,) = call["input"]
    assert message["role"] == "user"
    assert "[600.0 → 605.0] line 0" in message["content"]
    assert "between 15 and 90 seconds" in message["content"]
    assert "temperature" not in call  # reasoning models reject it; defaults are used
    assert result.provider == "openai" and result.model == MODEL


def test_max_output_tokens_comes_from_settings(client):
    provider = OpenAIClipProvider(
        settings_with(openai_clip_max_output_tokens=1234), MODEL, client=client
    )
    provider.analyze(request())
    assert client.responses.calls[0]["max_output_tokens"] == 1234


# --- responses -----------------------------------------------------------------------------


def test_parsed_output_becomes_raw_candidates(provider):
    (candidate,) = provider.analyze(request()).candidates
    assert candidate.start == 600.0 and candidate.end == 640.0
    assert candidate.title == "The reveal" and candidate.hook_score == 82


def test_empty_candidates_are_valid(provider, client):
    client.responses.result = parsed_response([])
    assert provider.analyze(request()).candidates == ()


def test_incomplete_answer_is_an_output_error(provider, client):
    client.responses.result = parsed_response([], status="incomplete", reason="max_output_tokens")
    with pytest.raises(ClipProviderOutputError) as info:
        provider.analyze(request())
    assert "max_output_tokens" in info.value.message and info.value.retryable is False


def test_refusal_is_an_output_error(provider, client):
    client.responses.result = SimpleNamespace(
        status="completed",
        incomplete_details=None,
        output_parsed=None,
        output=[SimpleNamespace(content=[SimpleNamespace(type="refusal", refusal="no")])],
    )
    with pytest.raises(ClipProviderOutputError) as info:
        provider.analyze(request())
    assert "declined" in info.value.message


def test_missing_parsed_output_is_an_output_error(provider, client):
    client.responses.result = SimpleNamespace(
        status="completed", incomplete_details=None, output_parsed=None, output=[]
    )
    with pytest.raises(ClipProviderOutputError) as info:
        provider.analyze(request())
    assert "no structured answer" in info.value.message


# --- SDK error mapping ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("error", "expected", "code", "retryable"),
    [
        (
            status_error(openai.AuthenticationError, 401),
            ClipProviderConfigurationError,
            "openai_authentication",
            False,
        ),
        (
            status_error(openai.PermissionDeniedError, 403),
            ClipProviderConfigurationError,
            "openai_model_unavailable",
            False,
        ),
        (
            status_error(openai.NotFoundError, 404),
            ClipProviderConfigurationError,
            "openai_model_unavailable",
            False,
        ),
        (
            status_error(openai.RateLimitError, 429),
            ClipProviderRateLimitError,
            "provider_rate_limited",
            True,
        ),
        (
            openai.APITimeoutError(request=REQUEST),
            ClipProviderTimeoutError,
            "provider_timeout",
            True,
        ),
        (
            openai.APIConnectionError(request=REQUEST),
            ClipProviderUnavailableError,
            "openai_unreachable",
            True,
        ),
        (
            status_error(openai.InternalServerError, 502),
            ClipProviderUnavailableError,
            "openai_server_error",
            True,
        ),
        (
            status_error(openai.BadRequestError, 400),
            ClipProviderError,
            "openai_request_rejected",
            False,
        ),
        (
            status_error(openai.UnprocessableEntityError, 422),
            ClipProviderError,
            "openai_request_rejected",
            False,
        ),
        (openai.OpenAIError("weird"), ClipProviderError, "openai_error", False),
    ],
)
def test_sdk_errors_map_to_contract_errors(provider, client, error, expected, code, retryable):
    client.responses.error = error
    with pytest.raises(expected) as info:
        provider.analyze(request())
    assert info.value.code == code
    assert info.value.retryable is retryable


def test_model_unavailable_message_names_the_model_only(provider, client):
    client.responses.error = status_error(openai.NotFoundError, 404)
    with pytest.raises(ClipProviderConfigurationError) as info:
        provider.analyze(request())
    assert info.value.message == f"OpenAI model '{MODEL}' is not available to this API key"


# --- availability -----------------------------------------------------------------------------


def test_availability_uses_one_metadata_call(provider, client):
    diagnostics = provider.check_availability()
    assert diagnostics.available is True
    assert client.models.retrieved == [MODEL]
    assert client.responses.calls == []  # no paid analysis call


def test_availability_reports_bad_key_and_unknown_model(provider, client):
    client.models.error = status_error(openai.AuthenticationError, 401)
    assert provider.check_availability() == module.ProviderDiagnostics(
        available=False, detail="OpenAI rejected the API key"
    )
    client.models.error = status_error(openai.NotFoundError, 404)
    assert provider.check_availability().detail == (
        f"OpenAI model '{MODEL}' is not available to this API key"
    )


def test_availability_reports_network_problems(provider, client):
    client.models.error = openai.APIConnectionError(request=REQUEST)
    diagnostics = provider.check_availability()
    assert diagnostics.available is False and diagnostics.detail == "Could not reach OpenAI"
