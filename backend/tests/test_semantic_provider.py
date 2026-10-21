"""The embedding provider contract: vector validation, canonical pixels, the CLIP ONNX provider
(on fake sessions: preprocessing, batching, lazy loading, pinned files, failures), the
registry, the deterministic fake provider and the opt-in real-model check."""

import hashlib
import io
import os
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from app.core.config import Settings, production_problems
from app.models import EMBEDDING_DIMENSIONS
from app.services.semantic import clip_onnx, registry
from app.services.semantic.clip_onnx import (
    CLIP_IDENTITY,
    IMAGE_MEAN,
    IMAGE_STD,
    ClipOnnxProvider,
    PinnedFile,
    file_matches,
    preprocess,
)
from app.services.semantic.contract import (
    EmbeddingFailure,
    EmbeddingUnavailable,
    VisualEmbeddingProvider,
    embed_image,
)
from app.services.semantic.fake import FAKE_IDENTITY, FakeEmbeddingProvider
from app.services.semantic.images import NEUTRAL_BACKGROUND, UnusableImage, canonical_rgb
from app.services.semantic.vectors import InvalidVector, cosine, to_unit

D = EMBEDDING_DIMENSIONS

# --- vectors ---------------------------------------------------------------------------------


def test_to_unit_normalizes_to_float32_unit_length():
    vector = to_unit([3.0, 4.0] + [0.0] * (D - 2), D)
    assert vector.dtype == np.float32 and vector.shape == (D,)
    assert vector[:2].tolist() == pytest.approx([0.6, 0.8])
    assert float(np.linalg.norm(vector)) == pytest.approx(1.0, abs=1e-6)


@pytest.mark.parametrize(
    "values",
    [
        [1.0] * (D - 1),
        [[1.0] * D],
        [float("nan")] + [1.0] * (D - 1),
        [float("-inf")] + [1.0] * (D - 1),
        [0.0] * D,
        [1e-9] * D,
        ["a"] * D,
        None,
    ],
    ids=["dimension", "2d", "nan", "inf", "zero", "tiny", "text", "none"],
)
def test_to_unit_refuses_invalid_vectors(values):
    with pytest.raises(InvalidVector):
        to_unit(values, D)


def test_cosine_is_deterministic_and_bounded():
    a = to_unit(np.arange(1, D + 1), D)
    b = to_unit(np.arange(D, 0, -1), D)
    assert cosine(a, a) == pytest.approx(1.0)
    assert cosine(a, -a) == pytest.approx(-1.0)
    assert cosine(a, b) == cosine(b, a) == cosine(a.copy(), b.copy())


# --- canonical pixels --------------------------------------------------------------------------


def _jpeg_with_orientation(size, orientation: int) -> Image.Image:
    image = Image.new("RGB", size, (200, 40, 40))
    exif = Image.Exif()
    exif[0x0112] = orientation
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", exif=exif)
    return Image.open(io.BytesIO(buffer.getvalue()))


def test_rotated_jpeg_is_embedded_upright():
    image = canonical_rgb(_jpeg_with_orientation((400, 200), 6))  # rotate 90°
    assert image.size == (200, 400) and image.mode == "RGB"


def test_transparency_is_composited_on_neutral_grey():
    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    image.paste((30, 200, 60, 255), (16, 16, 48, 48))
    out = canonical_rgb(image)
    assert out.mode == "RGB"
    assert out.getpixel((2, 2)) == NEUTRAL_BACKGROUND
    assert out.getpixel((32, 32)) == (30, 200, 60)
    # The same file always gives the same pixels.
    assert canonical_rgb(image).tobytes() == out.tobytes()


def test_palette_with_transparency_greyscale_16_bit_and_cmyk_become_rgb():
    palette = Image.new("P", (32, 32), 0)
    palette.putpalette([255, 0, 0, 0, 255, 0] + [0] * 762)
    palette.info["transparency"] = 0
    assert canonical_rgb(palette).getpixel((1, 1)) == NEUTRAL_BACKGROUND
    assert canonical_rgb(Image.new("L", (32, 32), 77)).getpixel((0, 0)) == (77, 77, 77)
    sixteen = canonical_rgb(Image.new("I;16", (32, 32), 65535))
    assert sixteen.mode == "RGB" and sixteen.getpixel((0, 0))[0] >= 250
    assert canonical_rgb(Image.new("CMYK", (32, 32), (0, 0, 0, 0))).mode == "RGB"


def test_large_images_are_bounded_and_tiny_ones_refused():
    out = canonical_rgb(Image.new("RGB", (4000, 1000)))
    assert out.size == (1024, 256)
    with pytest.raises(UnusableImage):
        canonical_rgb(Image.new("RGB", (4, 300)))


# --- CLIP preprocessing ------------------------------------------------------------------------


def test_preprocess_resizes_shortest_side_and_centre_crops():
    wide = Image.new("RGB", (800, 200), (255, 255, 255))
    wide.paste((0, 0, 0), (0, 0, 300, 200))  # black left part is outside the centre crop
    batch = preprocess([wide, Image.new("RGB", (224, 224), (0, 0, 0))])
    assert batch.shape == (2, 3, 224, 224) and batch.dtype == np.float32
    white = (1.0 - IMAGE_MEAN) / IMAGE_STD
    assert batch[0, :, 112, 112] == pytest.approx(white, abs=1e-4)
    assert batch[1, :, 0, 0] == pytest.approx(-IMAGE_MEAN / IMAGE_STD, abs=1e-4)


def test_preprocess_refuses_unprepared_images():
    with pytest.raises(EmbeddingFailure):
        preprocess([Image.new("RGBA", (64, 64))])


# --- the CLIP ONNX provider on fake sessions --------------------------------------------------


class FakeSession:
    def __init__(self, path: str, output=None, fail: bool = False) -> None:
        self.path = path
        self.calls: list[dict] = []
        self.output = output
        self.fail = fail

    def run(self, names, feeds):
        self.calls.append(feeds)
        if self.fail:
            raise RuntimeError("onnxruntime exploded at /secret/path")
        if self.output is not None:
            return [self.output(feeds)]
        batch = next(iter(feeds.values()))
        return [np.random.default_rng(len(self.calls)).standard_normal((batch.shape[0], D))]


class FakeEncoding:
    def __init__(self, ids):
        self.ids = ids


class FakeTokenizer:
    def encode(self, text):
        return FakeEncoding([49406] + [1000 + len(w) for w in text.split()] + [49407])

    def token_to_id(self, token):
        return 49407


def provider(sessions: list, **kwargs) -> ClipOnnxProvider:
    def factory(path: str, threads: int):
        session = FakeSession(path, **kwargs)
        sessions.append(session)
        return session

    return ClipOnnxProvider(
        "/models/clip",
        batch_size=3,
        session_factory=factory,
        tokenizer_factory=lambda path: FakeTokenizer(),
        verify=False,
    )


def test_construction_loads_nothing_and_each_encoder_loads_once_on_first_use():
    sessions: list[FakeSession] = []
    clip = provider(sessions)
    assert isinstance(clip, VisualEmbeddingProvider)
    assert sessions == []  # lazy: no model until something is embedded
    clip.embed_text("rocket launch")
    assert [Path(s.path).name for s in sessions] == ["text.onnx"]  # text only (the API's case)
    clip.embed_images([Image.new("RGB", (64, 64))])
    clip.embed_images([Image.new("RGB", (64, 64))])
    clip.embed_text("bridge")
    assert [Path(s.path).name for s in sessions] == ["text.onnx", "vision.onnx"]


def test_images_are_embedded_in_bounded_batches_as_unit_vectors():
    sessions: list[FakeSession] = []
    clip = provider(sessions)
    vectors = clip.embed_images([Image.new("RGB", (64, 64), (i, i, i)) for i in range(7)])
    assert len(vectors) == 7
    assert all(v.shape == (D,) and np.linalg.norm(v) == pytest.approx(1, abs=1e-5) for v in vectors)
    assert [call["pixel_values"].shape[0] for call in sessions[0].calls] == [3, 3, 1]
    assert clip.embed_images([]) == []
    assert embed_image(clip, Image.new("RGB", (64, 64))).shape == (D,)


def test_text_is_tokenized_to_the_clip_context():
    sessions: list[FakeSession] = []
    clip = provider(sessions)
    ids, mask = clip.tokenize("a rocket launch")
    assert ids.shape == mask.shape == (1, 77) and ids.dtype == np.int64
    assert ids[0, 0] == 49406 and ids[0, 4] == 49407 and mask[0].sum() == 5
    assert set(ids[0, 5:].tolist()) == {49407}  # padded with the end token
    long_ids, long_mask = clip.tokenize("word " * 200)
    assert long_mask[0].sum() == 77 and long_ids[0, -1] == 49407  # truncated, still terminated
    clip.embed_text("a rocket launch")
    assert set(sessions[0].calls[-1]) == {"input_ids", "attention_mask"}


@pytest.mark.parametrize(
    "output",
    [
        lambda feeds: np.full((1, D), np.nan),
        lambda feeds: np.zeros((1, D)),
        lambda feeds: np.ones((1, D - 1)),
        lambda feeds: np.ones((2, D)),
    ],
    ids=["nan", "zero", "dimension", "count"],
)
def test_invalid_model_output_is_a_failure_not_a_vector(output):
    clip = provider([], output=output)
    with pytest.raises(EmbeddingFailure) as error:
        clip.embed_text("bridge")
    assert "invalid" in error.value.message


def test_a_crashing_session_is_a_failure_without_internals():
    clip = provider([], fail=True)
    with pytest.raises(EmbeddingFailure) as error:
        clip.embed_images([Image.new("RGB", (64, 64))])
    assert "/secret" not in error.value.message and error.value.code == "embedding_failed"


def test_missing_or_unpinned_model_files_make_the_provider_unavailable(tmp_path, caplog):
    clip = ClipOnnxProvider(str(tmp_path), session_factory=lambda p, t: FakeSession(p))
    with pytest.raises(EmbeddingUnavailable) as missing:
        clip.embed_images([Image.new("RGB", (64, 64))])
    assert missing.value.code == "model_unavailable"
    assert str(tmp_path) not in missing.value.message
    assert "fetch_semantic_model" in caplog.text  # the operator hint is logged, not shown
    (tmp_path / "vision.onnx").write_bytes(b"not the model")
    with pytest.raises(EmbeddingUnavailable) as wrong:
        clip.embed_images([Image.new("RGB", (64, 64))])
    assert "expected version" in wrong.value.message


def test_a_session_that_cannot_start_is_unavailable(tmp_path):
    def broken(path, threads):
        raise RuntimeError(f"cannot mmap {path}")

    clip = ClipOnnxProvider(str(tmp_path), session_factory=broken, verify=False)
    with pytest.raises(EmbeddingUnavailable) as error:
        clip.embed_text("bridge")
    assert str(tmp_path) not in error.value.message


def test_file_matches_checks_size_and_sha256(tmp_path):
    path = tmp_path / "model.onnx"
    path.write_bytes(b"weights")
    digest = hashlib.sha256(b"weights").hexdigest()
    assert file_matches(path, PinnedFile("https://x", 7, digest))
    assert not file_matches(path, PinnedFile("https://x", 8, digest))
    assert not file_matches(path, PinnedFile("https://x", 7, "0" * 64))
    assert not file_matches(tmp_path / "absent", PinnedFile("https://x", 7, digest))


def test_pinned_files_and_identity_are_explicit():
    assert set(clip_onnx.MODEL_FILES) == {"vision.onnx", "text.onnx", "tokenizer.json"}
    for pinned in clip_onnx.MODEL_FILES.values():
        assert pinned.url.startswith("https://huggingface.co/Qdrant/")
        assert len(pinned.sha256) == 64 and pinned.size > 0
        assert "/resolve/main/" not in pinned.url  # pinned revisions, never a moving branch
    assert CLIP_IDENTITY.dimensions == D
    assert CLIP_IDENTITY.provider == "clip_onnx" and CLIP_IDENTITY.model_version


# --- registry ----------------------------------------------------------------------------------


@pytest.fixture
def clean_registry():
    registry.reset_providers()
    yield
    registry.reset_providers()


def test_registry_identity_needs_no_model(clean_registry):
    assert registry.configured_identity(Settings(semantic_provider="clip_onnx")) == CLIP_IDENTITY
    assert registry.configured_identity(Settings(semantic_provider="fake")) == FAKE_IDENTITY
    assert registry.configured_identity(Settings(semantic_provider="disabled")) is None
    with pytest.raises(EmbeddingUnavailable):
        registry.get_provider(Settings(semantic_provider="disabled"))


def test_registry_builds_one_provider_per_process(clean_registry):
    settings = Settings(semantic_provider="clip_onnx", semantic_model_dir="/nowhere")
    first = registry.get_provider(settings)
    assert first is registry.get_provider(settings)  # reused, not rebuilt per request
    assert isinstance(first, ClipOnnxProvider) and first._vision is None  # still not loaded
    fake = FakeEmbeddingProvider()
    registry.install_provider(Settings(semantic_provider="fake"), fake)
    assert registry.get_provider(Settings(semantic_provider="fake")) is fake


def test_importing_the_api_loads_no_model():
    import app.main  # noqa: F401

    loaded = [p for p in registry._providers.values() if getattr(p, "_vision", None) is not None]
    assert loaded == []


def test_production_refuses_the_fake_provider():
    problems = production_problems(Settings(semantic_provider="fake"))
    assert "SEMANTIC_PROVIDER must not be fake" in problems
    real = Settings(semantic_provider="clip_onnx")
    assert "SEMANTIC_PROVIDER must not be fake" not in production_problems(real)


# --- the deterministic fake --------------------------------------------------------------------


def test_fake_matches_content_not_names():
    fake = FakeEmbeddingProvider()
    blue, red = Image.new("RGB", (64, 64), (45, 95, 190)), Image.new("RGB", (64, 64), (215, 70, 45))
    bridge_image, rocket_image = fake.embed_images([blue, red])
    bridge = fake.embed_text("bridge structure")
    assert cosine(bridge, bridge_image) > 0.8
    assert cosine(bridge, rocket_image) < 0.3
    assert cosine(fake.embed_text("weather forecast"), bridge_image) < 0.3
    assert fake.embed_text("bridge structure").tolist() == bridge.tolist()  # deterministic
    assert fake.image_calls == 2 and fake.text_calls == 3
    with pytest.raises(EmbeddingFailure):
        fake.embed_images([Image.new("RGBA", (8, 8))])


# --- the real model (opt-in) -------------------------------------------------------------------


@pytest.mark.real_model
@pytest.mark.skipif(
    not os.environ.get("PEAKSIFT_REAL_SEMANTIC_MODEL_DIR"),
    reason="set PEAKSIFT_REAL_SEMANTIC_MODEL_DIR to an installed model directory to run",
)
def test_real_clip_model_ranks_drawn_concepts():
    clip = ClipOnnxProvider(os.environ["PEAKSIFT_REAL_SEMANTIC_MODEL_DIR"])
    sky = Image.new("RGB", (320, 240), (90, 150, 230))
    grass = Image.new("RGB", (320, 240), (40, 150, 50))
    sky_vector, grass_vector = clip.embed_images([sky, grass])
    blue = clip.embed_text("a plain blue background")
    green = clip.embed_text("a plain green background")
    assert cosine(blue, sky_vector) > cosine(blue, grass_vector)
    assert cosine(green, grass_vector) > cosine(green, sky_vector)
    # Same input, same vector (deterministic inference on one machine).
    assert clip.embed_images([sky])[0].tolist() == sky_vector.tolist()
