"""The B-roll suggestion configuration snapshot and its fingerprint.

Every value is server configuration — a request can only ask "suggest B-roll for this clip"
(and, deliberately, "regenerate"). The snapshot is stored on each ``BrollAnalysis``; its
fingerprint makes ``(clip_id, config_fingerprint)`` unique, so asking again returns the
existing analysis, while a new provider, model, rule version or generation produces a new
one. The job always runs with its stored snapshot, never with today's defaults.
"""

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any

from app.core.config import Settings
from app.services.broll.suggest import broll_model
from app.services.broll.validation import (
    MAX_SUGGESTION_SECONDS,
    MAX_SUGGESTIONS,
    MIN_SUGGESTION_SECONDS,
    SECONDS_PER_SUGGESTION,
)

SUGGESTION_VERSION = "broll_suggest_v1"


@dataclass(frozen=True)
class BrollConfig:
    suggestion_version: str
    provider: str
    model: str
    fallback_enabled: bool
    min_seconds: float
    max_seconds: float
    seconds_per_suggestion: float
    max_suggestions: int
    generation: int

    @classmethod
    def from_settings(cls, settings: Settings, *, generation: int = 1) -> "BrollConfig":
        provider = settings.broll_suggestion_provider
        return cls(
            suggestion_version=SUGGESTION_VERSION,
            provider=provider,
            model=broll_model(settings) if provider == "ollama" else "proper_names_v1",
            fallback_enabled=bool(settings.broll_fallback_enabled),
            min_seconds=MIN_SUGGESTION_SECONDS,
            max_seconds=MAX_SUGGESTION_SECONDS,
            seconds_per_suggestion=SECONDS_PER_SUGGESTION,
            max_suggestions=MAX_SUGGESTIONS,
            generation=int(generation),
        )

    @classmethod
    def from_snapshot(cls, snapshot: dict[str, Any]) -> "BrollConfig":
        if (
            not isinstance(snapshot, dict)
            or snapshot.get("suggestion_version") != SUGGESTION_VERSION
        ):
            raise ValueError("Unsupported B-roll suggestion configuration version")
        fields = cls.__dataclass_fields__
        if any(name not in snapshot for name in fields):
            raise ValueError("Incomplete B-roll suggestion configuration")
        return cls(**{name: snapshot[name] for name in fields})

    def snapshot(self) -> dict[str, Any]:
        return asdict(self)

    def fingerprint(self) -> str:
        canonical = json.dumps(self.snapshot(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()
