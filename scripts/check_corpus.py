"""Corpus check (SPEC slice 2, step 7), run in CI.

- every outlined § exists as a heading in its document, and the document has no unoutlined §s;
- every number and date in the prose appears in corpus/_facts.yaml;
- no not_covered term appears;
- each document carries its header block and FICTIONAL banner, in its tabled format;
- total length is within 30–120 pages (~500 words/page).

Usage: uv run python scripts/check_corpus.py .
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ingest.chunker import split_sections  # noqa: E402
from ingest.parse import corpus_files, parse_file  # noqa: E402

WORDS_PER_PAGE = 500
PAGES = (30, 120)
HEADER_KEYS = ("Document ID:", "Title:", "Version: 2026.1", "Effective date:", "Owner:", "Applies to:")
_DOC = re.compile(r"## (RSE-[A-Z]+-\d\d)")
_SEC = (re.compile(r"\s*- \*\*§(\d+)\b"), re.compile(r"\s*- §(\d+(?:\.\d+)?)\b"))


def outlined_sections(outlines: str) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    doc = None
    for line in outlines.splitlines():
        if m := _DOC.match(line):
            doc = m.group(1)
            out[doc] = set()
            continue
        for rx in _SEC:
            if doc and (m := rx.match(line)):
                out[doc].add(m.group(1))
    return out


def fact_numbers(facts_raw: str) -> set[str]:
    """Every number written in the facts sheet, plus the forms prose naturally uses for them."""
    nums = set(re.findall(r"\d+(?:\.\d+)?", facts_raw.replace(",", "")))
    for d in re.findall(r"\d{4}-(\d\d)-(\d\d)", facts_raw):  # dates written out ("November 11")
        nums.update({str(int(d[0])), str(int(d[1]))})
    return nums | {str(n) for n in range(1, 13)}  # section numbers and list counts


def prose_numbers(text: str) -> list[str]:
    body = re.sub(r"RSE-[A-Z]+-\d\d( §\d+(?:\.\d+)*(–§\d+(?:\.\d+)*)?)?", " ", text)  # IDs and § refs
    body = re.sub(r"§\d+(?:\.\d+)*", " ", body)
    body = re.sub(r"^\d+(?:\.\d+)* (?=[A-Z0-9])", " ", body, flags=re.M)  # heading numbers
    body = re.sub(r"\b(401\(k\)|America/\w+)", " ", body)
    return re.findall(r"\d+(?:\.\d+)?", body.replace(",", ""))


def main(root: Path) -> int:
    facts_raw = (root / "corpus" / "_facts.yaml").read_text(encoding="utf-8")
    facts = yaml.safe_load(facts_raw)
    outlines = outlined_sections((root / "corpus" / "_outlines.md").read_text(encoding="utf-8"))
    allowed = fact_numbers(facts_raw)
    formats = {d["id"]: d["format"] for d in facts["documents"]}
    gaps = [w.strip().lower() for t in facts["not_covered"] for w in t.split("/")]
    errs: list[str] = []
    words = 0
    seen: set[str] = set()

    for path in corpus_files(root / "corpus"):
        doc = parse_file(path)
        seen.add(doc.doc_id)
        words += len(doc.text.split())
        if formats.get(doc.doc_id) != path.suffix.lstrip("."):
            errs.append(f"{path.name}: format should be {formats.get(doc.doc_id)}")
        head = doc.text.split("\n1 ", 1)[0]
        for key in (*HEADER_KEYS, facts["meta"]["banner"]):
            if key not in head:
                errs.append(f"{doc.doc_id}: header missing {key!r}")
        found = {s.number for s in split_sections(doc.text)}
        want = outlines.get(doc.doc_id, set())
        if missing := sorted(want - found):
            errs.append(f"{doc.doc_id}: outlined § missing as headings: {missing}")
        if extra := sorted(found - want):
            errs.append(f"{doc.doc_id}: § not in the outline: {extra}")
        low = doc.text.lower()
        errs += [f"{doc.doc_id}: not_covered term {g!r}" for g in gaps if g in low]
        bad = sorted({n for n in prose_numbers(doc.text) if n not in allowed})
        if bad:
            errs.append(f"{doc.doc_id}: numbers not in _facts.yaml: {bad}")

    if missing_docs := sorted(set(formats) - seen):
        errs.append(f"documents missing: {missing_docs}")
    pages = words / WORDS_PER_PAGE
    if not PAGES[0] <= pages <= PAGES[1]:
        errs.append(f"length {pages:.1f} pages, want {PAGES[0]}–{PAGES[1]}")
    print(f"docs={len(seen)} words={words} pages≈{pages:.1f}")
    print("ERRORS:\n " + "\n ".join(errs) if errs else "OK: sections, numbers, gaps, headers and length all hold")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1] if len(sys.argv) > 1 else ".")))
