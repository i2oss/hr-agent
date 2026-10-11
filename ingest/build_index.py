"""Build the committed policy index (SPEC slice 3, step 3). Run with `make index`.

Writes index/policy_index.sqlite (tables chunks, chunks_fts, vectors, manifest) and
index/manifest.json (hash per corpus file, CHUNKER_VERSION, embedding model, Chunk IDs with a
text hash each). CI re-parses and re-chunks to check the manifest, without re-embedding.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import replace
from pathlib import Path
from typing import Any

from ingest.chunker import CHUNKER_VERSION, Chunk, TokenCounter, chunk_document
from ingest.parse import corpus_files, parse_file
from mcp_servers.policy.embeddings import Embedder

ROOT = Path(__file__).resolve().parent.parent
INDEX_FILE = "policy_index.sqlite"
MANIFEST_FILE = "manifest.json"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def chunk_corpus(corpus_dir: Path, count_tokens: TokenCounter) -> list[Chunk]:
    chunks: list[Chunk] = []
    for path in corpus_files(corpus_dir):
        chunks.extend(chunk_document(parse_file(path), count_tokens))
    return [replace(c, ord=i) for i, c in enumerate(chunks)]  # ord is global across the corpus


def compute_manifest(corpus_dir: Path, count_tokens: TokenCounter, embedding_model: str) -> dict[str, Any]:
    files = {p.name: _sha256(p.read_bytes()) for p in corpus_files(corpus_dir)}
    corpus_hash = _sha256("".join(f"{k}:{v}\n" for k, v in sorted(files.items())).encode())
    chunks = chunk_corpus(corpus_dir, count_tokens)
    return {
        "chunker_version": CHUNKER_VERSION,
        "embedding_model": embedding_model,
        "corpus_hash": corpus_hash,
        "files": files,
        "chunks": [{"chunk_id": c.chunk_id, "text_sha256": _sha256(c.text.encode())} for c in chunks],
    }


def build_index(corpus_dir: Path, out_dir: Path, embedder: Embedder) -> dict[str, Any]:
    manifest = compute_manifest(corpus_dir, embedder.count_tokens, embedder.model_name)
    chunks = chunk_corpus(corpus_dir, embedder.count_tokens)
    vectors = embedder.embed_passages([c.embed_text for c in chunks])

    out_dir.mkdir(parents=True, exist_ok=True)
    db_path = out_dir / INDEX_FILE
    db_path.unlink(missing_ok=True)
    db = sqlite3.connect(db_path)
    db.executescript(
        """
        CREATE TABLE chunks(chunk_id TEXT PRIMARY KEY, doc_id TEXT, title TEXT, section TEXT,
                            section_heading TEXT, heading_path TEXT, text TEXT, ord INTEGER);
        CREATE VIRTUAL TABLE chunks_fts USING fts5(chunk_id UNINDEXED, heading_path, text);
        CREATE TABLE vectors(chunk_id TEXT PRIMARY KEY, dim INTEGER, blob BLOB);
        CREATE TABLE manifest(key TEXT PRIMARY KEY, value TEXT);
        """
    )
    for c, v in zip(chunks, vectors, strict=True):
        db.execute(
            "INSERT INTO chunks VALUES (?,?,?,?,?,?,?,?)",
            (c.chunk_id, c.doc_id, c.title, c.section, c.section_heading, c.heading_path, c.text, c.ord),
        )
        db.execute("INSERT INTO chunks_fts VALUES (?,?,?)", (c.chunk_id, c.heading_path, c.text))
        db.execute("INSERT INTO vectors VALUES (?,?,?)", (c.chunk_id, len(v), v.astype("<f4").tobytes()))
    for key in ("chunker_version", "embedding_model", "corpus_hash"):
        db.execute("INSERT INTO manifest VALUES (?,?)", (key, manifest[key]))
    db.execute("INSERT INTO manifest VALUES (?,?)", ("chunk_count", str(len(chunks))))
    db.commit()
    db.execute("VACUUM")
    db.close()
    (out_dir / MANIFEST_FILE).write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


if __name__ == "__main__":
    from app.config import get_settings
    from mcp_servers.policy.embeddings import make_embedder

    m = build_index(ROOT / "corpus", ROOT / "index", make_embedder(get_settings()))
    print(f"indexed {len(m['chunks'])} chunks from {len(m['files'])} files, corpus {m['corpus_hash'][:12]}")
