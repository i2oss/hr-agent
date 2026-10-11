# Policy Corpus: section outlines

**FICTIONAL — for demonstration only.** Ridgeline Structural Engineering is invented.

One outline per Policy Document: every numbered section, and the facts it holds (keys into [`_facts.yaml`](_facts.yaml)). Prose is written from these in build slice 1. Rules for writing it:

- Section numbers appear **in the text** exactly as here (`4.2 Notice`), so section-aware chunking and `RSE-PTO-01 §4.2` Citations survive PDF/HTML extraction.
- Every number comes from `_facts.yaml`; the consistency script checks it.
- No contradictions between documents. Cross-references point, they don't restate a number owned elsewhere.
- **Never mention** anything in `not_covered` (pet insurance, stock options/equity, tuition reimbursement, sabbaticals, relocation assistance, commuter benefits).
- Policies state Ridgeline's rules only: no claims about real law. Tax, immigration and legal questions point to the Cross-Border Review or HR.
- Every document opens with the header block: ID, title, version `2026.1`, effective date, owner, applies-to, FICTIONAL banner.

Pages are targets (~55 total). Format is the shipped format; PDFs are generated from Markdown in `corpus/_src/`.

---

## RSE-HB-01 — Employee Handbook & Code of Conduct (8 pp, PDF, owner HR)

- **§1 About This Handbook**
  - §1.1 Purpose — what the handbook is; FICTIONAL banner restated
  - §1.2 Who it applies to — employees; contractors bound by §4–§6 and RSE-SEC-01 only, otherwise their contract/agency (`employment_types.contractor`, `contractor_scope_cite`)
  - §1.3 How Ridgeline policies fit together — list of the 12 documents (`documents`)
  - §1.4 Changes and versions — version, effective date (`meta`)
- **§2 Ridgeline at a Glance**
  - §2.1 Offices — DEN (HQ), AUS, SEA, TOR with timezones (`offices`)
  - §2.2 Employment Types — the five types, hours, contractor note (`employment_types`)
  - §2.3 Work Arrangements — office-hybrid (default), remote-approved, field/site; points to RSE-RW-01 (`work_arrangements`)
  - §2.4 Managers, directors and approvers — points to RSE-APR-01 (`approvals.definitions`)
- **§3 Working Hours**
  - §3.1 Standard week — 40 h (`hours.standard_week_hours`)
  - §3.2 Core hours — 10:00–15:00 local (`hours.core_hours_local`)
  - §3.3 Time recording and overtime (non-exempt) — written pre-approval (`hours.non_exempt_overtime`)
  - §3.4 Part-time schedules (`hours.part_time_schedule`)
- **§4 Code of Conduct**
  - §4.1 Respect and anti-harassment — prohibited conduct, examples (scenario `escalation_conduct`)
  - §4.2 Conflicts of interest
  - §4.3 Gifts and hospitality — modest gifts only; anything over $100 declared to HR
  - §4.4 Client confidentiality — points to RSE-SEC-01 §2
  - §4.5 Professional licensure — only licensed engineers seal drawings
- **§5 Health and Safety**
  - §5.1 Site safety and PPE — PPE required on site; reimbursement in RSE-EXP-01 §7.1
  - §5.2 Incident reporting — injuries and near-misses reported to the manager and HR within 24 hours
- **§6 Reporting Concerns** *(citable "contact HR" section)*
  - §6.1 How to report — manager, HR Service Desk, **HR Confidential**, ethics line (`contacts.hr_confidential`, `contacts.hr_service_desk`)
  - §6.2 Confidentiality — shared only with those who need to know
  - §6.3 Non-retaliation
  - §6.4 What happens next — HR acknowledges within 2 working days, investigates, closes the loop
- **§7 Personal Data and Privacy**
  - §7.1 What HR holds about you — profile, time off, benefits, tickets (mirrors Mock Data fields; no pay/health details in self-service)
  - §7.2 Who can see your records — you see all of yours; managers and directors see their reporting chain's profile and time-off balance only; benefits and HR tickets are private to you and HR (the access rule)
  - §7.3 Asking for your data — via HR Service Desk
- **§8 Acknowledgement** — read-and-acknowledge in the HR Portal

## RSE-PTO-01 — Paid Time Off Policy (5 pp, Markdown, owner HR)

- **§1 Purpose and Scope**
  - §1.1 Purpose — PTO covers vacation and personal time; sick time and leave are in RSE-LV-01
  - §1.2 Who is eligible — FT, PT, interns; contractors have no PTO (`pto.eligibility`) · rule **PTO-ELIGIBLE**
- **§2 Accrual**
  - §2.1 Full-time accrual — 15 / 20 / 25 days by completed years (0–2 / 3–5 / 6+) (`pto.accrual.full_time_days_per_year`)
  - §2.2 Part-time accrual — pro-rata by hours ÷ 40, worked example 24 h → 9 days (`pto.accrual.part_time_*`)
  - §2.3 Interns — 5 days per internship (`pto.accrual.intern_days_per_internship`)
  - §2.4 When PTO accrues — semi-monthly, annual ÷ 24 (`pto.accrual.timing`)
  - §2.5 Accrual during leave — continues on paid leave, pauses on unpaid (`pto.accrual.during_leave`)
- **§3 Using PTO**
  - §3.1 Increments — half-day minimum (`pto.use.minimum_increment_days`)
  - §3.2 Company holidays inside PTO — not deducted; see RSE-HOL-01 §1.3
  - §3.3 Your balance — no negative balance; options if short (`pto.use.negative_balance_allowed`, `insufficient_balance`) · rule **PTO-BALANCE**
  - §3.4 Checking your balance — HR Portal (`pto.use.balance_where`)
- **§4 Requesting and Approval**
  - §4.1 How to request (`pto.requesting.how`)
  - §4.2 Notice — more than 3 PTO days needs 14 calendar days' notice; shorter requests as early as practical (`notice_threshold_days`, `notice_required_calendar_days`) · rule **PTO-NOTICE**
  - §4.3 Who approves — manager; more than 10 consecutive days → director; see RSE-APR-01 §2 · rule **PTO-DIRECTOR**
  - §4.4 Field-role December blackout — Dec 18–31, director exception only · rule **PTO-BLACKOUT**
  - §4.5 Changing or cancelling PTO (`pto.requesting.changes`)
- **§5 Carryover and Payout**
  - §5.1 Carryover cap — 5 days; excess forfeited Dec 31 (`pto.carryover.cap_days`)
  - §5.2 Leave over year-end — up to 10 days if on approved leave spanning Dec 31 (`leave_exception_cap_days`)
  - §5.3 Leaving Ridgeline — HR handles any payout (`payout_on_exit`)
- **§6 Questions** — HR Service Desk

## RSE-HOL-01 — Holiday Calendar & Observance (2 pp, HTML, owner HR)

- **§1 How Holidays Work**
  - §1.1 Your calendar follows your home office — not where you're working or travelling (`holidays.calendar_follows`)
  - §1.2 Weekend holidays — observed Friday/Monday (`holidays.weekend_rule`)
  - §1.3 Holidays during PTO — not deducted (`holidays.during_pto`) · rule **PTO-DAYS**
  - §1.4 Part-time and field staff — scheduled-day rule; substitute day within 30 days (`holidays.part_time`, `field_worked_holiday`)
- **§2 US Company Holidays (Denver, Austin, Seattle)** — HTML table, 2026 and 2027, observed dates (`holidays.us`); includes Veterans Day
- **§3 Canada Company Holidays (Toronto)** — HTML table, 2026 and 2027 (`holidays.ca`)
- **§4 Floating Holidays** — US 2/yr, Canada 1/yr; not interns; no carryover (`holidays.floating`)
- **§5 Observances**
  - §5.1 Remembrance Day (Toronto) — two minutes' silence at 11:00; a working day (`holidays.observances.remembrance_day_toronto`)

## RSE-LV-01 — Leave of Absence Policy (6 pp, Markdown, owner HR)

- **§1 Purpose and Scope**
  - §1.1 Purpose
  - §1.2 Leave vs PTO — leave types here don't use PTO unless stated
- **§2 Sick Time** — 6 days/yr front-loaded; pro-rated; interns 3; note to HR after 3 consecutive days; no carryover (`leave.sick_time`)
- **§3 Parental Leave**
  - §3.1 Eligibility — 6 months' service; FT and PT; any parent (`leave.parental.eligible_*`)
  - §3.2 Pay and length — 12 weeks at 100% (`weeks_paid`, `pay`)
  - §3.3 When to take it — within 12 months; one block or two of ≥ 4 weeks (`take_within_months`, `blocks`)
  - §3.4 Notice — 30 calendar days when foreseeable (`notice_calendar_days`)
  - §3.5 Benefits and PTO during parental leave — benefits continue; PTO keeps accruing; points to RSE-PTO-01 §5.2 for year-end carryover
  - §3.6 Canadian employees — HR coordinates with government benefits (`leave.parental.canada`)
- **§4 Bereavement Leave** — 5 days immediate / 2 days extended family (`leave.bereavement`)
- **§5 Jury and Witness Duty** — up to 10 paid days (`leave.jury_witness`)
- **§6 Unpaid Personal Leave** — up to 30 calendar days; HR approves; PTO used first; accrual paused (`leave.unpaid_personal`)
- **§7 Medical Leave and Accommodations**
  - §7.1 Medical leave — arranged with HR; managers get dates only (`leave.medical_and_accommodations`)
  - §7.2 Accommodations *(citable "contact HR" section)* — how to ask HR, confidentiality
- **§8 Returning from Leave** — return-to-work check-in with manager and HR

## RSE-RW-01 — Remote & Hybrid Work Policy (5 pp, Markdown, owner HR)

- **§1 Purpose and Scope**
- **§2 Work Arrangements**
  - §2.1 Office-hybrid — default; 3 anchor days, Tue–Thu (`work_arrangements.office_hybrid`)
  - §2.2 Remote-approved — manager + HR; one week per quarter in the home office (`work_arrangements.remote_approved`)
  - §2.3 Field/site-based — not remote-eligible (`work_arrangements.field_site`)
- **§3 Who Can Become Remote-Approved** — 6 months' service; not field or interns; contractors per contract; no active performance plan (`remote_work.remote_approved_eligibility`)
- **§4 Requesting a Change** — manager endorses, HR approves within 10 working days; annual review; can be revoked (`remote_work.change_request`)
- **§5 Working Remotely**
  - §5.1 Core hours — 10:00–15:00 local (`hours.core_hours_local`)
  - §5.2 Workspace and security — must meet RSE-SEC-01 §5
  - §5.3 Equipment — see RSE-EQ-01
  - §5.4 Office visits for remote-approved staff
- **§6 Temporary Remote Work** (working away from your usual location; not business travel)
  - §6.1 What counts — definition; business travel is RSE-LOC-01 §2
  - §6.2 Within your state or province — allowed; tell your manager
  - §6.3 Another US state or province — manager up to 30 calendar days/yr; over → HR review · rule **TRW-DOMESTIC**
  - §6.4 Another country — always HR review; see RSE-LOC-01 §3
  - §6.5 Field/site roles — not eligible · rule **TRW-ARRANGEMENT**

## RSE-LOC-01 — Work Location, Travel & Cross-Border Work Guidelines (4 pp, Markdown, owner HR)

- **§1 Your Work Location**
  - §1.1 What "work location" means — region and country on your HR record (`location.work_location_definition`)
- **§2 Business Travel**
  - §2.1 Pre-approval — manager (`location.business_travel.preapproval`)
  - §2.2 Booking — Ridgeline Travel portal; costs per RSE-EXP-01
  - §2.3 Business travel vs temporary remote work — business trips up to 14 calendar days need no Cross-Border Review, even abroad (`business_trip_no_review_up_to_calendar_days`)
  - §2.4 Adding personal days to a trip — PTO + personal costs (`location.business_travel.personal_days`)
- **§3 Working from Another Country**
  - §3.1 Always reviewed by HR · rule **TRW-ABROAD**
  - §3.2 Annual cap — 20 working days/yr; over the cap only by HR exception (`cap_working_days_per_year`) · rule **TRW-ABROAD-CAP**
  - §3.3 Request at least 28 calendar days ahead · rule **TRW-ABROAD-NOTICE**
  - §3.4 Security requirements — see RSE-SEC-01 §5.4
- **§4 Cross-Border Review** *(citable "contact HR" section)*
  - §4.1 What HR reviews — tax, immigration/work authorization, insurance, payroll; Ridgeline doesn't give personal tax, immigration or legal advice
  - §4.2 How to request — HR ticket, category remote_work, with dates, country, work plan
  - §4.3 Timeline — decision within 10 working days
- **§5 Moving Permanently** — contact HR before any permanent change of work location

## RSE-SEC-01 — Information Security & Acceptable Use (6 pp, Markdown, owner IT)

- **§1 Scope and Ownership**
  - §1.1 Who this applies to — everyone with Ridgeline access, contractors included
  - §1.2 Policy owner — Head of Information Security (`people.security_lead`)
- **§2 Data Classification** — Public, Internal, Confidential, Client Restricted, with engineering examples (drawings, client models = Client Restricted)
- **§3 Devices**
  - §3.1 Company-managed devices — required for Confidential and Client Restricted data
  - §3.2 Personal devices — browser webmail and HR Portal only, with MFA; phones with mobile management
  - §3.3 Personal laptops — never for project files
  - §3.4 Lost or stolen devices — report within 1 hour
- **§4 Accounts and Access** — MFA; 5-minute screen lock; no shared accounts (`security.access`)
- **§5 Working Remotely and Travelling**
  - §5.1 VPN — always off-site
  - §5.2 Public Wi-Fi — VPN only
  - §5.3 Printing at home — never Client Restricted
  - §5.4 Working from another country — notify IT Security ≥ 5 working days ahead; travel laptop may be issued · rule **TRW-SECURITY**
- **§6 Acceptable Use**
  - §6.1 Personal use — limited, reasonable
  - §6.2 AI tools — no Confidential or Client Restricted data in public AI tools
  - §6.3 Installing software — approved catalogue only
- **§7 Incident Reporting**
  - §7.1 Report within 1 hour to IT Security (`contacts.it_security`)
- **§8 Consequences** — access removal; HR process per RSE-HB-01

## RSE-EXP-01 — Travel & Expense Reimbursement (5 pp, PDF, owner Finance)

- **§1 Principles and Scope** — reasonable, business-necessary, cheapest practical option
- **§2 Before You Travel**
  - §2.1 Pre-approval — manager; see RSE-LOC-01 §2.1
  - §2.2 Booking — Ridgeline Travel portal (`contacts.travel_desk`)
- **§3 Getting There**
  - §3.1 Airfare — economy ≤ 6 h; premium economy > 6 h; business class with director approval · rule **EXP-AIRFARE**
  - §3.2 Personal car mileage — $0.70/mile · rule **EXP-MILEAGE**
  - §3.3 Ground transport — taxis, ride-share, rental cars (compact/intermediate)
- **§4 Lodging** — $250/night US, $275/night international · rule **EXP-LODGING**
- **§5 Meals and Entertainment**
  - §5.1 Meals — $75/day domestic, $90/day international; amount over the cap not reimbursed · rule **EXP-MEALS**
  - §5.2 Client entertainment — $100/person, manager pre-approval · rule **EXP-ENTERTAIN**
  - §5.3 Alcohol — only within pre-approved client entertainment
- **§6 Combining Business and Personal Travel**
  - §6.1 Personal days are PTO — see RSE-PTO-01
  - §6.2 Airfare — reimbursed up to the business-only comparison fare quoted at booking
  - §6.3 Personal-day costs — lodging and meals on personal days not reimbursed
- **§7 Other Reimbursable Items**
  - §7.1 Safety equipment (PPE) — field/site roles, $300/yr · rule **EXP-PPE**
  - §7.2 Professional licence renewals
  - §7.3 Not reimbursable — list (`expenses.limits.not_reimbursable`)
- **§8 Submitting a Claim**
  - §8.1 Receipts — required from $25 · rule **EXP-RECEIPT**
  - §8.2 Deadlines — 30 days; after 60 days only with director exception
  - §8.3 Currency — USD limits; conversion at expense-date rate (`expenses.currency_rule`)
  - §8.4 Who approves — ≤ $1,000 manager; ≤ $5,000 director; above, VP Finance · rule **EXP-APPROVER**

## RSE-BEN-01 — Benefits Summary & Eligibility (6 pp, HTML, owner HR)

- **§1 Eligibility and Coverage**
  - §1.1 Who is eligible — by Employment Type (`benefits.eligibility`)
  - §1.2 When coverage starts — first of the month after hire (`benefits.coverage_start`)
  - §1.3 Coverage levels — employee / +spouse / +children / family
- **§2 US Plans** (HTML table per plan)
  - §2.1 Medical — PPO
  - §2.2 Medical — HDHP with HSA ($750 / $1,500 employer contribution)
  - §2.3 Dental
  - §2.4 Vision
  - §2.5 401(k) — 100% match on first 4%; immediate vesting
  - §2.6 Life insurance — 1× base pay, company-paid
- **§3 Enrolling and Making Changes**
  - §3.1 New hires — 30 calendar days from hire (`new_hire_window_calendar_days`)
  - §3.2 If you miss the window — open enrollment or a qualifying life event
  - §3.3 Open enrollment — Nov 16–30 2026, effective Jan 1 2027
  - §3.4 Qualifying life events — 31 days (birth/adoption, marriage, loss of coverage)
- **§4 Benefits During Leave** — continue on paid leave; unpaid > 30 days contact HR (`benefits.during_leave`)
- **§5 Canada: RSE Canada Group Plan** — summary only; details via HR (`benefits.canada`)
- **§6 Plan-Specific Questions** *(citable "contact HR" section)* — claims, plan details, Canadian plan, anything not in this summary → HR Service Desk

## RSE-EQ-01 — Equipment & Home-Office Stipend (3 pp, Markdown, owner IT)

- **§1 Standard Equipment** — laptop, two monitors, headset; field rugged tablet (`equipment.standard_kit`)
- **§2 Home-Office Stipend**
  - §2.1 Remote-approved — $500 one-time
  - §2.2 Office-hybrid — $250 one-time
  - §2.3 Not eligible — field/site, interns, contractors
  - §2.4 Internet — $50/month, remote-approved only
  - §2.5 How to claim — via expense claim within 90 days of becoming eligible; manager approves (RSE-APR-01 §5)
- **§3 Personal Equipment** — personal laptops not reimbursed and not for project files; see RSE-SEC-01 §3.3
- **§4 Care, Loss and Return** — report loss per RSE-SEC-01 §3.4; return on leaving

## RSE-ONB-01 — Onboarding Procedures (3 pp, Markdown, owner HR)

- **§1 Before Day One** — documents to HR; equipment ready (RSE-EQ-01 §1)
- **§2 Your First Week**
  - §2.1 Security training — within 5 working days
  - §2.2 HR Portal setup — profile, time off, benefits
  - §2.3 Benefits enrollment — 30-day window; see RSE-BEN-01 §3.1
- **§3 Your First 90 Days**
  - §3.1 Check-ins at 30, 60, 90 days
  - §3.2 Remote-approved arrangements — not before 6 months; see RSE-RW-01 §3
  - §3.3 Using PTO — as soon as accrued
- **§4 Who to Contact** — HR Service Desk, IT, manager

## RSE-APR-01 — Approval Matrix (2 pp, Markdown, owner HR)

- **§1 How to Read This Matrix** — manager / director / HR / VP Finance defined (`approvals.definitions`)
- **§2 Time Off** — table (`approvals.time_off`)
- **§3 Work Location and Travel** — table (`approvals.work_location`)
- **§4 Expenses** — table (`approvals.expenses`)
- **§5 Benefits, Equipment and Other** — table (`approvals.other`)
- **§6 Exceptions** — Director of People & HR (`approvals.exceptions`)
