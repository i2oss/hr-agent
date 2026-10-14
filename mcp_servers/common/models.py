"""Models shared by both MCP servers."""

from __future__ import annotations

from pydantic import BaseModel


class Passage(BaseModel):
    """One retrieved Chunk with its citation metadata. `text` is the full Chunk."""

    doc_id: str
    title: str
    section: str
    section_heading: str
    text: str
    score: float


class Citation(BaseModel):
    """A pointer to a Policy Document §, as carried by Compliance Check results and Mock Actions."""

    doc_id: str
    section: str
