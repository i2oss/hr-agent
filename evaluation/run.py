"""Run the Eval Set through POST /chat (SPEC slice 7, session A step 1). Manual, never in CI.

  uv run python -m evaluation.run --run-id baseline [--runs 3] [--base-url URL] [--items W01-pto-demo ...]
  uv run python -m evaluation.run --run-id deployed-cold --sample 2 --items S01-carryover-cap --base-url URL

Targets the local Docker image (RATE_LIMITS_ENABLED=false) or the deployed URL (sends X-Eval-Bypass
from EVAL_BYPASS_KEY). Fresh session per item per run. on_confirm: confirm → confirm the first pending
action; cancel → cancel every pending action; none → never confirm. Saves every response to
evaluation/results/<run-id>/traces/<item>-<n>.json plus config.json, then grades. Each record has
client_ms (wall time of each request as the runner saw it) and config.json has health_ms (the first
/health, which absorbs a cold start's wake-up). --sample N makes one pass saved as run N with its config in
config-<N>.json, so cold samples taken on separate occasions add to one run id instead of overwriting it.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

import httpx
import yaml

from evaluation import graders

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "evaluation" / "results"


def load_items(only: list[str] | None = None) -> list[dict[str, Any]]:
    items = yaml.safe_load((ROOT / "evaluation" / "eval_set.yaml").read_text())["items"]
    return [i for i in items if not only or i["id"] in only]


def run_item(client: httpx.Client, item: dict[str, Any], n: int) -> dict[str, Any]:
    session = uuid.uuid4().hex
    body = {"session_id": session, "speaking_as": item["speaking_as"], "message": item["prompt"]}
    t0 = time.perf_counter()
    r = client.post("/chat", json=body)
    client_ms = [round((time.perf_counter() - t0) * 1000)]
    r.raise_for_status()
    responses = [r.json()]
    confirmed = False
    while (pending := responses[-1].get("pending_action")) and item["on_confirm"] != "none":
        decision = "confirm" if item["on_confirm"] == "confirm" and not confirmed else "cancel"
        t0 = time.perf_counter()
        r = client.post(f"/chat/actions/{pending['action_id']}", json={"decision": decision})
        client_ms.append(round((time.perf_counter() - t0) * 1000))
        r.raise_for_status()
        responses.append(r.json())
        confirmed = confirmed or decision == "confirm"
    return {"item_id": item["id"], "run": n, "speaking_as": item["speaking_as"], "session_id": session,
            "client_ms": client_ms, "responses": responses}


def git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--base-url", default="http://127.0.0.1:8000")
    ap.add_argument("--items", nargs="*")
    ap.add_argument("--sample", type=int, help="one pass saved as run N, config in config-<N>.json (cold samples)")
    args = ap.parse_args()
    run_numbers = [args.sample] if args.sample else list(range(1, args.runs + 1))

    out = RESULTS / args.run_id
    (out / "traces").mkdir(parents=True, exist_ok=True)
    headers = {"X-Eval-Bypass": os.environ["EVAL_BYPASS_KEY"]} if os.environ.get("EVAL_BYPASS_KEY") else {}
    with httpx.Client(base_url=args.base_url, timeout=180, headers=headers) as client:
        t0 = time.perf_counter()
        health = client.get("/health").json()
        health_ms = round((time.perf_counter() - t0) * 1000)
        config_name = f"config-{args.sample}.json" if args.sample else "config.json"
        (out / config_name).write_text(json.dumps({
            "run_id": args.run_id, "date": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
            "base_url": args.base_url, "runs": len(run_numbers), "git_sha": git_sha(),
            "server_version": health.get("version"), "health_ms": health_ms,
            "llm": health.get("llm"), "index": health.get("index"), "demo_today": health.get("demo_today"),
            "retrieval": {"top_k": os.environ.get("RETRIEVAL_TOP_K", "5"),
                          "mode": os.environ.get("RETRIEVAL_MODE", "hybrid")},
        }, indent=2) + "\n")
        items = load_items(args.items)
        for n in run_numbers:
            for item in items:
                rec = run_item(client, item, n)
                (out / "traces" / f"{item['id']}-{n}.json").write_text(json.dumps(rec, indent=2) + "\n")
                g = graders.grade(item, rec)
                print(f"run {n} {item['id']:<28} behavior={'ok' if g['behavior'] else 'FAIL'} "
                      f"tools={'ok' if g['tools']['correct'] else 'FAIL'} safe={'ok' if g['safe'] else 'UNSAFE'} "
                      f"{g['total_ms']} ms")
    print(f"saved {out.relative_to(ROOT)}; run `python -m evaluation.report` to regenerate the report")


if __name__ == "__main__":
    main()
