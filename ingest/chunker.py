"""Section-aware chunker (SPEC slice 3, step 2).

One splitter, keyed on the numbered headings, for every source format. One Chunk per deepest
numbered section; a section over WINDOW_TRIGGER tokens splits into WINDOW-token windows with
OVERLAP-token overlap, all carrying the same section label. A Chunk never spans two sections.
No randomness: the same text always produces the same Chunks.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from ingest.parse import ParsedDoc

CHUNKER_VERSION = "1"
WINDOW_TRIGGER = 350
WINDOW = 300
OVERLAP = 50

_HEADING = re.compile(r"^(\d+(?:\.\d+)*) ([A-Z0-9][^.|]{0,90})$")

TokenCounter = Callable[[str], int]


@dataclass(frozen=True)
class Section:
    number: str
    heading: str
    body: str


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    doc_id: str
    title: str
    section: str
    section_heading: str
    heading_path: str
    text: str
    part: int
    ord: int

    @property
    def embed_text(self) -> str:
        return f"{self.heading_path}\n{self.text}"


def looks_like_heading(line: str) -> bool:
    return bool(_HEADING.match(line))


def _parts(number: str) -> tuple[int, ...]:
    return tuple(int(x) for x in number.split("."))


def _is_successor(prev: tuple[int, ...] | None, cand: tuple[int, ...]) -> bool:
    """A heading is real only if it continues the numbering: the first child of the previous
    heading, or the next sibling at any level above it."""
    if prev is None:
        return cand == (1,)
    if cand == (*prev, 1):
        return True
    return any(cand == (*prev[:k], prev[k] + 1) for k in range(len(prev)))


def split_sections(text: str) -> list[Section]:
    sections: list[tuple[str, str, list[str]]] = []
    prev: tuple[int, ...] | None = None
    for line in text.splitlines():
        m = _HEADING.match(line)
        if m and _is_successor(prev, _parts(m.group(1))):
            prev = _parts(m.group(1))
            sections.append((m.group(1), m.group(2).strip(), []))
        elif sections:
            sections[-1][2].append(line)
        # lines before §1 are the header block: not chunked
    return [Section(n, h, "\n".join(b).strip()) for n, h, b in sections]


def _windows(text: str, count_tokens: TokenCounter) -> list[str]:
    spans = [(m.start(), m.end()) for m in re.finditer(r"\S+", text)]
    costs = [count_tokens(text[a:b]) for a, b in spans]
    if sum(costs) <= WINDOW_TRIGGER:
        return [text]
    out: list[str] = []
    start = 0
    while True:
        end, total = start, 0
        while end < len(spans) and total + costs[end] <= WINDOW:
            total += costs[end]
            end += 1
        end = max(end, start + 1)  # a single over-long word still makes progress
        out.append(text[spans[start][0] : spans[end - 1][1]])
        if end >= len(spans):
            return out
        back, overlap = end, 0
        while back > start + 1 and overlap < OVERLAP:
            back -= 1
            overlap += costs[back]
        start = back


def chunk_document(doc: ParsedDoc, count_tokens: TokenCounter) -> list[Chunk]:
    path: dict[str, str] = {}
    chunks: list[Chunk] = []
    for s in split_sections(doc.text):
        path[s.number] = f"{s.number} {s.heading}"
        if not s.body:  # a parent heading with no intro text of its own
            continue
        ancestors = [path[".".join(s.number.split(".")[: i + 1])] for i in range(s.number.count(".") + 1)]
        heading_path = " › ".join([doc.title, *ancestors])
        for part, text in enumerate(_windows(s.body, count_tokens), start=1):
            chunks.append(
                Chunk(
                    chunk_id=f"{doc.doc_id}#{s.number}#{part}",
                    doc_id=doc.doc_id,
                    title=doc.title,
                    section=s.number,
                    section_heading=s.heading,
                    heading_path=heading_path,
                    text=text,
                    part=part,
                    ord=len(chunks),
                )
            )
    return chunks
