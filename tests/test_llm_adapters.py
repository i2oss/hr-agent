"""LLM adapters build the right requests (no network: the SDK clients are stubbed)."""

import inspect
from types import SimpleNamespace

import anthropic
import httpx
import pytest
from anthropic.resources.messages import AsyncMessages
from mcp import Client

from app.agent.answer import model_facing_schema
from app.agent.llm import MAX_STRICT_UNIONS, NON_STRICT_TOOLS, AnthropicLLM, OpenAICompatLLM
from app.agent.mcp_client import McpHub
from mcp_servers.hr.server import build_hr_server
from mcp_servers.hr.store import MockActionStore


@pytest.fixture
async def tools(settings):
    hub = McpHub({"hr": build_hr_server(settings, MockActionStore())})
    return list((await hub.discover()).values())


def objects(node):
    if isinstance(node, dict):
        if node.get("type") == "object" or "properties" in node:
            yield node
        for v in node.values():
            yield from objects(v)
    elif isinstance(node, list):
        for v in node:
            yield from objects(v)


def unions(node):
    """Count parameters Anthropic treats as union-typed (anyOf or a type array)."""
    if isinstance(node, dict):
        own = int("anyOf" in node or isinstance(node.get("type"), list))
        return own + sum(unions(v) for v in node.values())
    if isinstance(node, list):
        return sum(unions(v) for v in node)
    return 0


async def test_anthropic_request_uses_strict_tools_caching_and_structured_output(tools, monkeypatch):
    llm = AnthropicLLM("claude-haiku-4-5", "sk-test")
    seen = {}

    async def create(**kwargs):
        seen.update(kwargs)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text='{"lead": "hi"}')],
                               usage=SimpleNamespace(input_tokens=10, output_tokens=5))

    monkeypatch.setattr(llm._client.messages, "create", create)
    r = await llm.complete(["stable prompt", "Requester E1001"], [{"role": "user", "content": [
        {"type": "text", "text": "hi"}]}], tools, model_facing_schema())
    assert r.text == '{"lead": "hi"}' and r.input_tokens == 10
    inspect.signature(AsyncMessages.create).bind(None, **seen)  # every kwarg is one the real SDK takes
    assert seen["model"] == "claude-haiku-4-5"
    assert seen["system"][0]["cache_control"] == {"type": "ephemeral"} and "cache_control" not in seen["system"][1]
    assert seen["output_config"]["format"]["type"] == "json_schema"
    assert len(seen["tools"]) == 7
    assert {t["name"] for t in seen["tools"] if not t["strict"]} == NON_STRICT_TOOLS
    strict = [t["input_schema"] for t in seen["tools"] if t["strict"]] + [seen["output_config"]["format"]["schema"]]
    assert sum(unions(s) for s in strict) <= MAX_STRICT_UNIONS
    for t in seen["tools"]:
        assert "requester_id" not in t["input_schema"]["properties"]
        for o in objects(t["input_schema"]):
            assert o.get("additionalProperties") is False and set(o["required"]) == set(o["properties"]), t["name"]


async def test_anthropic_falls_back_to_json_parsing_without_structured_output(tools, monkeypatch):
    llm = AnthropicLLM("claude-haiku-4-5", "sk-test")
    calls = []

    async def create(**kwargs):
        calls.append(kwargs)
        if "output_config" in kwargs:
            req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
            raise anthropic.BadRequestError("output_config not supported", response=httpx.Response(400, request=req),
                                            body=None)
        return SimpleNamespace(content=[], usage=SimpleNamespace(input_tokens=0, output_tokens=0))

    monkeypatch.setattr(llm._client.messages, "create", create)
    await llm.complete(["p"], [], [], model_facing_schema())
    await llm.complete(["p"], [], [], model_facing_schema())
    assert ["output_config" in c for c in calls] == [True, False, False]


def test_openai_conversion_maps_tool_use_and_results():
    msgs = [
        {"role": "user", "content": [{"type": "text", "text": "q"}]},
        {"role": "assistant", "content": [{"type": "tool_use", "id": "c1", "name": "search_policy",
                                           "input": {"query": "pto"}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "c1", "content": "{}"},
                                     {"type": "text", "text": "[Loop] note"}]},
    ]
    out = OpenAICompatLLM._convert(["sys"], msgs)
    assert [m["role"] for m in out] == ["system", "user", "assistant", "tool", "user"]
    assert out[2]["tool_calls"][0]["function"] == {"name": "search_policy", "arguments": '{"query": "pto"}'}
    assert out[3] == {"role": "tool", "tool_call_id": "c1", "content": "{}"}


async def test_every_server_tool_converts_to_a_valid_strict_schema(settings):
    from app.agent.answer import strict_schema

    async with Client(build_hr_server(settings, MockActionStore())) as c:
        for t in (await c.list_tools()).tools:
            s = strict_schema(t.input_schema)
            assert "$ref" not in str(s) and "default" not in str(s)
