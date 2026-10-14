"""Access rule (SPEC §3.5, RSE-HB-01 §7.2), enforced by the hr server from the injected requester_id.

| Requester asks about…                     | Allowed                                                    |
| their own records                         | everything                                                 |
| someone in their reporting chain          | profile, PTO balance, Compliance Check on PTO requests     |
| anyone's benefits or HR tickets           | self only                                                  |
| Mock Actions                              | self only                                                  |
| anything else                             | NOT_PERMITTED                                              |
"""

from __future__ import annotations

from typing import Literal

from mcp_servers.common.errors import ToolFailure
from mcp_servers.hr.models import Employee, MockData

Resource = Literal["profile", "pto_balance", "benefits", "tickets", "compliance_pto", "compliance_other",
                   "mock_action"]
CHAIN_VISIBLE: frozenset[Resource] = frozenset({"profile", "pto_balance", "compliance_pto"})

NOT_SET_HINT = "Ask the user to choose who they are in the 'Speaking as' picker; an ID typed in chat doesn't count."


def resolve(data: MockData, requester_id: str | None, employee_id: str | None, resource: Resource) -> Employee:
    """Return the subject Employee if the Requester may access `resource` for them; otherwise raise."""
    if not requester_id:
        raise ToolFailure("MISSING_ARGUMENT", "No Requester: 'Speaking as' is (not set).", NOT_SET_HINT)
    if not employee_id:
        raise ToolFailure("MISSING_ARGUMENT", "employee_id is required.",
                          f"Use the Requester's own ID ({requester_id}) unless asking about someone in their "
                          "reporting chain.")
    if employee_id not in data.employees:
        raise ToolFailure("EMPLOYEE_NOT_FOUND", f"No employee {employee_id}.",
                          "Check the ID; there is no lookup by name.")
    if requester_id not in data.employees:
        raise ToolFailure("NOT_PERMITTED", "Unknown Requester.", NOT_SET_HINT)
    if requester_id == employee_id:
        return data.employees[employee_id]
    if resource in CHAIN_VISIBLE and requester_id in data.chain_above(employee_id):
        return data.employees[employee_id]
    raise ToolFailure(
        "NOT_PERMITTED",
        f"{requester_id} may not access {employee_id}'s {resource.replace('_', ' ')}.",
        "Say you can't share that record (RSE-HB-01 §7.2). Records are visible to the employee, HR and, for "
        "profile and PTO balance only, the employee's reporting chain.",
    )
