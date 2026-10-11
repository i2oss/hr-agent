"""policy MCP server: read-only access to the policy index (SPEC §3.4). Mounted at /mcp/policy."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Literal

from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from mcp_servers.common.errors import ToolFailure, coded_errors
from mcp_servers.common.models import Passage
from mcp_servers.policy.retrieval import PolicyIndex, UnknownDocumentOrSection

if TYPE_CHECKING:
    from app.config import Settings

READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False)


class SearchResultOut(BaseModel):
    passages: list[Passage]
    evidence: Literal["ok", "none"]


class SectionOut(BaseModel):
    passages: list[Passage]


def build_policy_server(index: PolicyIndex, settings: Settings) -> MCPServer:
    server = MCPServer(
        "policy",
        instructions="Ridgeline (FICTIONAL) policy corpus: search and read Policy Document sections.",
    )

    @server.tool(annotations=READ_ONLY)
    @coded_errors
    async def search_policy(
        query: Annotated[str, Field(description="Your own search query: short, keyword-style, about one topic.")],
        doc_ids: Annotated[
            list[str] | None, Field(description="Optional: only search these Policy Documents, e.g. ['RSE-PTO-01'].")
        ] = None,
    ) -> SearchResultOut:
        """Search Ridgeline's Policy Corpus and return the most relevant passages with citation fields.

        Use when: you need policy text to answer or cite anything about Ridgeline's rules; write your own
        query, and search again with different words (or narrower doc_ids) if the results are thin.
        Don't use when: you already have the passage this turn, or you need a whole section you can name
        (use get_policy_section). evidence "none" means nothing in the corpus matches: don't state policy.
        """
        r = index.search(query, k=settings.retrieval_top_k, mode=settings.retrieval_mode,
                         threshold=settings.evidence_threshold, doc_ids=doc_ids)
        return SearchResultOut(passages=r.passages, evidence=r.evidence)

    @server.tool(annotations=READ_ONLY)
    @coded_errors
    async def get_policy_section(
        doc_id: Annotated[str, Field(description="Policy Document ID, e.g. 'RSE-PTO-01'.")],
        section: Annotated[str, Field(description="Section number without '§', e.g. '4' or '4.2'.")],
    ) -> SectionOut:
        """Return every passage of one Policy Document section and its sub-sections, in order.

        Use when: a search hit points at a section and you need the rest of it, or you know exactly which
        section you need (e.g. RSE-APR-01 §2 for approvers).
        Don't use when: you don't know the section; search with search_policy first.
        """
        try:
            return SectionOut(passages=index.section(doc_id, section))
        except UnknownDocumentOrSection:
            raise ToolFailure(
                "UNKNOWN_DOCUMENT_OR_SECTION",
                f"No section {section} in {doc_id}.",
                f"Known documents: {', '.join(index.doc_ids)}. Use search_policy to find the right section.",
            ) from None

    return server
