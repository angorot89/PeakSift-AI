"""The detection settings a run was started with, snapshotted on the run row.

Changing server defaults later must not change how an existing run (or a retry of it)
behaves, so the API stores ``DetectionConfig.from_settings(...).as_dict()`` on the row and
the pipeline reads it back with ``DetectionConfig.from_run(...)``.
"""

from dataclasses import asdict, dataclass, fields
from typing import Any

from app.core.config import Settings


@dataclass(frozen=True)
class DetectionConfig:
    window_seconds: int
    window_overlap_seconds: int
    window_max_chars: int
    max_windows: int
    min_clip_seconds: float
    max_clip_seconds: float
    target_candidates: int
    candidates_per_window: int
    overlap_threshold: float
    timestamp_tolerance_seconds: float

    @classmethod
    def from_settings(cls, settings: Settings) -> "DetectionConfig":
        return cls(
            window_seconds=settings.clip_detection_window_seconds,
            window_overlap_seconds=settings.clip_detection_window_overlap_seconds,
            window_max_chars=settings.clip_detection_window_max_chars,
            max_windows=settings.clip_detection_max_windows,
            min_clip_seconds=settings.clip_detection_min_clip_seconds,
            max_clip_seconds=settings.clip_detection_max_clip_seconds,
            target_candidates=settings.clip_detection_target_candidates,
            candidates_per_window=settings.clip_detection_candidates_per_window,
            overlap_threshold=settings.clip_detection_overlap_threshold,
            timestamp_tolerance_seconds=settings.clip_detection_timestamp_tolerance_seconds,
        )

    @classmethod
    def from_run(cls, snapshot: dict[str, Any] | None, settings: Settings) -> "DetectionConfig":
        """The snapshot wins; anything missing or malformed falls back to current settings."""
        base = asdict(cls.from_settings(settings))
        for field in fields(cls):
            value = (snapshot or {}).get(field.name)
            if isinstance(value, bool) or not isinstance(value, int | float):
                continue
            base[field.name] = field.type(value) if field.type in (int, float) else value
        return cls(**base)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)
