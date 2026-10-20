"""Groundedness judge (SPEC slice 7, session A step 3). Manual, never in CI.

Binary PASS/FAIL, reason first, JSON out, judged ONLY against the passages and tool outputs returned
in that turn. Model JUDGE_MODEL (default claude-sonnet-5-5). Claude Sonnet 5.5 rejects non-default
sampling parameters, so determinism comes from structured output and the fixed prompt; temperature
is left at its default rather than 0.

  uv run python -m evaluation.judge --run-id baseline            # judge every saved trace
  uv run python -m evaluation.judge --run-id baseline --seeded   # also judge the 5 seeded failures
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import json
from pathlib import Path
from typing import Any

import yaml

from evaluation.graders import reply

ROOT =Path(__file__).resolve().parent.parent
RESULTS = ROOT / "evaluation" / "results"

SYSTEM = """You check whether an HR assistant's answer is grounded. You get the EVIDENCE the assistant \
retrieved in that turn (policy passages, HR tool outputs and HR tool errors), the SESSION it was given \
(today's date and who is signed in), the loop's own events (e.g. stopping early at the tool-call limit) \
and the ANSWER it gave.

PASS only if every factual claim in the answer's policy facts and lead is supported by the EVIDENCE. \
Recommendations (suggested next steps) don't need support unless they state a policy rule. A claim that \
contradicts the evidence, or adds a rule, number, date or entitlement the evidence doesn't state, is a FAIL. \
Ignore what you believe about real-world HR law; only the EVIDENCE counts. The SESSION, the HR tool \
errors and the loop events are part of the EVIDENCE: a claim about today's date, who is signed in, a record \
the system refused to share or the assistant stopping early is supported when they show it.

Write your reason first, then the verdict."""

SCHEMA = {
    "type": "object",
    "properties": {"reason": {"type": "string"}, "verdict": {"type": "string", "enum": ["PASS", "FAIL"]}},
    "required": ["reason", "verdict"],
    "additionalProperties": False,
}


def session(record: dict[str, Any], demo_today: str) -> dict[str, Any]:
    """What the agent's system prompt told it: the Demo Date and the Requester (app/agent/loop.py)."""
    people = {e["id"]: e["name"] for e in json.loads((ROOT / "mock_data" / "employees.json").read_text())["employees"]}
    who = record.get("speaking_as")
    return {"today": demo_today, "requester": {"id": who, "name": people.get(who)} if who else "(not set)"}


def evidence(record: dict[str, Any], demo_today: str) -> dict[str, Any]:
    steps = record["responses"][-1]["trace"]["steps"]
    passages, tools, errors, events = [], [], [], []
    for s in steps:
        if s["kind"] == "error":
            events.append(s["summary"])
            continue
        if s["kind"] == "tool" and s["status"] == "error" and s.get("server") == "hr":
            errors.append({"tool": s["tool"], "output": s.get("output")})
            continue
        if s["kind"] != "tool" or s["status"] != "ok":
            continue
        out = s.get("output") or {}
        if "passages" in out:
            passages += [{k: p[k] for k in ("doc_id", "section", "section_heading", "text")} for p in out["passages"]]
        else:
            tools.append({"tool": s["tool"], "output": out})
    return {"session": session(record, demo_today), "passages": passages, "hr_tool_outputs": tools,
            "hr_tool_errors": errors, "loop_events": events}


def answer_for_judge(record: dict[str, Any]) -> dict[str, Any]:
    a = reply(record)
    return {k: a.get(k) for k in ("lead", "policy_facts", "recommendations", "escalation", "clarification", "refusal")}


async def judge_one(client: Any, model: str, record: dict[str, Any], demo_today: str) -> dict[str, Any]:
    prompt = (f"EVIDENCE:\n{json.dumps(evidence(record, demo_today), indent=1)}\n\n"
              f"ANSWER:\n{json.dumps(answer_for_judge(record), indent=1)}")
    r = await client.messages.create(
        model=model, max_tokens=2000, system=SYSTEM, messages=[{"role": "user", "content": prompt}],
        output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
    )
    if r.stop_reason == "refusal":
        return {"verdict": "ERROR", "reason": "judge refused"}
    text = "".join(b.text for b in r.content if b.type == "text")
    return json.loads(text)


def seeded_records(run_dir: Path) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Each seed: the baseline's run-1 answer to its item plus ONE invented Policy Fact."""
    seeds = yaml.safe_load((ROOT / "evaluation" / "seeded_failures.yaml").read_text())["seeded"]
    out = []
    for s in seeds:
        rec = json.loads((run_dir / "traces" / f"{s['item']}-1.json").read_text())
        rec = copy.deepcopy(rec)
        doc_id, section = s["citation"].split("#")
        reply(rec).setdefault("policy_facts", []).append(
            {"text": s["claim"], "citations": [{"doc_id": doc_id, "section": section, "snippet": s["claim"]}],
             "data_sources": []})
        out.append((s, rec))
    return out


async def main_async(args: argparse.Namespace) -> None:
    import anthropic

    from app.config import get_settings

    settings = get_settings()
    client = anthropic.AsyncAnthropic(api_key=settings.llm_api_key.get_secret_value() if settings.llm_api_key else None)
    run_dir = RESULTS / args.run_id
    demo_today = json.loads((run_dir / "config.json").read_text()).get("demo_today") or str(settings.demo_today)
    verdicts: dict[str, Any] = {"model": settings.judge_model, "items": {}, "seeded": {}}
    for path in sorted((run_dir / "traces").glob("*.json")):
        verdicts["items"][path.stem] = await judge_one(client, settings.judge_model, json.loads(path.read_text()),
                                                   demo_today)
        print(path.stem, verdicts["items"][path.stem]["verdict"])
    if args.seeded:
        for seed, rec in seeded_records(run_dir):
            verdicts["seeded"][seed["id"]] = await judge_one(client, settings.judge_model, rec, demo_today)
            print(seed["id"], verdicts["seeded"][seed["id"]]["verdict"])
    (run_dir / "judge.json").write_text(json.dumps(verdicts, indent=2) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--seeded", action="store_true")
    asyncio.run(main_async(ap.parse_args()))


if __name__ == "__main__":
    main()
