"""Calibrate the evidence threshold T (SPEC slice 3, step 6). Run with `make calibrate`.

Runs the in-corpus and out-of-corpus queries in evaluation/calibration_queries.yaml (disjoint from
the Eval Set) through retrieval, records each top vector cosine, and sets T just below the lowest
in-corpus top cosine, so no in-corpus query is cut off. Out-of-corpus queries above T are reported,
not tuned away. Also checks each in-corpus query's expected § is in the top k (hybrid).
Writes evaluation/results/calibration/{calibration.json,report.md}.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import yaml

from app.config import ROOT, get_settings
from mcp_servers.policy.embeddings import make_embedder
from mcp_servers.policy.retrieval import PolicyIndex

MARGIN = 0.01
OUT = ROOT / "evaluation" / "results" / "calibration"


def _expected(q: dict[str, Any]) -> list[tuple[str, str]]:
    exp = q["expected"] if isinstance(q["expected"], list) else [q["expected"]]
    return [tuple(e.split("#")) for e in exp]  # type: ignore[misc]


def calibrate(index: PolicyIndex, queries: dict[str, Any], k: int) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for kind in ("in_corpus", "out_of_corpus"):
        for q in queries[kind]:
            res = index.search(q["query"], k=k, mode="hybrid", threshold=-1.0)
            row = {"id": q["id"], "set": kind, "query": q["query"], "top_cosine": round(res.top_cosine, 4),
                   "top_k": [f"{p.doc_id}#{p.section}" for p in res.passages]}
            if kind == "in_corpus":
                want = _expected(q)
                row["expected"] = [f"{d}#{s}" for d, s in want]
                row["hit"] = any(
                    p.doc_id == d and (p.section == s or p.section.startswith(s + "."))
                    for p in res.passages for d, s in want
                )
            else:
                row["kind"] = q["kind"]
            rows.append(row)
    lowest_in = min(r["top_cosine"] for r in rows if r["set"] == "in_corpus")
    threshold = math.floor((lowest_in - MARGIN) * 100) / 100
    for row in rows:
        row["passes_threshold"] = row["top_cosine"] >= threshold
    return {"threshold": threshold, "lowest_in_corpus": lowest_in, "k": k, "rows": rows}


def report(result: dict[str, Any], embedding_model: str) -> str:
    T = result["threshold"]
    ins = [r for r in result["rows"] if r["set"] == "in_corpus"]
    outs = [r for r in result["rows"] if r["set"] == "out_of_corpus"]
    lines = [
        "# Evidence threshold calibration",
        "",
        f"Embedding model `{embedding_model}`, k={result['k']}, hybrid retrieval. "
        f"**T = {T}** (lowest in-corpus top cosine {result['lowest_in_corpus']} minus {MARGIN}, floored).",
        "",
        f"- In-corpus queries cut off by T: {sum(not r['passes_threshold'] for r in ins)}/{len(ins)}",
        f"- In-corpus queries with the expected § in the top {result['k']}: {sum(r['hit'] for r in ins)}/{len(ins)}",
        f"- Out-of-corpus queries above T (left to the prompt's \"passages don't answer → refuse\"): "
        f"{sum(r['passes_threshold'] for r in outs)}/{len(outs)}",
        "",
        "| id | set | query | top cosine | ≥ T | expected | in top k |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in sorted(result["rows"], key=lambda r: -r["top_cosine"]):
        lines.append(
            f"| {r['id']} | {r['set'] if r['set'] == 'in_corpus' else r['kind']} | {r['query']} | "
            f"{r['top_cosine']:.3f} | {'yes' if r['passes_threshold'] else 'no'} | "
            f"{', '.join(r.get('expected', [])) or '—'} | {'' if 'hit' not in r else ('yes' if r['hit'] else '**miss**')} |"
        )
    misses = [r for r in ins if not r["hit"]]
    if misses:
        lines += ["", "## Misses", ""]
        lines += [f"- {r['id']} `{r['query']}`: expected {', '.join(r['expected'])}, got {', '.join(r['top_k'])}"
                  for r in misses]
    return "\n".join(lines) + "\n"


def main() -> None:
    settings = get_settings()
    embedder = make_embedder(settings)
    index = PolicyIndex.load(settings.index_path, embedder)
    queries = yaml.safe_load((ROOT / "evaluation" / "calibration_queries.yaml").read_text())
    result = calibrate(index, queries, settings.retrieval_top_k)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "calibration.json").write_text(json.dumps(result, indent=2) + "\n")
    (OUT / "report.md").write_text(report(result, index.embedding_model))
    print(f"T = {result['threshold']}  (set CALIBRATED_EVIDENCE_THRESHOLD in app/config.py)")
    print(f"wrote {Path(OUT).relative_to(ROOT)}/")


if __name__ == "__main__":
    main()
