"""In-app demo limits (SPEC §3.3): per-IP messages per 10 minutes, message length, turns per session,
and a site-wide daily cap. Every limit answers HTTP 429. A request with X-Eval-Bypass: <EVAL_BYPASS_KEY>
skips them (deployed latency runs, the demo runner)."""

from __future__ import annotations

import datetime as dt
import hmac
import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

from app.config import Settings

LIMIT_MESSAGE = "Demo limit reached, please try again later."
WINDOW_S = 600


class Limits:
    def __init__(self, settings: Settings):
        self.s = settings
        self._lock = threading.Lock()
        self._per_ip: dict[str, deque[float]] = defaultdict(deque)
        self._day = dt.datetime.now(dt.UTC).date()
        self._today = 0

    def bypassed(self, request: Request) -> bool:
        if not self.s.rate_limits_enabled:
            return True
        key = self.s.eval_bypass_key.get_secret_value() if self.s.eval_bypass_key else ""
        given = request.headers.get("x-eval-bypass", "")
        return bool(key) and hmac.compare_digest(given, key)

    @staticmethod
    def client_ip(request: Request) -> str:
        fwd = request.headers.get("x-forwarded-for")
        if fwd:
            return fwd.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    def check_message(self, request: Request, message: str, session_turns: int) -> None:
        """Raise 429 if this message is over any limit; otherwise count it."""
        if self.bypassed(request):
            return
        if len(message) > self.s.max_message_chars:
            raise HTTPException(429, f"{LIMIT_MESSAGE} (Messages are limited to {self.s.max_message_chars} "
                                     "characters.)")
        if session_turns >= self.s.max_turns_per_session:
            raise HTTPException(429, f"{LIMIT_MESSAGE} (This conversation reached its "
                                     f"{self.s.max_turns_per_session}-message limit; start a new one.)")
        now = time.monotonic()
        with self._lock:
            today = dt.datetime.now(dt.UTC).date()
            if today != self._day:
                self._day, self._today = today, 0
            if self._today >= self.s.daily_message_cap:
                raise HTTPException(429, LIMIT_MESSAGE)
            q = self._per_ip[self.client_ip(request)]
            while q and now - q[0] > WINDOW_S:
                q.popleft()
            if len(q) >= self.s.rate_limit_per_ip:
                raise HTTPException(429, LIMIT_MESSAGE)
            q.append(now)
            self._today += 1
