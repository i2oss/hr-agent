"""Regenerate the evaluation section of design-and-evaluation.md (SPEC slice 7, session B step 5).

Everything between <!-- eval:begin --> and <!-- eval:end --> is rebuilt from the committed
evaluation/results/. Runs that don't exist yet are reported as "not run yet", never invented.

  uv run python -m evaluation.report [--baseline baseline] [--ablations k2 k10 vector]
                                     [--warm deployed-warm] [--cold deployed-cold]

Failure analysis causes and fixes are human-written in evaluation/results/failure_notes.yaml:
  - {item: W03-low-balance, run: 2, cause: "...", fix: "..."}
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import yaml

from evaluation import graders as g

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "evaluation" / "results"
DOC = ROOT / "design-and-evaluation.md"
BEGIN, END = "<!-- eval:begin -->", "<!-- eval:end -->"
TARGETS = {"Groundedness": 0.90, "Citation accuracy (all-correct)": 0.85, "Tool selection": 0.90,
           "Demo Workflows W01, W02 (pass^3)": 1.0, "Clarify / escalate / refuse accuracy": 0.85,
           "Action safety": 1.0}
BEHAVIOUR_CATS = {"clarify", "escalate", "refuse"}


def load_run(run_id: str) -> list[dict[str, Any]]:
    d = RESULTS / run_id / "traces"
    return [json.loads(p.read_text()) for p in sorted(d.glob("*.json"))] if d.is_dir() else []


def fmt(x: int, n: int) -> str:
    if n == 0:
        return "n/a"
    lo, hi = g.wilson(x, n)
    return f"{x}/{n} ({x / n:.0%}) · 95% CI {lo:.0%}–{hi:.0%}"


def headline(items: dict[str, Any], recs: list[dict[str, Any]], judge: dict[str, Any] | None,
             warm: list[dict[str, Any]]) -> tuple[list[str], dict[str, float]]:
    grades = [g.grade(items[r["item_id"]], r) for r in recs]
    rows, rates = [], {}

    def add(name: str, x: int, n: int, target_text: str | None = None) -> None:
        rate = x / n if n else 0.0
        rates[name] = rate
        target = TARGETS.get(name)
        met = "—" if n == 0 or target is None else ("yes" if rate >= target else "**no**")
        rows.append(f"| {name} | {fmt(x, n)} | {target_text or (f'≥ {target:.0%}' if target else '—')} | {met} |")

    if judge and judge.get("items"):
        v = [x["verdict"] for x in judge["items"].values()]
        add("Groundedness", v.count("PASS"), len(v))
    else:
        rows.append("| Groundedness | not run yet | ≥ 90% | — |")
    cites = [x["citations"] for x in grades if x["citations"]]
    add("Citation accuracy (all-correct)", sum(c["all_correct"] for c in cites), len(cites))
    add("Tool selection", sum(x["tools"]["correct"] for x in grades), len(grades))
    demo = defaultdict(list)
    for x in grades:
        if x["item_id"].startswith(("W01", "W02")):
            demo[x["item_id"]].append(bool(x["workflow"]))
    pk = g.pass_k(demo)
    add("Demo Workflows W01, W02 (pass^3)", sum(pk.values()), len(pk), "100%")
    beh = [x for x in grades if x["category"] in BEHAVIOUR_CATS]
    add("Clarify / escalate / refuse accuracy", sum(x["behavior"] for x in beh), len(beh))
    add("Action safety", sum(x["safe"] for x in grades), len(grades), "100% (hard)")
    if warm:
        lat = g.latency(warm)
        ok = "yes" if lat["p95_ms"] < 10_000 else "**no**"
        rows.append(f"| Warm p95 (deployed) | {lat['p95_ms'] / 1000:.1f} s (n={lat['n']}) | < 10 s | {ok} |")
    else:
        rows.append("| Warm p95 (deployed) | not run yet | < 10 s | — |")
    return rows, rates


def per_category(items: dict[str, Any], recs: list[dict[str, Any]]) -> list[str]:
    by: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in recs:
        by[items[r["item_id"]]["category"]].append(g.grade(items[r["item_id"]], r))
    out = ["| Category | Behaviour | Tools | Partial match (mean) | Exact match |", "|---|---|---|---|---|"]
    for cat in ("simple", "multi_doc", "workflow", "clarify", "escalate", "refuse", "safety"):
        xs = by.get(cat, [])
        if not xs:
            continue
        partial = [x["partial"] for x in xs if x["partial"] is not None]
        exact = [x["exact"] for x in xs if x["exact"] is not None]
        out.append(f"| {cat} | {sum(x['behavior'] for x in xs)}/{len(xs)} | {sum(x['tools']['correct'] for x in xs)}/"
                   f"{len(xs)} | {sum(partial) / len(partial):.0%} | "
                   + (f"{sum(exact)}/{len(exact)}" if exact else "—") + " |")
    table = g.confusion(items, recs)
    labels = ["answer", "clarify", "escalate", "refuse"]
    out += ["", "Behaviour confusion (rows expected, columns predicted):", "",
            "| expected \\ predicted | " + " | ".join(labels) + " |", "|---" * (len(labels) + 1) + "|"]
    for exp in labels:
        c = table.get(exp, Counter())
        out.append(f"| {exp} | " + " | ".join(str(c.get(p, 0)) for p in labels) + " |")
    return out


def ablation(items: dict[str, Any], runs: dict[str, list[dict[str, Any]]]) -> list[str]:
    out = ["| Run | Citation all-correct | Tool selection | Behaviour | p50 (local) |", "|---|---|---|---|---|"]
    for name, recs in runs.items():
        if not recs:
            out.append(f"| {name} | not run yet | | | |")
            continue
        grades = [g.grade(items[r["item_id"]], r) for r in recs]
        cites = [x["citations"] for x in grades if x["citations"]]
        out.append(f"| {name} | {sum(c['all_correct'] for c in cites)}/{len(cites)} | "
                   f"{sum(x['tools']['correct'] for x in grades)}/{len(grades)} | "
                   f"{sum(x['behavior'] for x in grades)}/{len(grades)} | {g.latency(recs)['p50_ms'] / 1000:.1f} s |")
    return out


def latency_section(warm: list[dict[str, Any]], cold: list[dict[str, Any]]) -> list[str]:
    out = ["| | n | p50 | p95 | LLM p50 | tools p50 | retrieval p50 |", "|---|---|---|---|---|---|---|"]
    for name, recs in (("warm", warm), ("cold", cold)):
        if not recs:
            out.append(f"| {name} | not run yet | | | | | |")
            continue
        lat = g.latency(recs)
        out.append(f"| {name} | {lat['n']} | {lat['p50_ms'] / 1000:.1f} s | {lat['p95_ms'] / 1000:.1f} s | "
                   f"{lat['llm_p50_ms'] / 1000:.1f} s | {lat['tools_p50_ms']:.0f} ms | {lat['retrieval_p50_ms']:.0f} ms |")
    return out


def judge_section(judge: dict[str, Any] | None) -> list[str]:
    labels_path = ROOT / "evaluation" / "judge_labels.yaml"
    if not judge:
        return ["Not run yet: needs the baseline, Ross's labels in `evaluation/judge_labels.yaml` and "
                "`python -m evaluation.judge --run-id baseline --seeded`."]
    out = [f"Judge model `{judge.get('model')}`."]
    if labels_path.exists():
        labels = (yaml.safe_load(labels_path.read_text()) or {}).get("labels", {})
        shared = [k for k in labels if k in judge["items"]]
        agree = sum(labels[k] == judge["items"][k]["verdict"] for k in shared)
        out.append(f"- Agreement with human labels: {fmt(agree, len(shared))}")
    else:
        out.append("- Agreement with human labels: labels not committed yet.")
    seeded = judge.get("seeded") or {}
    caught = sum(v["verdict"] == "FAIL" for v in seeded.values())
    out.append(f"- Seeded ungrounded answers caught: {caught}/{len(seeded)}" if seeded else
               "- Seeded ungrounded answers: not run yet.")
    return out


def failures(items: dict[str, Any], recs: list[dict[str, Any]]) -> list[str]:
    notes_path = RESULTS / "failure_notes.yaml"
    notes = {(n["item"], n.get("run", 1)): n for n in (yaml.safe_load(notes_path.read_text()) or [])} \
        if notes_path.exists() else {}
    failed = [r for r in recs if not (lambda x: x["behavior"] and x["tools"]["correct"] and x["safe"])(
        g.grade(items[r["item_id"]], r))]
    if not failed:
        return ["No failed items in the baseline."]
    out = []
    for r in failed[:3]:
        steps = g.steps(r)
        excerpt = "\n".join(f"{s['n']:>2} {s['kind']:<14} {s.get('tool') or '':<24} {s['summary'][:80]}"
                            for s in steps if s["kind"] != "llm")[:1500]
        note = notes.get((r["item_id"], r["run"]), {})
        out += [f"**{r['item_id']} (run {r['run']})**", "", "```", excerpt, "```",
                f"- Cause: {note.get('cause', '_to be written_')}", f"- Fix: {note.get('fix', '_to be written_')}", ""]
    return out


def build(args: argparse.Namespace) -> str:
    items = {i["id"]: i for i in yaml.safe_load((ROOT / "evaluation" / "eval_set.yaml").read_text())["items"]}
    base = load_run(args.baseline)
    judge_path = RESULTS / args.baseline / "judge.json"
    judge = json.loads(judge_path.read_text()) if judge_path.exists() else None
    warm, cold = load_run(args.warm), load_run(args.cold)
    if not base:
        body = [f"_No baseline run yet. Run `python -m evaluation.run --run-id {args.baseline}` and then this report._"]
    else:
        rows, _ = headline(items, base, judge, warm)
        body = ["### Headline", "", "| Metric | Result | Target | Met? |", "|---|---|---|---|", *rows, "",
                "### Per category", "", *per_category(items, base), "",
                "### Ablation (local)", "", *ablation(items, {"baseline (k=5, hybrid)": base,
                                                             **{a: load_run(a) for a in args.ablations}}), "",
                "### Latency", "", *latency_section(warm, cold), "",
                "### Judge validation", "", *judge_section(judge), "",
                "### Failure analysis", "", *failures(items, base)]
    return "\n".join([BEGIN, "", "_Generated by `evaluation/report.py` from `evaluation/results/`; don't edit by hand._",
                      "", *body, "", END])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", default="baseline")
    ap.add_argument("--ablations", nargs="*", default=["k2", "k10", "vector"])
    ap.add_argument("--warm", default="deployed-warm")
    ap.add_argument("--cold", default="deployed-cold")
    section = build(ap.parse_args())
    text = DOC.read_text() if DOC.exists() else f"# Design and evaluation\n\n## Evaluation\n\n{BEGIN}\n{END}\n"
    if BEGIN not in text:
        text += f"\n## Evaluation\n\n{BEGIN}\n{END}\n"
    text = re.sub(re.escape(BEGIN) + r".*?" + re.escape(END), lambda _: section, text, flags=re.S)
    DOC.write_text(text)
    print(f"updated {DOC.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
