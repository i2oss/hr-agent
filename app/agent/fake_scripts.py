"""Scripts for the fake LLM (LLM_PROVIDER=fake): CI's end-to-end W01, and a local demo without a key.

Final answers quote passages that the policy tools actually returned in the conversation, so they
pass the real citation check: the fake replays the tool sequence, not the evidence.
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.agent.llm import Message, ScriptStep

W01 = "Can I take Wednesday to Friday off next week?"
SMOKE = "How many unused PTO days can I carry over?"


def returned_passages(messages: list[Message]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in messages:
        for b in m["content"]:
            if b["type"] == "tool_result" and not b.get("is_error"):
                data = json.loads(b["content"])
                out += data.get("passages", []) if isinstance(data, dict) else []
    return out


def first_sentence(text: str) -> str:
    return re.split(r"(?<=[.!?])\s", text.strip(), maxsplit=1)[0]


def cite(messages: list[Message], wanted: list[tuple[str, str]]) -> list[dict[str, str]]:
    """Citations for the wanted (doc_id, section)s that were returned; else the first passage returned."""
    passages = returned_passages(messages)
    hits = [p for w in wanted for p in passages if (p["doc_id"], p["section"]) == w][:1]
    hits = hits or passages[:1]
    return [{"doc_id": p["doc_id"], "section": p["section"], "snippet": first_sentence(p["text"])} for p in hits]


def _w01_answer(messages: list[Message]) -> dict[str, Any]:
    return {"final": {
        "lead": "Yes: Wed–Fri Nov 11–13 uses 2 PTO days, because Nov 11 is Veterans Day.",
        "policy_facts": [
            {"text": "Company holidays inside your PTO dates aren't deducted; Nov 11 is Veterans Day, so Nov 11–13 "
                     "is 2 PTO days.",
             "citations": cite(messages, [("RSE-HOL-01", "1.3"), ("RSE-PTO-01", "3.2"), ("RSE-HOL-01", "2")]),
             "data_sources": [{"tool": "check_policy_compliance"}]},
            {"text": "You have 11 days available.", "data_sources": [{"tool": "check_pto_balance"}]},
            {"text": "At 3 days or fewer there's no minimum notice; your manager, Jordan Lee, approves.",
             "citations": cite(messages, [("RSE-PTO-01", "4.2"), ("RSE-PTO-01", "4.3"), ("RSE-APR-01", "2")]),
             "data_sources": [{"tool": "check_policy_compliance"}]},
        ],
        "recommendations": [{"text": "Review the drafted message to Jordan Lee and confirm it."}],
    }}


SCRIPTS: dict[str, list[ScriptStep]] = {
    W01: [
        {"tool_calls": [{"name": "lookup_employee_profile", "input": {"employee_id": "E1001"}}]},
        {"tool_calls": [{"name": "check_pto_balance", "input": {"employee_id": "E1001"}}]},
        {"tool_calls": [{"name": "search_policy", "input": {
            "query": "PTO request notice and approval", "doc_ids": ["RSE-PTO-01", "RSE-HOL-01", "RSE-APR-01"]}}]},
        {"tool_calls": [{"name": "check_policy_compliance", "input": {
            "employee_id": "E1001", "request_type": "pto_request",
            "details": {"start_date": "2026-11-11", "end_date": "2026-11-13"}}}]},
        {"tool_calls": [{"name": "draft_manager_message", "input": {
            "employee_id": "E1001", "subject": "PTO request: Wed Nov 11 – Fri Nov 13",
            "body": "Hi Jordan, I'd like to take PTO from Wed Nov 11 to Fri Nov 13 (2 PTO days; Nov 11 is "
                    "Veterans Day). I have 11 days available. Thanks, Maya",
            "citations": [{"doc_id": "RSE-PTO-01", "section": "4.3"}]}}]},
        _w01_answer,
        {"final": {"lead": "Done: your message to Jordan Lee is drafted (mock; nothing was sent).",
                   "recommendations": [{"text": "Submit the request in the HR Portal too."}]}},
    ],
    SMOKE: [
        {"tool_calls": [{"name": "search_policy", "input": {"query": "PTO carryover unused days"}}]},
        lambda m: {"final": {
            "lead": "You can carry over up to 5 unused PTO days.",
            "policy_facts": [{"text": "Up to 5 unused days carry over; days above the cap are forfeited on Dec 31.",
                              "citations": cite(m, [("RSE-PTO-01", "5.1")])}],
        }},
    ],
}
