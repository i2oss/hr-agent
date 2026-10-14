"""Index build and hybrid retrieval (SPEC slice 3, steps 3–4)."""

from pathlib import Path

import pytest

from ingest.build_index import build_index, compute_manifest
from mcp_servers.policy.retrieval import PolicyIndex, UnknownDocumentOrSection, rrf
from tests.fakes import HashEmbedder

PTO = """# RSE-PTO-01 — Paid Time Off Policy

**FICTIONAL — for demonstration only**

## 1 Purpose and Scope

### 1.1 Purpose

Paid time off covers vacation and personal time.

## 5 Carryover and Payout

### 5.1 Carryover cap

You can carry over up to 5 unused PTO days into the next year. Days above the cap are forfeited.

### 5.2 Leave over year-end

On approved leave spanning year end you may carry over 10 unused days.
"""

SEC = """# RSE-SEC-01 — Information Security & Acceptable Use

**FICTIONAL — for demonstration only**

## 1 Scope and Ownership

### 1.1 Who this applies to

Everyone with Ridgeline access, contractors included.

## 2 Data Classification

Public, Internal, Confidential and Client Restricted information.
"""


@pytest.fixture
def index(tmp_path: Path) -> PolicyIndex:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    # PTO-01 sections deliberately skip §2–§4: fix the numbering so the successor check passes
    (corpus / "RSE-PTO-01.md").write_text(PTO.replace("## 5 ", "## 2 ").replace("### 5.", "### 2."))
    (corpus / "RSE-SEC-01.md").write_text(SEC)
    (corpus / "_facts.yaml").write_text("ignored: true\n")
    out = tmp_path / "index"
    build_index(corpus, out, HashEmbedder())
    return PolicyIndex.load(out / "policy_index.sqlite", HashEmbedder())


def test_rrf_merges_rankings_and_rewards_agreement():
    merged = rrf([["a", "b", "c"], ["b", "a", "d"]], k=60, tie_key=lambda x: x)
    assert [x for x, _ in merged][:2] == ["a", "b"]  # equal scores → tie broken by key
    assert dict(merged)["a"] == pytest.approx(1 / 61 + 1 / 62)
    assert dict(merged)["d"] == pytest.approx(1 / 63)


def test_rrf_ties_break_deterministically_by_key():
    merged = rrf([["z"], ["y"]], k=60, tie_key=lambda x: x)
    assert [x for x, _ in merged] == ["y", "z"]


def test_search_returns_the_carryover_section_with_full_text(index):
    r = index.search("carryover cap forfeited PTO days", k=2, mode="hybrid", threshold=0.1)
    assert r.evidence == "ok"
    top = r.passages[0]
    assert (top.doc_id, top.section) == ("RSE-PTO-01", "2.1")
    assert top.section_heading == "Carryover cap"
    assert top.title == "Paid Time Off Policy"
    assert "5 unused PTO days" in top.text
    assert len(r.passages) <= 2


def test_doc_ids_filter_restricts_results(index):
    r = index.search("carry over unused days", k=5, mode="hybrid", threshold=0.0, doc_ids=["RSE-SEC-01"])
    assert {p.doc_id for p in r.passages} == {"RSE-SEC-01"}


def test_evidence_none_when_top_cosine_below_threshold(index):
    r = index.search("pet insurance", k=5, mode="hybrid", threshold=0.5)
    assert r.evidence == "none"
    assert r.passages == []
    assert r.top_cosine < 0.5


def test_keyword_hit_does_not_override_the_cutoff(index):
    # "contractors" is an exact FTS5 hit, but the vector cosine is what gates evidence.
    r = index.search("contractors xylophone quasar nebula", k=5, mode="hybrid", threshold=0.99)
    assert r.evidence == "none"


def test_vector_mode_skips_keywords(index):
    r = index.search("carryover cap forfeited PTO days", k=5, mode="vector", threshold=0.0)
    assert r.passages[0].section == "2.1"
    assert all(0 <= p.score <= 1 for p in r.passages)


def test_get_section_returns_section_and_subsections_in_order(index):
    passages = index.section("RSE-PTO-01", "2")
    assert [p.section for p in passages] == ["2.1", "2.2"]
    assert [p.section for p in index.section("RSE-PTO-01", "2.2")] == ["2.2"]


def test_get_section_unknown_raises(index):
    with pytest.raises(UnknownDocumentOrSection):
        index.section("RSE-NOPE-01", "1")
    with pytest.raises(UnknownDocumentOrSection):
        index.section("RSE-PTO-01", "9.9")


def test_manifest_matches_a_rebuild_and_is_deterministic(tmp_path, index):
    corpus = tmp_path / "corpus"
    a = compute_manifest(corpus, HashEmbedder().count_tokens, "test/hash-embedder")
    b = compute_manifest(corpus, HashEmbedder().count_tokens, "test/hash-embedder")
    assert a == b
    assert [c["chunk_id"] for c in a["chunks"]][0] == "RSE-PTO-01#1.1#1"
    assert set(a["files"]) == {"RSE-PTO-01.md", "RSE-SEC-01.md"}
    assert index.chunk_count == len(a["chunks"])
    assert index.corpus_hash == a["corpus_hash"]
