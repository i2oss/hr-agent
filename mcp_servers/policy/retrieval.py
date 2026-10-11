"""Hybrid retrieval over the committed policy index (SPEC slice 3, step 4).

Vector top-20 (cosine) and FTS5 top-20 (bm25), both filtered by doc_ids, merged by reciprocal
rank fusion (constant 60); the top k are returned. RETRIEVAL_MODE=vector skips FTS5.
Evidence: if the top vector cosine is below the threshold, the result is empty with
evidence "none". Keyword hits never override that, because RRF scores are rank-based.
"""

from __future__ import annotations

import re
import sqlite3
import threading
from collections.abc import Callable, Hashable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypeVar

import numpy as np

from mcp_servers.common.models import Passage
from mcp_servers.policy.embeddings import Embedder

CANDIDATES = 20
RRF_K = 60

T = TypeVar("T", bound=Hashable)


class UnknownDocumentOrSection(LookupError):
    pass


@dataclass(frozen=True)
class SearchResult:
    passages: list[Passage]
    evidence: Literal["ok", "none"]
    top_cosine: float


def rrf[T: Hashable](rankings: Sequence[Sequence[T]], k: int, tie_key: Callable[[T], object]) -> list[tuple[T, float]]:
    scores: dict[T, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda kv: (-kv[1], tie_key(kv[0])))


def _section_key(section: str) -> tuple[int, ...]:
    return tuple(int(x) for x in section.split("."))


@dataclass(frozen=True)
class _Row:
    chunk_id: str
    doc_id: str
    title: str
    section: str
    section_heading: str
    text: str
    ord: int

    @property
    def sort_key(self) -> tuple[str, tuple[int, ...], int]:
        return (self.doc_id, _section_key(self.section), self.ord)


class PolicyIndex:
    def __init__(self, rows: list[_Row], vectors: np.ndarray, db: sqlite3.Connection, embedder: Embedder,
                 meta: dict[str, str]):
        self._rows = rows
        self._by_id = {r.chunk_id: r for r in rows}
        self._vectors = vectors
        self._db = db
        self._lock = threading.Lock()
        self._embedder = embedder
        self.corpus_hash = meta["corpus_hash"]
        self.embedding_model = meta["embedding_model"]
        self.chunk_count = len(rows)

    @classmethod
    def load(cls, path: Path, embedder: Embedder) -> PolicyIndex:
        # Copy the committed file into memory: read-only at runtime, safe to share across threads.
        disk = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        db = sqlite3.connect(":memory:", check_same_thread=False)
        disk.backup(db)
        disk.close()
        rows = [
            _Row(*r)
            for r in db.execute(
                "SELECT chunk_id, doc_id, title, section, section_heading, text, ord FROM chunks ORDER BY ord"
            )
        ]
        blobs = dict(db.execute("SELECT chunk_id, blob FROM vectors"))
        vectors = np.stack([np.frombuffer(blobs[r.chunk_id], dtype="<f4") for r in rows])
        meta = dict(db.execute("SELECT key, value FROM manifest"))
        return cls(rows, vectors, db, embedder, meta)

    def _passage(self, row: _Row, score: float) -> Passage:
        return Passage(doc_id=row.doc_id, title=row.title, section=row.section,
                       section_heading=row.section_heading, text=row.text, score=round(score, 4))

    def _fts(self, query: str, allowed: set[str] | None) -> list[str]:
        terms = re.findall(r"[A-Za-z0-9]+", query)
        if not terms:
            return []
        match = " OR ".join(f'"{t}"' for t in terms)
        with self._lock:  # one shared in-memory connection, searched from worker threads
            ids = [cid for (cid,) in self._db.execute(
                "SELECT chunk_id FROM chunks_fts WHERE chunks_fts MATCH ? ORDER BY bm25(chunks_fts), chunk_id",
                (match,),
            )]
        return [i for i in ids if allowed is None or i in allowed][:CANDIDATES]

    def search(self, query: str, *, k: int, mode: Literal["hybrid", "vector"], threshold: float,
               doc_ids: list[str] | None = None) -> SearchResult:
        mask = np.array([doc_ids is None or r.doc_id in doc_ids for r in self._rows])
        if not mask.any():
            return SearchResult([], "none", 0.0)
        cos = self._vectors @ self._embedder.embed_query(query)
        cos = np.where(mask, cos, -np.inf)
        order = sorted(np.flatnonzero(mask), key=lambda i: (-cos[i], self._rows[i].sort_key))[:CANDIDATES]
        top_cosine = float(cos[order[0]])
        if top_cosine < threshold:
            return SearchResult([], "none", top_cosine)

        vec_ids = [self._rows[i].chunk_id for i in order]
        if mode == "vector":
            ranked = [(cid, float(cos[i])) for cid, i in zip(vec_ids, order, strict=True)]
        else:
            allowed = {self._rows[i].chunk_id for i in np.flatnonzero(mask)}
            ranked = rrf([vec_ids, self._fts(query, allowed)], RRF_K, lambda cid: self._by_id[cid].sort_key)
        return SearchResult([self._passage(self._by_id[cid], s) for cid, s in ranked[:k]], "ok", top_cosine)

    def section(self, doc_id: str, section: str) -> list[Passage]:
        rows = [r for r in self._rows if r.doc_id == doc_id and
                (r.section == section or r.section.startswith(section + "."))]
        if not rows:
            raise UnknownDocumentOrSection(f"{doc_id} §{section}")
        return [self._passage(r, 1.0) for r in sorted(rows, key=lambda r: r.sort_key)]

    @property
    def doc_ids(self) -> list[str]:
        return sorted({r.doc_id for r in self._rows})
