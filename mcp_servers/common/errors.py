"""Tool errors (SPEC §3.4): MCP isError plus {code, message, hint}.

A tool raises ToolFailure; the @coded_errors decorator turns it into an isError result whose
structured content is {"error": {code, message, hint}} and whose text is the same JSON, so the
model sees the code and the hint. "No evidence" is not an error and never goes through here.
"""

from __future__ import annotations

import functools
import json
from collections.abc import Awaitable, Callable
from typing import Literal, ParamSpec, TypeVar

from mcp.types import CallToolResult, TextContent

ErrorCode = Literal[
    "EMPLOYEE_NOT_FOUND",
    "MISSING_ARGUMENT",
    "NOT_PERMITTED",
    "UNKNOWN_DOCUMENT_OR_SECTION",
    "TOOL_UNAVAILABLE",
]

P = ParamSpec("P")
R = TypeVar("R")


class ToolFailure(Exception):
    def __init__(self, code: ErrorCode, message: str, hint: str):
        super().__init__(message)
        self.code, self.message, self.hint = code, message, hint

    def payload(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message, "hint": self.hint}


def error_result(failure: ToolFailure) -> CallToolResult:
    body = {"error": failure.payload()}
    return CallToolResult(content=[TextContent(type="text", text=json.dumps(body))],
                          structured_content=body, is_error=True)


def coded_errors[**P, R](fn: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
    """Wrap an async tool so a ToolFailure becomes a coded isError result. functools.wraps keeps
    the signature and return annotation, so MCPServer still derives the input and output schemas."""

    @functools.wraps(fn)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return await fn(*args, **kwargs)
        except ToolFailure as f:
            return error_result(f)  # type: ignore[return-value]  # convert_result passes it through

    return wrapper
