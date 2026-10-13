"""Detection contract and the YuNet provider, with a fake ONNX session (no model download).

An opt-in check runs the real model: PEAKSIFT_REAL_DETECTOR=1 with REFRAME_MODEL_PATH set and
REFRAME_TEST_FACE_IMAGE pointing at a local photo of a face (nothing is committed or fetched).
"""

import hashlib
import math
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from app.core.config import Settings, get_settings
from app.services.reframe.detection import (
    DetectionType,
    DetectorFailure,
    DetectorUnavailable,
    get_detector,
    normalize_detection,
    reset_detector_cache,
    strongest,
)
from app.services.reframe.sampling import SampledFrame
from app.services.reframe.yunet import INPUT_SIZE, MODEL_SHA256, YuNetFaceDetector, verify_model


def norm(**kw):
    base = {
        "timestamp": 1.0,
        "detection_type": DetectionType.FACE,
        "confidence": 0.9,
        "x": 0.4,
        "y": 0.2,
        "width": 0.1,
        "height": 0.2,
    }
    return normalize_detection(**{**base, **kw})


# --- normalization -----


def test_valid_detection_is_kept_as_plain_floats():
    d = norm(x=np.float64(0.4))
    assert d is not None and type(d.box.x) is float and d.box.center_x == pytest.approx(0.45)
    assert d.box.center_y == pytest.approx(0.3) and d.box.area == pytest.approx(0.02)


@pytest.mark.parametrize(
    "bad",
    [
        {"x": math.nan},
        {"width": math.inf},
        {"confidence": -0.1},
        {"confidence": 1.2},
        {"timestamp": -1},
        {"width": 0},
        {"height": -0.1},
        {"width": 2.0},
        {"x": 1.5},  # entirely outside
        {"x": -0.95, "width": 1.0, "y": 0.0, "height": 0.1},  # 5% visible
        {"x": 0.98, "width": 0.1},  # 20% visible: mostly outside
    ],
)
def test_absurd_or_unusable_detections_are_rejected(bad):
    assert norm(**bad) is None


def test_face_cut_by_the_frame_edge_is_kept_and_clamped():
    d = norm(x=0.93, width=0.1)  # 70% visible
    assert (
        d is not None
        and d.box.x == pytest.approx(0.93)
        and d.box.x + d.box.width == pytest.approx(1.0)
    )
    d = norm(x=-0.02, y=-0.01)
    assert d is not None and d.box.x == 0 and d.box.y == 0


def test_strongest_is_deterministic_and_bounded():
    a, b, c = norm(confidence=0.9, x=0.5), norm(confidence=0.9, x=0.1), norm(confidence=0.95, x=0.7)
    assert strongest([a, b, c]) == [c, b, a]
    assert len(strongest([a] * 40)) == 32


# --- YuNet decoding with a fake session -----


class FakeOutput:
    def __init__(self, name):
        self.name = name


class FakeSession:
    """Mimics onnxruntime: returns YuNet-shaped outputs with faces placed in chosen cells."""

    def __init__(self, faces=(), raise_on_run=False):
        self.faces = faces  # (stride, row, col, score, offset_x, offset_y, log_w, log_h)
        self.raise_on_run = raise_on_run
        self.blobs = []
        names = [f"{k}_{s}" for k in ("cls", "obj", "bbox", "kps") for s in (8, 16, 32)]
        self._outputs = [FakeOutput(n) for n in names]

    def get_inputs(self):
        return [FakeOutput("input")]

    def get_outputs(self):
        return self._outputs

    def run(self, _names, feeds):
        if self.raise_on_run:
            raise RuntimeError("onnx kernel exploded at /opt/secret/path")
        self.blobs.append(feeds["input"])
        result = []
        for output in self._outputs:
            kind, stride = output.name.split("_")
            stride = int(stride)
            cells = (INPUT_SIZE // stride) ** 2
            width = {"cls": 1, "obj": 1, "bbox": 4, "kps": 10}[kind]
            array = np.zeros((1, cells, width), dtype=np.float32)
            if kind == "bbox":
                array[..., 2:] = -5
            for face in self.faces:
                if face[0] != stride:
                    continue
                index = face[1] * (INPUT_SIZE // stride) + face[2]
                if kind in ("cls", "obj"):
                    array[0, index, 0] = face[3]
                elif kind == "bbox":
                    array[0, index] = face[4:8]
            result.append(array)
        return result


def frame(width=640, height=360, rgb=None, t=2.5):
    return SampledFrame(0, t, width, height, rgb or bytes(width * height * 3))


def detector(session, **kw):
    return YuNetFaceDetector("unused", 0.5, session_factory=lambda _p: session, verify=False, **kw)


def test_decodes_a_face_into_normalized_frame_coordinates():
    # stride 16, cell (row 10, col 25): centre ((25+0.5)·16, (10+0.5)·16) = (408, 168),
    # size exp(ln 3)·16 = 48 × exp(ln 4)·16 = 64 px in a 640 × 360 frame.
    session = FakeSession([(16, 10, 25, 0.9, 0.5, 0.5, math.log(3), math.log(4))])
    (d,) = detector(session).detect(frame())
    assert d.timestamp == 2.5 and d.detection_type == "face" and d.confidence == pytest.approx(0.9)
    assert d.box.center_x == pytest.approx(408 / 640) and d.box.center_y == pytest.approx(168 / 360)
    assert d.box.width == pytest.approx(48 / 640) and d.box.height == pytest.approx(64 / 360)


def test_score_threshold_and_non_maximum_suppression():
    session = FakeSession(
        [
            (16, 10, 25, 0.9, 0.5, 0.5, math.log(3), math.log(4)),
            (16, 10, 26, 0.8, 0.0, 0.5, math.log(3), math.log(4)),  # same face, one cell over
            (8, 5, 10, 0.95, 0.5, 0.5, math.log(2), math.log(2)),  # a second, separate face
            (32, 2, 2, 0.3, 0.5, 0.5, 0.0, 0.0),  # below the 0.5 threshold
        ]
    )
    found = detector(session).detect(frame())
    assert [round(d.confidence, 2) for d in found] == [0.95, 0.9]


def test_portrait_frames_are_letterboxed_and_mapped_back():
    # A 360 × 640 frame fits as is; the face at canvas (180, 320) is the frame centre.
    session = FakeSession([(32, 9, 5, 0.9, 0.625, 0.0, math.log(2), math.log(2))])
    (d,) = detector(session).detect(frame(360, 640))
    assert d.box.center_x == pytest.approx(0.5) and d.box.center_y == pytest.approx(0.45)


def test_oversized_frames_are_scaled_into_the_input():
    session = FakeSession([(32, 10, 10, 0.9, 0.0, 0.0, math.log(2), math.log(2))])
    (d,) = detector(session).detect(frame(640, 1138))  # scaled to 360 × 640
    blob = session.blobs[0]
    assert blob.shape == (1, 3, INPUT_SIZE, INPUT_SIZE) and blob.dtype == np.float32
    assert d.box.center_x == pytest.approx(320 / 360, abs=1e-3)


def test_input_is_bgr_in_0_255():
    rgb = bytes([200, 100, 50]) * (640 * 360)
    session = FakeSession()
    detector(session).detect(frame(rgb=rgb))
    blob = session.blobs[0][0]
    assert blob[0, 0, 0] == 50 and blob[1, 0, 0] == 100 and blob[2, 0, 0] == 200
    assert blob[:, 400, 0].sum() == 0  # padding below the 360-row frame


def test_no_face_is_an_empty_result_not_an_error():
    assert detector(FakeSession()).detect(frame()) == []


def test_malformed_sizes_are_ignored():
    session = FakeSession(
        [(16, 10, 25, 0.9, 0.5, 0.5, 50.0, 50.0), (16, 3, 3, 0.9, 0.5, 0.5, math.nan, 0.0)]
    )
    assert detector(session).detect(frame()) == []


def test_runtime_errors_become_safe_detector_failures():
    with pytest.raises(DetectorFailure) as info:
        detector(FakeSession(raise_on_run=True)).detect(frame())
    assert "/opt" not in info.value.message and info.value.code == "detector_failed"


def test_session_start_failure_is_unavailable_not_no_face():
    def broken(_path):
        raise RuntimeError("cannot open /secret/model.onnx")

    d = YuNetFaceDetector("unused", 0.5, session_factory=broken, verify=False)
    with pytest.raises(DetectorUnavailable) as info:
        d.detect(frame())
    assert "secret" not in info.value.message


def test_session_is_created_lazily_once():
    created = []

    def factory(path):
        created.append(path)
        return FakeSession()

    d = YuNetFaceDetector("unused", 0.5, session_factory=factory, verify=False)
    assert created == []
    d.detect(frame())
    d.detect(frame())
    assert created == ["unused"]


# --- model file integrity -----


def test_missing_or_tampered_model_is_refused(tmp_path: Path, caplog):
    with pytest.raises(DetectorUnavailable) as info:
        verify_model(tmp_path / "missing.onnx")
    # The stored/shown message is generic; the operator hint goes to the server log only.
    assert str(tmp_path) not in info.value.message
    assert ".onnx" not in info.value.message and "scripts/" not in info.value.message
    assert "fetch_reframe_model" in caplog.text
    tampered = tmp_path / "model.onnx"
    tampered.write_bytes(b"not the model")
    assert hashlib.sha256(tampered.read_bytes()).hexdigest() != MODEL_SHA256
    with pytest.raises(DetectorUnavailable):
        verify_model(tampered)


# --- factory -----


def settings(**overrides) -> Settings:
    return Settings(**{**get_settings().model_dump(), **overrides})


def test_unknown_detector_is_unavailable():
    reset_detector_cache()
    with pytest.raises(DetectorUnavailable):
        get_detector(settings(reframe_detector="mediapipe_face"))


def test_factory_reuses_one_instance_per_configuration():
    reset_detector_cache()
    try:
        a = get_detector(settings())
        b = get_detector(settings())
        c = get_detector(settings(reframe_min_detection_confidence=0.7))
        assert a is b and a is not c and isinstance(a, YuNetFaceDetector)
        assert a._session is None  # still nothing loaded until a frame is analysed
    finally:
        reset_detector_cache()


def test_importing_the_app_and_worker_loads_no_detector():
    code = (
        "import sys; import app.main; import app.workers.celery_app; "
        "import app.services.reframe.detection; "
        "print('onnxruntime' in sys.modules, 'app.services.reframe.yunet' in sys.modules)"
    )
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])}
    out = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
        check=True,
    )
    assert out.stdout.strip().endswith("False"), out.stdout  # the YuNet module is not even imported


# --- opt-in real model check -----


@pytest.mark.skipif(
    not (os.environ.get("PEAKSIFT_REAL_DETECTOR") and os.environ.get("REFRAME_TEST_FACE_IMAGE")),
    reason="set PEAKSIFT_REAL_DETECTOR=1 and REFRAME_TEST_FACE_IMAGE to run the real detector",
)
def test_real_yunet_finds_the_face_in_a_local_photo():
    s = get_settings()
    raw = subprocess.run(
        [
            s.ffmpeg_path,
            "-v",
            "error",
            "-i",
            os.environ["REFRAME_TEST_FACE_IMAGE"],
            "-vf",
            "scale=640:360:force_original_aspect_ratio=decrease,pad=640:360,format=rgb24",
            "-f",
            "rawvideo",
            "-",
        ],
        capture_output=True,
        check=True,
        timeout=60,
    ).stdout
    reset_detector_cache()
    found = get_detector(s).detect(SampledFrame(0, 0.0, 640, 360, raw))
    assert found and found[0].confidence >= s.reframe_min_detection_confidence
