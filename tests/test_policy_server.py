"""policy MCP server over the in-memory Client (SPEC slice 3, step 7)."""

import pytest
from mcp import Client

from mcp_servers.policy.server import build_policy_server
from tests.test_retrieval import index  # noqa: F401  (fixture)


@pytest.fixture
def server(index, settings):  # noqa: F811
    settings.evidence_threshold = 0.1
    return build_policy_server(index, settings)


async def test_lists_two_read_only_tools(server):
    async with Client(server) as c:
        tools = {t.name: t for t in (await c.list_tools()).tools}
    assert set(tools) == {"search_policy", "get_policy_section"}
    for t in tools.values():
        assert t.annotations and t.annotations.read_only_hint
        assert "Use when" in (t.description or "") and "Don't use when" in (t.description or "")
    assert "top_k" not in tools["search_policy"].input_schema["properties"]


async def test_search_policy_returns_passages(server):
    async with Client(server) as c:
        r = await c.call_tool("search_policy", {"query": "carryover cap forfeited PTO days"})
    assert not r.is_error
    out = r.structured_content
    assert out["evidence"] == "ok"
    assert out["passages"][0]["doc_id"] == "RSE-PTO-01"
    assert {"doc_id", "title", "section", "section_heading", "text", "score"} <= set(out["passages"][0])


async def test_search_policy_no_evidence_is_not_an_error(server):
    async with Client(server) as c:
        r = await c.call_tool("search_policy", {"query": "xylophone quasar"})
    assert not r.is_error
    assert r.structured_content == {"passages": [], "evidence": "none"}


async def test_get_policy_section(server):
    async with Client(server) as c:
        r = await c.call_tool("get_policy_section", {"doc_id": "RSE-PTO-01", "section": "2"})
    assert [p["section"] for p in r.structured_content["passages"]] == ["2.1", "2.2"]


async def test_get_policy_section_unknown_is_a_coded_error(server):
    async with Client(server) as c:
        r = await c.call_tool("get_policy_section", {"doc_id": "RSE-PTO-01", "section": "9"})
    assert r.is_error
    assert r.structured_content["error"]["code"] == "UNKNOWN_DOCUMENT_OR_SECTION"
    assert r.structured_content["error"]["hint"]
