"""Consistency check for evaluation/: the Eval Set mix and format, every Citation resolves to a § in
corpus/_outlines.md, tools/Personas/enums are valid, the date arithmetic behind each gold answer
holds against corpus/_facts.yaml, the calibration set is disjoint from the Eval Set, and each
"contradicts" seed really contradicts the facts sheet.
Usage: python scripts/check_eval_set.py .   (needs pyyaml)"""
import re, sys, datetime as d, yaml
root=sys.argv[1]
F=yaml.safe_load(open(f"{root}/corpus/_facts.yaml"))
O=open(f"{root}/corpus/_outlines.md").read()
E=yaml.safe_load(open(f"{root}/evaluation/eval_set.yaml"))["items"]
C=yaml.safe_load(open(f"{root}/evaluation/calibration_queries.yaml"))
S=yaml.safe_load(open(f"{root}/evaluation/seeded_failures.yaml"))["seeded"]
errs=[]
def err(m): errs.append(m)
# sections defined in outlines (same parse as check_facts_outlines.py)
defined=set(); doc=None
for line in O.splitlines():
    m=re.match(r"## (RSE-[A-Z]+-\d\d)",line)
    if m: doc=m.group(1); continue
    m=re.match(r"\s*- \*\*§(\d+)\b",line) or re.match(r"\s*- §(\d+(?:\.\d+)?)\b",line)
    if m and doc: defined.add(f"{doc}#{m.group(1)}")
def flat(x): return [z for y in x for z in (y if isinstance(y,list) else [y])]
def cite_ok(c,where):
    if c not in defined: err(f"{where}: citation {c} not in outlines")
# enums and catalog (issues 8, 9, 10, 13)
MIX={"simple":5,"multi_doc":3,"workflow":7,"clarify":3,"escalate":4,"refuse":4,"safety":3}
BEH={"answer","clarify","escalate","refuse"}
TRIG={"sensitive_matter","needs_hr_review","hr_handles_per_policy","insufficient_evidence","user_requested_human"}
REAS={"not_covered","not_hr","legal_tax_immigration"}
TOOLS={"search_policy","get_policy_section","lookup_employee_profile","check_pto_balance","lookup_benefits_status",
       "list_hr_tickets","check_policy_compliance","draft_manager_message","create_mock_hr_ticket"}
PERSONAS={f"E10{n:02d}" for n in range(1,12)}
REQ=["id","category","speaking_as","prompt","expected_behavior","expected_citations","expected_tools",
     "forbidden_tools","on_confirm","gold_answer"]
ids=[i["id"] for i in E]
if len(E)!=29: err(f"{len(E)} items, want 29")
if len(set(ids))!=len(ids): err("duplicate ids")
got={k:sum(1 for i in E if i["category"]==k) for k in MIX}
if got!=MIX or any(i["category"] not in MIX for i in E): err(f"mix {got} != {MIX}")
for i in E:
    w=i["id"]
    for k in REQ:
        if k not in i: err(f"{w}: missing {k}")
    b=i["expected_behavior"]
    if b not in BEH: err(f"{w}: behaviour {b}")
    if (b=="escalate")!=("expected_trigger" in i) or i.get("expected_trigger",next(iter(TRIG))) not in TRIG: err(f"{w}: trigger")
    if (b=="refuse")!=("expected_reason" in i) or i.get("expected_reason",next(iter(REAS))) not in REAS: err(f"{w}: reason")
    if b=="answer" and i["category"] in MIX and "gold_short" not in i and i["category"]!="safety": err(f"{w}: answer item without gold_short")
    if i["speaking_as"] is not None and i["speaking_as"] not in PERSONAS: err(f"{w}: Persona {i['speaking_as']}")
    if i["on_confirm"] not in {"confirm","cancel","none"}: err(f"{w}: on_confirm")
    for c in flat(i["expected_citations"])+i.get("also_accept",[]): cite_ok(c,w)
    if set(flat(i["expected_citations"]))&set(i.get("also_accept",[])): err(f"{w}: citation both required and also_accept")
    for t in i["expected_tools"]+i["forbidden_tools"]+list(i.get("key_args",{})):
        if t not in TOOLS: err(f"{w}: unknown tool {t}")
    if set(i["expected_tools"])&set(i["forbidden_tools"]): err(f"{w}: tool both expected and forbidden")
    if set(i.get("key_args",{}))&set(i["forbidden_tools"]): err(f"{w}: key_args on a forbidden tool")
    if "gold_sequence" in i:
        if i["category"]!="workflow": err(f"{w}: gold_sequence outside workflow")
        if set(i["gold_sequence"])-{"CONFIRM"}-set(i["expected_tools"]): err(f"{w}: gold_sequence tool not expected")
if sum("gold_sequence" in i for i in E)!=2: err("want exactly 2 gold_sequences (the demo Workflows)")
if not any(i["on_confirm"]=="cancel" for i in E): err("no cancel item")
# eval prompts and calibration queries share nothing
cal=C["in_corpus"]+C["out_of_corpus"]
if len(C["in_corpus"])<15 or len(C["out_of_corpus"])<15: err("calibration: want ~15 in and ~15 out")
for q in C["in_corpus"]:
    for c in (q["expected"] if isinstance(q["expected"],list) else [q["expected"]]): cite_ok(c,q["id"])
words=lambda s:set(re.findall(r"[a-z0-9']+",s.lower()))-{"a","the","for","of","to","in","my","i","is","at","do","can","how","and","on","from","what"}
for q in cal:
    for i in E:
        a,b=words(q["query"]),words(i["prompt"])
        if a and len(a&b)/len(a|b)>=0.5: err(f"{q['id']} overlaps {i['id']}")
gaps=[g for g in F["not_covered"]]
held=[g for g in gaps if any(w in g for w in ("tuition",))]
gq=[q for q in C["out_of_corpus"] if q["kind"]=="gap"]
for g in gaps:
    hit=any(any(w[:6] in q["query"].lower() for w in re.split(r"[\s/]+",g) if len(w)>4) for q in gq)
    if g in held and hit: err(f"held-out gap {g} in calibration")
    if g not in held and not hit: err(f"gap {g} missing from calibration")
# date arithmetic behind the gold answers
def hol(cal): return {x["date"] for y in F["holidays"][cal].values() if isinstance(y,list) for x in y}
def wd(a,b,cal="us"):
    H=hol(cal); return sum(1 for k in range((b-a).days+1) if (a+d.timedelta(k)).weekday()<5 and (a+d.timedelta(k)) not in H)
D=d.date.fromisoformat; today=F["meta"]["demo_today"]
assert today==D("2026-11-02") and today.weekday()==0
P=F["pto"]["requesting"]; W=F["location"]["working_abroad"]
assert wd(D("2026-11-11"),D("2026-11-13"))==2                                   # W01
assert wd(D("2026-11-12"),D("2026-11-13"))==2 > 1.5                             # W03 vs Priya's 1.5
n=wd(D("2026-12-21"),D("2026-12-24")); assert n==4 > P["notice_threshold_days"]  # W04
assert (D("2026-12-21")-today).days>=P["notice_required_calendar_days"]
bl=P["field_blackout"]["window"]; assert D("2026-"+bl["from"])<=D("2026-12-21")<=D("2026-"+bl["to"])
n=wd(D("2026-11-30"),D("2026-12-14")); assert n==11>P["director_threshold_consecutive_days"]  # W05
assert F["scenarios"]["pto_demo"]["pto_available"]==11 and (D("2026-11-30")-today).days>=14
assert wd(D("2027-01-04"),D("2027-02-12"))==30>W["cap_working_days_per_year"]     # W02
assert (D("2027-01-04")-today).days>=W["request_notice_calendar_days"]
assert (D("2027-07-10")-D("2027-06-01")).days+1==40>F["remote_work"]["temporary_remote_work"]["other_us_state_or_province"]["manager_approval_up_to_calendar_days"]  # E02
assert [x["date"] for x in F["holidays"]["us"]["2026"] if "Thanksgiving" in x["name"]]==[D("2026-11-26"),D("2026-11-27")]  # S05
assert wd(D("2026-12-10"),D("2026-12-14"))==3                                   # M01
assert F["scenarios"]["benefits_triage"]["window_ends"]==D("2026-11-11")        # W07
L=F["expenses"]["limits"]
assert (L["meals_per_day"]["domestic"],L["ppe_per_year"],120-L["meals_per_day"]["domestic"])==(75,300,45)  # W06
assert (L["lodging_per_night"]["international"],L["meals_per_day"]["international"])==(275,90)            # M01
assert (F["pto"]["carryover"]["cap_days"],F["pto"]["carryover"]["leave_exception_cap_days"])==(5,10)       # S01, M02
assert F["equipment"]["home_office_stipend"]["remote_approved_one_time"]==500                               # S04
assert F["work_arrangements"]["office_hybrid"]["anchor_days"]==["Tue","Wed","Thu"]                         # S03
# seeds
for s in S:
    if s["item"] not in ids: err(f"{s['id']}: unknown item")
    cite_ok(s["citation"],s["id"])
    if s["kind"]=="contradicts":
        v=F
        for k in s["contradicts_fact"].split("."): v=v[k]
        nums=re.findall(r"\d+",s["claim"])
        if isinstance(v,int) and str(v) in nums: err(f"{s['id']}: claim agrees with {s['contradicts_fact']}")
if len(S)!=5: err("want 5 seeds")
print(f"items={len(E)} mix={got} citations={len({c for i in E for c in flat(i['expected_citations'])+i.get('also_accept',[])})} "
      f"calibration={len(C['in_corpus'])}in/{len(C['out_of_corpus'])}out seeds={len(S)}")
print("ERRORS:\n "+"\n ".join(errs) if errs else "OK: mix, format, citations, tools, Personas, date arithmetic, calibration disjointness and seeds all hold")
