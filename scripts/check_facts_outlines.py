"""Consistency check: every § cited in corpus/_facts.yaml exists in corpus/_outlines.md,
every Compliance Check rule is placed, not_covered gaps never appear, and the demo
scenario arithmetic holds. Usage: python scripts/check_facts_outlines.py .   (needs pyyaml)"""
import re, sys, datetime as d, yaml
root=sys.argv[1]
F=yaml.safe_load(open(f"{root}/corpus/_facts.yaml"))
O=open(f"{root}/corpus/_outlines.md").read()
errs=[]
# sections defined in outlines: per doc heading "## RSE-XX-01" then "§n" / "§n.n"
defined=set(); doc=None
for line in O.splitlines():
    m=re.match(r"## (RSE-[A-Z]+-\d\d)",line)
    if m: doc=m.group(1); continue
    m=re.match(r"\s*- \*\*§(\d+)\b",line) or re.match(r"\s*- §(\d+(?:\.\d+)?)\b",line)
    if m and doc: defined.add(f"{doc} §{m.group(1)}")
raw=open(f"{root}/corpus/_facts.yaml").read()
cites=set(re.findall(r"RSE-[A-Z]+-\d\d §\d+(?:\.\d+)?",raw))
missing=sorted(c for c in cites if c not in defined)
if missing: errs.append(f"cited but not in outlines: {missing}")
# cross-refs inside outlines too
oc=set(re.findall(r"RSE-[A-Z]+-\d\d §\d+(?:\.\d+)?",O))
m2=sorted(c for c in oc if c not in defined)
if m2: errs.append(f"outline cross-refs unresolved: {m2}")
# docs
ids=[x["id"] for x in F["documents"]]; pages=sum(x["pages"] for x in F["documents"])
for i in ids:
    if f"## {i}" not in O: errs.append(f"no outline for {i}")
fmts={x["format"] for x in F["documents"]}
# rule ids
rules={r["id"]:r for v in F["compliance_rules"].values() for r in v}
orules=set(re.findall(r"rule \*\*([A-Z-]+)\*\*",O))
if set(rules)-orules: errs.append(f"rules not placed in outlines: {sorted(set(rules)-orules)}")
if orules-set(rules): errs.append(f"outline rules unknown: {sorted(orules-set(rules))}")
for r in rules.values():
    if r["cite"] not in defined: errs.append(f"rule {r['id']} cite {r['cite']} undefined")
# not_covered never in outlines body (outside the rules list line)
body=O.split("---",1)[1].lower()
for t in F["not_covered"]:
    for w in re.split(r"\s*/\s*",t):
        if w.lower() in body: errs.append(f"not_covered term in outlines: {w}")
# demo arithmetic
def hol(cal): return {x["date"] for y in F["holidays"][cal].values() if isinstance(y,list) for x in y}
def wd(a,b,cal):
    H=hol(cal); return sum(1 for i in range((b-a).days+1) if (a+d.timedelta(i)).weekday()<5 and (a+d.timedelta(i)) not in H)
p=F["scenarios"]["pto_demo"]; n=wd(p["dates"]["from"],p["dates"]["to"],"us")
assert n==2, n
assert wd(p["dates"]["from"],p["dates"]["to"],"ca")==3
r=F["scenarios"]["remote_demo"]; n=wd(r["dates"]["from"],r["dates"]["to"],"us"); assert n==r["working_days"]==30, n
assert n>F["location"]["working_abroad"]["cap_working_days_per_year"]
assert (r["dates"]["from"]-F["meta"]["demo_today"]).days>=F["location"]["working_abroad"]["request_notice_calendar_days"]
t=F["scenarios"]["multi_doc_toronto_trip"]; assert len(t["pto_days"])==3 and all(x not in hol("us") for x in t["pto_days"])
b=F["scenarios"]["benefits_triage"]; assert b["window_ends"]==b["hire_date"]+d.timedelta(F["benefits"]["enrollment"]["new_hire_window_calendar_days"])
pl=F["scenarios"]["multi_doc_parental_leave"]["leave"]; assert pl["from"]+d.timedelta(weeks=pl["weeks"])==pl["returns"]
ex=F["scenarios"]["expense_compliance"]["items"]; assert ex[1]["computed"]["reimbursable"]==F["expenses"]["limits"]["meals_per_day"]["domestic"]
assert ex[0]["amount"]<=F["expenses"]["limits"]["ppe_per_year"]
for y in F["holidays"]["us"].values():
    if isinstance(y,list): assert all(x["date"].weekday()<5 for x in y)
for y in F["holidays"]["ca"].values():
    if isinstance(y,list): assert all(x["date"].weekday()<5 for x in y)
print(f"docs={len(ids)} pages={pages} formats={sorted(fmts)} sections={len(defined)} cites={len(cites)} rules={len(rules)}")
print("ERRORS:\n "+"\n ".join(errs) if errs else "OK: all cites resolve, rules placed, gaps absent, demo arithmetic holds")
