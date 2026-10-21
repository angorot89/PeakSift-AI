"""Local visual embeddings with OpenAI CLIP ViT-B/32 on onnxruntime (CPU).

Why this model (see docs/semantic-assets.md for the comparison):

- **Licensing:** OpenAI's CLIP weights are MIT; the ONNX exports used here are Qdrant's
  (published for fastembed, MIT). onnxruntime (MIT) and Hugging Face ``tokenizers`` (Apache-2.0)
  already ship with PeakSift through faster-whisper, so no deep-learning framework (PyTorch,
  TensorFlow, OpenCLIP's training stack) is added.
- **Compatibility:** CPU-only, the same wheels on Linux x86-64/arm64 and Apple silicon; the
  architecture is OpenCLIP's ``ViT-B-32`` with OpenAI's weights, so the vectors are the
  well-documented CLIP joint image–text space (512 dimensions).
- **Cost:** about 350 MB for the image encoder and 254 MB for the text encoder (fp32). Workers
  load both; the API loads only the text encoder, and only when a search actually needs it.

The model files are never committed or downloaded automatically. ``scripts/fetch_semantic_model.py``
fetches them from pinned repository revisions and verifies the pinned size and sha256; this
module refuses any other file. Sessions are created on first use and reused by the process,
with fixed threads and sequential execution so a given machine always produces the same vector.

Preprocessing follows the model's own ``CLIPImageProcessor`` configuration: shortest side to
224 px (bicubic), centre crop 224 × 224, scale to [0, 1], normalize with CLIP's mean and
standard deviation. Text is lower-cased and byte-pair encoded by the model's tokenizer,
truncated to CLIP's 77-token context.
"""

import hashlib
import logging
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from app.core.config import Settings
from app.models import EMBEDDING_DIMENSIONS
from app.services.semantic.contract import EmbeddingFailure, EmbeddingUnavailable
from app.services.semantic.state import EmbeddingIdentity
from app.services.semantic.vectors import InvalidVector, to_unit

logger = logging.getLogger(__name__)

PROVIDER_NAME = "clip_onnx"
MODEL_NAME = "openai-clip-vit-b-32"
# The pinned export revisions (vision, text). A different file is a different model version.
VISION_REVISION = "e0c24ed0fa57fa3e4f97f30de74c51d944036ace"
TEXT_REVISION = "48ca1db27cb4063eb311ec2aa7f087a808112876"
MODEL_VERSION = f"qdrant-onnx-{VISION_REVISION[:7]}-{TEXT_REVISION[:7]}"
# PeakSift's representation version: canonical pixels (upright, transparency on neutral grey)
# + the CLIP preprocessing below. Changing either makes existing vectors stale.
EMBEDDING_VERSION = "semantic_v1"

CLIP_IDENTITY = EmbeddingIdentity(
    provider=PROVIDER_NAME,
    model=MODEL_NAME,
    model_version=MODEL_VERSION,
    embedding_version=EMBEDDING_VERSION,
    dimensions=EMBEDDING_DIMENSIONS,
)

IMAGE_SIZE = 224
IMAGE_MEAN = np.array([0.48145466, 0.4578275, 0.40821073], dtype=np.float32)
IMAGE_STD = np.array([0.26862954, 0.26130258, 0.27577711], dtype=np.float32)
CONTEXT_LENGTH = 77
END_TOKEN = "<|endoftext|>"


@dataclass(frozen=True)
class PinnedFile:
    url: str
    size: int
    sha256: str


_HF = "https://huggingface.co"
MODEL_FILES: dict[str, PinnedFile] = {
    "vision.onnx": PinnedFile(
        f"{_HF}/Qdrant/clip-ViT-B-32-vision/resolve/{VISION_REVISION}/model.onnx",
        351_686_194,
        "c68d3d9a200ddd2a8c8a5510b576d4c94d1ae383bf8b36dd8c084f94e1fb4d63",
    ),
    "text.onnx": PinnedFile(
        f"{_HF}/Qdrant/clip-ViT-B-32-text/resolve/{TEXT_REVISION}/model.onnx",
        254_102_519,
        "4dbe762b11e36488304471e439cde89da053ad7acaddbf9e096745d142ec8d8b",
    ),
    "tokenizer.json": PinnedFile(
        f"{_HF}/Qdrant/clip-ViT-B-32-text/resolve/{TEXT_REVISION}/tokenizer.json",
        2_224_147,
        "b68d571997a1f81bf521fb73806740ddb91e4ed6666cb6e996c066bb289cf55b",
    ),
}

SessionFactory = Callable[[str, int], Any]
TokenizerFactory = Callable[[str], Any]


def file_matches(path: Path, pinned: PinnedFile) -> bool:
    if not path.is_file() or path.stat().st_size != pinned.size:
        return False
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest() == pinned.sha256


def verify_file(directory: Path, name: str) -> Path:
    """The file must be the pinned one. Raises EmbeddingUnavailable (no path in the message)."""
    path = directory / name
    if not path.is_file():
        # The operator hint goes to the server log; the stored/shown message stays generic.
        logger.warning("Semantic model file missing; run scripts/fetch_semantic_model.py")
        raise EmbeddingUnavailable("The visual search model is not installed on this server")
    if not file_matches(path, MODEL_FILES[name]):
        raise EmbeddingUnavailable("The visual search model file is not the expected version")
    return path


def _default_session(model_path: str, threads: int) -> Any:
    try:
        import onnxruntime as ort
    except ImportError:  # pragma: no cover - onnxruntime ships with faster-whisper
        raise EmbeddingUnavailable("The visual search runtime is not installed") from None
    options = ort.SessionOptions()
    options.intra_op_num_threads = threads  # a background job; leave CPU for the API and FFmpeg
    options.inter_op_num_threads = 1
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    options.log_severity_level = 3
    return ort.InferenceSession(
        model_path, sess_options=options, providers=["CPUExecutionProvider"]
    )


def _default_tokenizer(path: str) -> Any:
    try:
        from tokenizers import Tokenizer
    except ImportError:  # pragma: no cover - tokenizers ships with faster-whisper
        raise EmbeddingUnavailable("The visual search runtime is not installed") from None
    return Tokenizer.from_file(path)


def preprocess(images: Sequence[Image.Image]) -> np.ndarray:
    """Canonical RGB images → a (n, 3, 224, 224) float32 batch, as CLIPImageProcessor does."""
    batch = np.empty((len(images), 3, IMAGE_SIZE, IMAGE_SIZE), dtype=np.float32)
    for position, image in enumerate(images):
        if image.mode != "RGB":
            raise EmbeddingFailure("The image was not prepared for embedding")
        width, height = image.size
        scale = IMAGE_SIZE / min(width, height)
        size = (max(IMAGE_SIZE, round(width * scale)), max(IMAGE_SIZE, round(height * scale)))
        resized = image.resize(size, Image.Resampling.BICUBIC)
        left = (size[0] - IMAGE_SIZE) // 2
        top = (size[1] - IMAGE_SIZE) // 2
        crop = resized.crop((left, top, left + IMAGE_SIZE, top + IMAGE_SIZE))
        pixels = np.asarray(crop, dtype=np.float32) / 255.0
        batch[position] = ((pixels - IMAGE_MEAN) / IMAGE_STD).transpose(2, 0, 1)
    return batch


class ClipOnnxProvider:
    identity = CLIP_IDENTITY

    def __init__(
        self,
        model_dir: str,
        *,
        threads: int = 2,
        batch_size: int = 8,
        session_factory: SessionFactory | None = None,
        tokenizer_factory: TokenizerFactory | None = None,
        verify: bool = True,
    ) -> None:
        self.model_dir = Path(model_dir)
        self.threads = threads
        self.batch_size = batch_size
        self._session_factory = session_factory or _default_session
        self._tokenizer_factory = tokenizer_factory or _default_tokenizer
        self._verify = verify
        self._vision: Any = None
        self._text: Any = None
        self._tokenizer: Any = None
        self._lock = threading.Lock()

    @classmethod
    def from_settings(cls, settings: Settings) -> "ClipOnnxProvider":
        return cls(
            settings.semantic_model_dir,
            threads=settings.semantic_threads,
            batch_size=settings.semantic_batch_size,
        )

    def _path(self, name: str) -> str:
        path = verify_file(self.model_dir, name) if self._verify else self.model_dir / name
        return str(path)

    def _start(self, factory: Callable[[], Any]) -> Any:
        try:
            return factory()
        except EmbeddingUnavailable:
            raise
        except Exception:
            raise EmbeddingUnavailable("The visual search model could not be started") from None

    def _vision_session(self) -> Any:
        with self._lock:
            if self._vision is None:
                path = self._path("vision.onnx")
                self._vision = self._start(lambda: self._session_factory(path, self.threads))
            return self._vision

    def _text_session(self) -> tuple[Any, Any]:
        with self._lock:
            if self._text is None:
                tokenizer_path = self._path("tokenizer.json")
                text_path = self._path("text.onnx")
                tokenizer = self._start(lambda: self._tokenizer_factory(tokenizer_path))
                self._text = self._start(lambda: self._session_factory(text_path, self.threads))
                self._tokenizer = tokenizer
            return self._text, self._tokenizer

    def _vectors(self, output: Any, count: int) -> list[np.ndarray]:
        try:
            array = np.asarray(output, dtype=np.float32)
            if array.ndim != 2 or array.shape[0] != count:
                raise InvalidVector("unexpected output shape")
            return [to_unit(row, EMBEDDING_DIMENSIONS) for row in array]
        except InvalidVector:
            raise EmbeddingFailure("The visual search model returned an invalid result") from None

    def embed_images(self, images: Sequence[Image.Image]) -> list[np.ndarray]:
        if not images:
            return []
        session = self._vision_session()
        vectors: list[np.ndarray] = []
        for start in range(0, len(images), self.batch_size):
            chunk = images[start : start + self.batch_size]
            batch = preprocess(chunk)
            try:
                (output,) = session.run(["image_embeds"], {"pixel_values": batch})
            except Exception:
                raise EmbeddingFailure("The visual search model failed on an image") from None
            vectors.extend(self._vectors(output, len(chunk)))
        return vectors

    def tokenize(self, text: str) -> tuple[np.ndarray, np.ndarray]:
        """The tokenizer normalizes (NFC, whitespace, lower case) and adds the start and end
        tokens; the sequence is truncated to the context (still ending with the end token)
        and padded with the end token, as CLIPTokenizer does."""
        _, tokenizer = self._text_session()
        end = tokenizer.token_to_id(END_TOKEN)
        ids = list(tokenizer.encode(text).ids[:CONTEXT_LENGTH])
        if len(ids) == CONTEXT_LENGTH:
            ids[-1] = end
        mask = [1] * len(ids) + [0] * (CONTEXT_LENGTH - len(ids))
        ids = ids + [end] * (CONTEXT_LENGTH - len(ids))
        return np.array([ids], dtype=np.int64), np.array([mask], dtype=np.int64)

    def embed_text(self, text: str) -> np.ndarray:
        session, _ = self._text_session()
        input_ids, attention_mask = self.tokenize(text)
        try:
            (output,) = session.run(
                ["text_embeds"], {"input_ids": input_ids, "attention_mask": attention_mask}
            )
        except Exception:
            raise EmbeddingFailure("The visual search model failed on the query") from None
        return self._vectors(output, 1)[0]
