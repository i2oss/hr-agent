"""Agent loop + HTTP API with the fake LLM (SPEC slice 5, CI additions). No key, no network."""

import uuid

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.agent.fake_scripts import SMOKE, W01, cite
from app.agent.llm import FakeLLM
from app.main import create_app


def sid() -> str:
    return uuid.uuid4().hex


def client_for(settings, scripts=None, **app_kwargs):
    llm = FakeLLM(scripts) if scripts is not None else FakeLLM()
    app = create_app(settings, in_memory_mcp=True, llm=llm, **app_kwargs)
    return TestClient(app), app, llm


def chat(c, message, speaking_as="E1001", session=None, headers=None):
    r = c.post("/chat", json={"session_id": session or sid(), "speaking_as": speaking_as, "message": message},
               headers=headers or {})
    return r


def tool_steps(trace):
    return [s for s in trace["steps"] if s["kind"] == "tool"]


# ---------------------------------------------------------------- W01 end to end

def test_w01_gold_sequence_pause_confirm_and_mock_id(settings):
    c, app, _ = client_for(settings)
    with c:
        s = sid()
        r = chat(c, W01, session=s).json()
        assert [t["tool"] for t in tool_steps(r["trace"])] == [
            "lookup_employee_profile", "check_pto_balance", "search_policy", "check_policy_compliance"]
        assert r["pending_action"]["tool"] == "draft_manager_message"
        preview = r["pending_action"]["preview"]
        assert preview["to"]["name"] == "Jordan Lee" and "Nov 11" in preview["body"]
        # the injected Requester shows in the Trace args
        assert all(t["args"]["requester_id"] == "E1001" and t["args"]["session_id"] == s
                   for t in tool_steps(r["trace"]) if t["server"] == "hr")
        pause = [x for x in r["trace"]["steps"] if x["kind"] == "confirmation"]
        assert len(pause) == 1 and pause[0]["summary"].startswith("⏸")
        assert r["answer"]["policy_facts"] and r["answer"].get("verification_note") is None
        assert app.state.store.messages == {}  # nothing executed before Confirm

        done = c.post(f"/chat/actions/{r['pending_action']['action_id']}", json={"decision": "confirm"}).json()
    assert done["action_result"] == {"tool": "draft_manager_message", "id": "MSG-MOCK-0001", "mock": True,
                                     "status": "confirmed"}
    assert [x["status"] for x in done["trace"]["steps"] if x["kind"] == "confirmation"][-1] == "confirmed"
    assert tool_steps(done["trace"])[-1]["tool"] == "draft_manager_message"
    assert done["trace"]["totals"]["tool_calls"] == 5
    assert app.state.store.messages[s][0]["id"] == "MSG-MOCK-0001"


def test_w01_citations_pass_the_real_check(settings):
    c, _, _ = client_for(settings)
    with c:
        r = chat(c, W01).json()
    checks = [x for x in r["trace"]["steps"] if x["kind"] == "citation_check"]
    assert checks[-1]["status"] == "ok"
    sources = {x["tool"] for f in r["answer"]["policy_facts"] for x in f["data_sources"]}
    assert sources == {"check_pto_balance", "check_policy_compliance"}


def test_cancel_changes_nothing(settings):
    c, app, llm = client_for(settings)
    with c:
        r = chat(c, W01).json()
        done = c.post(f"/chat/actions/{r['pending_action']['action_id']}", json={"decision": "cancel"}).json()
    assert done["action_result"]["status"] == "cancelled" and done["action_result"]["id"] is None
    assert app.state.store.messages == {}
    assert "declined" in llm.calls[-1]["last"]["content"][0]["text"]


def test_new_message_while_pending_cancels_the_action(settings):
    c, app, llm = client_for(settings)
    with c:
        s = sid()
        r = chat(c, W01, session=s).json()
        r2 = chat(c, SMOKE, session=s).json()
        stale = c.post(f"/chat/actions/{r['pending_action']['action_id']}", json={"decision": "confirm"})
    assert stale.status_code == 404
    assert any(x["kind"] == "confirmation" and x["status"] == "cancelled" for x in r2["trace"]["steps"])
    assert app.state.store.messages == {}
    first_call_of_turn_2 = next(cl for cl in llm.calls if cl["prompt"] == SMOKE)
    assert "cancelled" in first_call_of_turn_2["last"]["content"][0]["text"]


# ---------------------------------------------------------------- citation check

SEARCH = {"tool_calls": [{"name": "search_policy", "input": {"query": "PTO carryover unused days"}}]}


def test_non_verbatim_snippet_is_retried_then_removed_with_a_note(settings):
    bad = {"final": {"lead": "5 days.", "policy_facts": [{"text": "Invented fact.", "citations": [
        {"doc_id": "RSE-PTO-01", "section": "5.1", "snippet": "you may carry over unlimited days"}]}]}}
    c, _, llm = client_for(settings, {"q": [SEARCH, bad, bad]})
    with c:
        r = chat(c, "q").json()
    assert r["answer"]["policy_facts"] == []
    assert r["answer"]["verification_note"].startswith("Some details couldn't be verified")
    checks = [x for x in r["trace"]["steps"] if x["kind"] == "citation_check"]
    assert [x["status"] for x in checks] == ["retry", "removed"]
    assert checks[-1]["output"]["removed"] == ["Invented fact."]
    assert "Citation check failed" in llm.calls[-1]["last"]["content"][0]["text"]


def test_retry_that_fixes_the_citation_keeps_the_fact(settings):
    bad = {"final": {"lead": "5 days.", "policy_facts": [{"text": "Cap is 5.", "citations": [
        {"doc_id": "RSE-PTO-01", "section": "5.1", "snippet": "paraphrase"}]}]}}

    def good(m):
        return {"final": {"lead": "5 days.", "policy_facts": [
            {"text": "Cap is 5.", "citations": cite(m, [("RSE-PTO-01", "5.1")])}]}}

    c, _, _ = client_for(settings, {"q": [SEARCH, bad, good]})
    with c:
        r = chat(c, "q").json()
    assert len(r["answer"]["policy_facts"]) == 1 and "verification_note" not in r["answer"]


def test_data_source_that_did_not_run_is_removed(settings):
    claim = {"final": {"lead": "x", "policy_facts": [
        {"text": "You have 11 days.", "data_sources": [{"tool": "check_pto_balance"}]}]}}
    c, _, _ = client_for(settings, {"q": [claim, claim]})
    with c:
        r = chat(c, "q").json()
    assert r["answer"]["policy_facts"] == [] and r["answer"]["verification_note"]


def test_invalid_final_answer_gets_one_retry(settings):
    c, _, _ = client_for(settings, {"q": [{"final": "not json"}, {"final": {"lead": "Fixed."}}]})
    with c:
        r = chat(c, "q").json()
    assert r["answer"]["lead"] == "Fixed."
    assert any(x["kind"] == "error" and x["status"] == "retry" for x in r["trace"]["steps"])


# ---------------------------------------------------------------- guardrails

def test_policy_server_down_reports_tool_unavailable_and_no_policy_facts(settings):
    def answer(m):
        return {"final": {"lead": "5 days.", "policy_facts": [
            {"text": "Cap is 5.", "citations": [{"doc_id": "RSE-PTO-01", "section": "5.1",
                                                  "snippet": "You can carry over up to 5 unused PTO days"}]}]}}

    c, app, _ = client_for(settings, {"q": [SEARCH, answer, answer]})
    with c:
        chat(c, "warm up")  # discover tools while both servers are up
        app.state.hub.targets["policy"] = "http://127.0.0.1:9/mcp/policy/"
        app.state.hub.timeout_s = 2
        r = chat(c, "q").json()
    step = tool_steps(r["trace"])[0]
    assert step["status"] == "error" and step["output"]["error"]["code"] == "TOOL_UNAVAILABLE"
    assert "retry" in step["summary"]
    assert r["answer"]["policy_facts"] == []


def test_not_set_plus_missing_argument_forces_one_clarification(settings):
    ask = {"tool_calls": [{"name": "check_pto_balance", "input": {}}]}
    c, _, llm = client_for(settings, {"How many PTO days do I have left?": [ask, {"final": {"lead": "Let me check."}}]})
    with c:
        r = chat(c, "How many PTO days do I have left?", speaking_as=None).json()
    assert "Speaking as" in r["answer"]["clarification"]["question"]
    assert any(x["kind"] == "clarification" for x in r["trace"]["steps"])
    assert llm.calls[-1]["tools"] == []  # no more tool calls after the forced Clarification


def test_injected_requester_overwrites_what_the_model_wrote(settings):
    spoof = {"tool_calls": [{"name": "check_pto_balance", "input": {"employee_id": "E1001",
                                                                   "requester_id": "E1009"}}]}
    c, _, _ = client_for(settings, {"q": [spoof, {"final": {"lead": "Can't share that."}}]})
    with c:
        r = chat(c, "q", speaking_as="E1004").json()
    step = tool_steps(r["trace"])[0]
    assert step["args"]["requester_id"] == "E1004"
    assert step["output"]["error"]["code"] == "NOT_PERMITTED"


def test_tool_limit_forces_a_final_answer(settings):
    loop_forever = {"tool_calls": [{"name": "search_policy", "input": {"query": "pto"}}]}
    c, _, llm = client_for(settings, {"q": [loop_forever] * 20 + [{"final": {"lead": "Stopped early."}}]})
    with c:
        r = chat(c, "q").json()
    assert r["trace"]["totals"]["tool_calls"] == 8
    assert llm.calls[-1]["tools"] == []


# ---------------------------------------------------------------- API rules and limits

def test_changed_speaking_as_is_409(settings):
    c, _, _ = client_for(settings)
    with c:
        s = sid()
        assert chat(c, "hi", session=s).status_code == 200
        assert chat(c, "hi", speaking_as="E1002", session=s).status_code == 409


def test_config_lists_eleven_personas(settings):
    c, _, _ = client_for(settings)
    with c:
        cfg = c.get("/config").json()
    assert cfg["demo_today"] == "2026-11-02" and len(cfg["personas"]) == 11
    assert cfg["personas"][0] == {"id": "E1001", "name": "Maya Chen", "title": "Structural Engineer II",
                                  "office": "Denver"}


@pytest.fixture
def limited(settings):
    settings.rate_limits_enabled = True
    settings.rate_limit_per_ip = 2
    settings.eval_bypass_key = SecretStr("let-me-in")
    return settings


def test_rate_limit_returns_429_and_bypass_skips_it(limited):
    c, _, _ = client_for(limited)
    with c:
        assert [chat(c, "hi").status_code for _ in range(3)] == [200, 200, 429]
        assert chat(c, "hi").json()["detail"] == "Demo limit reached, please try again later."
        assert chat(c, "hi", headers={"X-Eval-Bypass": "let-me-in"}).status_code == 200
        assert chat(c, "hi", headers={"X-Eval-Bypass": "wrong"}).status_code == 429


def test_message_length_and_turn_caps(limited):
    limited.rate_limit_per_ip = 100
    limited.max_message_chars = 10
    limited.max_turns_per_session = 1
    c, _, _ = client_for(limited)
    with c:
        assert chat(c, "x" * 11).status_code == 429
        s = sid()
        assert chat(c, "hi", session=s).status_code == 200
        assert chat(c, "hi", session=s).status_code == 429


def test_daily_cap(limited):
    limited.rate_limit_per_ip = 100
    limited.daily_message_cap = 1
    c, _, _ = client_for(limited)
    with c:
        assert [chat(c, "hi").status_code for _ in range(2)] == [200, 429]


def test_chat_page_is_served_at_root(settings):
    c, _, _ = client_for(settings)
    with c:
        r = c.get("/")
        js = c.get("/app.js")
    assert r.status_code == 200 and "FICTIONAL" in r.text and "Speaking as" in r.text
    assert js.status_code == 200 and "chat/actions/" in js.text
