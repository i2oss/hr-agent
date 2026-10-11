"""LLM adapters (SPEC §3.6), chosen by LLM_PROVIDER.

- AnthropicLLM: the native SDK, strict tool schemas, prompt caching, structured output for the
  final answer. Never Claude behind Anthropic's OpenAI-compatible endpoint (test-only, ignores strict).
- OpenAICompatLLM: the openai SDK plus base_url (Groq, OpenRouter, Gemini, Ollama).
- FakeLLM: replays scripted tool calls and answers, for CI and tests (no key, no network).

Conversation messages are provider-neutral, in Anthropic's block shape:
  {"role": "user"|"assistant", "content": [{"type": "text"|"tool_use"|"tool_result", ...}]}
"""

from __future__ import annotations

import itertools
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

from app.agent.answer import strict_schema
from app.agent.mcp_client import ToolSpec

if TYPE_CHECKING:
    from app.config import Settings

Message = dict[str, Any]
MAX_TOKENS = 4096


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict[str, Any]


@dataclass
class LLMResponse:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0


class LLM(Protocol):
    provider: str
    model: str

    async def complete(self, system: Sequence[str], messages: list[Message], tools: list[ToolSpec],
                       answer_schema: dict[str, Any]) -> LLMResponse: ...


# ---------------------------------------------------------------- Anthropic

class AnthropicLLM:
    provider = "anthropic"

    def __init__(self, model: str, api_key: str | None):
        import anthropic

        self.model = model
        self._client = anthropic.AsyncAnthropic(api_key=api_key, max_retries=2, timeout=60.0)
        self._structured = True

    def _tools(self, tools: list[ToolSpec]) -> list[dict[str, Any]]:
        return [{"name": t.name, "description": t.description, "input_schema": strict_schema(t.input_schema),
                 "strict": True} for t in tools]

    async def complete(self, system: Sequence[str], messages: list[Message], tools: list[ToolSpec],
                       answer_schema: dict[str, Any]) -> LLMResponse:
        import anthropic

        # The first system block is stable across sessions and cached together with the tools; the
        # per-session block (Demo Date, Requester) comes after the breakpoint.
        sys_blocks: list[dict[str, Any]] = [{"type": "text", "text": system[0], "cache_control": {"type": "ephemeral"}}]
        sys_blocks += [{"type": "text", "text": s} for s in system[1:]]
        kwargs: dict[str, Any] = {"model": self.model, "max_tokens": MAX_TOKENS, "temperature": 0,
                                  "system": sys_blocks, "messages": messages}
        if tools:
            kwargs["tools"] = self._tools(tools)
        if self._structured:
            kwargs["output_config"] = {"format": {"type": "json_schema", "schema": answer_schema}}
        try:
            r = await self._client.messages.create(**kwargs)
        except anthropic.BadRequestError as e:
            if not self._structured or "output_config" not in str(e):
                raise
            self._structured = False  # model doesn't take structured output: parse JSON instead
            kwargs.pop("output_config")
            r = await self._client.messages.create(**kwargs)
        text = "".join(b.text for b in r.content if b.type == "text")
        calls = [ToolCall(b.id, b.name, dict(b.input)) for b in r.content if b.type == "tool_use"]
        return LLMResponse(text, calls, r.usage.input_tokens, r.usage.output_tokens)


# ---------------------------------------------------------------- OpenAI-compatible

class OpenAICompatLLM:
    provider = "openai_compat"

    def __init__(self, model: str, api_key: str | None, base_url: str | None):
        import openai

        self.model = model
        self._client = openai.AsyncOpenAI(api_key=api_key or "none", base_url=base_url)

    @staticmethod
    def _convert(system: Sequence[str], messages: list[Message]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = [{"role": "system", "content": "\n\n".join(system)}]
        for m in messages:
            texts = [b["text"] for b in m["content"] if b["type"] == "text"]
            if m["role"] == "assistant":
                calls = [{"id": b["id"], "type": "function",
                          "function": {"name": b["name"], "arguments": json.dumps(b["input"])}}
                         for b in m["content"] if b["type"] == "tool_use"]
                msg: dict[str, Any] = {"role": "assistant", "content": "\n".join(texts) or None}
                if calls:
                    msg["tool_calls"] = calls
                out.append(msg)
            else:
                for b in m["content"]:
                    if b["type"] == "tool_result":
                        out.append({"role": "tool", "tool_call_id": b["tool_use_id"], "content": b["content"]})
                if texts:
                    out.append({"role": "user", "content": "\n".join(texts)})
        return out

    async def complete(self, system: Sequence[str], messages: list[Message], tools: list[ToolSpec],
                       answer_schema: dict[str, Any]) -> LLMResponse:
        sys = [*system, "When you give your final answer, reply with only a JSON object matching this schema:\n"
               + json.dumps(answer_schema)]
        kwargs: dict[str, Any] = {"model": self.model, "temperature": 0, "max_tokens": MAX_TOKENS,
                                  "messages": self._convert(sys, messages)}
        if tools:
            kwargs["tools"] = [{"type": "function", "function": {"name": t.name, "description": t.description,
                                                                 "parameters": t.input_schema}} for t in tools]
        r = await self._client.chat.completions.create(**kwargs)
        msg = r.choices[0].message
        calls = [ToolCall(c.id, c.function.name, json.loads(c.function.arguments or "{}"))
                 for c in (msg.tool_calls or []) if c.type == "function"]
        usage = r.usage
        return LLMResponse(msg.content or "", calls, usage.prompt_tokens if usage else 0,
                           usage.completion_tokens if usage else 0)


# ---------------------------------------------------------------- Fake (CI and tests)

ScriptStep = dict[str, Any] | Callable[[list[Message]], dict[str, Any]]


def last_prompt(messages: list[Message]) -> tuple[str, int]:
    """The latest real user message (not a loop note, which starts with '[') and how many assistant
    turns followed it."""
    for i in range(len(messages) - 1, -1, -1):
        m = messages[i]
        if m["role"] != "user":
            continue
        texts = [b["text"] for b in m["content"] if b["type"] == "text" and not b["text"].startswith("[")]
        if texts:
            return texts[-1], sum(1 for x in messages[i + 1:] if x["role"] == "assistant")
    return "", 0


class FakeLLM:
    """Replays a script per prompt. Each step is {"tool_calls": [{"name", "input"}]}, {"final": {...}}
    or a callable(messages) -> step. Steps are indexed by the number of assistant turns since the prompt,
    so a confirm/cancel resume continues the same script."""

    provider = "fake"

    def __init__(self, scripts: dict[str, list[ScriptStep]] | None = None, model: str = "fake-llm"):
        self.model = model
        self.scripts = scripts if scripts is not None else default_scripts()
        self.calls: list[dict[str, Any]] = []
        self._ids = itertools.count(1)

    async def complete(self, system: Sequence[str], messages: list[Message], tools: list[ToolSpec],
                       answer_schema: dict[str, Any]) -> LLMResponse:
        prompt, index = last_prompt(messages)
        self.calls.append({"prompt": prompt, "index": index, "tools": [t.name for t in tools],
                           "last": messages[-1] if messages else None})
        script = self.scripts.get(prompt)
        if script is None:
            step: dict[str, Any] = {"final": {"lead": "(fake LLM) I have no script for that message."}}
        else:
            raw = script[min(index, len(script) - 1)]
            step = raw(messages) if callable(raw) else raw
        if "tool_calls" in step and tools:
            return LLMResponse("", [ToolCall(f"call_{next(self._ids)}", c["name"], c["input"])
                                    for c in step["tool_calls"]])
        final = step.get("final", {"lead": "(fake LLM) Stopped."})
        return LLMResponse(final if isinstance(final, str) else json.dumps(final))


def default_scripts() -> dict[str, list[ScriptStep]]:
    from app.agent.fake_scripts import SCRIPTS

    return dict(SCRIPTS)


def make_llm(settings: Settings) -> LLM:
    key = settings.llm_api_key.get_secret_value() if settings.llm_api_key else None
    if settings.llm_provider == "anthropic":
        return AnthropicLLM(settings.llm_model, key)
    if settings.llm_provider == "openai_compat":
        return OpenAICompatLLM(settings.llm_model, key, settings.llm_base_url)
    return FakeLLM()
