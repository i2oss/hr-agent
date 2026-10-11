"""The Trace (SPEC §3.9): the operational record of a run, never chain-of-thought. Kept per session
across turns and returned with every response."""

from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from pydantic import BaseModel

StepKind = Literal["tool", "llm", "citation_check", "clarification", "escalation", "confirmation", "error"]
StepStatus = Literal["ok", "error", "retry", "removed", "confirmed", "cancelled"]


class Step(BaseModel):
    n: int
    turn: int
    kind: StepKind
    server: Literal["policy", "hr"] | None = None
    tool: str | None = None
    args: dict[str, Any] | None = None
    output: Any = None
    summary: str
    sources: list[str] | None = None
    status: StepStatus = "ok"
    latency_ms: int = 0
    started_at: str


class Totals(BaseModel):
    tool_calls: int = 0
    tool_ms: int = 0
    llm_calls: int = 0
    llm_ms: int = 0
    total_ms: int = 0
    model: str = ""


class Trace(BaseModel):
    steps: list[Step] = []
    totals: Totals = Totals()

    def add(self, turn: int, kind: StepKind, summary: str, **fields: Any) -> Step:
        step = Step(n=len(self.steps) + 1, turn=turn, kind=kind, summary=summary,
                    started_at=dt.datetime.now(dt.UTC).isoformat(timespec="milliseconds"), **fields)
        self.steps.append(step)
        if kind == "tool":
            self.totals.tool_calls += 1
            self.totals.tool_ms += step.latency_ms
        elif kind == "llm":
            self.totals.llm_calls += 1
            self.totals.llm_ms += step.latency_ms
        return step
