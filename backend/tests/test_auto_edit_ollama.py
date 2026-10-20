"""The local Auto Edit planner over an Ollama-compatible API (mocked transport): the request it
sends (schema, temperature 0, editor rules, handles but no ids), one bounded corrective
attempt, and every failure mapped to a safe planner error. A real-model check is opt-in."""

import json
import os
import re

import httpx
import pytest

from app.core.config import Settings, get_settings
from app.services.auto_edit.contract import (
    PlannerConfigurationError,
    PlannerError,
    PlannerOutputError,
    PlannerTimeoutError,
    PlannerUnavailableError,
)
from app.services.auto_edit.ollama import SYSTEM_PROMPT, OllamaAutoEditPlanner
from app.services.auto_edit.planners import get_planner, planner_model
from tests.test_auto_edit_contract import GOOD, UUID, context


def settings(**overrides) -> Settings:
    return Settings(**{**get_settings().model_dump(), **overrides})


class Server:
    """A scripted Ollama: each request gets the next reply (or raises)."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.requests: list[dict] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(json.loads(request.content))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        if isinstance(reply, httpx.Response):
            return reply
        content = reply if isinstance(reply, str) else json.dumps(reply)
        return httpx.Response(200, json={"message": {"content": content}, "done_reason": "stop"})


def planner(server: Server, **overrides) -> OllamaAutoEditPlanner:
    client = httpx.Client(transport=httpx.MockTransport(server), base_url="http://ollama.test")
    return OllamaAutoEditPlanner(settings(**overrides), "llama3.2:3b", client=client)


def test_a_valid_answer_is_one_request():
    server = Server(GOOD)
    result = planner(server).plan(context())
    assert result.provider == "ollama" and result.model == "llama3.2:3b" and result.attempts == 1
    assert result.proposal.captions.preset == "punch"
    (request,) = server.requests
    assert request["model"] == "llama3.2:3b" and request["stream"] is False
    assert request["options"]["temperature"] == 0
    assert request["format"]["additionalProperties"] is False


def test_the_model_is_told_to_edit_not_to_decorate():
    for rule in (
        "speech clear",
        "Never invent",
        "none is fine",
        "Never invent handles",
        "matching_assets",
        "Do not add effects everywhere",
        "No internal reasoning",
    ):
        assert rule in SYSTEM_PROMPT, rule  # fmt: skip


def test_the_model_sees_handles_and_facts_but_never_ids():
    server = Server(GOOD)
    planner(server).plan(context())
    text = json.dumps(server.requests[0]["messages"])
    assert not UUID.search(text)
    assert "visual_asset_1" in text and "suggestion_1" in text and "music_1" in text
    assert "weakest joint" in text


def test_one_corrective_attempt_repairs_malformed_json():
    server = Server("{not json", GOOD)
    result = planner(server).plan(context())
    assert result.attempts == 2 and len(server.requests) == 2
    second = server.requests[1]["messages"]
    assert second[-2] == {"role": "assistant", "content": "{not json"}
    assert "ONLY the JSON object" in second[-1]["content"]


def test_one_corrective_attempt_repairs_a_wrong_shape():
    wrong = {**GOOD, "layout": {"mode": "zoom"}}
    server = Server(wrong, GOOD)
    assert planner(server).plan(context()).attempts == 2


def test_no_endless_reprompting():
    server = Server("{", {"layout": "x"}, GOOD)
    with pytest.raises(PlannerOutputError) as caught:
        planner(server).plan(context())
    assert len(server.requests) == 2  # initial + one corrective, never more
    assert caught.value.fallback_ok


def test_a_cut_off_answer_counts_as_malformed():
    cut = httpx.Response(200, json={"message": {"content": '{"lay'}, "done_reason": "length"})
    server = Server(cut, GOOD)
    assert planner(server).plan(context()).attempts == 2


def test_no_corrective_attempt_without_time_left(monkeypatch):
    clock = iter([0.0, 0.0, 119.0, 119.0])
    monkeypatch.setattr("app.services.auto_edit.ollama.time.monotonic", lambda: next(clock))
    server = Server("{")
    with pytest.raises(PlannerOutputError):
        planner(server, auto_edit_timeout_seconds=120).plan(context())
    assert len(server.requests) == 1


@pytest.mark.parametrize(
    ("reply", "kind", "code"),
    [
        (httpx.ConnectError("refused"), PlannerUnavailableError, "planner_unavailable"),
        (httpx.ReadTimeout("slow"), PlannerTimeoutError, "planner_timeout"),
        (httpx.Response(404, json={"error": "model not found"}), PlannerUnavailableError,
         "model_not_installed"),
        (httpx.Response(500, text="boom"), PlannerUnavailableError, "planner_server_error"),
        (httpx.Response(400, text="bad"), PlannerError, "planner_request_rejected"),
        (httpx.Response(200, text="<html>"), PlannerOutputError, "planner_output"),
        (httpx.Response(200, json={"unexpected": True}), PlannerOutputError, "planner_output"),
    ],
)  # fmt: skip
def test_failures_become_safe_planner_errors(reply, kind, code):
    server = Server(reply)
    with pytest.raises(kind) as caught:
        planner(server).plan(context())
    assert caught.value.code == code
    assert "ollama.test" not in caught.value.message and "llama" not in caught.value.message
    assert len(server.requests) == 1  # transport failures are not re-prompted


def test_the_planner_is_server_configuration():
    assert planner_model(settings(auto_edit_ollama_model="", ollama_clip_models="a:1,b:2")) == "a:1"
    assert planner_model(settings(auto_edit_ollama_model=" custom:7b ")) == "custom:7b"
    assert isinstance(get_planner(settings(), "ollama", "a:1"), OllamaAutoEditPlanner)
    with pytest.raises(PlannerConfigurationError):
        get_planner(settings(), "ollama", "")
    with pytest.raises(PlannerConfigurationError):
        get_planner(settings(), "openai", "gpt")


@pytest.mark.skipif(
    not os.environ.get("PEAKSIFT_REAL_OLLAMA"), reason="set PEAKSIFT_REAL_OLLAMA=1 to run"
)
def test_a_real_local_model_returns_a_valid_proposal():  # pragma: no cover - opt-in
    model = planner_model(get_settings())
    result = get_planner(get_settings(), "ollama", model).plan(context())
    assert result.proposal.layout.mode in {"smart_reframe", "blur_background", "center_crop", "fit"}
    assert all(re.match(r"^visual_asset_\d+$", v.asset) for v in result.proposal.visuals)
