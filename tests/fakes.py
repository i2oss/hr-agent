"""Test doubles shared across test modules."""

from __future__ import annotations

import hashlib
import re

import numpy as np

DIM = 128


class HashEmbedder:
    """Deterministic bag-of-words embedder: words hash into DIM buckets, vectors are unit length.
    Texts sharing words have high cosine; texts sharing none have cosine 0."""

    model_name = "test/hash-embedder"
    dim = DIM

    def _vec(self, text: str) -> np.ndarray:
        v = np.zeros(DIM, dtype=np.float32)
        for w in re.findall(r"[a-z0-9]+", text.lower()):
            v[int(hashlib.md5(w.encode()).hexdigest(), 16) % DIM] += 1.0
        n = np.linalg.norm(v)
        return v / n if n else v

    def embed_passages(self, texts: list[str]) -> np.ndarray:
        return np.stack([self._vec(t) for t in texts])

    def embed_query(self, text: str) -> np.ndarray:
        return self._vec(text)

    def count_tokens(self, text: str) -> int:
        return len(text.split())
