"""Copilot model providers: the local Ollama model, and a deterministic fake for tests and CI.

A provider receives the prepared chat messages (``prompt.build_messages``) and returns the
model's JSON object; it never sees the database, ids, credentials or files. The endpoint
(``OLLAMA_BASE_URL``) and model (``COPILOT_OLLAMA_MODEL``, default the first
``OLLAMA_CLIP_MODELS`` entry) are operator configuration. One request at temperature 0 with the
answer schema, plus **one** corrective request when the reply is not a JSON object — within the
``COPILOT_TIMEOUT_SECONDS`` budget. Unreachable, timed out or still malformed raise a
``CopilotProviderError`` and the service answers without the model ("PeakSift's local assistant
isn't available right now"); nothing else in PeakSift depends on it.
"""

import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from app.core.config import Settings
from app.services.copilot.contract import output_schema
from app.services.copilot.prompt import CORRECTION, CORRECTION_IDEAS

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 2
MIN_RETRY_SECONDS = 5.0
MAX_REPLY_CHARS = 8000  # a longer raw answer is cut off and treated as malformed


class CopilotProviderError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ProviderReply:
    data: dict[str, Any]
    provider: str
    model: str
    attempts: int


class CopilotProvider(Protocol):
    name: str
    model: str

    def reply(self, messages: list[dict[str, str]], *, ideas: bool = False) -> ProviderReply: ...


def configured_model(settings: Settings) -> str:
    if settings.copilot_ollama_model.strip():
        return settings.copilot_ollama_model.strip()
    models = [m.strip() for m in settings.ollama_clip_models.split(",") if m.strip()]
    return models[0] if models else "llama3.2:3b"


def get_provider(settings: Settings) -> CopilotProvider:
    if settings.copilot_provider == "fake":
        return FakeCopilotProvider()
    return OllamaCopilotProvider(settings, configured_model(settings))


class OllamaCopilotProvider:
    name = "ollama"

    def __init__(self, settings: Settings, model: str, *, client: httpx.Client | None = None):
        self.model = model
        self._budget = settings.copilot_timeout_seconds
        self._connect = settings.ollama_connect_timeout_seconds
        self._num_ctx = settings.ollama_num_ctx
        self._base_url = settings.ollama_base_url.rstrip("/")
        self._injected = client
        self._schema = output_schema()
        self._correction = CORRECTION

    def reply(self, messages: list[dict[str, str]], *, ideas: bool = False) -> ProviderReply:
        client = self._injected or httpx.Client(base_url=self._base_url)
        self._schema = output_schema(ideas=ideas)
        self._correction = CORRECTION_IDEAS if ideas else CORRECTION
        try:
            return self._reply(list(messages), client)
        finally:
            if self._injected is None:
                client.close()

    def _reply(self, messages: list[dict[str, str]], client: httpx.Client) -> ProviderReply:
        deadline = time.monotonic() + self._budget
        for attempt in range(1, MAX_ATTEMPTS + 1):
            remaining = deadline - time.monotonic()
            if attempt > 1 and remaining < MIN_RETRY_SECONDS:
                break
            content = self._chat(client, messages, timeout=max(remaining, 1.0))
            try:
                data = json.loads(content)
            except (TypeError, ValueError):
                data = None
            if isinstance(data, dict):
                return ProviderReply(data, self.name, self.model, attempt)
            logger.info("Copilot answer %d was not a JSON object; correcting once", attempt)
            messages += [
                {"role": "assistant", "content": str(content)[:2000]},
                {"role": "user", "content": self._correction},
            ]
        raise CopilotProviderError("malformed", "The local assistant's answer was not usable")

    def _chat(self, client: httpx.Client, messages: list[dict[str, str]], *, timeout: float) -> str:
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "format": self._schema,
            "options": {"temperature": 0, "num_ctx": self._num_ctx, "num_predict": 700},
        }
        limits = httpx.Timeout(timeout, connect=min(self._connect, timeout))
        try:
            response = client.post("/api/chat", json=payload, timeout=limits)
        except httpx.ConnectError as error:
            raise CopilotProviderError(
                "unavailable", "The local assistant is not reachable"
            ) from error
        except httpx.TimeoutException as error:
            raise CopilotProviderError(
                "timeout", "The local assistant did not answer in time"
            ) from error
        except httpx.HTTPError as error:
            raise CopilotProviderError(
                "unavailable", "Could not reach the local assistant"
            ) from error
        if response.status_code == 404:
            raise CopilotProviderError("model_not_installed", "The local model is not installed")
        if response.status_code >= 400:
            raise CopilotProviderError(
                "unavailable", f"The local assistant failed ({response.status_code})"
            )
        try:
            body = response.json()
            content = body["message"]["content"]
        except (ValueError, KeyError, TypeError) as error:
            raise CopilotProviderError(
                "malformed", "Unexpected answer from the local assistant"
            ) from error
        if body.get("done_reason") == "length" or len(content) > MAX_REPLY_CHARS:
            return ""  # cut off: malformed (one corrective attempt)
        return content


class FakeCopilotProvider:
    """Deterministic answers for tests, CI and demos — never a model. ``replies`` scripts
    exact answers (dicts, or exceptions to raise); otherwise it reads the DATA block and
    answers with the next step it finds there, or a plain statement of what it can see."""

    name = "fake"
    model = "fake-copilot-v1"

    def __init__(self, replies: list[Any] | None = None):
        self.replies = list(replies or [])
        self.calls: list[list[dict[str, str]]] = []

    def reply(self, messages: list[dict[str, str]], *, ideas: bool = False) -> ProviderReply:
        self.calls.append(messages)
        if self.replies:
            scripted = self.replies.pop(0)
            if isinstance(scripted, Exception):
                raise scripted
            return ProviderReply(scripted, self.name, self.model, 1)
        view = _data_block(messages[-1]["content"])
        step = view.get("next_step") if isinstance(view, dict) else None
        if isinstance(step, dict) and step.get("title"):
            action = step.get("action")
            return ProviderReply(
                {
                    "message": f"{step['title']}. {step.get('why', '')}".strip(),
                    "suggestion": None,
                    "actions": [action] if action else [],
                    "references": [],
                },
                self.name,
                self.model,
                1,
            )
        project = view.get("project") if isinstance(view, dict) else None
        if isinstance(project, dict):
            message = f"I can see your project “{project.get('name')}”."
            references = ["project"]
        else:
            message = "I can see your workspace."
            references = []
        return ProviderReply(
            {"message": message, "suggestion": None, "actions": [], "references": references},
            self.name,
            self.model,
            1,
        )


def _data_block(text: str) -> dict:
    start = text.find("<<<DATA\n")
    end = text.rfind("\nDATA>>>")
    if start < 0 or end < 0:
        return {}
    try:
        return json.loads(text[start + len("<<<DATA\n") : end])
    except ValueError:
        return {}


_HEALTH: dict[str, tuple[float, bool]] = {}
HEALTH_TTL_SECONDS = 30.0


def assistant_available(settings: Settings) -> bool:
    """Whether the local assistant can answer now (the model is installed and the server
    answers), checked at most every 30 s per process. Never raises."""
    if not settings.copilot_enabled:
        return False
    if settings.copilot_provider == "fake":
        return True
    model = configured_model(settings)
    key = f"{settings.ollama_base_url}|{model}"
    cached = _HEALTH.get(key)
    now = time.monotonic()
    if cached and now - cached[0] < HEALTH_TTL_SECONDS:
        return cached[1]
    try:
        response = httpx.get(
            settings.ollama_base_url.rstrip("/") + "/api/tags",
            timeout=httpx.Timeout(2.0, connect=min(settings.ollama_connect_timeout_seconds, 2.0)),
        )
        names = {m.get("name") for m in response.json().get("models", [])}
        ok = response.status_code == 200 and (model in names or f"{model}:latest" in names)
    except (httpx.HTTPError, ValueError, AttributeError):
        ok = False
    _HEALTH[key] = (now, ok)
    return ok
