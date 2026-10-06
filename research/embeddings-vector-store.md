# Embedding model and vector store for a ~512MB free-tier host

Ticket: [#5](https://github.com/i2oss/hr-agent/issues/5) · Researched 2026-10-06 · Assumes ~512MB RAM (host ticket #4 still open).

## The short answer

- **Embeddings:** `BAAI/bge-small-en-v1.5` run locally through **fastembed** (ONNX Runtime, no PyTorch).
- **Store:** **one SQLite file** holding chunks + metadata, an **FTS5** keyword index, and the vectors. Search vectors with plain numpy cosine similarity; merge with keyword hits (reciprocal rank fusion).
- **Index:** build it with a script (`scripts/build_index.py`) and **commit the SQLite file** to the repo. Deploys and cold starts never re-embed the corpus.
- **Fallback if RAM is tighter than expected:** swap to **Voyage `voyage-4-lite`** via API (200M free tokens) behind the same `embed()` function, set by env var. Rebuild the index when switching models.

This is the same pattern the sibling project (rag-portfolio SPEC) already chose, minus PyTorch.

## Why size matters here

The corpus is tiny: ~2,000 chunks × 384 numbers × 4 bytes ≈ **3 MB** of vectors. The vectors are not the problem. The problem is the *libraries* that load to make them:

| Option | What loads in RAM | Rough fit in 512MB |
|---|---|---|
| sentence-transformers + PyTorch | PyTorch runtime + model. Images ~800MB compressed; a typical sentence-BERT setup is cited at ~1.8GB | **Does not fit** |
| fastembed + bge-small-en-v1.5 | ONNX Runtime + a 67MB model file | **Fits**, leaves room for FastAPI + agent loop (estimate: low hundreds of MB total; measure in build) |
| Embedding API (Voyage, Gemini) | Only an HTTP client | **Fits easily**; adds a second key and a network hop per query |

## Embedding models compared

| Model (via fastembed) | File size | Dims | Notes |
|---|---|---|---|
| **BAAI/bge-small-en-v1.5** | 0.067 GB | 384 | Smallest; strong for its size; fastembed's default family |
| all-MiniLM-L6-v2 | 0.090 GB | 384 | Older, widely known; slightly weaker retrieval |
| snowflake-arctic-embed-xs / -s | 0.090 / 0.130 GB | 384 | Good alternatives if eval shows misses |
| BAAI/bge-base-en-v1.5 | 0.210 GB | 768 | Step up only if eval demands; tighter fit |
| nomic-embed-text-v1.5 | 0.520 GB | 768 | Too big for 512MB |

Free-tier APIs:

- **Voyage AI** (`voyage-4`, `voyage-4-lite`): first **200M tokens free** per account; then $0.06 / $0.02 per M tokens. The whole corpus is well under 1M tokens, so it stays free indefinitely.
- **Google Gemini Embedding**: free tier exists but rate limits are per-project and unpublished; free-tier data may be used by Google to improve products. Less predictable for a graded demo.

Quality: for a few hundred HR policy chunks, any of the small models is enough, especially with keyword (FTS5) search alongside. The eval set will show if a step up is needed.

## Vector stores compared

| | Chroma | FAISS | sqlite-vec | **SQLite + numpy** |
|---|---|---|---|---|
| RAM | Chroma's own docs say <2GB not recommended | Small | Small | Smallest (3MB of vectors) |
| Persistence | Folder of files | Separate index file + your own metadata store | One SQLite file | One SQLite file |
| Metadata filter (doc/section for citations) | Yes | No (DIY) | Yes, metadata columns since v0.1.6 | Yes, plain SQL |
| Keyword search too | No | No | Pair with FTS5 | **FTS5 in the same file** |
| Extra moving parts | Server/client, heavy deps | C++ wheel | Loadable extension (pre-1.0) | None beyond numpy |

- At ~2k vectors, brute-force numpy is instant (milliseconds). An approximate index (HNSW, FAISS) buys nothing.
- One SQLite file is easy to explain in the design doc, easy to inspect, and gives citations for free: each chunk row carries `doc`, `section`, `heading`, `page`.
- **sqlite-vec** is a fine upgrade path if we want SQL-only vector queries, but it's a pre-1.0 extension; not needed at this size.

## Build at deploy time, or commit the index?

- **Commit it.** The file is a few MB. Benefits: no embedding work during deploy, faster cold start, the exact index that was evaluated is the one that ships.
- CI re-runs `build_index.py` and fails if the committed file is stale (checksum of corpus vs. a stored hash). That's a nice CI/CD rubric point.
- **Bake the model into the Docker image** (download during `docker build`) so a cold start doesn't fetch 67MB from Hugging Face. Queries still need the model at runtime to embed the user's question.

## Risks and what to measure in the build

- Real RSS of FastAPI + fastembed + model: measure on day one (`ps`/host metrics). If it's over ~400MB, flip `EMBEDDINGS=voyage` and rebuild the index.
- ONNX Runtime can spawn many threads; set `threads=1` or 2 in fastembed to cap memory on a shared CPU.
- Pin `fastembed` and model name in requirements; record them in the index file's metadata table so a mismatch is caught at startup.

## Sources

- fastembed (ONNX, no PyTorch): https://github.com/qdrant/fastembed
- fastembed model sizes: https://qdrant.github.io/fastembed/examples/Supported_Models/
- Qdrant on fastembed design: https://qdrant.tech/articles/fastembed/
- sentence-transformers memory (~1.8GB cited): https://markaicode.com/alternatives/sentence-transformers-alternatives/
- sentence-transformer CPU Docker image ~787MB: https://hub.docker.com/r/gandviksoft/python-3_10-sentence-transformer-cpu/tags
- Chroma resource requirements (<2GB not recommended): https://cookbook.chromadb.dev/core/resources/
- sqlite-vec metadata columns (v0.1.6): https://github.com/asg017/sqlite-vec/releases/tag/v0.1.6 and https://alexgarcia.xyz/blog/2024/sqlite-vec-metadata-release/index.html
- Voyage pricing / free tokens: https://docs.voyageai.com/docs/pricing
- Gemini free tier overview: https://www.grizzlypeaksoftware.com/articles/p/every-ai-api-with-a-free-tier-in-2026-the-developers-cheat-sheet-jl33ach0
- Sibling project precedent: rag-portfolio SPEC.md (one SQLite file, FTS5 + bge-small + numpy cosine, RRF)
