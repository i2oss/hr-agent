"""hr MCP server over the in-memory Client (SPEC slice 4): one call per tool, the access rule,
Mock Actions and error codes. requester_id / session_id are passed the way the agent loop injects them."""

import pytest
from mcp import Client

from mcp_servers.hr.server import build_hr_server
from mcp_servers.hr.store import MockActionStore

HR_TOOLS = {"lookup_employee_profile", "check_pto_balance", "lookup_benefits_status", "list_hr_tickets",
            "check_policy_compliance", "draft_manager_message", "create_mock_hr_ticket"}
CITE = [{"doc_id": "RSE-PTO-01", "section": "4.2"}]


@pytest.fixture
def server(settings):
    return build_hr_server(settings, MockActionStore())


async def call(server, tool, args, requester="E1001", session="s1"):
    async with Client(server) as c:
        r = await c.call_tool(tool, {**args, "requester_id": requester, "session_id": session})
    return r


def err(r):
    assert r.is_error, r
    return r.structured_content["error"]["code"]


async def test_lists_seven_tools_with_annotations(server):
    async with Client(server) as c:
        tools = {t.name: t for t in (await c.list_tools()).tools}
    assert set(tools) == HR_TOOLS
    for name, t in tools.items():
        destructive = name in {"draft_manager_message", "create_mock_hr_ticket"}
        assert bool(t.annotations.destructive_hint) is destructive, name
        assert bool(t.annotations.read_only_hint) is (not destructive), name
        assert "requester_id" in t.input_schema["properties"]  # stripped later by the agent's MCP client


# ---------------------------------------------------------------- one call per tool

async def test_lookup_employee_profile(server):
    r = await call(server, "lookup_employee_profile", {"employee_id": "E1001"})
    p = r.structured_content
    assert p["name"] == "Maya Chen" and p["manager"] == {"id": "E1012", "name": "Jordan Lee"}
    assert p["office"]["city"] == "Denver" and p["holiday_calendar"] == "US"
    assert p["director"] == {"id": "E1009", "name": "Marcus Reed"}


async def test_check_pto_balance(server):
    r = await call(server, "check_pto_balance", {"employee_id": "E1001"})
    assert r.structured_content["available"] == 11
    assert r.structured_content["as_of"] == "2026-11-02"


async def test_lookup_benefits_status(server):
    r = await call(server, "lookup_benefits_status", {"employee_id": "E1011", "plan": "Medical PPO"},
                   requester="E1011")
    [e] = r.structured_content["elections"]
    assert (e["status"], e["enrollment_window_end"]) == ("pending", "2026-11-11")


async def test_list_hr_tickets(server):
    r = await call(server, "list_hr_tickets", {"employee_id": "E1010", "status": "open"}, requester="E1010")
    assert [t["id"] for t in r.structured_content["tickets"]] == ["HR-2026-0412"]


async def test_check_policy_compliance(server):
    r = await call(server, "check_policy_compliance", {
        "employee_id": "E1001", "request_type": "pto_request",
        "details": {"start_date": "2026-11-11", "end_date": "2026-11-13"}})
    assert r.structured_content["outcome"] == "allowed_with_approval"
    assert r.structured_content["computed"]["working_days"] == 2


async def test_draft_manager_message(server):
    r = await call(server, "draft_manager_message", {
        "employee_id": "E1001", "subject": "PTO Nov 11–13", "body": "Hi Jordan, …", "citations": CITE})
    out = r.structured_content
    assert out["id"] == "MSG-MOCK-0001" and out["mock"] is True
    assert out["to"] == {"id": "E1012", "name": "Jordan Lee", "email": "jordan.lee@ridgeline.example"}


async def test_create_mock_hr_ticket(server):
    r = await call(server, "create_mock_hr_ticket", {
        "employee_id": "E1002", "category": "remote_work", "subject": "Lisbon Jan 4 – Feb 12",
        "summary": "Work from Lisbon, PT, 2027-01-04 to 2027-02-12.", "priority": "normal",
        "citations": [{"doc_id": "RSE-LOC-01", "section": "4.2"}]}, requester="E1002")
    out = r.structured_content
    assert out["id"] == "HR-MOCK-0001" and out["mock"] is True
    assert out["queue"] == "HR · Cross-Border Review" and out["status"] == "open"


# ---------------------------------------------------------------- access rule (SPEC §3.5)

async def test_maya_cannot_see_daniels_balance(server):
    assert err(await call(server, "check_pto_balance", {"employee_id": "E1002"})) == "NOT_PERMITTED"


async def test_marcus_can_see_maya_profile_balance_and_check_her_pto(server):
    for tool, args in [("lookup_employee_profile", {}), ("check_pto_balance", {}),
                       ("check_policy_compliance", {"request_type": "pto_request",
                                                    "details": {"start_date": "2026-11-30", "end_date": "2026-12-14"}})]:
        r = await call(server, tool, {"employee_id": "E1001", **args}, requester="E1009")
        assert not r.is_error, (tool, r)


async def test_marcus_cannot_see_maya_benefits_or_tickets(server):
    assert err(await call(server, "lookup_benefits_status", {"employee_id": "E1001"}, requester="E1009")) == \
        "NOT_PERMITTED"
    assert err(await call(server, "list_hr_tickets", {"employee_id": "E1001"}, requester="E1009")) == "NOT_PERMITTED"


async def test_marcus_cannot_check_maya_expenses(server):
    r = await call(server, "check_policy_compliance", {
        "employee_id": "E1001", "request_type": "expense_item",
        "details": {"category": "meals", "amount": 10, "currency": "USD", "description": "x"}}, requester="E1009")
    assert err(r) == "NOT_PERMITTED"


async def test_mock_action_for_another_employee_is_not_permitted(server):
    r = await call(server, "draft_manager_message", {
        "employee_id": "E1001", "subject": "s", "body": "b", "citations": []}, requester="E1009")
    assert err(r) == "NOT_PERMITTED"


async def test_priya_cannot_see_maya_even_claiming_to_be_marcus(server):
    r = await call(server, "check_pto_balance", {"employee_id": "E1001"}, requester="E1004")
    assert err(r) == "NOT_PERMITTED"


# ---------------------------------------------------------------- errors

async def test_unknown_employee(server):
    assert err(await call(server, "lookup_employee_profile", {"employee_id": "E9999"})) == "EMPLOYEE_NOT_FOUND"


async def test_missing_employee_id_while_not_set(server):
    r = await call(server, "check_pto_balance", {}, requester=None)
    assert err(r) == "MISSING_ARGUMENT"
    assert "Speaking as" in r.structured_content["error"]["hint"]


async def test_requester_not_set_with_an_employee_id_is_missing_argument(server):
    assert err(await call(server, "check_pto_balance", {"employee_id": "E1001"}, requester=None)) == \
        "MISSING_ARGUMENT"


async def test_missing_compliance_details(server):
    r = await call(server, "check_policy_compliance", {"employee_id": "E1001", "request_type": "pto_request",
                                                        "details": {}})
    assert err(r) == "MISSING_ARGUMENT"


# ---------------------------------------------------------------- Mock Action store

async def test_ids_are_process_wide_and_sessions_are_isolated(server):
    a = await call(server, "create_mock_hr_ticket", {
        "employee_id": "E1001", "category": "pto", "subject": "a", "summary": "a", "priority": "low",
        "citations": []}, session="s1")
    b = await call(server, "create_mock_hr_ticket", {
        "employee_id": "E1001", "category": "pto", "subject": "b", "summary": "b", "priority": "low",
        "citations": []}, session="s2")
    assert (a.structured_content["id"], b.structured_content["id"]) == ("HR-MOCK-0001", "HR-MOCK-0002")
    s1 = await call(server, "list_hr_tickets", {"employee_id": "E1001"}, session="s1")
    s2 = await call(server, "list_hr_tickets", {"employee_id": "E1001"}, session="s2")
    assert [t["id"] for t in s1.structured_content["tickets"]] == ["HR-MOCK-0001"]
    assert [t["id"] for t in s2.structured_content["tickets"]] == ["HR-MOCK-0002"]
    assert s1.structured_content["tickets"][0]["mock"] is True


async def test_preview_only_creates_nothing(server):
    r = await call(server, "create_mock_hr_ticket", {
        "employee_id": "E1001", "category": "pto", "subject": "a", "summary": "a", "priority": "low",
        "citations": [], "preview_only": True})
    assert r.structured_content["id"] == "HR-MOCK-(on confirm)"
    listed = await call(server, "list_hr_tickets", {"employee_id": "E1001"})
    assert listed.structured_content["tickets"] == []


async def test_conduct_ticket_routes_to_hr_confidential_with_a_minimal_summary(server):
    long = "Comments about my accent in meetings. " * 20
    r = await call(server, "create_mock_hr_ticket", {
        "employee_id": "E1004", "category": "conduct", "subject": "Concern", "summary": long, "priority": "high",
        "citations": [{"doc_id": "RSE-HB-01", "section": "6.1"}]}, requester="E1004")
    out = r.structured_content
    assert out["queue"] == "HR Confidential"
    assert len(out["summary"]) <= 200
