"""hr MCP server: Mock Data, the Compliance Check and Mock Actions (SPEC §3.4). Mounted at /mcp/hr.

Every tool also takes requester_id and session_id. The agent loop fills them from the session,
overwrites anything the model wrote, and removes them from the schema the model sees. The two
Mock Actions also take preview_only, which the loop uses to show the exact draft for Confirmation
without creating anything.
"""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING, Annotated, Any, Literal

from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from mcp_servers.common.errors import ToolFailure, coded_errors
from mcp_servers.common.models import Citation
from mcp_servers.hr.access import Resource, resolve
from mcp_servers.hr.compliance import ComplianceChecker, ComplianceResult, RequestType, load_facts
from mcp_servers.hr.models import BenefitElection, HrTicket, Priority, TicketCategory, load_mock_data
from mcp_servers.hr.store import MockActionStore

if TYPE_CHECKING:
    from app.config import Settings

READ = ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False)
ACTION = ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=False, open_world_hint=False)
QUEUES: dict[str, str] = {"pto": "HR Service Desk", "remote_work": "HR · Cross-Border Review",
                          "benefits": "HR · Benefits", "expense": "Finance · Expenses",
                          "conduct": "HR Confidential", "other": "HR Service Desk"}
CONDUCT_SUMMARY_MAX = 200
PENDING_ID = "(on confirm)"

EmployeeId = Annotated[str | None, Field(description="Employee ID, e.g. 'E1001'. Normally the Requester's own ID.")]
RequesterId = Annotated[str | None, Field(description="Injected by the agent loop.")]
SessionId = Annotated[str | None, Field(description="Injected by the agent loop.")]
PreviewOnly = Annotated[bool, Field(description="Injected by the agent loop.")]


class ComplianceDetails(BaseModel):
    """The request being checked. Which fields apply depends on request_type."""

    start_date: str | None = Field(None, description="YYYY-MM-DD (pto_request, temporary_remote_work)")
    end_date: str | None = Field(None, description="YYYY-MM-DD (pto_request, temporary_remote_work)")
    country: str | None = Field(None, description="temporary_remote_work: ISO code or name, e.g. 'PT'")
    region: str | None = Field(None, description="temporary_remote_work: state/province, e.g. 'OR'")
    working_days: int | None = Field(None, description="temporary_remote_work: duration if no dates")
    category: str | None = Field(None, description="expense_item: meals | lodging | airfare | mileage | "
                                 "entertainment | ppe | other")
    amount: float | None = Field(None, description="expense_item: amount claimed")
    currency: str | None = Field(None, description="expense_item: e.g. USD")
    description: str | None = Field(None, description="expense_item: what it was")
    international: bool | None = Field(None, description="expense_item: travel outside your own country")
    nights: int | None = Field(None, description="expense_item lodging: number of nights")
    days: int | None = Field(None, description="expense_item meals: number of days")
    people: int | None = Field(None, description="expense_item entertainment: number of people")
    miles: float | None = Field(None, description="expense_item mileage: business miles")


class Person(BaseModel):
    id: str
    name: str


class OfficeOut(BaseModel):
    id: str
    city: str
    region: str
    country: str
    timezone: str


class Profile(BaseModel):
    employee_id: str
    name: str
    title: str
    department: str
    employment_type: str
    work_arrangement: str
    office: OfficeOut
    holiday_calendar: Literal["US", "CA"]
    manager: Person | None
    director: Person | None
    hire_date: dt.date
    weekly_hours: int
    work_email: str
    work_region: str
    work_country: str
    employment_status: str


class Balance(BaseModel):
    employee_id: str
    accrued: float
    used: float
    pending: float
    carryover: float
    available: float
    as_of: dt.date


class Elections(BaseModel):
    employee_id: str
    elections: list[BenefitElection]


class Tickets(BaseModel):
    employee_id: str
    tickets: list[dict[str, Any]]


class Recipient(BaseModel):
    id: str
    name: str
    email: str


class DraftedMessage(BaseModel):
    id: str
    mock: Literal[True]
    to: Recipient
    subject: str
    body: str
    citations: list[Citation]


class MockTicket(BaseModel):
    id: str
    mock: Literal[True]
    queue: str
    employee_id: str
    category: TicketCategory
    subject: str
    summary: str
    priority: Priority
    status: Literal["open"]
    created: dt.date
    citations: list[Citation]


def build_hr_server(settings: Settings, store: MockActionStore) -> MCPServer:
    data = load_mock_data(settings.mock_data_dir)
    checker = ComplianceChecker(load_facts(settings.facts_path), data, settings.demo_today)
    server = MCPServer("hr", instructions="Ridgeline (FICTIONAL) HR Mock Data, Compliance Check and Mock Actions.")

    def person(eid: str | None) -> Person | None:
        return Person(id=eid, name=data.employees[eid].name) if eid else None

    @server.tool(annotations=READ)
    @coded_errors
    async def lookup_employee_profile(employee_id: EmployeeId = None, requester_id: RequesterId = None,
                                      session_id: SessionId = None) -> Profile:
        """Look up an Employee's HR profile: title, Employment Type, Work Arrangement, office, manager, director.

        Use when: the answer depends on who the Requester is (their office, holiday calendar, Employment Type,
        Work Arrangement, manager or approver), or before a Compliance Check.
        Don't use when: the question is general policy that doesn't depend on the person.
        """
        e = resolve(data, requester_id, employee_id, "profile")
        chain = data.chain_above(e.id)
        office = data.offices[e.office_id]
        return Profile(employee_id=e.id, name=e.name, title=e.title, department=e.department,
                       employment_type=e.employment_type, work_arrangement=e.work_arrangement,
                       office=OfficeOut(**office.model_dump()), holiday_calendar="CA" if office.country == "CA" else "US",
                       manager=person(chain[0] if chain else None), director=person(chain[1] if len(chain) > 1 else None),
                       hire_date=e.hire_date, weekly_hours=e.weekly_hours, work_email=e.work_email,
                       work_region=e.work_region, work_country=e.work_country, employment_status=e.employment_status)

    @server.tool(annotations=READ)
    @coded_errors
    async def check_pto_balance(employee_id: EmployeeId = None, requester_id: RequesterId = None,
                                session_id: SessionId = None) -> Balance:
        """Return an Employee's PTO balance as of the Demo Date: accrued, used, pending, carryover, available.

        Use when: the Requester asks how much PTO they (or someone in their reporting chain) have, or before
        judging whether a PTO request fits the balance.
        Don't use when: the question is about PTO rules in general (search_policy).
        """
        e = resolve(data, requester_id, employee_id, "pto_balance")
        b = data.pto[e.id]
        return Balance(employee_id=e.id, accrued=b.accrued, used=b.used, pending=b.pending,
                       carryover=b.carryover, available=b.available, as_of=b.as_of)

    @server.tool(annotations=READ)
    @coded_errors
    async def lookup_benefits_status(employee_id: EmployeeId = None,
                                     plan: Annotated[str | None, Field(description="Optional plan name filter, "
                                                                       "e.g. 'Medical PPO'.")] = None,
                                     requester_id: RequesterId = None, session_id: SessionId = None) -> Elections:
        """Return the Requester's own benefits elections: plan, coverage level, status, effective date and
        enrollment window end.

        Use when: the Requester asks about their own enrollment, coverage or deadline.
        Don't use when: asking about plan rules in general (search_policy), or about anyone else's benefits.
        """
        e = resolve(data, requester_id, employee_id, "benefits")
        rows = [b for b in data.benefits if b.employee_id == e.id and (plan is None or b.plan.lower() == plan.lower())]
        return Elections(employee_id=e.id, elections=rows)

    @server.tool(annotations=READ)
    @coded_errors
    async def list_hr_tickets(employee_id: EmployeeId = None,
                              status: Annotated[Literal["open", "in_review", "closed"] | None,
                                                Field(description="Optional status filter.")] = None,
                              requester_id: RequesterId = None, session_id: SessionId = None) -> Tickets:
        """List the Requester's own HR tickets: the seed tickets plus any mock tickets created this session.

        Use when: the Requester asks about an existing case or ticket, or before opening a new one.
        Don't use when: asking about anyone else's tickets.
        """
        e = resolve(data, requester_id, employee_id, "tickets")
        seed = [HrTicket.model_validate(t).model_dump(mode="json") for t in data.tickets if t.employee_id == e.id]
        mine = [t for t in store.session_tickets(session_id or "") if t["employee_id"] == e.id]
        rows = [t for t in seed + mine if status is None or t["status"] == status]
        return Tickets(employee_id=e.id, tickets=rows)

    @server.tool(annotations=READ)
    @coded_errors
    async def check_policy_compliance(
        employee_id: EmployeeId = None,
        request_type: Annotated[RequestType | None, Field(description="pto_request | temporary_remote_work | "
                                                         "expense_item")] = None,
        details: Annotated[ComplianceDetails | None, Field(description=(
            "pto_request: start_date, end_date. temporary_remote_work: country, region (own country only), "
            "start_date + end_date or working_days. expense_item: category, amount, currency, description."
        ))] = None,
        requester_id: RequesterId = None, session_id: SessionId = None,
    ) -> ComplianceResult:
        """Run the deterministic Compliance Check on a concrete request and return the outcome, approver, each
        rule checked (with its citation) and computed values such as working days and reimbursable amounts.

        Use when: the Requester has a concrete PTO request (dates), temporary remote work (where and when) or
        expense item (category and amount) and wants to know if it's allowed and who approves.
        Don't use when: the question is general, or the dates/location are too vague to check (ask instead).
        """
        if not request_type:
            raise ToolFailure("MISSING_ARGUMENT", "request_type is required.",
                              "Use pto_request, temporary_remote_work or expense_item.")
        resource: Resource = "compliance_pto" if request_type == "pto_request" else "compliance_other"
        e = resolve(data, requester_id, employee_id, resource)
        return checker.check(e.id, request_type, details.model_dump(exclude_none=True) if details else {})

    @server.tool(annotations=ACTION)
    @coded_errors
    async def draft_manager_message(
        employee_id: EmployeeId = None,
        subject: Annotated[str, Field(description="Message subject.")] = "",
        body: Annotated[str, Field(description="The full message to the Requester's manager.")] = "",
        citations: Annotated[list[Citation], Field(description="Policy sections the message relies on.")] = [],  # noqa: B006
        requester_id: RequesterId = None, session_id: SessionId = None, preview_only: PreviewOnly = False,
    ) -> DraftedMessage:
        """Mock Action: draft a message from the Requester to their manager (saved for this session; never
        sent). Runs only after the user confirms.

        Use when: the Requester wants to ask their manager to approve something, e.g. a PTO request that the
        Compliance Check allows with manager approval.
        Don't use when: the matter is for HR (create_mock_hr_ticket), or for someone other than the Requester.
        """
        e = resolve(data, requester_id, employee_id, "mock_action")
        mgr = data.employees[e.manager_id] if e.manager_id else None
        if mgr is None:
            raise ToolFailure("NOT_PERMITTED", f"{e.id} has no manager on record.", "Suggest an HR ticket instead.")
        draft = {"to": Recipient(id=mgr.id, name=mgr.name, email=mgr.work_email).model_dump(), "subject": subject,
                 "body": body, "citations": [c.model_dump() for c in citations]}
        if preview_only:
            return DraftedMessage.model_validate({"id": f"MSG-MOCK-{PENDING_ID}", "mock": True, **draft})
        return DraftedMessage.model_validate(store.add_message(session_id or "", draft))

    @server.tool(annotations=ACTION)
    @coded_errors
    async def create_mock_hr_ticket(
        employee_id: EmployeeId = None,
        category: Annotated[TicketCategory, Field(description="pto | remote_work | benefits | expense | conduct "
                                                  "| other")] = "other",
        subject: Annotated[str, Field(description="Short subject.")] = "",
        summary: Annotated[str, Field(description="What HR needs to know. For conduct: a minimal summary only.")] = "",
        priority: Annotated[Priority, Field(description="low | normal | high")] = "normal",
        citations: Annotated[list[Citation], Field(description="Policy sections the ticket relies on.")] = [],  # noqa: B006
        requester_id: RequesterId = None, session_id: SessionId = None, preview_only: PreviewOnly = False,
    ) -> MockTicket:
        """Mock Action: open an HR ticket for the Requester (simulated; saved for this session). Runs only after
        the user confirms. conduct tickets go to HR Confidential with a minimal summary.

        Use when: a request needs HR (needs_hr_review, Cross-Border Review, a sensitive matter, a question HR
        handles, or the user asks for a person in HR) and the user agrees to raise it.
        Don't use when: the manager is the right approver (draft_manager_message), or for someone else.
        """
        e = resolve(data, requester_id, employee_id, "mock_action")
        if category == "conduct" and len(summary) > CONDUCT_SUMMARY_MAX:
            summary = summary[: CONDUCT_SUMMARY_MAX - 1].rsplit(" ", 1)[0] + "…"
        ticket = {"queue": QUEUES[category], "employee_id": e.id, "category": category, "subject": subject,
                  "summary": summary, "priority": priority, "status": "open", "created": settings.demo_today.isoformat(),
                  "citations": [c.model_dump() for c in citations]}
        if preview_only:
            return MockTicket.model_validate({"id": f"HR-MOCK-{PENDING_ID}", "mock": True, **ticket})
        return MockTicket.model_validate(store.add_ticket(session_id or "", ticket))

    return server
