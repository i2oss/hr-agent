"""Parse Policy Documents (Markdown, HTML, PDF) into plain text with their heading lines.

Every format comes out the same way: one line per heading ("4.2 Notice") or paragraph, so a
single splitter (ingest/chunker.py) can key on the numbered headings for all three formats.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from bs4 import BeautifulSoup
from pypdf import PdfReader

CORPUS_FORMATS = (".md", ".html", ".pdf")
_TITLE = re.compile(r"^(RSE-[A-Z]+-\d\d)\s+—\s+(.+)$")


@dataclass(frozen=True)
class ParsedDoc:
    doc_id: str
    title: str
    text: str


def corpus_files(corpus_dir: Path) -> list[Path]:
    """The shipped Policy Documents, sorted by name (underscore files are planning inputs)."""
    return sorted(p for p in corpus_dir.iterdir() if p.suffix in CORPUS_FORMATS and not p.name.startswith("_"))


def parse_file(path: Path) -> ParsedDoc:
    if path.suffix == ".md":
        lines = _markdown_lines(path.read_text(encoding="utf-8"))
    elif path.suffix == ".html":
        lines = _html_lines(path.read_text(encoding="utf-8"))
    elif path.suffix == ".pdf":
        lines = _pdf_lines(path)
    else:
        raise ValueError(f"unsupported format: {path}")
    lines = [_clean(line) for line in lines]
    lines = [line for line in lines if line]
    m = _TITLE.match(lines[0]) if lines else None
    if not m:
        raise ValueError(f"{path.name}: first line must be '<doc_id> — <title>'")
    return ParsedDoc(doc_id=m.group(1), title=m.group(2), text="\n".join(lines) + "\n")


def _clean(line: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", line)).strip()


def _markdown_lines(md: str) -> list[str]:
    out: list[str] = []
    para: list[str] = []

    def flush() -> None:
        if para:
            out.append(" ".join(para))
            para.clear()

    for raw in md.splitlines():
        line = raw.strip()
        if not line:
            flush()
            continue
        if line.startswith("#"):
            flush()
            out.append(line.lstrip("#").strip())
        elif line.startswith("|"):
            flush()
            cells = [c.strip() for c in line.strip("|").split("|")]
            if not all(re.fullmatch(r":?-{3,}:?", c) for c in cells):
                out.append(" | ".join(cells))
        elif line.startswith(("- ", "* ")):
            flush()
            out.append(line[2:])
        else:
            para.append(line)
    flush()
    return [re.sub(r"\*\*|__|`", "", line) for line in out]


def _html_lines(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    body = soup.body or soup
    out: list[str] = []
    for el in body.find_all(["h1", "h2", "h3", "h4", "p", "li", "tr"]):
        if el.name == "tr":
            out.append(" | ".join(c.get_text(" ", strip=True) for c in el.find_all(["th", "td"])))
        else:
            out.append(el.get_text(" ", strip=True))
    return out


def _pdf_lines(path: Path) -> list[str]:
    text = "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)
    lines = [_clean(line).lstrip("•").strip() for line in text.splitlines()]
    return _merge_pdf_paragraphs([line for line in lines if line])


def _merge_pdf_paragraphs(lines: list[str]) -> list[str]:
    """PDF extraction hard-wraps paragraphs. Keep heading-like and header lines on their own;
    join the rest into one paragraph per run of body lines."""
    from ingest.chunker import looks_like_heading  # local import: chunker imports this module

    out: list[str] = []
    run: list[str] = []
    for i, line in enumerate(lines):
        standalone = i == 0 or looks_like_heading(line) or ":" in line[:20] and len(line) < 90 and not run
        if standalone:
            out.extend(join_wrapped_lines(run))
            run = []
            out.append(line)
        else:
            run.append(line)
    out.extend(join_wrapped_lines(run))
    return out


def join_wrapped_lines(lines: list[str]) -> list[str]:
    """Join hard-wrapped lines into one paragraph. A line ending in '-' was split mid-token
    ("RSE-" + "PTO-01"), so it joins without a space."""
    if not lines:
        return []
    text = lines[0]
    for line in lines[1:]:
        text = text + line if text.endswith("-") else f"{text} {line}"
    return [text]
