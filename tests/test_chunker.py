"""Section-aware chunker (SPEC slice 3, step 2)."""

from ingest.chunker import Chunk, chunk_document, split_sections
from ingest.parse import ParsedDoc, join_wrapped_lines


def words(text: str) -> int:
    return len(text.split())


DOC = """RSE-PTO-01 — Paid Time Off Policy
FICTIONAL — for demonstration only
Version: 2026.1
1 Purpose and Scope
1.1 Purpose
PTO is paid time away.
1.2 Who is eligible
Full-time staff are eligible.
2 Accrual
10 Days are earned each year by some interns.
2.1 Full-time accrual
You earn 15 days.
3 Questions
Ask HR.
"""


def doc(text: str = DOC) -> ParsedDoc:
    return ParsedDoc(doc_id="RSE-PTO-01", title="Paid Time Off Policy", text=text)


def test_split_sections_finds_numbered_headings_in_order():
    secs = split_sections(DOC)
    assert [s.number for s in secs] == ["1", "1.1", "1.2", "2", "2.1", "3"]
    assert secs[1].heading == "Purpose"


def test_a_body_line_that_looks_like_a_heading_is_not_a_heading():
    # "10 Days are earned…" is not a valid successor of §2, so it stays body text.
    secs = {s.number: s for s in split_sections(DOC)}
    assert "10 Days are earned" in secs["2"].body


def test_preamble_before_section_1_is_not_chunked():
    chunks = chunk_document(doc(), words)
    assert all("FICTIONAL" not in c.text for c in chunks)


def test_one_chunk_per_deepest_section_and_parent_intro_kept():
    chunks = chunk_document(doc(), words)
    assert [c.section for c in chunks] == ["1.1", "1.2", "2", "2.1", "3"]
    assert [c.chunk_id for c in chunks][:2] == ["RSE-PTO-01#1.1#1", "RSE-PTO-01#1.2#1"]


def test_chunk_never_spans_two_sections():
    for c in chunk_document(doc(), words):
        assert "Ask HR" not in c.text or c.section == "3"


def test_heading_path_prefixes_the_embedded_text_only():
    c = next(c for c in chunk_document(doc(), words) if c.section == "1.2")
    assert c.heading_path == "Paid Time Off Policy › 1 Purpose and Scope › 1.2 Who is eligible"
    assert c.embed_text.startswith(c.heading_path)
    assert c.text == "Full-time staff are eligible."
    assert c.section_heading == "Who is eligible"


def test_long_section_splits_into_overlapping_windows_with_the_same_label():
    body = " ".join(f"w{i}" for i in range(800))
    chunks = chunk_document(doc(f"1 Purpose and Scope\n1.1 Purpose\n{body}\n"), words)
    assert len(chunks) >= 3
    assert {c.section for c in chunks} == {"1.1"}
    assert [c.part for c in chunks] == list(range(1, len(chunks) + 1))
    assert all(words(c.text) <= 300 for c in chunks)
    first, second = chunks[0].text.split(), chunks[1].text.split()
    assert first[-50:] == second[:50]  # 50-token overlap
    assert chunks[-1].text.split()[-1] == "w799"


def test_section_at_threshold_is_not_split():
    body = " ".join(f"w{i}" for i in range(350))
    chunks = chunk_document(doc(f"1 Purpose and Scope\n1.1 Purpose\n{body}\n"), words)
    assert len(chunks) == 1


def test_chunking_is_deterministic():
    a: list[Chunk] = chunk_document(doc(), words)
    b: list[Chunk] = chunk_document(doc(), words)
    assert a == b


def test_join_wrapped_lines_rejoins_pdf_hyphen_breaks():
    assert join_wrapped_lines(["Policy (RSE-", "PTO-01) applies."]) == ["Policy (RSE-PTO-01) applies."]
    assert join_wrapped_lines(["one line", "continues here"]) == ["one line continues here"]
