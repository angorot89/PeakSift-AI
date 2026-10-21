"""A deterministic stand-in embedding provider for tests, CI and non-production stacks.

It is **not** a vision model and never claims to be one: its identity says ``fake``, it is
refused in production, and its thresholds are its own. It exists so the whole semantic stack
(indexing, persistence, search, B-roll matching, Auto Edit) runs in CI without model weights.

Its "understanding" is a fixed palette: each concept has a colour, and an image embeds as the
concept whose colour is nearest to the image's average colour. Text embeds as the concepts its
words name (with a few synonyms). So a plain blue test image named ``IMG_0001.png`` with no tags
matches "bridge structure" — the same shape of evidence the real model gives on real photos —
and unrelated concepts stay far apart. A little deterministic, content-derived variation keeps
different images from producing identical vectors.
"""

import hashlib
import re
from collections.abc import Sequence

import numpy as np
from PIL import Image, ImageStat

from app.models import EMBEDDING_DIMENSIONS
from app.services.semantic.contract import EmbeddingFailure
from app.services.semantic.state import EmbeddingIdentity
from app.services.semantic.vectors import to_unit

FAKE_IDENTITY = EmbeddingIdentity(
    provider="fake",
    model="palette-concepts",
    model_version="1",
    embedding_version="semantic_v1",
    dimensions=EMBEDDING_DIMENSIONS,
)

# concept → (colour, words that name it)
CONCEPTS: dict[str, tuple[tuple[int, int, int], tuple[str, ...]]] = {
    "bridge": ((40, 90, 200), ("bridge", "bridges", "truss", "joint", "structure", "span")),
    "rocket": ((220, 60, 40), ("rocket", "launch", "spacecraft", "liftoff", "launchpad")),
    "kitchen": ((240, 200, 40), ("kitchen", "food", "cooking", "chef", "recipe", "meal")),
    "city": ((120, 120, 140), ("city", "skyline", "downtown", "skyscraper", "street")),
    "car": ((30, 160, 70), ("car", "driving", "road", "vehicle", "dashboard", "interior")),
    "microphone": ((150, 60, 170), ("microphone", "podcast", "studio", "mic", "recording")),
}
_WORD = re.compile(r"[a-z]+")


def _direction(seed: str) -> np.ndarray:
    digest = hashlib.sha256(seed.encode()).digest()
    rng = np.random.default_rng(int.from_bytes(digest[:8], "big"))
    return rng.standard_normal(EMBEDDING_DIMENSIONS)


_CONCEPT_VECTORS = {name: _direction(f"concept:{name}") for name in CONCEPTS}


class FakeEmbeddingProvider:
    identity = FAKE_IDENTITY
    batch_size = 8

    def __init__(self) -> None:
        self.image_calls = 0  # images embedded (tests check model reuse and frame bounds)
        self.text_calls = 0

    def _nearest_concept(self, image: Image.Image) -> str:
        mean = ImageStat.Stat(image).mean[:3]
        return min(
            CONCEPTS,
            key=lambda name: sum(
                (a - b) ** 2 for a, b in zip(CONCEPTS[name][0], mean, strict=True)
            ),
        )

    def embed_images(self, images: Sequence[Image.Image]) -> list[np.ndarray]:
        vectors = []
        for image in images:
            if image.mode != "RGB":
                raise EmbeddingFailure("The image was not prepared for embedding")
            self.image_calls += 1
            concept = self._nearest_concept(image)
            detail = hashlib.sha256(image.resize((8, 8)).tobytes()).hexdigest()
            raw = 4.0 * _CONCEPT_VECTORS[concept] + _direction(f"image:{detail}")
            vectors.append(to_unit(raw, EMBEDDING_DIMENSIONS))
        return vectors

    def embed_text(self, text: str) -> np.ndarray:
        self.text_calls += 1
        words = set(_WORD.findall(text.lower()))
        raw = _direction(f"text:{text.lower().strip()}")
        for name, (_, names) in CONCEPTS.items():
            if words & set(names):
                raw = raw + 4.0 * _CONCEPT_VECTORS[name]
        return to_unit(raw, EMBEDDING_DIMENSIONS)
