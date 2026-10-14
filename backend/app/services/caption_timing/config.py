"""The caption-timing configuration snapshot and its fingerprint.

Every value is server configuration — a request can only ask "time the words of this clip".
The snapshot is stored on each ``CaptionTrack`` and its fingerprint makes ``(clip_id,
config_fingerprint)`` unique, so repeating the request returns the existing track while a
new provider, model or alignment version produces a new one. Visual styling never appears
here: a track describes when words were spoken, not how captions look.
"""

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any

from app.core.config import Settings

ALIGNMENT_VERSION = "caption_alignment_v1"


@dataclass(frozen=True)
class CaptionTimingConfig:
    alignment_version: str
    provider: str
    model: str
    compute_type: str
    beam_size: int
    language_hint: str | None

    @classmethod
    def from_settings(
        cls, settings: Settings, *, language_hint: str | None
    ) -> "CaptionTimingConfig":
        return cls(
            alignment_version=ALIGNMENT_VERSION,
            provider=settings.caption_timing_provider,
            model=settings.faster_whisper_model,
            compute_type=settings.faster_whisper_compute_type,
            beam_size=int(settings.faster_whisper_beam_size),
            language_hint=language_hint or None,
        )

    @classmethod
    def from_snapshot(cls, snapshot: dict[str, Any]) -> "CaptionTimingConfig":
        if not isinstance(snapshot, dict) or snapshot.get("alignment_version") != ALIGNMENT_VERSION:
            raise ValueError("Unsupported caption timing configuration version")
        fields = cls.__dataclass_fields__
        if any(name not in snapshot for name in fields):
            raise ValueError("Incomplete caption timing configuration")
        return cls(**{name: snapshot[name] for name in fields})

    def snapshot(self) -> dict[str, Any]:
        return asdict(self)

    def fingerprint(self) -> str:
        """sha256 of the canonical JSON: equal configurations, equal fingerprints."""
        canonical = json.dumps(self.snapshot(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()
