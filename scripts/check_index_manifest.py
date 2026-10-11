"""Index manifest check (SPEC slice 3, step 7), run in CI.

Re-parses and re-chunks the corpus and asserts the file hashes, CHUNKER_VERSION and the Chunk
ID/text list all match index/manifest.json, and that the committed SQLite agrees. No embedding
recompute (floats drift across machines), so a stale index fails here: run `make index`.
Usage: uv run python scripts/check_index_manifest.py
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ingest.build_index import compute_manifest  # noqa: E402
from mcp_servers.policy.embeddings import LocalEmbedder  # noqa: E402


def main() -> int:
    committed = json.loads((ROOT / "index" / "manifest.json").read_text())
    fresh = compute_manifest(ROOT / "corpus", LocalEmbedder().count_tokens, committed["embedding_model"])
    errs = []
    for key in ("chunker_version", "corpus_hash", "files"):
        if fresh[key] != committed[key]:
            errs.append(f"{key} differs")
    if fresh["chunks"] != committed["chunks"]:
        have = {c["chunk_id"]: c["text_sha256"] for c in committed["chunks"]}
        want = {c["chunk_id"]: c["text_sha256"] for c in fresh["chunks"]}
        changed = sorted(k for k in want.keys() & have.keys() if want[k] != have[k])
        errs.append(f"chunks differ: +{sorted(want.keys() - have.keys())[:5]} -{sorted(have.keys() - want.keys())[:5]} "
                    f"changed {changed[:5]}")
    db = sqlite3.connect(ROOT / "index" / "policy_index.sqlite")
    meta = dict(db.execute("SELECT key, value FROM manifest"))
    ids = [r[0] for r in db.execute("SELECT chunk_id FROM chunks ORDER BY ord")]
    if meta.get("corpus_hash") != committed["corpus_hash"] or ids != [c["chunk_id"] for c in committed["chunks"]]:
        errs.append("policy_index.sqlite doesn't match manifest.json")
    print(f"chunks={len(fresh['chunks'])} files={len(fresh['files'])} corpus={fresh['corpus_hash'][:12]}")
    print("ERRORS (run `make index`):\n " + "\n ".join(errs) if errs else "OK: index matches the corpus")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
