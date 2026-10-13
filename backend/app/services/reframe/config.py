"""The smart-reframing configuration snapshot and its fingerprint.

Every value comes from server settings — a request can only ask "analyse this clip". The
snapshot is stored with each analysis (future algorithm versions may behave differently),
and its fingerprint deduplicates identical requests: ``(clip_id, config_fingerprint)`` is
unique, so a repeated "Analyze framing" returns the existing analysis.

Coordinate convention (used by every reframe module, the API and the renderer): positions
and sizes are fractions of the *display-oriented* source frame — after rotation metadata is
applied — with ``x`` growing to the right and ``y`` downwards, both in ``[0, 1]``.
"""

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any

from app.core.config import Settings

ALGORITHM_VERSION = "smart_reframe_v1"
TARGET_ASPECT_RATIO = "9:16"
TARGET_RATIO = 9 / 16  # width / height of the crop


@dataclass(frozen=True)
class ReframeConfig:
    algorithm_version: str
    target_aspect_ratio: str
    detector: str
    sample_fps: float
    analysis_width: int
    min_detection_confidence: float
    face_margin: float
    dead_zone: float
    smoothing_seconds: float
    max_pan_per_second: float
    max_gap_seconds: float

    @classmethod
    def from_settings(cls, settings: Settings) -> "ReframeConfig":
        return cls(
            algorithm_version=ALGORITHM_VERSION,
            target_aspect_ratio=TARGET_ASPECT_RATIO,
            detector=settings.reframe_detector,
            sample_fps=float(settings.reframe_sample_fps),
            analysis_width=int(settings.reframe_analysis_width),
            min_detection_confidence=float(settings.reframe_min_detection_confidence),
            face_margin=float(settings.reframe_face_margin),
            dead_zone=float(settings.reframe_dead_zone),
            smoothing_seconds=float(settings.reframe_smoothing_seconds),
            max_pan_per_second=float(settings.reframe_max_pan_per_second),
            max_gap_seconds=float(settings.reframe_max_gap_seconds),
        )

    @classmethod
    def from_snapshot(cls, snapshot: dict[str, Any]) -> "ReframeConfig":
        if not isinstance(snapshot, dict) or snapshot.get("algorithm_version") != ALGORITHM_VERSION:
            raise ValueError("Unsupported reframe configuration version")
        fields = cls.__dataclass_fields__
        missing = [name for name in fields if name not in snapshot]
        if missing:
            raise ValueError("Incomplete reframe configuration")
        return cls(**{name: snapshot[name] for name in fields})

    def snapshot(self) -> dict[str, Any]:
        return asdict(self)

    def fingerprint(self) -> str:
        """sha256 of the canonical JSON: equal configurations, equal fingerprints."""
        canonical = json.dumps(self.snapshot(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()
