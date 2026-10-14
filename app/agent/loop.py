"""The hand-rolled agent loop (SPEC §3.6). One user turn:

1. Context: the system prompt, the Demo Date, the Requester, and the session's prior turns.
2. Call the LLM with the tools discovered from both MCP servers; run each tool call through the MCP
   client (10 s timeout, 1 retry for read-only tools, never for Mock Actions, ≤ 8 calls per turn).
3. Confirmation pause: a destructiveHint tool is not executed. The loop stores it as a pending action
   (with an exact preview from a preview_only dry run) and the turn ends with pending_action.
   Confirm executes it and resumes; cancel tells the model "user declined"; a new message cancels it.
4. Forced Clarification: Requester "(not set)" + an hr tool's MISSING_ARGUMENT → exactly one
   Clarification asking for the "Speaking as" picker.
5. Final answer in the FinalAnswer schema; an invalid structure gets one retry naming the error.
6. Citation check; one retry naming the problems; facts that still fail are removed with a note.

History is append-only. Loop notes to the model are user-role text blocks starting with "[".
"""

from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from app.agent.answer import Clarification, FinalAnswer, Recommendation, model_facing_schema
from app.agent.citations import check_answer
from app.agent.llm import LLM, LLMResponse
from app.agent.mcp_client import CallOutcome, McpHub
from app.agent.sessions import PendingAction, Session, TurnContext
from mcp_servers.common.models import Passage

if TYPE_CHECKING:
    from app.config import Settings

MAX_TOOL_CALLS = 8
POLICY_TOOLS = ("search_policy", "get_policy_section")
PROMPT = (Path(__file__).parent / "prompt.md").read_text(encoding="utf-8")
NOT_SET_QUESTION = ("Who are you? Please choose yourself in the \"Speaking as\" picker at the top, so I can "
                    "look up your records.")


@dataclass
class TurnResult:
    answer: FinalAnswer
    pending_action: dict[str, Any] | None = None
    action_result: dict[str, Any] | None = None


def _text(*notes: str) -> dict[str, Any]:
    return {"role": "user", "content": [{"type": "text", "text": n} for n in notes]}


def parse_answer(text: str) -> tuple[FinalAnswer | None, str | None]:
    raw = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", raw, re.S)
    if fenced:
        raw = fenced.group(1)
    elif not raw.startswith("{") and "{" in raw and "}" in raw:
        raw = raw[raw.index("{"): raw.rindex("}") + 1]
    try:
        data = json.loads(raw)
    except ValueError as e:
        return None, f"not valid JSON ({e})"
    if not isinstance(data, dict):
        return None, "the answer must be a JSON object"
    data.pop("verification_note", None)
    try:
        return FinalAnswer.model_validate(data), None
    except ValidationError as e:
        return None, "; ".join(f"{'.'.join(map(str, err['loc']))}: {err['msg']}" for err in e.errors())


def summarise(tool: str, o: CallOutcome) -> tuple[str, list[str] | None]:
    out = o.output
    if not o.ok:
        err = out.get("error", {}) if isinstance(out, dict) else {}
        return f"{err.get('code', o.error_code)}: {err.get('message', '')}".strip(), None
    if tool in POLICY_TOOLS:
        sources = [f"{p['doc_id']} §{p['section']}" for p in out.get("passages", [])]
        if out.get("evidence") == "none":
            return "no evidence in the corpus (evidence: none)", []
        return f"{len(sources)} passage(s)", sources
    if tool == "check_pto_balance":
        return f"{out['available']} days available (as of {out['as_of']})", None
    if tool == "lookup_employee_profile":
        mgr = (out.get("manager") or {}).get("name", "no manager")
        return f"{out['name']}, {out['title']}, {out['office']['city']}; manager {mgr}", None
    if tool == "check_policy_compliance":
        c = out.get("computed", {})
        extra = f", {c['working_days']} working days" if "working_days" in c else ""
        return f"{out['outcome']}, approver {out.get('approver') or 'none'}{extra}", None
    if tool == "lookup_benefits_status":
        return ", ".join(f"{e['plan']}: {e['status']}" for e in out.get("elections", [])) or "no elections", None
    if tool == "list_hr_tickets":
        return f"{len(out.get('tickets', []))} ticket(s)", None
    if "id" in out:
        return f"{out['id']} (mock)", None
    return "ok", None


class AgentLoop:
    def __init__(self, hub: McpHub, llm: LLM, settings: Settings, prompt: str = PROMPT):
        self.hub = hub
        self.llm = llm
        self.settings = settings
        self.prompt = prompt
        self.answer_schema = model_facing_schema()

    async def ensure_tools(self) -> None:
        """Discover tools, and re-discover while any server is missing (e.g. it was down at first contact)."""
        if {t.server for t in self.hub.tools.values()} != set(self.hub.targets):
            await self.hub.discover()

    def _system(self, session: Session) -> list[str]:
        today = self.settings.demo_today
        who = session.speaking_as or "(not set)"
        return [self.prompt, f"Today (the Demo Date) is {today:%A} {today.isoformat()}. The Requester is {who}."]

    def _injected(self, session: Session) -> dict[str, Any]:
        return {"requester_id": session.speaking_as, "session_id": session.id}

    # ------------------------------------------------------------ public entry points

    async def chat(self, session: Session, message: str) -> TurnResult:
        await self.ensure_tools()
        snapshot = (len(session.history), session.pending, session.turns)
        try:
            return await self._chat(session, message)
        except BaseException:
            self._rollback(session, snapshot)
            raise

    @staticmethod
    def _rollback(session: Session, snapshot: tuple[int, PendingAction | None, int]) -> None:
        """Keep history well-formed after a failure: no dangling tool_use without its tool_result."""
        length, pending, turns = snapshot
        del session.history[length:]
        session.pending, session.turns = pending, turns

    async def _chat(self, session: Session, message: str) -> TurnResult:
        session.turns += 1
        ctx = TurnContext(turn=session.turns, started=time.perf_counter())
        notes: list[str] = []
        if session.pending:
            p = session.pending
            session.pending = None
            session.trace.add(ctx.turn, "confirmation", f"⏸ {p.tool} cancelled: a new message was sent",
                              tool=p.tool, args=p.args, status="cancelled")
            notes.append(f"[Loop] The pending {p.tool} was cancelled because the user sent a new message. "
                         "Nothing was created or sent.")
        session.history.append(_text(*notes, message))
        return await self._run(session, ctx)

    async def decide(self, session: Session, decision: str) -> TurnResult:
        await self.ensure_tools()
        snapshot = (len(session.history), session.pending, session.turns)
        try:
            return await self._decide(session, decision)
        except BaseException:
            self._rollback(session, snapshot)
            raise

    async def _decide(self, session: Session, decision: str) -> TurnResult:
        assert session.pending is not None
        p = session.pending
        session.pending = None
        ctx = p.context
        ctx.started = time.perf_counter()
        if decision == "confirm":
            session.trace.add(ctx.turn, "confirmation", f"⏸ {p.tool} confirmed by the user; executing",
                              tool=p.tool, status="confirmed")
            o = await self.hub.call(p.tool, p.args, self._injected(session))
            summary, _ = summarise(p.tool, o)
            spec = self.hub.tools[p.tool]
            session.trace.add(ctx.turn, "tool", summary, server=spec.server, tool=p.tool, args=o.args,
                              output=o.output, status="ok" if o.ok else "error", latency_ms=o.latency_ms)
            if o.ok:
                ctx.tools_ok.add(p.tool)
                note = (f"[Confirmation] The user confirmed {p.tool}. Result: {json.dumps(o.output)}. It is a mock "
                        "action saved for this session; nothing was sent. Reply with a short final answer that "
                        "confirms it and gives its ID. Any Policy Fact still needs a citation from a passage "
                        "returned earlier this turn or a data_sources entry; leave out what you can't back.")
                result_info = {"tool": p.tool, "id": o.output.get("id"), "mock": True, "status": "confirmed"}
            else:
                note = (f"[Confirmation] The user confirmed {p.tool}, but it failed: {json.dumps(o.output)}. "
                        "Nothing was created. Say so briefly.")
                result_info = {"tool": p.tool, "id": None, "mock": True, "status": "cancelled"}
        else:
            session.trace.add(ctx.turn, "confirmation", f"⏸ {p.tool} cancelled by the user", tool=p.tool,
                              args=p.args, status="cancelled")
            note = (f"[Confirmation] The user declined {p.tool}. Nothing was created or sent. Reply with a short "
                    "final answer saying nothing was changed.")
            result_info = {"tool": p.tool, "id": None, "mock": True, "status": "cancelled"}
        session.history.append(_text(note))
        result = await self._run(session, ctx, allow_tools=False)
        result.action_result = result_info
        return result

    # ------------------------------------------------------------ the loop

    async def _llm(self, session: Session, ctx: TurnContext, tools_on: bool) -> LLMResponse:
        # Tool definitions are always sent (the history may hold tool_use blocks); tools_on only says
        # whether the model may call one now.
        t0 = time.perf_counter()
        r = await self.llm.complete(self._system(session), session.history, list(self.hub.tools.values()),
                                    self.answer_schema, allow_tool_calls=tools_on)
        ms = int((time.perf_counter() - t0) * 1000)
        what = (f"→ {len(r.tool_calls)} tool call(s): {', '.join(c.name for c in r.tool_calls)}" if r.tool_calls
                else "→ answer")
        session.trace.add(ctx.turn, "llm", f"{self.llm.model} {what}", latency_ms=ms,
                          output={"input_tokens": r.input_tokens, "output_tokens": r.output_tokens})
        return r

    async def _run(self, session: Session, ctx: TurnContext, allow_tools: bool = True) -> TurnResult:
        forced_clarification = False
        limit_noted = False
        try:
            while True:
                tools_on = allow_tools and ctx.tool_calls < MAX_TOOL_CALLS
                if allow_tools and not tools_on and not limit_noted:
                    limit_noted = True
                    session.history.append(_text(
                        f"[Loop] Tool limit reached ({MAX_TOOL_CALLS} calls this turn). Give your final answer now "
                        "from what you have, and say you stopped early."))
                    session.trace.add(ctx.turn, "error", f"stopped early: {MAX_TOOL_CALLS} tool calls this turn",
                                      status="error")
                resp = await self._llm(session, ctx, tools_on)
                if resp.tool_calls and tools_on:
                    forced_clarification |= await self._run_tools(session, ctx, resp)
                    if forced_clarification or session.pending:
                        allow_tools = False
                    continue
                answer = await self._finalise(session, ctx, resp)
                if forced_clarification and not answer.clarification:
                    answer = answer.model_copy(update={"clarification": Clarification(question=NOT_SET_QUESTION),
                                                       "escalation": None, "refusal": None})
                if answer.escalation:
                    session.trace.add(ctx.turn, "escalation",
                                      f"{answer.escalation.trigger}: {answer.escalation.reason}")
                pending = None
                if session.pending:
                    p = session.pending
                    pending = {"action_id": p.action_id, "tool": p.tool, "preview": p.preview}
                return TurnResult(answer, pending_action=pending)
        finally:
            session.trace.totals.total_ms += int((time.perf_counter() - ctx.started) * 1000)
            session.trace.totals.model = self.llm.model

    async def _run_tools(self, session: Session, ctx: TurnContext, resp: LLMResponse) -> bool:
        """Run one assistant message's tool calls. Returns True if a Clarification is now forced."""
        blocks: list[dict[str, Any]] = ([{"type": "text", "text": resp.text}] if resp.text else [])
        blocks += [{"type": "tool_use", "id": c.id, "name": c.name, "input": c.input} for c in resp.tool_calls]
        session.history.append({"role": "assistant", "content": blocks})
        results: list[dict[str, Any]] = []
        notes: list[str] = []
        clarify = False
        for call in resp.tool_calls:
            spec = self.hub.tools.get(call.name)
            if spec is None or ctx.tool_calls >= MAX_TOOL_CALLS or call.error:
                why = (f"unknown tool {call.name}" if spec is None else call.error if call.error
                       else f"tool limit ({MAX_TOOL_CALLS}) reached")
                session.trace.add(ctx.turn, "error", why, tool=call.name, args=call.input, status="error")
                results.append(self._result(call.id, {"error": {"code": "TOOL_ERROR", "message": why}}, True))
                continue
            ctx.tool_calls += 1
            if spec.destructive:
                results.append(await self._pause(session, ctx, call.id, call.name, call.input))
                continue
            o = await self.hub.call(call.name, call.input, self._injected(session))
            summary, sources = summarise(call.name, o)
            if o.retried:
                summary += f" (after {o.attempts - 1} retry)"
            session.trace.add(ctx.turn, "tool", summary, server=spec.server, tool=call.name, args=o.args,
                              output=o.output, sources=sources, latency_ms=o.latency_ms,
                              status="ok" if o.ok else ("retry" if o.retried and not o.unavailable else "error"))
            if o.ok:
                ctx.tools_ok.add(call.name)
                if call.name in POLICY_TOOLS:
                    ctx.passages += [Passage.model_validate(p) for p in o.output.get("passages", [])]
            elif o.error_code == "MISSING_ARGUMENT" and spec.server == "hr" and session.speaking_as is None:
                clarify = True
            results.append(self._result(call.id, o.output, not o.ok))
        if clarify:
            session.trace.add(ctx.turn, "clarification", "forced: Requester (not set) + MISSING_ARGUMENT")
            notes.append("[Loop] The Requester is (not set), so personal records can't be looked up. Ask exactly "
                         "one Clarification: ask the user to choose who they are in the \"Speaking as\" picker. "
                         "Give your final answer now with `clarification` set.")
        session.history.append({"role": "user", "content": results + [{"type": "text", "text": n} for n in notes]})
        return clarify

    @staticmethod
    def _result(tool_use_id: str, output: Any, is_error: bool) -> dict[str, Any]:
        return {"type": "tool_result", "tool_use_id": tool_use_id, "content": json.dumps(output),
                "is_error": is_error}

    async def _pause(self, session: Session, ctx: TurnContext, call_id: str, name: str,
                     args: dict[str, Any]) -> dict[str, Any]:
        spec = self.hub.tools[name]
        if session.pending:
            msg = "Only one Mock Action can await Confirmation at a time."
            session.trace.add(ctx.turn, "error", msg, tool=name, args=args, status="error")
            return self._result(call_id, {"error": {"code": "TOOL_ERROR", "message": msg}}, True)
        preview = await self.hub.call(name, args, {**self._injected(session), "preview_only": True})
        if not preview.ok:
            summary, _ = summarise(name, preview)
            session.trace.add(ctx.turn, "tool", summary, server=spec.server, tool=name, args=preview.args,
                              output=preview.output, status="error", latency_ms=preview.latency_ms)
            return self._result(call_id, preview.output, True)
        model_args = {k: v for k, v in preview.args.items() if k != "preview_only"}
        pending = PendingAction(action_id=uuid.uuid4().hex[:12], tool=name, args=model_args,
                                preview=preview.output, context=ctx)
        session.pending = pending
        session.trace.add(ctx.turn, "confirmation", f"⏸ {name} awaiting the user's Confirmation (not executed)",
                          server=spec.server, tool=name, args=model_args, output=preview.output,
                          latency_ms=preview.latency_ms)
        return self._result(call_id, {"status": "awaiting_confirmation", "preview": preview.output,
                                      "note": "Not executed. The user sees a Confirm card with this preview. Write "
                                              "your final answer now and ask them to confirm; don't say it was done."},
                            False)

    async def _finalise(self, session: Session, ctx: TurnContext, resp: LLMResponse) -> FinalAnswer:
        session.history.append({"role": "assistant", "content": [{"type": "text", "text": resp.text or "{}"}]})
        answer, error = parse_answer(resp.text)
        if error:
            session.trace.add(ctx.turn, "error", f"final answer invalid, retrying: {error}", status="retry")
            session.history.append(_text(f"[Loop] Your final answer was not valid: {error}. Reply again with only "
                                         "the corrected JSON final answer."))
            retry = await self._llm(session, ctx, tools_on=False)
            session.history.append({"role": "assistant", "content": [{"type": "text", "text": retry.text or "{}"}]})
            answer, error = parse_answer(retry.text)
            if answer is None:
                session.trace.add(ctx.turn, "error", f"final answer still invalid: {error}", status="error")
                return FinalAnswer(lead="Sorry, I couldn't put together a reliable answer this time.",
                                   recommendations=[Recommendation(text="Try rephrasing, or ask the HR Service "
                                                                        "Desk (hr@ridgeline.example).")])
        assert answer is not None
        check = check_answer(answer, ctx.passages, ctx.tools_ok)
        n_cites = sum(len(f.citations) + len(f.data_sources) for f in answer.policy_facts)
        if check.ok:
            session.trace.add(ctx.turn, "citation_check", f"{n_cites} citation(s) verified")
            return answer
        session.trace.add(ctx.turn, "citation_check", f"{len(check.problems)} problem(s); asking for a fix",
                          output={"problems": check.problems}, status="retry")
        session.history.append(_text("[Loop] Citation check failed:\n- " + "\n- ".join(check.problems) +
                                     "\nFix or drop those facts. Quote snippets verbatim from passages returned "
                                     "this turn. Reply with the full corrected JSON final answer."))
        retry = await self._llm(session, ctx, tools_on=False)
        session.history.append({"role": "assistant", "content": [{"type": "text", "text": retry.text or "{}"}]})
        fixed, _ = parse_answer(retry.text)
        if fixed is not None:
            answer = fixed
        check = check_answer(answer, ctx.passages, ctx.tools_ok)
        if check.ok:
            session.trace.add(ctx.turn, "citation_check", "verified after one retry")
            return answer
        session.trace.add(ctx.turn, "citation_check", f"removed {len(check.failed)} unverified fact(s)",
                          output={"removed": check.removed_texts(), "problems": check.problems}, status="removed")
        return check.remove_failures(answer)

