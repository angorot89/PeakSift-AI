"""Local clip analysis through an Ollama-compatible HTTP endpoint.

The endpoint (``OLLAMA_BASE_URL``) and the allowed models are operator configuration; a
request never carries a URL chosen by a client. Responses are constrained with Ollama's
``format`` (a JSON schema), decoded, and handed to the shared shape check. No model is
pulled or loaded here: if the configured model is not installed the provider says so.
"""

import json
import logging
from typing import Any

import httpx

from app.core.config import Settings
from app.services.clip_detection.contract import (
    ClipAnalysisRequest,
    ClipAnalysisResult,
    ClipProviderConfigurationError,
    ClipProviderError,
    ClipProviderOutputError,
    ClipProviderTimeoutError,
    ClipProviderUnavailableError,
    ProviderDiagnostics,
    analysis_output_json_schema,
    parse_analysis_output,
)
from app.services.clip_detection.prompt import SYSTEM_PROMPT, user_prompt

logger = logging.getLogger(__name__)

UNREACHABLE = "The local inference server is not reachable"
TIMED_OUT = "The local inference server did not answer in time"


def _same_model(installed: str, wanted: str) -> bool:
    """``llama3.2:3b`` is what Ollama reports for a pull of ``llama3.2:3b``; a bare name
    means the ``:latest`` tag."""
    norm = lambda name: name if ":" in name else f"{name}:latest"  # noqa: E731
    return norm(installed) == norm(wanted)


class OllamaClipProvider:
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

    # --- diagnostics ----------------------------------------------------------------------

    def check_availability(self) -> ProviderDiagnostics:
        try:
            response = self._client.get("/api/tags")
            response.raise_for_status()
            installed = [m.get("name", "") for m in response.json().get("models", [])]
        except (httpx.ConnectError, httpx.TimeoutException):
            return ProviderDiagnostics(available=False, detail=UNREACHABLE)
        except (httpx.HTTPError, ValueError, AttributeError):
            return ProviderDiagnostics(
                available=False, detail="The local inference server returned an unexpected answer"
            )
        if not any(_same_model(name, self.model) for name in installed):
            return ProviderDiagnostics(
                available=False,
                detail=f"Model '{self.model}' is not installed on the local inference server",
            )
        return ProviderDiagnostics(available=True, detail="ready")

    # --- analysis ---------------------------------------------------------------------------

    def analyze(self, request: ClipAnalysisRequest) -> ClipAnalysisResult:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt(request)},
            ],
            "stream": False,
            "format": analysis_output_json_schema(),
            "options": {"temperature": 0, "num_ctx": self._num_ctx},
        }
        try:
            response = self._client.post("/api/chat", json=payload)
        except httpx.ConnectError as error:
            raise ClipProviderUnavailableError(UNREACHABLE) from error
        except httpx.TimeoutException as error:
            raise ClipProviderTimeoutError(TIMED_OUT) from error
        except httpx.HTTPError as error:
            raise ClipProviderUnavailableError(
                "Could not talk to the local inference server"
            ) from error

        if response.status_code == 404:
            raise ClipProviderConfigurationError(
                f"Model '{self.model}' is not installed on the local inference server",
                code="model_not_installed",
            )
        if response.status_code >= 500:
            raise ClipProviderUnavailableError(
                f"The local inference server failed (HTTP {response.status_code})",
                code="provider_server_error",
            )
        if response.status_code >= 400:
            raise ClipProviderError(
                "provider_request_rejected",
                f"The local inference server rejected the request (HTTP {response.status_code})",
            )

        try:
            body = response.json()
            content = body["message"]["content"]
        except (ValueError, KeyError, TypeError) as error:
            raise ClipProviderOutputError(
                "The local inference server returned an unexpected response"
            ) from error
        if body.get("done_reason") == "length":
            raise ClipProviderOutputError(
                "The model's answer was cut off; use a smaller analysis window or a larger context"
            )
        try:
            data = json.loads(content)
        except (TypeError, ValueError) as error:
            raise ClipProviderOutputError("The model did not return valid JSON") from error

        candidates = parse_analysis_output(data, provider="The local model")
        logger.debug("Ollama window %s: %s raw candidates", request.window.index, len(candidates))
        return ClipAnalysisResult(candidates=candidates, provider=self.name, model=self.model)
