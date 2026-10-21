"""The visual embedding contract: providers turn validated pixels or a short text into vectors.

A ``VisualEmbeddingProvider`` maps images (and video frames) and natural-language text into
one shared vector space, so "rocket launch" lands near a photo of one. Providers know nothing
about the database, storage or users:

- ``embed_images`` takes **decoded, canonical RGB images** (``images.canonical_rgb``: upright,
  transparency composited, bounded size) — never a path, a URL or user-supplied bytes — and
  returns one unit vector per image, in order;
- ``embed_text`` takes an already length-bounded query and returns one unit vector.

Every vector leaves a provider through ``vectors.to_unit`` (exact dimension, finite, non-zero,
unit length). ``identity`` names the model; it is fixed per provider build and never derived
from user input, and vectors of different identities are never compared.

Failure semantics are explicit, so "the model is not installed" never looks like "nothing
matched":

- ``EmbeddingUnavailable`` — the provider cannot run here (model files missing or not the
  pinned files, runtime missing). Indexing fails with a clear, retryable state; search falls
  back to names, descriptions and tags.
- ``EmbeddingFailure`` — the model ran but failed or produced an invalid vector.

Providers are created lazily and cached per process (``registry``): importing this module,
starting FastAPI or starting the Celery app never loads a model.
"""

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

import numpy as np
from PIL import Image

from app.services.semantic.state import EmbeddingIdentity


class EmbeddingUnavailable(Exception):
    """The embedding model cannot run on this server. ``message`` is safe to show."""

    code = "model_unavailable"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class EmbeddingFailure(Exception):
    """The model failed on an input or returned an invalid vector. ``message`` is safe."""

    code = "embedding_failed"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@runtime_checkable
class VisualEmbeddingProvider(Protocol):
    identity: EmbeddingIdentity
    batch_size: int

    def embed_images(self, images: Sequence[Image.Image]) -> list[np.ndarray]: ...

    def embed_text(self, text: str) -> np.ndarray: ...


def embed_image(provider: VisualEmbeddingProvider, image: Image.Image) -> np.ndarray:
    return provider.embed_images([image])[0]
