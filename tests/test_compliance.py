"""Compliance Check unit tests (SPEC slice 4, step 8)."""

import datetime as dt

import pytest

from app.config import ROOT
from mcp_servers.common.errors import ToolFailure
from mcp_servers.hr.compliance import ComplianceChecker, load_facts
from mcp_servers.hr.models import load_mock_data

DEMO = dt.date(2026, 11, 2)


@pytest.fixture(scope="module")
def check():
    facts = load_facts(ROOT / "corpus" / "_facts.yaml")
    return ComplianceChecker(facts, load_mock_data(ROOT / "mock_data"), DEMO).check


def rules(result):
    return {c.rule: c for c in result.checks}


def test_maya_nov_11_13_is_two_days_with_manager_approval(check):
    r = check("E1001", "pto_request", {"start_date": "2026-11-11", "end_date": "2026-11-13"})
    assert r.computed["working_days"] == 2
    assert r.computed["holidays_excluded"] == [{"date": "2026-11-11", "name": "Veterans Day"}]
    assert (r.outcome, r.approver) == ("allowed_with_approval", "manager")
    assert r.computed["approver_name"] == "Jordan Lee"
    assert {"PTO-ELIGIBLE", "PTO-DAYS", "PTO-BALANCE", "PTO-NOTICE"} <= set(rules(r))
    assert all(c.passed for c in r.checks)
    assert rules(r)["PTO-NOTICE"].citation.model_dump() == {"doc_id": "RSE-PTO-01", "section": "4.2"}


def test_chloe_same_dates_is_three_days_on_the_canada_calendar(check):
    r = check("E1008", "pto_request", {"start_date": "2026-11-11", "end_date": "2026-11-13"})
    assert r.computed["working_days"] == 3
    assert r.computed["holidays_excluded"] == []


def test_daniel_lisbon_is_thirty_working_days_and_needs_hr_review(check):
    r = check("E1002", "temporary_remote_work",
              {"country": "PT", "start_date": "2027-01-04", "end_date": "2027-02-12"})
    assert r.computed["working_days"] == 30
    assert (r.outcome, r.approver) == ("needs_hr_review", "HR")
    rr = rules(r)
    assert not rr["TRW-ABROAD"].passed and not rr["TRW-ABROAD-CAP"].passed
    assert rr["TRW-ABROAD-NOTICE"].passed
    assert rr["TRW-SECURITY"].citation.section == "5.4"


def test_lisbon_by_country_name_and_duration_only(check):
    r = check("E1002", "temporary_remote_work", {"country": "Portugal", "working_days": 30})
    assert r.outcome == "needs_hr_review"
    assert r.computed["working_days"] == 30
    assert "no start date" in rules(r)["TRW-ABROAD-NOTICE"].detail


def test_priya_two_days_fails_the_balance_check(check):
    r = check("E1004", "pto_request", {"start_date": "2026-11-12", "end_date": "2026-11-13"})
    assert r.computed["working_days"] == 2
    assert not rules(r)["PTO-BALANCE"].passed
    assert r.outcome == "not_allowed"


def test_luis_december_blackout_needs_the_director(check):
    r = check("E1003", "pto_request", {"start_date": "2026-12-21", "end_date": "2026-12-24"})
    assert r.computed["working_days"] == 4
    assert not rules(r)["PTO-BLACKOUT"].passed
    assert (r.outcome, r.approver) == ("allowed_with_approval", "director")
    assert rules(r)["PTO-NOTICE"].passed  # 49 days' notice for 4 days


def test_more_than_ten_consecutive_days_goes_to_the_director(check):
    r = check("E1001", "pto_request", {"start_date": "2026-11-30", "end_date": "2026-12-14"})
    assert r.computed["working_days"] == 11
    assert r.approver == "director" and r.computed["approver_name"] == "Marcus Reed"
    assert rules(r)["PTO-BALANCE"].passed  # exactly 11 available


def test_short_notice_for_more_than_three_days_fails_notice(check):
    r = check("E1001", "pto_request", {"start_date": "2026-11-09", "end_date": "2026-11-13"})
    assert r.computed["working_days"] == 4
    assert not rules(r)["PTO-NOTICE"].passed


def test_contractor_has_no_pto(check):
    r = check("E1007", "pto_request", {"start_date": "2026-11-11", "end_date": "2026-11-13"})
    assert r.outcome == "not_allowed" and not rules(r)["PTO-ELIGIBLE"].passed


def test_luis_boots_allowed_with_approval(check):
    r = check("E1003", "expense_item", {"category": "ppe", "amount": 180, "currency": "USD",
                                         "description": "steel-toe boots"})
    assert (r.outcome, r.approver) == ("allowed_with_approval", "manager")
    assert rules(r)["EXP-PPE"].passed
    assert rules(r)["EXP-RECEIPT"].detail.startswith("Receipt required")


def test_luis_dinner_over_the_meal_cap(check):
    r = check("E1003", "expense_item", {"category": "meals", "amount": 120, "currency": "USD",
                                         "description": "dinner, Pueblo site visit"})
    assert r.outcome == "not_allowed"
    assert r.computed["reimbursable"] == 75
    assert r.computed["not_reimbursable"] == 45


def test_ppe_for_an_office_role_is_not_allowed(check):
    r = check("E1001", "expense_item", {"category": "ppe", "amount": 50, "currency": "USD", "description": "boots"})
    assert r.outcome == "not_allowed"


def test_expense_approver_by_amount(check):
    r = check("E1001", "expense_item", {"category": "lodging", "amount": 2400, "currency": "USD",
                                         "description": "hotel", "nights": 10, "international": False})
    assert r.approver == "director"


def test_domestic_trw_over_thirty_calendar_days_needs_hr(check):
    r = check("E1005", "temporary_remote_work",
              {"country": "US", "region": "OR", "start_date": "2027-06-01", "end_date": "2027-07-10"})
    assert r.computed["calendar_days"] == 40
    assert (r.outcome, r.approver) == ("needs_hr_review", "HR")


def test_same_state_trw_is_allowed(check):
    r = check("E1002", "temporary_remote_work",
              {"country": "US", "region": "Texas", "start_date": "2027-03-01", "end_date": "2027-03-12"})
    assert r.outcome == "allowed" and r.approver is None


def test_field_role_cannot_work_remotely(check):
    r = check("E1003", "temporary_remote_work",
              {"country": "US", "region": "CO", "start_date": "2027-03-01", "end_date": "2027-03-05"})
    assert r.outcome == "not_allowed" and not rules(r)["TRW-ARRANGEMENT"].passed


def test_noah_enrollment_window_ends_nov_11():
    data = load_mock_data(ROOT / "mock_data")
    medical = next(b for b in data.benefits if b.employee_id == "E1011" and b.plan.startswith("Medical"))
    assert medical.enrollment_window_end == dt.date(2026, 11, 11)


@pytest.mark.parametrize("details", [{}, {"start_date": "2026-11-11"}, {"start_date": "x", "end_date": "y"},
                                     {"start_date": "2026-11-13", "end_date": "2026-11-11"}])
def test_bad_pto_details_are_missing_argument(check, details):
    with pytest.raises(ToolFailure) as e:
        check("E1001", "pto_request", details)
    assert e.value.code == "MISSING_ARGUMENT"


def test_every_check_cites_its_rule_from_the_facts_sheet(check):
    facts = load_facts(ROOT / "corpus" / "_facts.yaml")
    cites = {r["id"]: r["cite"] for v in facts["compliance_rules"].values() for r in v}
    r = check("E1002", "temporary_remote_work",
              {"country": "PT", "start_date": "2027-01-04", "end_date": "2027-02-12"})
    for c in r.checks:
        assert f"{c.citation.doc_id} §{c.citation.section}" == cites[c.rule]
