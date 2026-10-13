"""Hosted clip analysis with the official OpenAI SDK and structured outputs.

The installed SDK's ``responses.parse`` takes a pydantic model as ``text_format`` and
returns ``output_parsed`` constrained to that schema, so the answer is validated by the
API before we ever see it; the shared shape check still runs for symmetry with other
providers. The key comes from ``OPENAI_API_KEY`` (server environment) and is never
logged, returned or sent anywhere but OpenAI.
"""

import logging
from typing import Any

import openai

from app.core.config import Settings
from app.services.clip_detection.contract import (
    AnalysisOutput,
    ClipAnalysisRequest,
    ClipAnalysisResult,
    ClipProviderConfigurationError,
    ClipProviderError,
    ClipProviderOutputError,
    ClipProviderRateLimitError,
    ClipProviderTimeoutError,
    ClipProviderUnavailableError,
    ProviderDiagnostics,
    parse_analysis_output,
)
from app.services.clip_detection.prompt import SYSTEM_PROMPT, user_prompt

logger = logging.getLogger(__name__)


class OpenAIClipProvider:
    name = "openai"

    def __init__(self, settings: Settings, model: str, *, client: Any | None = None) -> None:
        if settings.openai_api_key is None or not settings.openai_api_key.get_secret_value():
            raise ClipProviderConfigurationError(
                "OPENAI_API_KEY is required for the OpenAI clip provider", code="missing_api_key"
            )
        self.model = model
        self._max_output_tokens = settings.openai_clip_max_output_tokens
        # The pipeline applies bounded retries; keep the SDK's own retries minimal.
        self._client = client or openai.OpenAI(
            api_key=settings.openai_api_key.get_secret_value(),
            timeout=settings.openai_clip_timeout_seconds,
            max_retries=1,
        )

    # --- diagnostics ----------------------------------------------------------------------

    def check_availability(self) -> ProviderDiagnostics:
        """One cheap metadata call: is the key accepted and the model visible to it?"""
        try:
            self._client.models.retrieve(self.model)
        except ClipProviderError as error:  # pragma: no cover - defensive
            return ProviderDiagnostics(available=False, detail=error.message)
        except openai.OpenAIError as error:
            try:
                self._raise_mapped(error)
            except ClipProviderError as mapped:
                return ProviderDiagnostics(available=False, detail=mapped.message)
        return ProviderDiagnostics(available=True, detail="ready")

    # --- analysis ---------------------------------------------------------------------------

    def analyze(self, request: ClipAnalysisRequest) -> ClipAnalysisResult:
        try:
            response = self._client.responses.parse(
                model=self.model,
                instructions=SYSTEM_PROMPT,
                input=[{"role": "user", "content": user_prompt(request)}],
                text_format=AnalysisOutput,
                max_output_tokens=self._max_output_tokens,
            )
        except openai.OpenAIError as error:
            self._raise_mapped(error)

        if getattr(response, "status", None) == "incomplete":
            details = getattr(response, "incomplete_details", None)
            reason = getattr(details, "reason", None) or "unknown"
            raise ClipProviderOutputError(
                f"OpenAI stopped before finishing the answer ({reason}); "
                "use a smaller analysis window or more output tokens"
            )
        parsed = getattr(response, "output_parsed", None)
        if parsed is None:
            if _refused(response):
                raise ClipProviderOutputError("OpenAI declined to analyse this transcript excerpt")
            raise ClipProviderOutputError("OpenAI returned no structured answer")

        candidates = parse_analysis_output(parsed.model_dump(), provider="OpenAI")
        logger.debug("OpenAI window %s: %s raw candidates", request.window.index, len(candidates))
        return ClipAnalysisResult(candidates=candidates, provider=self.name, model=self.model)

    # --- error mapping -------------------------------------------------------------------

    def _raise_mapped(self, error: openai.OpenAIError) -> None:
        """Translate SDK exceptions into contract errors with explicit retryability."""
        if isinstance(error, openai.AuthenticationError):
            raise ClipProviderConfigurationError(
                "OpenAI rejected the API key", code="openai_authentication"
            ) from error
        if isinstance(error, openai.PermissionDeniedError | openai.NotFoundError):
            raise ClipProviderConfigurationError(
                f"OpenAI model '{self.model}' is not available to this API key",
                code="openai_model_unavailable",
            ) from error
        if isinstance(error, openai.RateLimitError):
            raise ClipProviderRateLimitError("OpenAI rate limit reached") from error
        if isinstance(error, openai.APITimeoutError):
            raise ClipProviderTimeoutError("OpenAI did not answer in time") from error
        if isinstance(error, openai.APIConnectionError):
            raise ClipProviderUnavailableError(
                "Could not reach OpenAI", code="openai_unreachable"
            ) from error
        if isinstance(error, openai.InternalServerError):
            raise ClipProviderUnavailableError(
                "OpenAI returned a server error", code="openai_server_error"
            ) from error
        if isinstance(error, openai.APIStatusError):
            raise ClipProviderError(
                "openai_request_rejected",
                f"OpenAI rejected the request (HTTP {error.status_code})",
            ) from error
        # Type only: an SDK error message could echo request details (even the key).
        logger.warning("OpenAI SDK error (%s)", type(error).__name__)
        raise ClipProviderError(
            "openai_error", f"OpenAI request failed ({type(error).__name__})"
        ) from error


def _refused(response: Any) -> bool:
    for item in getattr(response, "output", None) or []:
        for part in getattr(item, "content", None) or []:
            if getattr(part, "type", None) == "refusal":
                return True
    return False
