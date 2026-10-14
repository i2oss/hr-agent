"""Mock Data models and loader (SPEC §3.10). Loaded once at startup, validated, never modified.

Fields exist only where a policy needs them: no pay, birth dates, home addresses, government IDs
or health details. The accrual helpers implement RSE-PTO-01 §2 and are shared with the data test.
"""

from __future__ import annotations

import calendar
import datetime as dt
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, computed_field

from mcp_servers.common.models import Citation

EmploymentType = Literal["full_time_exempt", "full_time_non_exempt", "part_time", "intern", "contractor"]
WorkArrangement = Literal["office_hybrid", "remote_approved", "field_site"]
TicketCategory = Literal["pto", "remote_work", "benefits", "expense", "conduct", "other"]
Priority = Literal["low", "normal", "high"]

FULL_TIME = ("full_time_exempt", "full_time_non_exempt")
INTERN_DAYS = 5
INTERN_PERIODS = 12  # internships last at most 6 months = 12 semi-monthly periods


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Office(_Strict):
    id: str
    city: str
    region: str
    country: Literal["US", "CA"]
    timezone: str


class Employee(_Strict):
    id: str
    name: str
    title: str
    department: str
    job_family: str
    employment_type: EmploymentType
    work_arrangement: WorkArrangement
    office_id: str
    manager_id: str | None
    hire_date: dt.date
    weekly_hours: int
    work_email: str
    work_region: str
    work_country: str
    employment_status: Literal["active", "on_leave", "pending_start"]


class PtoBalance(_Strict):
    employee_id: str
    accrued: float
    used: float
    pending: float
    carryover: float
    as_of: dt.date

    @computed_field  # type: ignore[prop-decorator]
    @property
    def available(self) -> float:
        return round(self.accrued + self.carryover - self.used - self.pending, 2)


class BenefitElection(_Strict):
    employee_id: str
    plan: Literal["Medical PPO", "Medical HDHP", "Dental", "Vision", "401(k)", "Life", "RSE Canada Group Plan"]
    coverage_level: Literal["employee", "employee_spouse", "employee_children", "family"]
    status: Literal["enrolled", "waived", "pending", "not_eligible"]
    effective_date: dt.date
    enrollment_window_end: dt.date


class HrTicket(_Strict):
    id: str
    employee_id: str
    category: TicketCategory
    subject: str
    summary: str
    status: Literal["open", "in_review", "closed"]
    priority: Priority
    created: dt.date
    assigned_queue: str
    citations: list[Citation]
    mock: bool


@dataclass(frozen=True)
class MockData:
    offices: dict[str, Office]
    employees: dict[str, Employee]
    pto: dict[str, PtoBalance]
    benefits: list[BenefitElection]
    tickets: list[HrTicket]

    def chain_above(self, employee_id: str) -> list[str]:
        """Managers and directors above an Employee, nearest first."""
        out: list[str] = []
        cur = self.employees[employee_id].manager_id
        while cur is not None and cur not in out:
            out.append(cur)
            cur = self.employees[cur].manager_id
        return out


def _load(path: Path, key: str) -> list[dict]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    if doc.get("_synthetic") is not True:
        raise ValueError(f"{path.name}: missing '_synthetic': true")
    return doc[key]


def load_mock_data(directory: Path) -> MockData:
    offices = [Office(**r) for r in _load(directory / "offices.json", "offices")]
    employees = [Employee(**r) for r in _load(directory / "employees.json", "employees")]
    pto = [PtoBalance(**r) for r in _load(directory / "pto_balances.json", "pto_balances")]
    return MockData(
        offices={o.id: o for o in offices},
        employees={e.id: e for e in employees},
        pto={p.employee_id: p for p in pto},
        benefits=[BenefitElection(**r) for r in _load(directory / "benefits_elections.json", "benefits_elections")],
        tickets=[HrTicket(**r) for r in _load(directory / "hr_tickets.json", "hr_tickets")],
    )


# ---------------------------------------------------------------- accrual (RSE-PTO-01 §2)

def completed_years(hire: dt.date, on: dt.date) -> int:
    years = on.year - hire.year - ((on.month, on.day) < (hire.month, hire.day))
    return max(years, 0)


def annual_pto_days(employment_type: str, hire: dt.date, weekly_hours: int, year: int,
                    bands: tuple[tuple[int, int], ...] = ((0, 15), (3, 20), (6, 25))) -> float:
    """Annual PTO days: full-time by completed years of service on Jan 1 (§2.1); part-time pro rata
    by hours ÷ 40 to the nearest half day (§2.2); interns 5 per internship (§2.3); contractors none."""
    if employment_type == "contractor":
        return 0.0
    if employment_type == "intern":
        return float(INTERN_DAYS)
    years = completed_years(hire, dt.date(year, 1, 1))
    days = next(d for start, d in reversed(bands) if years >= start)
    if employment_type == "part_time":
        return round(days * weekly_hours / 40 * 2) / 2
    return float(days)


def pay_period_ends(start: dt.date, end: dt.date) -> int:
    """Semi-monthly periods (ending the 15th and the last day of the month) that end in [start, end]."""
    n = 0
    for y in range(start.year, end.year + 1):
        for m in range(1, 13):
            for d in (15, calendar.monthrange(y, m)[1]):
                if start <= dt.date(y, m, d) <= end:
                    n += 1
    return n


def accrual_to_date(annual: float, hire: dt.date, as_of: dt.date, employment_type: str) -> float:
    start = max(hire, dt.date(as_of.year, 1, 1))
    periods = pay_period_ends(start, as_of)
    if employment_type == "intern":
        return round(min(INTERN_DAYS, INTERN_DAYS * periods / INTERN_PERIODS), 2)
    return round(annual * periods / 24, 2)
