"""Vector math utilities for semantic search (Phase H5).

Pure-Python implementations of cosine similarity, dot product, L2 normalization
and top-k selection. Avoid numpy dependency so the framework stays lightweight.

All vectors are assumed to be lists of floats with matching dimensions.
Most callers pass **already-normalized** vectors (EmbeddingProvider guarantees
this), so `cosine_similarity` reduces to a dot product — we still handle the
general case for robustness.
"""

from __future__ import annotations

import heapq
import math
from typing import Iterable, Sequence, TypeVar

T = TypeVar("T")


def dot(a: Sequence[float], b: Sequence[float]) -> float:
    if len(a) != len(b):
        raise ValueError(f"dim mismatch: {len(a)} vs {len(b)}")
    return sum(x * y for x, y in zip(a, b))


def l2_norm(v: Sequence[float]) -> float:
    return math.sqrt(sum(x * x for x in v))


def normalize(v: Sequence[float]) -> list[float]:
    n = l2_norm(v)
    if n == 0:
        return list(v)
    return [x / n for x in v]


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity in [-1.0, 1.0]. Handles non-normalized inputs."""
    if len(a) != len(b):
        raise ValueError(f"dim mismatch: {len(a)} vs {len(b)}")
    na = l2_norm(a)
    nb = l2_norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return dot(a, b) / (na * nb)


def top_k(
    scored: Iterable[tuple[float, T]],
    k: int,
    *,
    min_score: float | None = None,
) -> list[tuple[float, T]]:
    """Return the k highest-scoring items, sorted by score descending.

    Args:
        scored: iterable of (score, item) pairs.
        k: max items to return (must be > 0).
        min_score: optional lower bound; items with score < min_score are discarded.
    """
    if k <= 0:
        return []

    if min_score is not None:
        filtered = [s for s in scored if s[0] >= min_score]
    else:
        filtered = list(scored)

    # heapq.nlargest uses the first element of each tuple as key by default.
    return heapq.nlargest(k, filtered, key=lambda s: s[0])
