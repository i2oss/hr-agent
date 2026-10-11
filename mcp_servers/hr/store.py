"""Mock Action store (SPEC §3.10): in memory, per chat session, layered over the seed JSON.

New tickets get HR-MOCK-#### and drafted messages MSG-MOCK-####, from process-wide counters
starting at 0001. Both carry mock: true. Nothing is ever sent. Everything resets on restart.
"""

from __future__ import annotations

import itertools
import threading
from collections import defaultdict
from typing import Any


class MockActionStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tickets = itertools.count(1)
        self._messages = itertools.count(1)
        self.tickets: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.messages: dict[str, list[dict[str, Any]]] = defaultdict(list)

    def add_ticket(self, session_id: str, ticket: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            ticket = {**ticket, "id": f"HR-MOCK-{next(self._tickets):04d}", "mock": True}
            self.tickets[session_id].append(ticket)
        return ticket

    def add_message(self, session_id: str, message: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            message = {**message, "id": f"MSG-MOCK-{next(self._messages):04d}", "mock": True}
            self.messages[session_id].append(message)
        return message

    def session_tickets(self, session_id: str) -> list[dict[str, Any]]:
        return list(self.tickets.get(session_id, []))
