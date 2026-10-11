"""In-memory chat sessions (SPEC §3.6), keyed by a client-generated session_id.

A session holds the history, the Requester, the turn count, any pending Mock Action and the
Trace. The Mock Action store lives in the hr server, keyed by the same session_id. Everything
resets on restart or cold start, which is why the server runs one uvicorn worker.
"""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass, field
from typing import Any

from app.agent.trace import Trace
from mcp_servers.common.models import Passage


@dataclass
class TurnContext:
    """What the citation check needs: what was returned and what ran during the current turn."""

    turn: int
    passages: list[Passage] = field(default_factory=list)
    tools_ok: set[str] = field(default_factory=set)
    tool_calls: int = 0
    started: float = 0.0


@dataclass
class PendingAction:
    action_id: str
    tool: str
    args: dict[str, Any]
    preview: dict[str, Any]
    context: TurnContext


@dataclass
class Session:
    id: str
    speaking_as: str | None
    history: list[dict[str, Any]] = field(default_factory=list)
    turns: int = 0
    pending: PendingAction | None = None
    trace: Trace = field(default_factory=Trace)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)


class SessionConflict(Exception):
    """speaking_as changed on an existing session: the page must start a new one."""


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}
        self._lock = threading.Lock()

    def get_or_create(self, session_id: str, speaking_as: str | None) -> Session:
        with self._lock:
            s = self._sessions.get(session_id)
            if s is None:
                s = self._sessions[session_id] = Session(id=session_id, speaking_as=speaking_as)
            elif s.speaking_as != speaking_as:
                raise SessionConflict(session_id)
            return s

    def find_pending(self, action_id: str) -> Session | None:
        with self._lock:
            return next((s for s in self._sessions.values() if s.pending and s.pending.action_id == action_id), None)
