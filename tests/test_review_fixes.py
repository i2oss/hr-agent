"""Regression tests for the code-review findings on the build branch."""

import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from mcp import Client
from starlette.requests import Request

from app.agent.answer import FinalAnswer
from app.agent.citations import check_answer
from app.agent.fake_scripts import W01
from app.agent.llm import AnthropicLLM, FakeLLM, OpenAICompatLLM
from app.agent.loop import parse_answer
from app.api.limits import Limits
from app.main import create_app
from mcp_servers.common.models import Passage
from mcp_servers.hr.server import build_hr_server
from mcp_servers.hr.store import MockActionStore
from tests.test_policy_server import server as policy_server  # noqa: F401  (fixture)
from tests.test_retrieval import index  # noqa: F401  (fixture)


def chat(c, message, speaking_as="E1001", session=None):
    return c.post("/chat", json={"session_id": session or uuid.uuid4().hex, "speaking_as": speaking_as,
                                 "message": message})


def test_tool_definitions_are_still_sent_when_calls_are_off(settings):
    """Anthropic rejects a history with tool_use blocks unless tools are defined: the confirm path, retries
    and forced Clarification must keep sending them (with tool calls disabled)."""
    llm = FakeLLM()
    with TestClient(create_app(settings, in_memory_mcp=True, llm=llm)) as c:
        r = chat(c, W01).json()
        c.post(f"/chat/actions/{r['pending_action']['action_id']}", json={"decision": "confirm"})
    last = llm.calls[-1]
    assert last["tools"] == [] and last["offered"] == 9


async def test_anthropic_sends_tool_choice_none_when_calls_are_off(settings, monkeypatch):
    from app.agent.mcp_client import McpHub

    hub = McpHub({"hr": build_hr_server(settings, MockActionStore())})
    tools = list((await hub.discover()).values())
    llm = AnthropicLLM("claude-haiku-4-5", "sk-test")
    seen = {}

    async def create(**kw):
        seen.update(kw)
        return SimpleNamespace(content=[], usage=SimpleNamespace(input_tokens=0, output_tokens=0))

    monkeypatch.setattr(llm._client.messages, "create", create)
    await llm.complete(["p"], [], tools, {}, allow_tool_calls=False)
    assert seen["tool_choice"] == {"type": "none"} and len(seen["tools"]) == 7


def test_openai_invalid_tool_arguments_become_a_tool_error():
    call = OpenAICompatLLM._call("c1", "search_policy", '{"query": "pto')
    assert call.input == {} and "not a valid JSON object" in call.error
    assert OpenAICompatLLM._call("c2", "search_policy", '{"query": "pto"}').error is None


def test_invalid_tool_call_is_reported_to_the_model_not_executed(settings):
    from app.agent.llm import LLMResponse, ToolCall

    class BadArgs(FakeLLM):
        async def complete(self, system, messages, tools, answer_schema, allow_tool_calls=True):
            if allow_tool_calls and len(self.calls) == 0:
                self.calls.append({})
                return LLMResponse("", [ToolCall("x1", "search_policy", {}, error="bad JSON")])
            return await super().complete(system, messages, tools, answer_schema, allow_tool_calls)

    with TestClient(create_app(settings, in_memory_mcp=True, llm=BadArgs({}))) as c:
        r = chat(c, "q").json()
    assert [s["summary"] for s in r["trace"]["steps"] if s["kind"] == "error"] == ["bad JSON"]


def test_parse_answer_handles_an_unclosed_brace():
    answer, error = parse_answer('Here is the answer: {"lead": "You can')
    assert answer is None and error


def test_short_or_empty_snippets_fail_the_citation_check():
    p = Passage(doc_id="RSE-PTO-01", title="t", section="4.2", section_heading="h",
                text="Requests for more than 3 PTO days need notice.", score=1)
    for snippet in ("", "  ", "a", "PTO days"):
        a = FinalAnswer.model_validate({"lead": "x", "policy_facts": [
            {"text": "Invented.", "citations": [{"doc_id": "RSE-PTO-01", "section": "4.2", "snippet": snippet}]}]})
        assert not check_answer(a, [p], set()).ok, snippet


def _request(xff: str) -> Request:
    return Request({"type": "http", "headers": [(b"x-forwarded-for", xff.encode())], "client": ("10.0.0.1", 1)})


def test_rate_limit_uses_the_proxy_appended_address_not_a_spoofed_one():
    assert Limits.client_ip(_request("6.6.6.6, 203.0.113.9")) == "203.0.113.9"


def test_spoofed_forwarded_for_cannot_dodge_the_per_ip_limit(settings):
    settings.rate_limits_enabled = True
    settings.rate_limit_per_ip = 2
    limits = Limits(settings)
    for i in range(2):
        limits.check_message(_request(f"1.2.3.{i}, 203.0.113.9"), "hi", 0)
    with pytest.raises(Exception) as e:
        limits.check_message(_request("9.9.9.9, 203.0.113.9"), "hi", 0)
    assert e.value.status_code == 429


async def test_unknown_expense_category_is_missing_argument(settings):
    async with Client(build_hr_server(settings, MockActionStore())) as c:
        r = await c.call_tool("check_policy_compliance", {
            "employee_id": "E1003", "request_type": "expense_item", "requester_id": "E1003", "session_id": "s",
            "details": {"category": "hotel", "amount": 900, "currency": "USD", "description": "x"}})
    assert r.is_error and r.structured_content["error"]["code"] == "MISSING_ARGUMENT"
    assert "lodging" in r.structured_content["error"]["hint"]


async def test_unknown_doc_ids_are_an_error_not_no_evidence(policy_server):  # noqa: F811
    async with Client(policy_server) as c:
        r = await c.call_tool("search_policy", {"query": "carryover", "doc_ids": ["RSE-PTO-1"]})
    assert r.is_error and r.structured_content["error"]["code"] == "UNKNOWN_DOCUMENT_OR_SECTION"


def test_tools_are_rediscovered_after_a_server_was_down(settings):
    llm = FakeLLM({"q": [{"final": {"lead": "ok"}}]})
    app = create_app(settings, in_memory_mcp=True, llm=llm)
    with TestClient(app) as c:
        real_policy = app.state.hub.targets["policy"]
        app.state.hub.targets["policy"] = "http://127.0.0.1:9/mcp/policy/"
        app.state.hub.timeout_s = 2
        chat(c, "q")
        assert {t.server for t in app.state.hub.tools.values()} == {"hr"}
        app.state.hub.targets["policy"] = real_policy
        chat(c, "q")
    assert {t.server for t in app.state.hub.tools.values()} == {"hr", "policy"}


def test_a_failure_mid_turn_leaves_the_history_well_formed(settings):
    class Explodes(FakeLLM):
        async def complete(self, system, messages, tools, answer_schema, allow_tool_calls=True):
            if any(b["type"] == "tool_result" for m in messages for b in m["content"]):
                raise RuntimeError("provider down")
            return await super().complete(system, messages, tools, answer_schema, allow_tool_calls)

    llm = Explodes({"q": [{"tool_calls": [{"name": "search_policy", "input": {"query": "pto"}}]}]})
    app = create_app(settings, in_memory_mcp=True, llm=llm)
    s = uuid.uuid4().hex
    with TestClient(app, raise_server_exceptions=False) as c:
        assert chat(c, "q", session=s).status_code == 500
    session = app.state.sessions.get_or_create(s, "E1001")
    assert session.history == [] and session.turns == 0
