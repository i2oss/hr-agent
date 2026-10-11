"""The agent's MCP client (SPEC §3.4, §3.6): discovery from both servers, routing, timeouts,
retries, argument injection and schema stripping.

Every tool call is a real MCP call through `mcp.Client`: over Streamable HTTP to the URLs in
MCP_POLICY_URL / MCP_HR_URL in production, or to an in-memory server object in tests. No tool is
ever called as a direct Python function.
"""

from __future__ import annotations

import asyncio
import copy
import json
import time
from dataclasses import dataclass, field
from typing import Any, Literal

from mcp import Client

ServerName = Literal["policy", "hr"]
INJECTED_ARGS = ("requester_id", "session_id", "preview_only")
TIMEOUT_S = 10.0
READ_RETRIES = 1


@dataclass(frozen=True)
class ToolSpec:
    name: str
    server: ServerName
    description: str
    input_schema: dict[str, Any]  # model-facing: injected arguments removed
    destructive: bool
    injectable: tuple[str, ...]


@dataclass
class CallOutcome:
    ok: bool
    output: dict[str, Any]
    latency_ms: int
    attempts: int
    error_code: str | None = None
    unavailable: bool = False
    retried: bool = False
    extra: dict[str, Any] = field(default_factory=dict)


def strip_injected(schema: dict[str, Any]) -> tuple[dict[str, Any], tuple[str, ...]]:
    s = copy.deepcopy(schema)
    props = s.get("properties", {})
    found = tuple(k for k in INJECTED_ARGS if k in props)
    for k in found:
        props.pop(k)
    if "required" in s:
        s["required"] = [r for r in s["required"] if r not in found]
    return s, found


class McpHub:
    """Routes tool calls to the server that owns each tool. `targets` maps server name to whatever
    `mcp.Client` accepts: a URL (Streamable HTTP) or a server object (in-memory)."""

    def __init__(self, targets: dict[ServerName, Any], timeout_s: float = TIMEOUT_S):
        self.targets = targets
        self.timeout_s = timeout_s
        self.tools: dict[str, ToolSpec] = {}

    async def list_tools(self, server: ServerName) -> list[Any]:
        async with asyncio.timeout(self.timeout_s), Client(self.targets[server]) as c:
            return list((await c.list_tools()).tools)

    async def discover(self) -> dict[str, ToolSpec]:
        """list_tools() on each server; a server that is down contributes no tools."""
        found: dict[str, ToolSpec] = {}
        for server in self.targets:
            try:
                tools = await self.list_tools(server)
            except Exception:  # noqa: BLE001 - a down server is reported, not raised
                continue
            for t in tools:
                schema, injectable = strip_injected(t.input_schema)
                ann = t.annotations
                found[t.name] = ToolSpec(name=t.name, server=server, description=t.description or "",
                                         input_schema=schema, destructive=bool(ann and ann.destructive_hint),
                                         injectable=injectable)
        if found:
            self.tools = found
        return found

    async def health(self) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for server in self.targets:
            try:
                names = sorted(t.name for t in await self.list_tools(server))
                out[server] = {"ok": bool(names), "tools": names}
            except Exception as e:  # noqa: BLE001
                out[server] = {"ok": False, "tools": [], "error": type(e).__name__}
        return out

    async def call(self, name: str, model_args: dict[str, Any], injected: dict[str, Any]) -> CallOutcome:
        spec = self.tools[name]
        # Injected arguments overwrite anything the model wrote.
        args = {k: v for k, v in model_args.items() if k not in INJECTED_ARGS}
        args |= {k: v for k, v in injected.items() if k in spec.injectable}
        attempts_allowed = 1 if spec.destructive else 1 + READ_RETRIES
        start = time.perf_counter()
        last_error = ""
        for attempt in range(1, attempts_allowed + 1):
            try:
                async with asyncio.timeout(self.timeout_s), Client(self.targets[spec.server]) as c:
                    r = await c.call_tool(name, args)
            except Exception as e:  # noqa: BLE001 - transport failure or timeout
                last_error = f"{type(e).__name__}: {e}"[:300]
                continue
            ms = int((time.perf_counter() - start) * 1000)
            if r.is_error:
                output = r.structured_content or _text_json(r)
                code = (output.get("error") or {}).get("code") if isinstance(output, dict) else None
                return CallOutcome(False, output, ms, attempt, error_code=code or "TOOL_ERROR",
                                   retried=attempt > 1)
            return CallOutcome(True, r.structured_content or _text_json(r), ms, attempt, retried=attempt > 1)
        ms = int((time.perf_counter() - start) * 1000)
        return CallOutcome(
            False,
            {"error": {"code": "TOOL_UNAVAILABLE",
                       "message": f"The {spec.server} server did not respond ({last_error}).",
                       "hint": "Tell the user this part is unavailable right now. Don't state policy without "
                               "evidence; tools on the other server still work."}},
            ms, attempts_allowed, error_code="TOOL_UNAVAILABLE", unavailable=True, retried=attempts_allowed > 1,
        )


def _text_json(result: Any) -> dict[str, Any]:
    text = "".join(getattr(c, "text", "") for c in result.content)
    try:
        val = json.loads(text)
        return val if isinstance(val, dict) else {"result": val}
    except ValueError:
        return {"text": text}
