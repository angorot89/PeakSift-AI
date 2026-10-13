"""The subject-detection contract: providers turn a sampled frame into normalized detections.

Everything downstream (tracking, path planning, persistence) sees only ``SubjectDetection``:
a clip-local timestamp, a type, a confidence in ``[0, 1]`` and a box in normalized frame
coordinates (``x``/``y`` = top-left, fractions of the frame's width/height, ``y`` down). No
provider object, array or model handle leaves a provider module.

Failure semantics are explicit, because "the detector broke" must never look like "there
was nobody in the frame":

- ``DetectorUnavailable`` — the configured detector cannot run here (unknown name, model file
  missing or not the pinned file, runtime missing). The analysis fails with a clear code.
- ``DetectorFailure`` — the detector crashed on a frame. The analysis fails; it is retryable.
- an empty list — the detector ran and found no face. That is a valid result (centre fallback).

Providers are created lazily, on the first frame a worker analyses, and cached per process:
importing this module, starting FastAPI or starting the Celery app never loads a model.
"""

import math
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from app.core.config import Settings
from app.services.reframe.sampling import SampledFrame

# A face cut by the frame edge legitimately gets a box that extends past it; the visible part
# is kept (clamped to the frame) as long as enough of the box is inside. Boxes mostly outside
# the frame, or larger than the frame by a wide margin, are malformed and rejected.
MIN_VISIBLE_FRACTION = 0.3
MAX_BOX_SIZE = 1.5  # in frame widths/heights
MIN_BOX_FRACTION = 1e-4  # a box narrower/shorter than this (e.g. 0.06 px at 640 px) is noise
MAX_DETECTIONS_PER_FRAME = 32


class DetectionType(StrEnum):
    FACE = "face"


@dataclass(frozen=True)
class BoundingBox:
    x: float
    y: float
    width: float
    height: float

    @property
    def center_x(self) -> float:
        return self.x + self.width / 2

    @property
    def center_y(self) -> float:
        return self.y + self.height / 2

    @property
    def area(self) -> float:
        return self.width * self.height


@dataclass(frozen=True)
class SubjectDetection:
    timestamp: float
    detection_type: DetectionType
    confidence: float
    box: BoundingBox


class DetectorUnavailable(Exception):
    """The configured detector cannot run on this server. ``message`` is safe to show."""

    code = "detector_unavailable"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class DetectorFailure(Exception):
    """The detector raised while analysing a frame. ``message`` is safe to show."""

    code = "detector_failed"

    def __init__(self, message: str = "The face detector failed while analysing the clip") -> None:
        super().__init__(message)
        self.message = message


class SubjectDetectionProvider(Protocol):
    name: str
    version: str

    def detect(self, frame: SampledFrame) -> list[SubjectDetection]:
        """Detections in ``frame`` (possibly none). Raises DetectorFailure."""
        ...


def _finite(*values: float) -> bool:
    return all(isinstance(v, int | float) and math.isfinite(v) for v in values)


def normalize_detection(
    *,
    timestamp: float,
    detection_type: DetectionType,
    confidence: float,
    x: float,
    y: float,
    width: float,
    height: float,
) -> SubjectDetection | None:
    """Validate one normalized detection; ``None`` if it is not a usable box.

    Rejects NaN/infinity, confidences outside [0, 1], non-positive or absurd sizes, and boxes
    mostly outside the frame. A box cut by the frame edge is clamped to its visible part.
    """
    if not _finite(timestamp, confidence, x, y, width, height):
        return None
    timestamp, confidence = float(timestamp), float(confidence)
    x, y, width, height = float(x), float(y), float(width), float(height)
    if timestamp < 0 or not 0 <= confidence <= 1:
        return None
    if (
        width < MIN_BOX_FRACTION
        or height < MIN_BOX_FRACTION
        or width > MAX_BOX_SIZE
        or height > MAX_BOX_SIZE
    ):
        return None
    left, top = max(0.0, x), max(0.0, y)
    right, bottom = min(1.0, x + width), min(1.0, y + height)
    if right - left < MIN_BOX_FRACTION or bottom - top < MIN_BOX_FRACTION:
        return None  # no intersection with the frame
    if (right - left) * (bottom - top) < MIN_VISIBLE_FRACTION * width * height:
        return None
    return SubjectDetection(
        timestamp=float(timestamp),
        detection_type=detection_type,
        confidence=float(confidence),
        box=BoundingBox(x=left, y=top, width=right - left, height=bottom - top),
    )


def strongest(
    detections: Sequence[SubjectDetection], limit: int = MAX_DETECTIONS_PER_FRAME
) -> list[SubjectDetection]:
    """Highest-confidence first, bounded (deterministic tie-break by position)."""
    ordered = sorted(detections, key=lambda d: (-d.confidence, d.box.x, d.box.y))
    return ordered[:limit]


# --- factory: lazy, one instance per process ------------------------------------------------

ProviderFactory = Callable[[Settings], SubjectDetectionProvider]

_lock = threading.Lock()
_cache: dict[tuple[str, str, float], SubjectDetectionProvider] = {}


def _registry() -> dict[str, ProviderFactory]:
    # Imported here, not at module import, so nothing heavy loads until a worker needs it.
    from app.services.reframe.yunet import YuNetFaceDetector

    return {YuNetFaceDetector.name: YuNetFaceDetector.from_settings}


def get_detector(settings: Settings) -> SubjectDetectionProvider:
    """The configured detector, created on first use and reused by this worker process."""
    key = (
        settings.reframe_detector,
        settings.reframe_model_path,
        settings.reframe_min_detection_confidence,
    )
    with _lock:
        if key not in _cache:
            factory = _registry().get(settings.reframe_detector)
            if factory is None:
                raise DetectorUnavailable("The configured face detector is not supported")
            _cache[key] = factory(settings)
        return _cache[key]


def reset_detector_cache() -> None:
    """Tests only: forget cached providers."""
    with _lock:
        _cache.clear()
