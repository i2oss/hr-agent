"""Compliance Check (SPEC §3.4): a deterministic rule checker for PTO requests, temporary remote
work and expense items. Rules, parameters and citations load from corpus/_facts.yaml — the same
file the Policy Documents are written from — so code and corpus can't drift.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel

from mcp_servers.common.errors import ToolFailure
from mcp_servers.common.models import Citation
from mcp_servers.hr.models import Employee, MockData

Outcome = Literal["allowed", "allowed_with_approval", "not_allowed", "needs_hr_review"]
Approver = Literal["manager", "director", "HR", "VP Finance"]
RequestType = Literal["pto_request", "temporary_remote_work", "expense_item"]

COUNTRIES = {"US": "US", "USA": "US", "UNITED STATES": "US", "CA": "CA", "CANADA": "CA", "PT": "PT",
             "PORTUGAL": "PT", "MX": "MX", "MEXICO": "MX", "GB": "GB", "UK": "GB", "UNITED KINGDOM": "GB",
             "FR": "FR", "FRANCE": "FR", "ES": "ES", "SPAIN": "ES", "DE": "DE", "GERMANY": "DE",
             "IT": "IT", "ITALY": "IT", "IE": "IE", "IRELAND": "IE", "JP": "JP", "JAPAN": "JP"}
REGIONS = {"COLORADO": "CO", "TEXAS": "TX", "WASHINGTON": "WA", "OREGON": "OR", "CALIFORNIA": "CA",
           "ONTARIO": "ON", "QUEBEC": "QC", "BRITISH COLUMBIA": "BC", "NEW YORK": "NY", "ARIZONA": "AZ",
           "NEW MEXICO": "NM", "UTAH": "UT", "IDAHO": "ID", "FLORIDA": "FL", "ILLINOIS": "IL"}


class Check(BaseModel):
    rule: str
    passed: bool
    detail: str
    citation: Citation


class ComplianceResult(BaseModel):
    outcome: Outcome
    approver: Approver | None
    checks: list[Check]
    computed: dict[str, Any]


def load_facts(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _missing(message: str, hint: str) -> ToolFailure:
    return ToolFailure("MISSING_ARGUMENT", message, hint)


def _date(details: dict[str, Any], key: str, required: bool = True) -> dt.date | None:
    raw = details.get(key)
    if raw in (None, ""):
        if required:
            raise _missing(f"details.{key} is required.", f"Give {key} as YYYY-MM-DD.")
        return None
    try:
        return dt.date.fromisoformat(str(raw))
    except ValueError:
        raise _missing(f"details.{key} is not a date: {raw!r}.", f"Give {key} as YYYY-MM-DD.") from None


class ComplianceChecker:
    def __init__(self, facts: dict[str, Any], data: MockData, today: dt.date):
        self.f = facts
        self.data = data
        self.today = today
        self.cites = {r["id"]: r["cite"] for rules in facts["compliance_rules"].values() for r in rules}

    # ------------------------------------------------------------ helpers

    def _check(self, rule: str, passed: bool, detail: str) -> Check:
        doc_id, section = self.cites[rule].split(" §")
        return Check(rule=rule, passed=passed, detail=detail, citation=Citation(doc_id=doc_id, section=section))

    def holidays(self, emp: Employee) -> dict[dt.date, str]:
        cal = next(o["holiday_calendar"] for o in self.f["offices"] if o["id"] == emp.office_id).lower()
        return {h["date"]: h["name"] for year in self.f["holidays"][cal].values() if isinstance(year, list)
                for h in year}

    def working_days(self, emp: Employee, start: dt.date, end: dt.date) -> tuple[int, list[dict[str, str]]]:
        hols = self.holidays(emp)
        days, excluded = 0, []
        d = start
        while d <= end:
            if d.weekday() < 5:
                if d in hols:
                    excluded.append({"date": d.isoformat(), "name": hols[d]})
                else:
                    days += 1
            d += dt.timedelta(days=1)
        return days, excluded

    def _name(self, eid: str | None) -> str | None:
        return self.data.employees[eid].name if eid else None

    def _director(self, emp: Employee) -> str | None:
        chain = self.data.chain_above(emp.id)
        return chain[1] if len(chain) > 1 else (chain[0] if chain else None)

    # ------------------------------------------------------------ entry point

    def check(self, employee_id: str, request_type: str, details: dict[str, Any]) -> ComplianceResult:
        emp = self.data.employees[employee_id]
        if request_type == "pto_request":
            return self._pto(emp, details)
        if request_type == "temporary_remote_work":
            return self._trw(emp, details)
        if request_type == "expense_item":
            return self._expense(emp, details)
        raise _missing(f"Unknown request_type {request_type!r}.",
                       "Use pto_request, temporary_remote_work or expense_item.")

    # ------------------------------------------------------------ PTO (RSE-PTO-01, RSE-HOL-01)

    def _pto(self, emp: Employee, details: dict[str, Any]) -> ComplianceResult:
        start, end = _date(details, "start_date"), _date(details, "end_date")
        assert start and end
        if end < start:
            raise _missing("details.end_date is before start_date.", "Give the first and last day off.")
        req = self.f["pto"]["requesting"]
        checks: list[Check] = []

        eligible = emp.employment_type in self.f["pto"]["eligibility"]["eligible"]
        checks.append(self._check("PTO-ELIGIBLE", eligible,
                                  f"{emp.employment_type} {'earns' if eligible else 'does not earn'} PTO."))
        days, excluded = self.working_days(emp, start, end)
        hol_text = ", ".join(f"{h['name']} ({h['date']})" for h in excluded) or "none"
        checks.append(self._check("PTO-DAYS", True, f"{days} PTO day(s); company holidays excluded: {hol_text}."))
        computed: dict[str, Any] = {"working_days": days, "holidays_excluded": excluded,
                                    "calendar": "CA" if emp.office_id == "TOR" else "US"}
        if not eligible:
            return ComplianceResult(outcome="not_allowed", approver=None, checks=checks, computed=computed)

        available = self.data.pto[emp.id].available
        computed["available"] = available
        checks.append(self._check("PTO-BALANCE", available >= days,
                                  f"{available} day(s) available vs {days} requested; no negative balance."))

        notice = (start - self.today).days
        computed["notice_calendar_days"] = notice
        threshold, required = req["notice_threshold_days"], req["notice_required_calendar_days"]
        if days > threshold:
            checks.append(self._check("PTO-NOTICE", notice >= required,
                                      f"{days} days > {threshold}: needs {required} calendar days' notice; "
                                      f"giving {notice}."))
        else:
            checks.append(self._check("PTO-NOTICE", True,
                                      f"{days} days ≤ {threshold}: no minimum notice (as early as practical)."))

        approver: Approver = "manager"
        over = days > req["director_threshold_consecutive_days"]
        checks.append(self._check("PTO-DIRECTOR", True,
                                  f"{days} consecutive PTO days "
                                  f"{'> ' if over else '≤ '}{req['director_threshold_consecutive_days']}: "
                                  f"{'director approves' if over else 'manager approves'}."))
        if over:
            approver = "director"

        bl = req["field_blackout"]
        if emp.work_arrangement == bl["applies_to"]:
            win_start = dt.date.fromisoformat(f"{start.year}-{bl['window']['from']}")
            win_end = dt.date.fromisoformat(f"{start.year}-{bl['window']['to']}")
            hits = start <= win_end and end >= win_start
            checks.append(self._check("PTO-BLACKOUT", not hits,
                                      f"Field/site December blackout {win_start:%b %d}–{win_end:%b %d}: "
                                      + ("needs a director's exception." if hits else "not affected.")))
            if hits:
                approver = "director"

        hard_fail = not all(c.passed for c in checks if c.rule == "PTO-BALANCE")
        computed["approver_name"] = self._name(self._director(emp) if approver == "director" else emp.manager_id)
        return ComplianceResult(outcome="not_allowed" if hard_fail else "allowed_with_approval",
                                approver=approver, checks=checks, computed=computed)

    # ------------------------------------------------------------ temporary remote work (RSE-RW-01, RSE-LOC-01)

    def _trw(self, emp: Employee, details: dict[str, Any]) -> ComplianceResult:
        country_raw = str(details.get("country") or "").strip()
        if not country_raw:
            raise _missing("details.country is required.", "Give the country (ISO code or name).")
        country = COUNTRIES.get(country_raw.upper(), country_raw.upper())
        start, end = _date(details, "start_date", required=False), _date(details, "end_date", required=False)
        wd_given = details.get("working_days")
        if end and not start:
            raise _missing("details.end_date needs a start_date.", "Give start_date, or working_days alone.")
        if start and end and end < start:
            raise _missing("details.end_date is before start_date.", "Give the first and last day.")
        if not (start and end) and wd_given is None:
            raise _missing("details needs start_date and end_date, or working_days.",
                           "Give the dates, or the number of working days.")

        checks: list[Check] = []
        computed: dict[str, Any] = {"country": country}
        if start and end:
            working, _ = self.working_days(emp, start, end)
            computed["calendar_days"] = (end - start).days + 1
        else:
            working = int(wd_given)  # type: ignore[arg-type]
        computed["working_days"] = working

        arrangement_ok = emp.work_arrangement != "field_site"
        checks.append(self._check("TRW-ARRANGEMENT", arrangement_ok,
                                  "Field/site roles are not eligible for temporary remote work." if not arrangement_ok
                                  else f"{emp.work_arrangement} is eligible."))
        if not arrangement_ok:
            return ComplianceResult(outcome="not_allowed", approver=None, checks=checks, computed=computed)

        if country != emp.work_country:
            wa = self.f["location"]["working_abroad"]
            cap, notice_req = wa["cap_working_days_per_year"], wa["request_notice_calendar_days"]
            checks.append(self._check("TRW-ABROAD", False,
                                      f"Working from another country ({country}) always needs HR review."))
            checks.append(self._check("TRW-ABROAD-CAP", working <= cap,
                                      f"{working} working days vs a {cap}-working-day annual cap"
                                      + ("; over the cap the manager can't approve, HR reviews it as an exception."
                                         if working > cap else ".")))
            if start:
                notice = (start - self.today).days
                computed["notice_calendar_days"] = notice
                checks.append(self._check("TRW-ABROAD-NOTICE", notice >= notice_req,
                                          f"Request ≥ {notice_req} calendar days ahead; giving {notice}."))
            else:
                checks.append(self._check("TRW-ABROAD-NOTICE", True,
                                          f"no start date given: request ≥ {notice_req} calendar days ahead."))
            sec = self.f["security"]["remote_and_travel"]["abroad_notify_it_working_days"]
            checks.append(self._check("TRW-SECURITY", True,
                                      f"Notify IT Security ≥ {sec} working days before working abroad; VPN always."))
            return ComplianceResult(outcome="needs_hr_review", approver="HR", checks=checks, computed=computed)

        region_raw = str(details.get("region") or "").strip()
        if not region_raw:
            raise _missing("details.region is required within your own country.",
                           "Give the state or province, so in-state and cross-state can be told apart.")
        region = REGIONS.get(region_raw.upper(), region_raw.upper())
        computed["region"] = region
        if region == emp.work_region:
            checks.append(self._check("TRW-DOMESTIC", True,
                                      "Within your own state or province: allowed; tell your manager."))
            return ComplianceResult(outcome="allowed", approver=None, checks=checks, computed=computed)

        limit = self.f["remote_work"]["temporary_remote_work"]["other_us_state_or_province"][
            "manager_approval_up_to_calendar_days"]
        cal_days = computed.get("calendar_days", working)
        ok = cal_days <= limit
        checks.append(self._check("TRW-DOMESTIC", ok,
                                  f"Another state/province: {cal_days} calendar days vs {limit} the manager can "
                                  f"approve per year" + ("." if ok else "; over that needs HR review.")))
        return ComplianceResult(outcome="allowed_with_approval" if ok else "needs_hr_review",
                                approver="manager" if ok else "HR", checks=checks, computed=computed)

    # ------------------------------------------------------------ expenses (RSE-EXP-01)

    def _expense(self, emp: Employee, details: dict[str, Any]) -> ComplianceResult:
        category = str(details.get("category") or "").lower()
        if not category:
            raise _missing("details.category is required.",
                           "One of meals, lodging, airfare, mileage, entertainment, ppe, other.")
        try:
            amount = float(details["amount"])
        except (KeyError, TypeError, ValueError):
            raise _missing("details.amount is required.", "Give the amount as a number.") from None
        currency = str(details.get("currency") or "USD").upper()
        intl = bool(details.get("international", False))
        lim = self.f["expenses"]["limits"]
        checks: list[Check] = []
        reimbursable = amount
        ok = True
        approver_override: Approver | None = None

        if category == "meals":
            cap = lim["meals_per_day"]["international" if intl else "domestic"]
            days = int(details.get("days", 1))
            reimbursable = min(amount, cap * days)
            ok = amount <= cap * days
            checks.append(self._check("EXP-MEALS", ok, f"Meals cap ${cap}/day ({'international' if intl else 'domestic'}"
                                      f"); ${amount:g} over {days} day(s)" + ("." if ok else
                                      f": ${reimbursable:g} reimbursable, ${amount - reimbursable:g} not.")))
        elif category == "lodging":
            cap = lim["lodging_per_night"]["international" if intl else "us"]
            nights = int(details.get("nights", 1))
            reimbursable = min(amount, cap * nights)
            ok = amount <= cap * nights
            checks.append(self._check("EXP-LODGING", ok, f"Lodging cap ${cap}/night; ${amount:g} for {nights} "
                                      f"night(s)" + ("." if ok else f": ${reimbursable:g} reimbursable.")))
        elif category == "airfare":
            desc = str(details.get("description", "")).lower()
            business = "business" in desc and "class" in desc
            hours = lim["airfare"]["economy_up_to_flight_hours"]
            checks.append(self._check("EXP-AIRFARE", True, f"Economy up to {hours} h; premium economy over {hours} h"
                                      + ("; business class needs director approval." if business else ".")))
            if business:
                approver_override = "director"
        elif category == "mileage":
            rate = lim["mileage_per_mile"]
            miles = details.get("miles")
            if miles is not None:
                reimbursable = round(float(miles) * rate, 2)
            checks.append(self._check("EXP-MILEAGE", True, f"${rate:.2f} per business mile"
                                      + (f": {miles} miles = ${reimbursable:g}." if miles is not None else ".")))
        elif category == "entertainment":
            cap = lim["client_entertainment_per_person"]
            people = int(details.get("people", 1))
            reimbursable = min(amount, cap * people)
            ok = amount <= cap * people
            checks.append(self._check("EXP-ENTERTAIN", ok, f"Client entertainment ≤ ${cap}/person with manager "
                                      f"pre-approval; ${amount:g} for {people} person(s)."))
        elif category == "ppe":
            cap = lim["ppe_per_year"]
            field = emp.work_arrangement in lim["ppe_eligible"]
            ok = field and amount <= cap
            reimbursable = min(amount, cap) if field else 0.0
            checks.append(self._check("EXP-PPE", ok, (f"PPE up to ${cap}/year for field/site roles; "
                                      f"${amount:g} claimed.") if field else
                                      "PPE is reimbursable for field/site roles only."))

        receipt_from = self.f["expenses"]["claims"]["receipt_required_from"]
        checks.append(self._check("EXP-RECEIPT", True,
                                  f"Receipt required (items of ${receipt_from} or more)." if amount >= receipt_from
                                  else f"No receipt needed under ${receipt_from}."))
        tiers = self.f["expenses"]["claims"]["approvers"]
        approver: Approver = "VP Finance"
        for t in tiers:
            if "up_to" in t and reimbursable <= t["up_to"]:
                approver = t["approver"]
                break
        if approver_override == "director" and approver == "manager":
            approver = "director"
        checks.append(self._check("EXP-APPROVER", True, f"Claim of ${reimbursable:g} is approved by the {approver}."))

        computed: dict[str, Any] = {"category": category, "amount": amount, "currency": currency,
                                    "reimbursable": reimbursable, "not_reimbursable": round(amount - reimbursable, 2)}
        if currency != "USD":
            computed["currency_note"] = ("Limits are in USD; the claim is compared at the card or Finance rate on "
                                         "the expense date (RSE-EXP-01 §8.3). Amount compared as given.")
        return ComplianceResult(outcome="allowed_with_approval" if ok else "not_allowed",
                                approver=approver, checks=checks, computed=computed)
