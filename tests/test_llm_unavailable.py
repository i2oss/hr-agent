"""An LLM provider failure (no credit, an outage) reaches the visitor as a plain 503, not a bare 500
(follow-up (e), seen twice in production)."""

import logging
import uuid
from types import SimpleNamespace

import anthropic
import httpx
import openai
import pytest
from fastapi.testclient import TestClient

from app.agent.fake_scripts import W01
from app.agent.llm import AnthropicLLM, FakeLLM, LLMUnavailable, OpenAICompatLLM
from app.api.routes import LLM_UNAVAILABLE
from app.main import create_app

CREDIT = "Your credit balance is too low to access the Anthropic API."


class Flaky(FakeLLM):
    """A FakeLLM whose provider can be switched off."""

    down = False

    async def complete(self, system, messages, tools, answer_schema, allow_tool_calls=True):
        if self.down:
            raise LLMUnavailable(f"BadRequestError: {CREDIT}")
        return await super().complete(system, messages, tools, answer_schema, allow_tool_calls)


def chat(c, message, session, speaking_as="E1001"):
    return c.post("/chat", json={"session_id": session, "speaking_as": speaking_as, "message": message})


def test_chat_returns_503_logs_the_cause_and_rolls_back(settings, caplog):
    llm = Flaky()
    llm.down = True
    app = create_app(settings, in_memory_mcp=True, llm=llm)
    s = uuid.uuid4().hex
    with TestClient(app) as c, caplog.at_level(logging.ERROR, logger="uvicorn.error"):
        r = chat(c, W01, s)
    assert r.status_code == 503
    assert r.json() == {"detail": LLM_UNAVAILABLE}
    assert any("LLM unavailable" in m and CREDIT in m for m in caplog.messages)
    session = app.state.sessions.get_or_create(s, "E1001")
    assert session.history == [] and session.turns == 0


def test_the_same_session_works_once_the_provider_is_back(settings):
    llm = Flaky()
    llm.down = True
    s = uuid.uuid4().hex
    with TestClient(create_app(settings, in_memory_mcp=True, llm=llm)) as c:
        assert chat(c, W01, s).status_code == 503
        llm.down = False
        r = chat(c, W01, s)
    assert r.status_code == 200 and r.json()["pending_action"]["tool"] == "draft_manager_message"


def test_a_decision_returns_503_when_the_provider_fails(settings):
    llm = Flaky()
    s = uuid.uuid4().hex
    with TestClient(create_app(settings, in_memory_mcp=True, llm=llm)) as c:
        pending = chat(c, W01, s).json()["pending_action"]
        llm.down = True
        r = c.post(f"/chat/actions/{pending['action_id']}", json={"decision": "cancel"})
    assert r.status_code == 503 and r.json()["detail"] == LLM_UNAVAILABLE


def _response(status: int) -> httpx.Response:
    return httpx.Response(status, request=httpx.Request("POST", "https://api.example/v1/messages"))


async def test_anthropic_api_errors_become_llm_unavailable(monkeypatch):
    llm = AnthropicLLM("claude-sonnet-5-5", "sk-test")

    async def create(**kw):
        raise anthropic.BadRequestError(CREDIT, response=_response(400), body=None)

    monkeypatch.setattr(llm._client.messages, "create", create)
    with pytest.raises(LLMUnavailable, match="credit balance is too low"):
        await llm.complete(["p"], [], [], {})


async def test_anthropic_still_falls_back_when_structured_output_is_refused(monkeypatch):
    llm = AnthropicLLM("claude-sonnet-5-5", "sk-test")
    seen = []

    async def create(**kw):
        seen.append("output_config" in kw)
        if "output_config" in kw:
            raise anthropic.BadRequestError("output_config is not supported", response=_response(400), body=None)
        return SimpleNamespace(content=[], usage=SimpleNamespace(input_tokens=0, output_tokens=0))

    monkeypatch.setattr(llm._client.messages, "create", create)
    await llm.complete(["p"], [], [], {})
    assert seen == [True, False]


async def test_openai_compat_api_errors_become_llm_unavailable(monkeypatch):
    llm = OpenAICompatLLM("some-model", "sk-test", "https://api.example/v1")

    async def create(**kw):
        raise openai.APIConnectionError(request=httpx.Request("POST", "https://api.example/v1/chat"))

    monkeypatch.setattr(llm._client.chat.completions, "create", create)
    with pytest.raises(LLMUnavailable, match="APIConnectionError"):
        await llm.complete(["p"], [], [], {})
