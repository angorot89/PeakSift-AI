"""Local face detection with YuNet (OpenCV Zoo, ``face_detection_yunet_2023mar``) on onnxruntime.

Why this detector (see docs/smart-reframing.md for the full comparison):

- **Licensing:** the weights are MIT (OpenCV Zoo, © 2020 Shiqi Yu); onnxruntime is MIT and is
  already a PeakSift dependency (faster-whisper's VAD), so no new package is added.
- **Wide shots:** YuNet takes the whole letterboxed 640 × 640 frame, so faces that are small in
  a landscape shot are still found. MediaPipe's BlazeFace short-range model resizes the frame
  to 128 × 128 and is designed for selfie-distance faces; MediaPipe 1.x also no longer bundles
  a face model, so it would need the same kind of model provisioning plus heavy extra
  dependencies (OpenCV contrib, matplotlib, sounddevice/PortAudio).

The model file is never committed or downloaded automatically. ``scripts/fetch_reframe_model.py``
fetches it from a pinned URL and verifies the pinned sha256; this module refuses any other
file. The ONNX session is created on the first frame and reused by the worker process.

Decoding follows OpenCV's ``FaceDetectorYN``: BGR input in 0..255, strides 8/16/32 with one
anchor per cell, score = sqrt(cls × obj), box centre = (cell + offset) × stride, size =
exp(log-size) × stride, then non-maximum suppression.
"""

import hashlib
import logging
import math
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

from app.core.config import Settings
from app.services.reframe.detection import (
    DetectionType,
    DetectorFailure,
    DetectorUnavailable,
    SubjectDetection,
    normalize_detection,
    strongest,
)
from app.services.reframe.sampling import SampledFrame

logger = logging.getLogger(__name__)

MODEL_NAME = "face_detection_yunet_2023mar"
MODEL_SHA256 = "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4"
INPUT_SIZE = 640
STRIDES = (8, 16, 32)
NMS_IOU = 0.3
MAX_CANDIDATES = 200

SessionFactory = Callable[[str], Any]


def _default_session(model_path: str) -> Any:
    try:
        import onnxruntime as ort
    except ImportError:  # pragma: no cover - onnxruntime ships with faster-whisper
        raise DetectorUnavailable("The face detector runtime is not installed") from None
    options = ort.SessionOptions()
    options.intra_op_num_threads = 2  # a background job; leave CPU for the API and FFmpeg
    options.log_severity_level = 3
    return ort.InferenceSession(
        model_path, sess_options=options, providers=["CPUExecutionProvider"]
    )


def verify_model(path: Path) -> None:
    """The model must be the pinned file. Raises DetectorUnavailable (no path in the message)."""
    if not path.is_file():
        # The operator hint goes to the server log; the stored/shown message stays generic.
        logger.warning("Face detector model missing; run scripts/fetch_reframe_model.py")
        raise DetectorUnavailable("The face detector model is not installed on the server")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != MODEL_SHA256:
        raise DetectorUnavailable("The face detector model file is not the expected version")


def _nms(boxes: np.ndarray, scores: np.ndarray, iou: float) -> list[int]:
    """Greedy non-maximum suppression on [x, y, w, h] boxes; deterministic order."""
    order = sorted(range(len(scores)), key=lambda i: (-float(scores[i]), i))
    keep: list[int] = []
    x1, y1 = boxes[:, 0], boxes[:, 1]
    x2, y2 = x1 + boxes[:, 2], y1 + boxes[:, 3]
    areas = boxes[:, 2] * boxes[:, 3]
    suppressed = np.zeros(len(scores), dtype=bool)
    for i in order:
        if suppressed[i]:
            continue
        keep.append(i)
        ix1, iy1 = np.maximum(x1[i], x1), np.maximum(y1[i], y1)
        ix2, iy2 = np.minimum(x2[i], x2), np.minimum(y2[i], y2)
        inter = np.clip(ix2 - ix1, 0, None) * np.clip(iy2 - iy1, 0, None)
        union = areas[i] + areas - inter
        overlap = np.divide(inter, union, out=np.zeros_like(inter), where=union > 0)
        suppressed |= overlap > iou
    return keep


class YuNetFaceDetector:
    name = "yunet_face"
    version = MODEL_NAME

    def __init__(
        self,
        model_path: str,
        min_confidence: float,
        *,
        session_factory: SessionFactory | None = None,
        verify: bool = True,
    ) -> None:
        self.model_path = model_path
        self.min_confidence = min_confidence
        self._session_factory = session_factory or _default_session
        self._verify = verify
        self._session: Any = None
        self._lock = threading.Lock()

    @classmethod
    def from_settings(cls, settings: Settings) -> "YuNetFaceDetector":
        return cls(settings.reframe_model_path, settings.reframe_min_detection_confidence)

    def _ensure_session(self) -> Any:
        with self._lock:
            if self._session is None:
                if self._verify:
                    verify_model(Path(self.model_path))
                try:
                    self._session = self._session_factory(self.model_path)
                except DetectorUnavailable:
                    raise
                except Exception:
                    raise DetectorUnavailable("The face detector could not be started") from None
            return self._session

    # --- preprocessing ------------------------------------------------------------------

    @staticmethod
    def _letterbox(frame: SampledFrame) -> tuple[np.ndarray, int, int]:
        """BGR float32 blob (1, 3, 640, 640) with the frame top-left; returns its scaled size."""
        image = np.frombuffer(frame.rgb, dtype=np.uint8).reshape(frame.height, frame.width, 3)
        scale = min(1.0, INPUT_SIZE / frame.width, INPUT_SIZE / frame.height)
        width = max(1, min(INPUT_SIZE, round(frame.width * scale)))
        height = max(1, min(INPUT_SIZE, round(frame.height * scale)))
        if (width, height) != (frame.width, frame.height):
            # Nearest-neighbour downscale (only portrait/oversized frames reach this).
            ys = np.minimum((np.arange(height) / scale).astype(np.int64), frame.height - 1)
            xs = np.minimum((np.arange(width) / scale).astype(np.int64), frame.width - 1)
            image = image[ys[:, None], xs[None, :]]
        canvas = np.zeros((INPUT_SIZE, INPUT_SIZE, 3), dtype=np.float32)
        canvas[:height, :width] = image[:, :, ::-1]  # RGB → BGR
        return canvas.transpose(2, 0, 1)[None], width, height

    # --- inference + decoding ---------------------------------------------------------------

    def _decode(self, outputs: dict[str, np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
        boxes, scores = [], []
        for stride in STRIDES:
            cols = INPUT_SIZE // stride
            cls = np.clip(np.asarray(outputs[f"cls_{stride}"], dtype=np.float64).reshape(-1), 0, 1)
            obj = np.clip(np.asarray(outputs[f"obj_{stride}"], dtype=np.float64).reshape(-1), 0, 1)
            bbox = np.asarray(outputs[f"bbox_{stride}"], dtype=np.float64).reshape(-1, 4)
            score = np.sqrt(cls * obj)
            for i in np.nonzero(score >= self.min_confidence)[0]:
                row, col = divmod(int(i), cols)
                log_w, log_h = bbox[i, 2], bbox[i, 3]
                if not (math.isfinite(log_w) and math.isfinite(log_h)) or max(log_w, log_h) > 10:
                    continue  # exp would overflow: a malformed output, not a face
                w, h = math.exp(log_w) * stride, math.exp(log_h) * stride
                cx, cy = (col + bbox[i, 0]) * stride, (row + bbox[i, 1]) * stride
                boxes.append((cx - w / 2, cy - h / 2, w, h))
                scores.append(score[i])
        if not boxes:
            return np.zeros((0, 4)), np.zeros(0)
        return np.asarray(boxes, dtype=np.float64), np.asarray(scores, dtype=np.float64)

    def detect(self, frame: SampledFrame) -> list[SubjectDetection]:
        session = self._ensure_session()
        blob, width, height = self._letterbox(frame)
        try:
            names = [o.name for o in session.get_outputs()]
            outputs = dict(
                zip(names, session.run(None, {session.get_inputs()[0].name: blob}), strict=True)
            )
            boxes, scores = self._decode(outputs)
        except DetectorFailure:
            raise
        except Exception:
            raise DetectorFailure() from None
        if len(scores) > MAX_CANDIDATES:
            top = np.argsort(-scores, kind="stable")[:MAX_CANDIDATES]
            boxes, scores = boxes[top], scores[top]
        detections = []
        for i in _nms(boxes, scores, NMS_IOU) if len(scores) else []:
            x, y, w, h = boxes[i]
            detection = normalize_detection(
                timestamp=frame.timestamp,
                detection_type=DetectionType.FACE,
                confidence=float(scores[i]),
                x=x / width,
                y=y / height,
                width=w / width,
                height=h / height,
            )
            if detection is not None:
                detections.append(detection)
        return strongest(detections)
