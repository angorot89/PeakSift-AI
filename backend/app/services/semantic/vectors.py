"""Embedding vectors: the one validation every vector passes before it is stored or compared.

A provider's raw output is untrusted until ``to_unit`` has checked it: one dimension of exactly
the expected length, every value finite, a norm clearly above zero. It is then scaled to unit
length in float32, so cosine similarity is a plain dot product and behaves the same everywhere
(the database's cosine distance agrees: ``1 - distance``).
"""

import math
from collections.abc import Sequence

import numpy as np

MIN_NORM = 1e-6


class InvalidVector(ValueError):
    """A vector that must not be stored or compared. The message names the problem only."""


def to_unit(values: Sequence[float] | np.ndarray, dimensions: int) -> np.ndarray:
    try:
        vector = np.asarray(values, dtype=np.float64)
    except (TypeError, ValueError):
        raise InvalidVector("The embedding is not numeric") from None
    if vector.ndim != 1 or vector.shape[0] != dimensions:
        raise InvalidVector("The embedding has the wrong dimension")
    if not np.all(np.isfinite(vector)):
        raise InvalidVector("The embedding contains non-finite values")
    norm = float(np.linalg.norm(vector))
    if not math.isfinite(norm) or norm < MIN_NORM:
        raise InvalidVector("The embedding has no direction (zero norm)")
    return (vector / norm).astype(np.float32)


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity of two unit vectors, in [-1, 1]."""
    return float(np.clip(np.dot(a.astype(np.float64), b.astype(np.float64)), -1.0, 1.0))
