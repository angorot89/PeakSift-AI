"""Choosing a suggestion provider, falling back honestly, and reviewing what it proposed.

- The provider is server configuration (``BROLL_SUGGESTION_PROVIDER``): ``ollama`` (a local
  model) or ``keyword`` (the deterministic name-based fallback). Clients never choose it.
- When the model cannot answer — unreachable, timed out, not installed, malformed reply —
  and ``BROLL_FALLBACK_ENABLED`` is on, the keyword provider stands in and the result says so
  (``fallback_reason``); the API and the editor label those suggestions accordingly.
- Every proposal then goes through the same review: per-item checks (``validation``), grounding
  in what was said (``grounding``), then duplicates, overlaps and density. Grounding runs
  before the density cap, so a refused suggestion never takes a better one's place.
"""

import logging
from dataclasses import dataclass

from app.core.config import Settings
from app.services.broll.contract import (
    BrollProvider,
    BrollProviderConfigurationError,
    BrollProviderError,
    BrollRequest,
    BrollResult,
    TranscriptLine,
)
from app.services.broll.grounding import ground
from app.services.broll.keyword import KeywordBrollProvider
from app.services.broll.validation import (
    RawSuggestion,
    ValidationReport,
    check_one,
    select_suggestions,
)

logger = logging.getLogger(__name__)

PROVIDERS = ("ollama", "keyword")


def broll_model(settings: Settings) -> str:
    """The configured model, or the first allowed clip-detection model."""
    configured = settings.broll_ollama_model.strip()
    if configured:
        return configured
    allowed = [m.strip() for m in settings.ollama_clip_models.split(",") if m.strip()]
    return allowed[0] if allowed else ""


def get_broll_provider(settings: Settings, name: str, model: str) -> BrollProvider:
    if name == "keyword":
        return KeywordBrollProvider()
    if name == "ollama":
        if not model:
            raise BrollProviderConfigurationError("No local model is configured for B-roll")
        from app.services.broll.ollama import OllamaBrollProvider  # lazy: no client at import

        return OllamaBrollProvider(settings, model)
    raise BrollProviderConfigurationError("The B-roll suggestion provider is not supported")


@dataclass(frozen=True)
class Outcome:
    result: BrollResult
    fallback_reason: str | None  # the primary provider's error code when the fallback answered


def suggest(request: BrollRequest, primary: BrollProvider, *, fallback_enabled: bool) -> Outcome:
    """Ask the primary provider; on a provider failure, the keyword fallback (if allowed)."""
    try:
        return Outcome(primary.suggest(request), None)
    except BrollProviderError as error:
        if not (fallback_enabled and error.fallback_ok) or primary.name == "keyword":
            raise
        logger.warning(
            "B-roll provider %s failed (%s); using the keyword fallback", primary.name, error.code
        )
        return Outcome(KeywordBrollProvider().suggest(request), error.code)


def review(
    raw: tuple[RawSuggestion, ...] | list[RawSuggestion],
    lines: tuple[TranscriptLine, ...],
    clip_duration: float,
) -> ValidationReport:
    report = ValidationReport()
    if clip_duration <= 0:
        for _ in raw:
            report.reject("outside_clip")
        return report
    checked = [s for s in (check_one(item, clip_duration, report) for item in raw) if s is not None]
    grounded, refused = ground(checked, lines)
    for reason, count in refused.items():
        report.rejected[reason] = report.rejected.get(reason, 0) + count
    report.kept = select_suggestions(grounded, clip_duration, report)
    return report
