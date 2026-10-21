"""HTTP API (SPEC §3.8): /chat, /chat/actions/{action_id}, /config. (/health lives in app/main.py.)

Identity comes only from speaking_as. A changed speaking_as on an existing session_id is a 409:
the page starts a new session whenever the picker changes. When the LLM provider can't answer (no
credit, an outage), the turn is rolled back and the visitor gets a 503 with a plain message, while the
provider's error goes to the log ("LLM unavailable: …"); /health never calls the LLM, so it stays green.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.agent.answer import FinalAnswer
from app.agent.llm import LLMUnavailable
from app.agent.loop import AgentLoop, TurnResult
from app.agent.sessions import SessionConflict, SessionStore
from app.agent.trace import Trace
from app.api.limits import Limits
from mcp_servers.hr.models import MockData

PERSONAS = [f"E10{n:02d}" for n in range(1, 12)]
LLM_UNAVAILABLE = "The assistant can't reach its language model right now. Please try again in a few minutes."
log = logging.getLogger("uvicorn.error")  # Render's log stream, formatted like the server's own lines


def unavailable(e: LLMUnavailable) -> HTTPException:
    log.error("LLM unavailable: %s", e)
    return HTTPException(503, LLM_UNAVAILABLE)


class ChatRequest(BaseModel):
    session_id: str = Field(min_length=8, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    speaking_as: str | None = None
    message: str = Field(min_length=1)


class ActionRequest(BaseModel):
    decision: Literal["confirm", "cancel"]


class ChatResponse(BaseModel):
    answer: FinalAnswer
    trace: Trace
    pending_action: dict[str, Any] | None = None
    action_result: dict[str, Any] | None = None


def build_router(loop: AgentLoop, sessions: SessionStore, limits: Limits, data: MockData) -> APIRouter:
    router = APIRouter()

    def respond(result: TurnResult, trace: Trace) -> ChatResponse:
        return ChatResponse(answer=result.answer, trace=trace, pending_action=result.pending_action,
                            action_result=result.action_result)

    @router.post("/chat", response_model=ChatResponse, response_model_exclude_none=True)
    async def chat(body: ChatRequest, request: Request) -> ChatResponse:
        if body.speaking_as is not None and body.speaking_as not in data.employees:
            raise HTTPException(422, f"Unknown employee {body.speaking_as}.")
        try:
            session = sessions.get_or_create(body.session_id, body.speaking_as)
        except SessionConflict:
            raise HTTPException(409, "speaking_as changed: start a new session.") from None
        limits.check_message(request, body.message, session.turns)
        async with session.lock:
            try:
                result = await loop.chat(session, body.message)
            except LLMUnavailable as e:
                raise unavailable(e) from None
            return respond(result, session.trace)

    @router.post("/chat/actions/{action_id}", response_model=ChatResponse, response_model_exclude_none=True)
    async def decide(action_id: str, body: ActionRequest) -> ChatResponse:
        session = sessions.find_pending(action_id)
        if session is None:
            raise HTTPException(404, "No pending action with that ID (it may have been cancelled).")
        async with session.lock:
            if not session.pending or session.pending.action_id != action_id:
                raise HTTPException(404, "No pending action with that ID (it may have been cancelled).")
            try:
                result = await loop.decide(session, body.decision)
            except LLMUnavailable as e:
                raise unavailable(e) from None
            return respond(result, session.trace)

    @router.get("/config")
    async def config() -> dict[str, Any]:
        personas = []
        for pid in PERSONAS:
            e = data.employees[pid]
            personas.append({"id": e.id, "name": e.name, "title": e.title, "office": data.offices[e.office_id].city})
        return {"demo_today": loop.settings.demo_today.isoformat(), "model": loop.llm.model, "personas": personas}

    return router
