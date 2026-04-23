"""EmbeddingProvider — abstraction for text-embedding backends (Phase H5).

Mirrors the LLM provider pattern: an ABC for production + test implementations,
plus a small singleton helper so other modules can grab the active provider
without importing concrete classes.

## Available providers

- `HashEmbeddingProvider` — deterministic, pure-Python, no network. Used as
  the default/fallback; also ideal for unit tests where we need stable
  vectors without calling an external API.
- `OpenAIEmbeddingProvider` — uses the `openai` SDK (already in requirements)
  to call text-embedding-3-small / -large. Requires `OPENAI_API_KEY`.

## Design notes

- We keep dimensions configurable (default 256 for Hash provider) to balance
  discriminative power vs. storage overhead.
- All vectors are returned L2-normalized; this makes cosine similarity
  a plain dot product downstream.
- Failures gracefully degrade: if `embed` raises, the caller is expected
  to fall back to substring search.
"""

from __future__ import annotations

import hashlib
import logging
import math
import os
from abc import ABC, abstractmethod
from typing import Any, Iterable

logger = logging.getLogger(__name__)


# ───────────────────────────────────────────────────────────────────
# ABC
# ───────────────────────────────────────────────────────────────────


class EmbeddingError(RuntimeError):
    """Raised when an embedding call fails."""


class EmbeddingProvider(ABC):
    """Abstract embedding backend. Returns L2-normalized float vectors."""

    @property
    @abstractmethod
    def dim(self) -> int:
        """Dimensionality of returned vectors. Constant per provider."""
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable identifier for logs/metrics."""
        ...

    @abstractmethod
    def embed(self, text: str) -> list[float]:
        """Return an L2-normalized embedding vector for a single string."""
        ...

    def embed_many(self, texts: Iterable[str]) -> list[list[float]]:
        """Batch embed. Default implementation calls `embed` per item.

        Concrete providers should override when batch APIs are available.
        """
        return [self.embed(t) for t in texts]


# ───────────────────────────────────────────────────────────────────
# HashEmbeddingProvider — deterministic, offline, test-friendly
# ───────────────────────────────────────────────────────────────────


class HashEmbeddingProvider(EmbeddingProvider):
    """Deterministic embedding based on hashed token bag.

    Properties:
    - Zero dependencies, zero network calls.
    - Produces stable vectors: same text → same vector, across runs.
    - Semantically lightweight — two texts sharing tokens will be nearer.
    - Acceptable as a fallback and for CI / unit tests.

    Algorithm:
    1. Lowercase + split on whitespace/punctuation into tokens.
    2. For each token, hash → fold into a `dim`-dimensional accumulator.
    3. L2-normalize the result.
    """

    def __init__(self, dim: int = 256) -> None:
        if dim < 8:
            raise ValueError(f"dim must be >= 8, got {dim}")
        self._dim = dim

    @property
    def dim(self) -> int:
        return self._dim

    @property
    def name(self) -> str:
        return f"hash:{self._dim}"

    def embed(self, text: str) -> list[float]:
        vec = [0.0] * self._dim
        if not text:
            # Zero-length input → zero vector is problematic for cosine.
            # Return a canonical "neutral" unit vector instead.
            vec[0] = 1.0
            return vec

        tokens = _tokenize(text)
        if not tokens:
            vec[0] = 1.0
            return vec

        for tok in tokens:
            # Two independent hashes for index + sign — reduces collisions.
            h1 = hashlib.md5(tok.encode("utf-8")).digest()
            h2 = hashlib.md5(("s:" + tok).encode("utf-8")).digest()
            # First 4 bytes → index bucket.
            idx = int.from_bytes(h1[:4], "big") % self._dim
            # Next 4 bytes → signed weight in [-1, 1).
            sign_bits = int.from_bytes(h2[:4], "big")
            weight = 1.0 if (sign_bits & 1) else -1.0
            vec[idx] += weight

        # L2 normalize.
        norm = math.sqrt(sum(v * v for v in vec))
        if norm == 0:
            vec[0] = 1.0
            return vec
        return [v / norm for v in vec]


# ───────────────────────────────────────────────────────────────────
# OpenAIEmbeddingProvider — production
# ───────────────────────────────────────────────────────────────────


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """Embedding via OpenAI's `/v1/embeddings` endpoint.

    Reads `OPENAI_API_KEY` + optional `OPENAI_BASE_URL` from env.
    Model defaults to `text-embedding-3-small` (1536-dim, cheap).
    """

    def __init__(
        self,
        *,
        model: str = "text-embedding-3-small",
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> None:
        key = api_key or os.environ.get("OPENAI_API_KEY")
        if not key:
            raise EmbeddingError(
                "OPENAI_API_KEY not set; cannot construct OpenAIEmbeddingProvider"
            )
        try:
            from openai import OpenAI
        except ImportError as e:  # pragma: no cover
            raise EmbeddingError(
                "openai package not installed; pip install openai"
            ) from e

        # Read timeout from AI_TIMEOUT_SECONDS (shared with LLM settings), default 120s.
        try:
            timeout_s = float(os.environ.get("AI_TIMEOUT_SECONDS", "120"))
        except ValueError:
            timeout_s = 120.0
        self._client = OpenAI(
            api_key=key,
            base_url=base_url or os.environ.get("OPENAI_BASE_URL"),
            timeout=timeout_s,
        )
        self._model = model

        # Infer dim from a probe call lazily on first use.
        self._dim_cache: int | None = None

    @property
    def dim(self) -> int:
        if self._dim_cache is None:
            # Probe with a tiny call. Most 3-series models:
            # -small = 1536, -large = 3072.
            probe = self.embed("dim-probe")
            self._dim_cache = len(probe)
        return self._dim_cache

    @property
    def name(self) -> str:
        return f"openai:{self._model}"

    def embed(self, text: str) -> list[float]:
        return self.embed_many([text])[0]

    def embed_many(self, texts: Iterable[str]) -> list[list[float]]:
        inputs = list(texts)
        if not inputs:
            return []
        try:
            resp = self._client.embeddings.create(
                model=self._model,
                input=inputs,
            )
        except Exception as e:
            raise EmbeddingError(f"openai embeddings call failed: {e}") from e

        vectors: list[list[float]] = []
        for item in resp.data:
            v = list(item.embedding)
            # Normalize defensively — OpenAI already returns normalized
            # vectors for 3-series models, but we cannot assume it.
            norm = math.sqrt(sum(x * x for x in v))
            if norm > 0:
                v = [x / norm for x in v]
            vectors.append(v)
        return vectors


# ───────────────────────────────────────────────────────────────────
# Tokenization
# ───────────────────────────────────────────────────────────────────


def _tokenize(text: str) -> list[str]:
    """Lowercase + split on non-alphanumeric ASCII; keep CJK as single chars.

    CJK characters get their own token so hash-based embeddings
    discriminate between e.g. '混凝土' and '钢筋'.
    """
    out: list[str] = []
    buf: list[str] = []
    for ch in text.lower():
        cp = ord(ch)
        # CJK Unified Ideographs block: 0x4E00–0x9FFF (approx).
        if 0x4E00 <= cp <= 0x9FFF:
            if buf:
                out.append("".join(buf))
                buf = []
            out.append(ch)
        elif ch.isalnum():
            buf.append(ch)
        else:
            if buf:
                out.append("".join(buf))
                buf = []
    if buf:
        out.append("".join(buf))
    return out


# ───────────────────────────────────────────────────────────────────
# Module-level singleton accessor
# ───────────────────────────────────────────────────────────────────


_active_provider: EmbeddingProvider | None = None


def get_embedding_provider() -> EmbeddingProvider:
    """Return the active embedding provider.

    On first call, auto-detects: uses OpenAI if `OPENAI_API_KEY` is set
    (and `EMBEDDING_BACKEND != 'hash'`); otherwise falls back to Hash.
    """
    global _active_provider
    if _active_provider is not None:
        return _active_provider

    backend = os.environ.get("EMBEDDING_BACKEND", "").strip().lower()
    if backend == "hash":
        _active_provider = HashEmbeddingProvider()
        logger.info("Embedding provider (forced): %s", _active_provider.name)
        return _active_provider

    if backend in ("openai", ""):
        if os.environ.get("OPENAI_API_KEY"):
            try:
                _active_provider = OpenAIEmbeddingProvider()
                logger.info("Embedding provider: %s", _active_provider.name)
                return _active_provider
            except EmbeddingError as e:  # pragma: no cover
                logger.warning("OpenAI embedding unavailable (%s); using hash fallback", e)

    _active_provider = HashEmbeddingProvider()
    logger.info("Embedding provider (fallback): %s", _active_provider.name)
    return _active_provider


def set_embedding_provider(provider: EmbeddingProvider | None) -> None:
    """Override the active embedding provider. Pass None to reset to auto-detect."""
    global _active_provider
    _active_provider = provider


def reset_embedding_provider() -> None:
    """Reset the singleton so next get_embedding_provider() re-initializes."""
    set_embedding_provider(None)
