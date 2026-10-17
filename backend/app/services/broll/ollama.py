"""Local B-roll suggestions through an Ollama-compatible HTTP endpoint.

The endpoint (``OLLAMA_BASE_URL``) and model (``BROLL_OLLAMA_MODEL``) are operator
configuration; a request never carries a URL or model chosen by a client. The answer is
constrained with Ollama's ``format`` (a JSON schema), decoded and shape-checked; its values
are judged afterwards by validation and grounding. No model is pulled or loaded here.
"""

import json
import logging
from typing import Any

import httpx

from app.core.config import Settings
from app.services.broll.contract import (
    BrollProviderError,
    BrollProviderOutputError,
    BrollProviderTimeoutError,
    BrollProviderUnavailableError,
    BrollRequest,
    BrollResult,
    parse_suggestions,
    suggestions_json_schema,
)

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a short-form video editor. You read the timestamped transcript of a \
vertical short (a person talking to camera) and pick the FEW moments where cutting to a \
supporting visual (B-roll: a photo or a short video clip) would make the point clearer or \
keep viewers watching.

Rules:
- Only suggest something that can actually be shown: a place, an object, a vehicle, an \
animal, an event, a process, a product category, a chart of a number that was said.
- The query must use words that were actually said (or an obvious visual of them, e.g. \
"rocket launch" for "we launched the rocket"). Never add names, brands, people, places or \
facts that the speaker did not mention.
- Avoid abstract or vague ideas ("success", "emotion", "an important thing").
- Do not suggest a visual for every sentence. Prefer specific nouns. Fewer is better; an \
empty list is fine when nothing is visual.
- Time each visual to when the thing is mentioned: start at (or just before) the words, \
stay inside the clip, and keep each visual within the allowed length.
- query: 2-6 words describing what to show. reason: one short sentence naming the line it \
supports. score: 0-100, how much the visual would help."""


def user_prompt(request: BrollRequest) -> str:
    lines = "\n".join(f"[{line.start:.1f}-{line.end:.1f}] {line.text}" for line in request.lines)
    context = ""
    if request.title:
        context += f"Clip title: {request.title}\n"
    if request.hook:
        context += f"Clip hook: {request.hook}\n"
    return (
        f"{context}Clip length: {request.clip_duration:.1f} seconds.\n"
        f"Suggest at most {request.max_suggestions} visuals, each "
        f"{request.min_seconds:g}-{request.max_seconds:g} seconds long, between 0 and "
        f"{request.clip_duration:.1f} seconds.\n\nTranscript (seconds from the clip start):\n"
        f"{lines}"
    )


class OllamaBrollProvider:
    name = "ollama"

    def __init__(self, settings: Settings, model: str, *, client: httpx.Client | None = None):
        self.model = model
        self._num_ctx = settings.ollama_num_ctx
        self._client = client or httpx.Client(
            base_url=settings.ollama_base_url.rstrip("/"),
            timeout=httpx.Timeout(
                connect=settings.ollama_connect_timeout_seconds,
                read=settings.ollama_timeout_seconds,
                write=settings.ollama_connect_timeout_seconds,
                pool=settings.ollama_connect_timeout_seconds,
            ),
        )

    def suggest(self, request: BrollRequest) -> BrollResult:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt(request)},
            ],
            "stream": False,
            "format": suggestions_json_schema(),
            "options": {"temperature": 0, "num_ctx": self._num_ctx},
        }
        try:
            response = self._client.post("/api/chat", json=payload)
        except httpx.ConnectError as error:
            raise BrollProviderUnavailableError(
                "The local inference server is not reachable"
            ) from error
        except httpx.TimeoutException as error:
            raise BrollProviderTimeoutError(
                "The local inference server did not answer in time"
            ) from error
        except httpx.HTTPError as error:
            raise BrollProviderUnavailableError(
                "Could not talk to the local inference server"
            ) from error
        if response.status_code == 404:
            raise BrollProviderUnavailableError(
                f"Model '{self.model}' is not installed on the local inference server",
                code="model_not_installed",
            )
        if response.status_code >= 500:
            raise BrollProviderUnavailableError(
                f"The local inference server failed (HTTP {response.status_code})",
                code="provider_server_error",
            )
        if response.status_code >= 400:
            raise BrollProviderError(
                "provider_request_rejected",
                f"The local inference server rejected the request (HTTP {response.status_code})",
            )
        try:
            body = response.json()
            content = body["message"]["content"]
        except (ValueError, KeyError, TypeError) as error:
            raise BrollProviderOutputError(
                "The local inference server returned an unexpected response"
            ) from error
        if body.get("done_reason") == "length":
            raise BrollProviderOutputError("The model's answer was cut off")
        try:
            data = json.loads(content)
        except (TypeError, ValueError) as error:
            raise BrollProviderOutputError("The model did not return valid JSON") from error
        suggestions = parse_suggestions(data, provider="The local model")
        logger.debug("Ollama B-roll: %s raw suggestions", len(suggestions))
        return BrollResult(suggestions=suggestions, provider=self.name, model=self.model)
