"""Embedding providers for the policy index (SPEC §3.2).

`local` runs BAAI/bge-small-en-v1.5 through fastembed (ONNX, no PyTorch). `voyage` calls Voyage's
API (voyage-4-lite); switching provider means rebuilding the committed index with `make index`.
Chunk token counts always use the bge tokenizer, so the Chunk list doesn't depend on the provider.
"""

from __future__ import annotations

from functools import cached_property
from typing import TYPE_CHECKING, Protocol

import httpx
import numpy as np

if TYPE_CHECKING:
    from fastembed import TextEmbedding

    from app.config import Settings

LOCAL_MODEL = "BAAI/bge-small-en-v1.5"
VOYAGE_MODEL = "voyage-4-lite"


class Embedder(Protocol):
    model_name: str

    def embed_passages(self, texts: list[str]) -> np.ndarray: ...
    def embed_query(self, text: str) -> np.ndarray: ...
    def count_tokens(self, text: str) -> int: ...


class LocalEmbedder:
    model_name = LOCAL_MODEL

    @cached_property
    def _model(self) -> TextEmbedding:
        from fastembed import TextEmbedding

        return TextEmbedding(LOCAL_MODEL)

    def embed_passages(self, texts: list[str]) -> np.ndarray:
        return np.stack(list(self._model.embed(texts))).astype(np.float32)

    def embed_query(self, text: str) -> np.ndarray:
        # query_embed adds bge's retrieval instruction prefix
        return np.asarray(next(iter(self._model.query_embed([text]))), dtype=np.float32)

    def count_tokens(self, text: str) -> int:
        return len(self._model.model.tokenizer.encode(text, add_special_tokens=False).ids)  # type: ignore[attr-defined]


class VoyageEmbedder(LocalEmbedder):
    model_name = f"voyage/{VOYAGE_MODEL}"

    def __init__(self, api_key: str):
        self._key = api_key

    def _embed(self, texts: list[str], input_type: str) -> np.ndarray:
        r = httpx.post(
            "https://api.voyageai.com/v1/embeddings",
            headers={"Authorization": f"Bearer {self._key}"},
            json={"input": texts, "model": VOYAGE_MODEL, "input_type": input_type},
            timeout=30,
        )
        r.raise_for_status()
        vecs = np.array([d["embedding"] for d in r.json()["data"]], dtype=np.float32)
        return vecs / np.linalg.norm(vecs, axis=1, keepdims=True)

    def embed_passages(self, texts: list[str]) -> np.ndarray:
        return self._embed(texts, "document")

    def embed_query(self, text: str) -> np.ndarray:
        return self._embed([text], "query")[0]


def make_embedder(settings: Settings) -> Embedder:
    if settings.embeddings_provider == "voyage":
        if not settings.voyage_api_key:
            raise RuntimeError("EMBEDDINGS_PROVIDER=voyage needs VOYAGE_API_KEY")
        return VoyageEmbedder(settings.voyage_api_key.get_secret_value())
    return LocalEmbedder()
