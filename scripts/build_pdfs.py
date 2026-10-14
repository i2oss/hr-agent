"""Build the PDF Policy Documents (RSE-HB-01, RSE-EXP-01) from their Markdown in corpus/_src/.

Usage: uv run python scripts/build_pdfs.py      (dev dependency: markdown-pdf)
The PDFs are committed; re-run this after editing a source, then `make index`.
"""

from pathlib import Path

from markdown_pdf import MarkdownPdf, Section

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "corpus" / "_src"
CSS = "body { font-family: sans-serif; font-size: 11pt; } h1 { font-size: 18pt; } table { border-collapse: collapse; }"


def build(src: Path) -> Path:
    pdf = MarkdownPdf(toc_level=0)
    pdf.meta["title"] = src.stem
    pdf.meta["subject"] = "FICTIONAL — for demonstration only"
    pdf.add_section(Section(src.read_text(encoding="utf-8"), toc=False), user_css=CSS)
    out = ROOT / "corpus" / f"{src.stem}.pdf"
    pdf.save(out)
    return out


if __name__ == "__main__":
    for src in sorted(SRC.glob("*.md")):
        print(build(src).relative_to(ROOT))
