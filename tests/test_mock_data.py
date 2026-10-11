"""Data test (SPEC slice 4, step 2): mock_data/ against corpus/_facts.yaml."""

import datetime as dt
import json
import re

import pytest
import yaml

from app.config import ROOT
from mcp_servers.hr.models import (
    accrual_to_date,
    annual_pto_days,
    load_mock_data,
)

FACTS = yaml.safe_load((ROOT / "corpus" / "_facts.yaml").read_text())
DEMO = FACTS["meta"]["demo_today"]
FORBIDDEN = re.compile(r"salary|pay_rate|wage|birth|dob|address|ssn|sin\b|passport|government|health|diagnos|medical_",
                       re.I)


@pytest.fixture(scope="module")
def data():
    return load_mock_data(ROOT / "mock_data")


def chain(data, eid):
    return data.chain_above(eid)


# ---------------------------------------------------------------- persona_constraints, row by row

def test_every_persona_constraint_row_is_covered():
    covered = {"E1001", "E1002", "E1003", "E1004", "E1005", "E1007", "E1008", "E1010", "E1011"}
    assert {r["employee"] for r in FACTS["persona_constraints"]} == covered


def test_e1001_maya(data):
    maya = data.employees["E1001"]
    assert data.pto["E1001"].available == 11
    assert maya.manager_id == "E1012" and data.employees["E1012"].name == "Jordan Lee"
    assert data.employees["E1012"].manager_id == "E1009" and data.employees["E1009"].name == "Marcus Reed"
    assert not [e for e in data.employees.values() if e.manager_id == "E1001"]  # no direct reports
    assert "E1001" not in chain(data, "E1002")
    assert completed_band(maya) == 20  # "4 completed years -> 20 days/yr"


def test_e1002_daniel(data):
    d = data.employees["E1002"]
    assert (d.work_arrangement, d.office_id, d.work_region, d.work_country) == ("office_hybrid", "AUS", "TX", "US")


def test_e1003_luis(data):
    luis = data.employees["E1003"]
    assert (luis.work_arrangement, luis.office_id) == ("field_site", "DEN")
    assert data.pto["E1003"].available >= 4
    assert not [t for t in data.tickets if t.employee_id == "E1003" and t.category == "expense"]  # no PPE claimed


def test_e1004_priya(data):
    priya = data.employees["E1004"]
    assert data.pto["E1004"].available == 1.5
    assert data.offices[priya.office_id].country == "US"
    assert "E1004" not in chain(data, "E1001")


def test_e1005_grace(data):
    g = data.employees["E1005"]
    assert (g.work_arrangement, g.office_id, g.work_region, g.employment_type) == (
        "office_hybrid", "SEA", "WA", "part_time")


def test_e1007_sam_is_a_contractor(data):
    assert data.employees["E1007"].employment_type == "contractor"


def test_e1008_chloe(data):
    c = data.employees["E1008"]
    assert c.employment_type.startswith("full_time") and c.office_id == "TOR"
    plans = {b.plan for b in data.benefits if b.employee_id == "E1008"}
    assert plans == {"RSE Canada Group Plan"}


def test_e1010_aisha(data):
    a = data.employees["E1010"]
    assert a.employment_type.startswith("full_time")
    assert (DEMO - a.hire_date).days >= 183  # ≥ 6 months' service
    open_leave = [t for t in data.tickets if t.employee_id == "E1010" and t.status == "open"]
    assert len(open_leave) == 1 and "2026-12-07" in open_leave[0].subject


def test_e1011_noah(data):
    n = data.employees["E1011"]
    assert n.hire_date == dt.date(2026, 10, 12) and n.office_id == "AUS"
    medical = [b for b in data.benefits if b.employee_id == "E1011" and b.plan.startswith("Medical")]
    assert [b.status for b in medical] == ["pending"]
    assert medical[0].enrollment_window_end == FACTS["scenarios"]["benefits_triage"]["window_ends"]
    assert medical[0].effective_date == FACTS["scenarios"]["benefits_triage"]["coverage_start"]


# ---------------------------------------------------------------- accrual and structure

def completed_band(e):
    return annual_pto_days(e.employment_type, e.hire_date, e.weekly_hours, DEMO.year)


def test_accrual_bands_match_the_facts_sheet():
    bands = FACTS["pto"]["accrual"]["full_time_days_per_year"]
    assert [(b["years_from"], b["days"]) for b in bands] == [(0, 15), (3, 20), (6, 25)]
    ex = FACTS["pto"]["accrual"]["part_time_example"]
    assert annual_pto_days("part_time", dt.date(2026, 1, 1), ex["weekly_hours"], 2026) == ex["days"]
    assert annual_pto_days("intern", dt.date(2026, 6, 1), 40, 2026) == 5
    assert annual_pto_days("contractor", dt.date(2020, 1, 1), 40, 2026) == 0


def test_accrued_is_consistent_with_tenure_and_type(data):
    for e in data.employees.values():
        bal = data.pto[e.id]
        want = accrual_to_date(completed_band(e), e.hire_date, DEMO, e.employment_type)
        assert bal.accrued == pytest.approx(want, abs=0.01), e.id
        assert bal.as_of == DEMO
        assert bal.available >= 0, e.id
        if e.employment_type == "contractor":
            assert (bal.accrued, bal.used, bal.carryover) == (0, 0, 0)
        if e.employment_type == "intern":
            assert bal.accrued <= 5
        assert bal.carryover <= FACTS["pto"]["carryover"]["cap_days"]


def test_every_employee_has_one_balance_row(data):
    assert set(data.pto) == set(data.employees)


def test_managers_exist_and_reporting_lines_have_no_cycles(data):
    for e in data.employees.values():
        if e.manager_id is not None:
            assert e.manager_id in data.employees, e.id
        seen = {e.id}
        cur = e.manager_id
        while cur is not None:
            assert cur not in seen, f"cycle through {e.id}"
            seen.add(cur)
            cur = data.employees[cur].manager_id


def test_offices_exist_and_match_the_facts_sheet(data):
    assert {o["id"] for o in FACTS["offices"]} == set(data.offices)
    for e in data.employees.values():
        o = data.offices[e.office_id]
        assert (e.work_region, e.work_country) == (o.region, o.country), e.id


def test_about_25_employees_with_invented_example_emails(data):
    assert 20 <= len(data.employees) <= 30
    assert all(e.work_email.endswith("@ridgeline.example") for e in data.employees.values())
    assert all(re.fullmatch(r"E1\d{3}", e) for e in data.employees)


def test_seed_tickets_and_benefits_reference_real_employees(data):
    assert len(data.tickets) == 3
    ids = set(data.employees)
    assert all(t.employee_id in ids and not t.mock for t in data.tickets)
    assert all(b.employee_id in ids for b in data.benefits)
    contractors = {e.id for e in data.employees.values() if e.employment_type == "contractor"}
    assert not [b for b in data.benefits if b.employee_id in contractors]


@pytest.mark.parametrize("name", ["offices", "employees", "pto_balances", "benefits_elections", "hr_tickets"])
def test_files_are_marked_synthetic_and_hold_no_forbidden_fields(name):
    doc = json.loads((ROOT / "mock_data" / f"{name}.json").read_text())
    assert doc["_synthetic"] is True
    keys = {k for row in doc[name] for k in row}
    assert not [k for k in keys if FORBIDDEN.search(k)]
