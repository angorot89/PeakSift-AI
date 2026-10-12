"""Ollama provider tests against an in-process fake HTTP transport — no server, no model."""

import json
import os

import httpx
import pytest

from app.core.config import Settings, get_settings
from app.services.clip_detection.contract import (
    AnalysisWindow,
    ClipAnalysisRequest,
    ClipProviderConfigurationError,
    ClipProviderError,
    ClipProviderOutputError,
    ClipProviderTimeoutError,
    ClipProviderUnavailableError,
    TranscriptLine,
)
from app.services.clip_detection.ollama_provider import OllamaClipProvider

MODEL = "llama3.2:3b"

GOOD_CANDIDATE = {
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


def request() -> ClipAnalysisRequest:
    lines = tuple(
        TranscriptLine(start=600.0 + 5 * i, end=605.0 + 5 * i, text=f"line {i}") for i in range(12)
    )
    return ClipAnalysisRequest(
        window=AnalysisWindow(index=2, start=600.0, end=660.0, lines=lines),
        video_duration=3600.0,
        min_clip_seconds=15,
        max_clip_seconds=90,
        max_candidates=3,
        language="en",
    )


def settings_with(**overrides) -> Settings:
    base = get_settings().model_dump()
    base.update(overrides)
    return Settings(**base)


def chat_reply(content, *, done_reason="stop", status=200) -> httpx.Response:
    text = content if isinstance(content, str) else json.dumps(content)
    return httpx.Response(
        status,
        json={
            "model": MODEL,
            "message": {"role": "assistant", "content": text},
            "done": True,
            "done_reason": done_reason,
        },
    )


def provider_with(handler, **settings_overrides) -> tuple[OllamaClipProvider, list[httpx.Request]]:
    """Provider whose HTTP goes to `handler`; also returns the requests it made."""
    seen: list[httpx.Request] = []

    def transport_handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        result = handler(req)
        if isinstance(result, Exception):
            raise result
        return result

    settings = settings_with(**settings_overrides)
    client = httpx.Client(
        transport=httpx.MockTransport(transport_handler), base_url=settings.ollama_base_url
    )
    return OllamaClipProvider(settings, MODEL, client=client), seen


# --- request shape ---------------------------------------------------------------------------


def test_request_is_a_constrained_json_chat_with_the_shared_prompt():
    provider, seen = provider_with(lambda req: chat_reply({"candidates": [GOOD_CANDIDATE]}))
    result = provider.analyze(request())

    (req,) = seen
    assert req.method == "POST" and req.url.path == "/api/chat"
    assert str(req.url).startswith(
        get_settings().ollama_base_url.rstrip("/")
    )  # the configured endpoint
    body = json.loads(req.content)
    assert body["model"] == MODEL
    assert body["stream"] is False
    assert body["options"] == {"temperature": 0, "num_ctx": 8192}
    assert body["format"]["additionalProperties"] is False  # the shared JSON schema
    assert "CandidateOutput" in body["format"]["$defs"]
    system, user = body["messages"]
    assert system["role"] == "system" and "Never invent" in system["content"]
    assert user["role"] == "user" and "[600.0 → 605.0] line 0" in user["content"]
    assert "between 15 and 90 seconds" in user["content"]
    assert result.provider == "ollama" and result.model == MODEL


def test_endpoint_and_context_come_from_settings():
    provider, seen = provider_with(
        lambda req: chat_reply({"candidates": []}),
        ollama_base_url="http://inference.internal:11434/",
        ollama_num_ctx=16384,
    )
    provider.analyze(request())
    (req,) = seen
    assert req.url.host == "inference.internal"
    assert json.loads(req.content)["options"]["num_ctx"] == 16384


def test_constructing_the_provider_makes_no_network_call():
    calls: list = []
    provider, seen = provider_with(lambda req: calls.append(req) or chat_reply({"candidates": []}))
    assert calls == [] and seen == [] and provider.model == MODEL


# --- responses -----------------------------------------------------------------------------


def test_candidates_are_parsed_into_raw_candidates():
    provider, _ = provider_with(lambda req: chat_reply({"candidates": [GOOD_CANDIDATE]}))
    (candidate,) = provider.analyze(request()).candidates
    assert candidate.start == 600.0 and candidate.end == 640.0
    assert candidate.title == "The reveal" and candidate.category == "story"
    assert candidate.payoff_score == 88


def test_empty_candidate_list_is_a_valid_answer():
    provider, _ = provider_with(lambda req: chat_reply({"candidates": []}))
    assert provider.analyze(request()).candidates == ()


def test_non_json_content_is_an_output_error():
    provider, _ = provider_with(lambda req: chat_reply("Sure! Here are some clips: ..."))
    with pytest.raises(ClipProviderOutputError) as info:
        provider.analyze(request())
    assert info.value.retryable is False
    assert "valid JSON" in info.value.message


def test_schema_mismatch_is_an_output_error():
    provider, _ = provider_with(lambda req: chat_reply({"clips": [GOOD_CANDIDATE]}))
    with pytest.raises(ClipProviderOutputError) as info:
        provider.analyze(request())
    assert "expected schema" in info.value.message


def test_truncated_answer_is_reported_not_parsed():
    provider, _ = provider_with(
        lambda req: chat_reply('{"candidates": [{"start_seconds": 600', done_reason="length")
    )
    with pytest.raises(ClipProviderOutputError) as info:
        provider.analyze(request())
    assert "cut off" in info.value.message


def test_unexpected_body_shape_is_an_output_error():
    provider, _ = provider_with(lambda req: httpx.Response(200, json={"done": True}))
    with pytest.raises(ClipProviderOutputError):
        provider.analyze(request())


# --- transport and HTTP failures ------------------------------------------------------------------


def test_connection_refused_is_retryable_unavailable():
    provider, _ = provider_with(lambda req: httpx.ConnectError("refused", request=req))
    with pytest.raises(ClipProviderUnavailableError) as info:
        provider.analyze(request())
    assert info.value.retryable is True
    assert info.value.message == "The local inference server is not reachable"


def test_read_timeout_is_retryable_timeout():
    provider, _ = provider_with(lambda req: httpx.ReadTimeout("slow", request=req))
    with pytest.raises(ClipProviderTimeoutError) as info:
        provider.analyze(request())
    assert info.value.retryable is True and info.value.code == "provider_timeout"


def test_missing_model_is_a_configuration_error_not_a_retry():
    provider, _ = provider_with(
        lambda req: httpx.Response(404, json={"error": f"model '{MODEL}' not found"})
    )
    with pytest.raises(ClipProviderConfigurationError) as info:
        provider.analyze(request())
    assert info.value.code == "model_not_installed"
    assert info.value.retryable is False
    assert MODEL in info.value.message  # operator configuration, safe to name


def test_server_error_is_retryable():
    provider, _ = provider_with(lambda req: httpx.Response(500, text="boom"))
    with pytest.raises(ClipProviderUnavailableError) as info:
        provider.analyze(request())
    assert info.value.retryable is True and "500" in info.value.message


def test_client_error_is_not_retryable():
    provider, _ = provider_with(lambda req: httpx.Response(400, json={"error": "bad"}))
    with pytest.raises(ClipProviderError) as info:
        provider.analyze(request())
    assert info.value.retryable is False and info.value.code == "provider_request_rejected"


def test_errors_never_mention_the_endpoint(monkeypatch):
    provider, _ = provider_with(
        lambda req: httpx.ConnectError("refused", request=req),
        ollama_base_url="http://inference.internal:11434",
    )
    with pytest.raises(ClipProviderError) as info:
        provider.analyze(request())
    assert "inference.internal" not in info.value.message
    assert "11434" not in info.value.message


# --- availability diagnostics ----------------------------------------------------------------


def tags(*names: str) -> httpx.Response:
    return httpx.Response(200, json={"models": [{"name": n} for n in names]})


def test_available_when_the_model_is_installed():
    provider, seen = provider_with(lambda req: tags("qwen2.5:7b", MODEL))
    diagnostics = provider.check_availability()
    assert diagnostics.available is True
    assert seen[0].url.path == "/api/tags"


def test_bare_names_match_the_latest_tag():
    settings = settings_with()
    client = httpx.Client(
        transport=httpx.MockTransport(lambda req: tags("llama3.2:latest")),
        base_url=settings.ollama_base_url,
    )
    assert OllamaClipProvider(settings, "llama3.2", client=client).check_availability().available


def test_unavailable_when_the_model_is_missing():
    provider, _ = provider_with(lambda req: tags("qwen2.5:7b"))
    diagnostics = provider.check_availability()
    assert diagnostics.available is False
    assert diagnostics.detail == f"Model '{MODEL}' is not installed on the local inference server"


def test_unavailable_when_the_server_is_down():
    provider, _ = provider_with(lambda req: httpx.ConnectError("refused", request=req))
    diagnostics = provider.check_availability()
    assert diagnostics.available is False
    assert diagnostics.detail == "The local inference server is not reachable"


def test_unavailable_on_garbage_tags_response():
    provider, _ = provider_with(lambda req: httpx.Response(200, text="<html>"))
    assert provider.check_availability().available is False


# --- real local model (opt-in; never in CI) ---------------------------------------------


@pytest.mark.skipif(
    not os.environ.get("PEAKSIFT_REAL_OLLAMA"), reason="set PEAKSIFT_REAL_OLLAMA=1 to run"
)
def test_real_ollama_round_trip():
    """Talks to the Ollama at OLLAMA_BASE_URL with the first allowed model."""
    settings = get_settings()
    model = settings.ollama_clip_models.split(",")[0].strip()
    provider = OllamaClipProvider(settings, model)
    diagnostics = provider.check_availability()
    assert diagnostics.available, diagnostics.detail

    lines = (
        TranscriptLine(0.0, 6.0, "Okay so I have to tell you what happened at the airport."),
        TranscriptLine(6.0, 12.0, "I get to the gate and the agent looks at my passport."),
        TranscriptLine(12.0, 18.0, "She goes, sir, this expired three years ago."),
        TranscriptLine(18.0, 24.0, "Three years. I had flown twice that year already."),
        TranscriptLine(24.0, 30.0, "Nobody had checked. Not once. I just stood there laughing."),
        TranscriptLine(30.0, 36.0, "Anyway, that is why I missed your wedding. Sorry."),
    )
    result = provider.analyze(
        ClipAnalysisRequest(
            window=AnalysisWindow(index=0, start=0.0, end=36.0, lines=lines),
            video_duration=36.0,
            min_clip_seconds=10,
            max_clip_seconds=36,
            max_candidates=2,
            language="en",
        )
    )
    assert result.provider == "ollama" and result.model == model
    for candidate in result.candidates:
        assert 0 <= candidate.start < candidate.end <= 40  # shape only; validation judges values
