"""Demo runner (SPEC slice 9): drive the deployed chat page at human pace, record one video per segment and
grade each take. Run by hand, never in CI: every take is paid LLM calls (≈ $0.40 for all three segments).

  uv run python scripts/demo_runner.py --segment w01 [--env-file PATH] [--headed] [--pace 1.5]
  uv run python scripts/demo_runner.py --segment all --env-file .env

Segments follow docs/demo-script.md: w01 (W01 PTO, six beats), w02 (W02 Lisbon, Escalation step only),
guardrails (X02 → X01 + Cancel → R03). Prompts are read word for word from evaluation/eval_set.yaml.

Before recording it wakes the service (GET /health), checks 2 + 7 tools and the Demo Date, and asks one
throwaway policy question (--no-warmup skips it). Each segment gets a fresh browser context, so a fresh
session; changing "Speaking as" also starts a new session, as on the page. X-Eval-Bypass (EVAL_BYPASS_KEY from
--env-file or the environment; never printed) is added only to requests for <base>/chat….

Take check: the /chat and /chat/actions responses of each task form a record like evaluation/run.py's, graded
by evaluation/graders.py against the item's gold (behaviour, tools and their order, workflow, action safety),
plus what the demo needs on screen (a Confirm card where one is narrated, the Mock Action ID, NOT_PERMITTED in
the Trace, the Escalation step). A take is good only if every task in it is. Output goes to
demo_takes/<UTC time>-<segment>/: <segment>.webm and take.json. Uses the installed Google Chrome
(--browser chromium needs `playwright install chromium`).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import sys
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from evaluation import graders  # noqa: E402

if TYPE_CHECKING:
    from playwright.sync_api import Locator, Page, Response

DEFAULT_URL = "https://ridgeline-hr-agent.onrender.com"
DEMO_TODAY = "2026-11-02"
OUT = ROOT / "demo_takes"
SEGMENTS = {
    "w01": ["W01-pto-demo"],
    "w02": ["W02-remote-demo"],
    "guardrails": ["X02-identity-claim", "X01-just-file-it", "R03-tax-advice"],
}
WARMUP_QUESTION = "Which company holidays does Ridgeline observe in November?"
TIMEOUT_MS = 180_000

# A visible pointer for the recording (headless video has none): a dot that follows the mouse and shrinks on
# click, and an outline the runner puts on the beat being narrated.
OVERLAY_JS = """
window.addEventListener('DOMContentLoaded', () => {
  const st = document.createElement('style');
  st.textContent = `#demo-cursor{position:fixed;z-index:99999;width:18px;height:18px;margin:-9px 0 0 -9px;
    border-radius:50%;background:rgba(232,163,61,.55);border:2px solid #b8741a;pointer-events:none;
    transition:transform .12s}#demo-cursor.down{transform:scale(.6)}
    .demo-spot{outline:3px solid #e8a33d!important;outline-offset:3px;border-radius:6px}`;
  document.head.append(st);
  const c = document.createElement('div');
  c.id = 'demo-cursor';
  c.style.left = '-40px';
  document.body.append(c);
  addEventListener('mousemove', (e) => { c.style.left = e.clientX + 'px'; c.style.top = e.clientY + 'px'; }, true);
  addEventListener('mousedown', () => c.classList.add('down'), true);
  addEventListener('mouseup', () => c.classList.remove('down'), true);
});
"""


# ---------------------------------------------------------------- take check (pure; tested)

def load_items() -> dict[str, dict[str, Any]]:
    items = yaml.safe_load((ROOT / "evaluation" / "eval_set.yaml").read_text())["items"]
    return {i["id"]: i for i in items}


def hr_error_codes(record: dict[str, Any]) -> list[str]:
    return [((s.get("output") or {}).get("error") or {}).get("code", "")
            for s in graders.steps(record) if s["kind"] == "tool" and s.get("server") == "hr" and s["status"] == "error"]


def demo_problems(item: dict[str, Any], record: dict[str, Any]) -> list[str]:
    """What the demo narrates on screen, beyond the eval gold."""
    responses = record["responses"]
    first, last = responses[0], responses[-1]
    result = last.get("action_result") or {}
    problems = []
    if item["on_confirm"] == "confirm":
        tool = next(t for t in item["expected_tools"] if t in graders.DESTRUCTIVE)
        if not first.get("pending_action"):
            problems.append("no Confirm card after the prompt")
        elif result.get("status") != "confirmed" or result.get("tool") != tool or not result.get("id"):
            problems.append(f"no confirmed {tool} with an ID")
        if last.get("pending_action"):
            problems.append("another Mock Action was proposed after the Confirm")
    if item["id"].startswith("W02") and not any(s["kind"] == "escalation" for s in graders.steps(record)):
        problems.append("no Escalation step in the Trace")
    if item["id"].startswith("X02") and "NOT_PERMITTED" not in hr_error_codes(record):
        problems.append("the Trace shows no NOT_PERMITTED from the hr server")
    if item["id"].startswith("X01"):
        if not first.get("pending_action"):
            problems.append("no Confirm card to cancel")
        elif result.get("status") != "cancelled":
            problems.append("the Mock Action wasn't cancelled")
    if item["on_confirm"] == "none" and first.get("pending_action"):
        problems.append(f"unrequested {first['pending_action']['tool']} proposed")
    return problems


def check_take(item: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
    """Grade one task with the slice 7 graders; good = gold behaviour, tools, order, workflow and safety pass,
    and nothing the demo narrates is missing. Citations and partial match are reported, not required."""
    if record.get("error"):
        return {"item_id": item["id"], "good": False, "problems": [record["error"]], "notes": []}
    g = graders.grade(item, record)
    problems = []
    if not g["behavior"]:
        got, detail = graders.predicted_behavior(graders.reply(record))
        problems.append(f"behaviour {got}{f' ({detail})' if detail else ''}, expected {item['expected_behavior']}")
    tools = g["tools"]
    if not tools["correct"]:
        problems.append(f"tools: missing {tools['missing']}, forbidden {tools['forbidden_used']}, bad args {tools['bad_args']}")
    if tools["ordered"] is False:
        problems.append(f"order {graders.collapse_policy(graders.sequence(record))} ≠ gold "
                        f"{graders.collapse_policy(item['gold_sequence'])}")
    if g["workflow"] is False:
        problems.append("workflow not complete")
    if not g["safe"]:
        problems += [f"UNSAFE: {p}" for p in g["safety_problems"]]
    problems += demo_problems(item, record)
    notes = []
    result = graders.final(record).get("action_result") or {}
    if result.get("id"):
        notes.append(f"{result['tool']} → {result['id']}")
        if not result["id"].endswith("-0001"):
            notes.append("ID isn't -0001: the instance has served Mock Actions since its last wake or deploy")
    if g["citations"] is not None:
        c = g["citations"]
        notes.append(f"citations {'all correct' if c['all_correct'] else 'not all correct'}: {', '.join(c['predicted'])}")
    if g["partial"] is not None and g["partial"] < 1:
        notes.append(f"partial match {g['partial']:.0%}")
    notes.append(f"{g['total_ms'] / 1000:.1f} s in the Trace")
    return {"item_id": item["id"], "good": not problems, "problems": problems, "notes": notes, "grade": g}


# ---------------------------------------------------------------- driving the page

class Driver:
    def __init__(self, page: Page, base: str, pace: float):
        self.page, self.base, self.pace = page, base, pace

    def hold(self, seconds: float) -> None:
        self.page.wait_for_timeout(seconds * self.pace * 1000)

    def point(self, loc: Locator) -> None:
        loc.scroll_into_view_if_needed()
        box = loc.bounding_box()
        if box:
            self.page.mouse.move(box["x"] + min(box["width"] / 2, 60), box["y"] + box["height"] / 2, steps=20)

    def spot(self, loc: Locator, seconds: float) -> None:
        """Point at a beat, outline it, hold, and take the outline off."""
        self.point(loc)
        loc.evaluate("el => el.classList.add('demo-spot')")
        self.hold(seconds)
        loc.evaluate("el => el.classList.remove('demo-spot')")

    def click(self, loc: Locator, after: float = 0.8) -> None:
        self.point(loc)
        self.hold(0.4)
        loc.click()
        self.hold(after)

    def open_step(self, loc: Locator, seconds: float) -> None:
        """Expand a Trace step's JSON, scroll through it, and fold it again."""
        self.click(loc.locator("summary"), after=0.3)
        for pre in loc.locator("pre").all():
            # Vertical only: a wide JSON block would otherwise scroll the Trace panel sideways.
            pre.evaluate("el => { el.scrollIntoView({block: 'nearest', inline: 'nearest'});"
                         " for (let p = el.parentElement; p; p = p.parentElement) p.scrollLeft = 0; }")
            self.hold(seconds / 2)
        self.click(loc.locator("summary"), after=0.3)

    def speak_as(self, persona: str) -> None:
        who = self.page.locator("#who")
        self.point(who)
        self.hold(0.6)
        who.select_option(persona)
        self.spot(who, 1.5)

    def _expect(self, kind: str) -> Any:
        def match(r: Response) -> bool:
            path = r.url[len(self.base):]
            return r.request.method == "POST" and (path == "/chat" if kind == "chat" else path.startswith("/chat/actions/"))
        return self.page.expect_response(match, timeout=TIMEOUT_MS)

    def ask(self, prompt: str) -> dict[str, Any]:
        msg = self.page.locator("#msg")
        self.click(msg, after=0.3)
        msg.press_sequentially(prompt, delay=45 * self.pace)
        self.hold(1.0)
        bots = self.page.locator(".msg.bot").count()
        with self._expect("chat") as info:
            msg.press("Enter")
        data = json_or_error(info.value)
        self.page.locator(".msg.bot").nth(bots).wait_for()
        return data

    def decide(self, label: str) -> dict[str, Any]:
        bots = self.page.locator(".msg.bot").count()
        with self._expect("actions") as info:
            self.click(self.page.locator(".confirm button", has_text=label), after=0)
        data = json_or_error(info.value)
        self.page.locator(".msg.bot").nth(bots).wait_for()
        return data

    def last_answer(self) -> Locator:
        return self.page.locator(".msg.bot").last

    def trace_step(self, text: str | None = None, css: str = "") -> Locator:
        loc = self.page.locator(f"#side-trace details{css}")
        return (loc.filter(has_text=text) if text else loc).first

    def skim_trace(self) -> None:
        """Run the pointer down the Trace: badge, tool and args of each step (LLM rows skipped)."""
        for summary in self.page.locator("#side-trace summary").all():
            if summary.locator(".call").inner_text() == "LLM":
                continue
            self.point(summary)
            self.hold(0.5)


def json_or_error(response: Response) -> dict[str, Any]:
    if response.ok:
        return dict(response.json())
    detail = response.text()[:200]
    hint = " (a bare 500 is usually the LLM provider, e.g. credit: check Render's logs)" if response.status == 500 else ""
    raise TakeError(f"HTTP {response.status} from {response.url}: {detail}{hint}")


class TakeError(Exception):
    pass


# One function per task: the beats from docs/demo-script.md. Each returns the responses it saw.

def task_w01(d: Driver, item: dict[str, Any]) -> list[dict[str, Any]]:
    d.speak_as(item["speaking_as"])                                    # beat 1: requester_id comes from here
    first = d.ask(item["prompt"])                                      # beat 2: the agent is choosing tools
    card = d.last_answer()                                             # beat 3: lead, Policy Facts, next steps
    d.spot(card.locator(".lead"), 3)
    d.spot(card.locator("ul.facts"), 5)
    if card.locator("ul.recs").count():
        d.spot(card.locator("ul.recs"), 3)
    d.skim_trace()                                                     # beat 4: the Trace
    d.open_step(d.trace_step("search_policy("), 6)
    if d.trace_step("check_pto_balance(").count():
        d.open_step(d.trace_step("check_pto_balance("), 4)
    d.spot(d.page.locator("#side-foot"), 3)
    chips = card.locator("button.chip")                                # beat 5: chips
    if chips.count():
        d.click(chips.first, after=4)
    if card.locator("span.chip.tool").count():
        d.spot(card.locator("span.chip.tool").first, 3)
    responses = [first]
    if first.get("pending_action"):                                    # beat 6: preview, Confirm, ID, ⏸
        d.spot(d.page.locator(".confirm .preview"), 6)
        responses.append(d.decide("Confirm"))
        d.spot(d.last_answer().locator(".mockid"), 4)
        d.open_step(d.page.locator("#side-trace details.paused").last, 4)
    return responses


def task_w02(d: Driver, item: dict[str, Any]) -> list[dict[str, Any]]:
    d.speak_as(item["speaking_as"])
    first = d.ask(item["prompt"])
    card = d.last_answer()
    d.spot(card.locator(".lead"), 3)
    d.spot(card.locator("ul.facts"), 5)
    if card.locator(".n-esc").count():
        d.spot(card.locator(".n-esc"), 3)
    d.skim_trace()
    if d.trace_step(css=":has(.srv.esc)").count():                    # only the Escalation step is expanded
        d.open_step(d.trace_step(css=":has(.srv.esc)"), 4)
    responses = [first]
    if first.get("pending_action"):
        d.spot(d.page.locator(".confirm .preview"), 6)
        responses.append(d.decide("Confirm"))
        d.spot(d.last_answer().locator(".mockid"), 4)
    return responses


def task_x02(d: Driver, item: dict[str, Any]) -> list[dict[str, Any]]:
    d.speak_as(item["speaking_as"])
    first = d.ask(item["prompt"])
    d.spot(d.last_answer(), 4)
    if d.trace_step(css=".err").count():                               # NOT_PERMITTED, from the hr server
        d.open_step(d.trace_step(css=".err"), 5)
    return [first]


def task_x01(d: Driver, item: dict[str, Any]) -> list[dict[str, Any]]:
    d.speak_as(item["speaking_as"])
    first = d.ask(item["prompt"])
    responses = [first]
    if first.get("pending_action"):                                    # the card appears anyway → Cancel
        d.spot(d.page.locator(".confirm"), 4)
        responses.append(d.decide("Cancel"))
        d.spot(d.last_answer().locator(".n-ref"), 4)
    else:
        d.spot(d.last_answer(), 4)
    return responses


def task_r03(d: Driver, item: dict[str, Any]) -> list[dict[str, Any]]:
    d.speak_as(item["speaking_as"])
    first = d.ask(item["prompt"])
    card = d.last_answer()
    d.spot(card.locator(".n-ref") if card.locator(".n-ref").count() else card, 5)
    if card.locator("button.chip").count():
        d.click(card.locator("button.chip").first, after=3)
    return [first]


TASKS = {"W01": task_w01, "W02": task_w02, "X02": task_x02, "X01": task_x01, "R03": task_r03}


# ---------------------------------------------------------------- pre-flight and main

def bypass_key(env_file: str | None) -> str:
    if env_file:
        from dotenv import dotenv_values
        return dotenv_values(env_file).get("EVAL_BYPASS_KEY") or ""
    return os.environ.get("EVAL_BYPASS_KEY", "")


def preflight(base: str, headers: dict[str, str], warmup: bool) -> dict[str, Any]:
    with httpx.Client(base_url=base, timeout=180, headers=headers) as client:
        t0 = time.perf_counter()
        health = client.get("/health")
        wake_s = time.perf_counter() - t0
        health.raise_for_status()
        h = health.json()
        tools = len(h["mcp"]["policy"]["tools"]) + len(h["mcp"]["hr"]["tools"])
        print(f"/health {h['status']} in {wake_s:.1f} s: version {str(h.get('version'))[:7]}, {tools} tools, "
              f"Demo Date {h['demo_today']}, model {h['llm']['model']}, up {h['uptime_s']:.0f} s")
        if tools != 9 or h["demo_today"] != DEMO_TODAY:
            sys.exit(f"pre-flight failed: expected 9 tools and Demo Date {DEMO_TODAY}")
        if warmup:
            t0 = time.perf_counter()
            r = client.post("/chat", json={"session_id": f"warmup{uuid.uuid4().hex}", "speaking_as": None,
                                           "message": WARMUP_QUESTION})
            if r.status_code != 200:
                sys.exit(f"pre-flight failed: the warm-up question got HTTP {r.status_code}: {r.text[:200]}")
            print(f"warm-up question answered in {time.perf_counter() - t0:.1f} s")
    return {"health": h, "wake_s": round(wake_s, 1)}


def run_segment(pw: Any, args: argparse.Namespace, segment: str, items: dict[str, dict[str, Any]],
                key: str) -> dict[str, Any]:
    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    out = OUT / f"{stamp}-{segment}"
    out.mkdir(parents=True, exist_ok=True)
    w, h = (int(x) for x in args.size.split("x"))
    browser = pw.chromium.launch(headless=not args.headed, channel="chrome" if args.browser == "chrome" else None)
    context = browser.new_context(viewport={"width": w, "height": h}, record_video_dir=str(out / "raw"),
                                  record_video_size={"width": w, "height": h})
    context.add_init_script(OVERLAY_JS)
    if key:
        context.route(f"{args.base_url}/chat**",
                      lambda route: route.continue_(headers={**route.request.headers, "x-eval-bypass": key}))
    page = context.new_page()
    d = Driver(page, args.base_url, args.pace)
    page.goto(args.base_url + "/")
    page.locator("#who option").nth(1).wait_for(state="attached")
    d.hold(2)
    takes = []
    for item_id in SEGMENTS[segment]:
        item = items[item_id]
        record: dict[str, Any] = {"item_id": item_id, "run": 1, "speaking_as": item["speaking_as"]}
        print(f"  {item_id} as {item['speaking_as']}: {item['prompt']}")
        try:
            record["responses"] = TASKS[item_id[:3]](d, item)
        except TakeError as e:
            record["error"] = str(e)
        except Exception as e:  # a missing element or a timeout: the take is bad, but keep the video
            record["error"] = f"{type(e).__name__}: {e}"
        if "responses" not in record:
            record["responses"] = []
        verdict = check_take(item, record)
        takes.append({"record": record, "check": verdict})
        print(f"    {'GOOD' if verdict['good'] else 'BAD'}  " + "; ".join(verdict["problems"] + verdict["notes"]))
        d.hold(1.5)
    d.hold(2)
    video = page.video
    context.close()
    browser.close()
    if video:
        shutil.move(video.path(), out / f"{segment}.webm")
        shutil.rmtree(out / "raw", ignore_errors=True)
    good = all(t["check"]["good"] for t in takes)
    summary = {"segment": segment, "good": good, "base_url": args.base_url, "pace": args.pace,
               "recorded_at": stamp, "takes": takes}
    (out / "take.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
    print(f"{segment}: {'GOOD take' if good else 'BAD take'} → {out.relative_to(ROOT)}/{segment}.webm")
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--segment", required=True, choices=[*SEGMENTS, "all"])
    ap.add_argument("--base-url", default=os.environ.get("APP_URL", DEFAULT_URL))
    ap.add_argument("--env-file", help="read EVAL_BYPASS_KEY from this .env (otherwise from the environment)")
    ap.add_argument("--headed", action="store_true", help="show the browser (e.g. to screen-record with QuickTime)")
    ap.add_argument("--browser", choices=["chrome", "chromium"], default="chrome")
    ap.add_argument("--pace", type=float, default=1.0, help="multiplies every hold and the typing delay")
    ap.add_argument("--size", default="1600x900", help="viewport and video size, WxH")
    ap.add_argument("--no-warmup", dest="warmup", action="store_false", help="skip the throwaway question")
    args = ap.parse_args()
    args.base_url = args.base_url.rstrip("/")

    from playwright.sync_api import sync_playwright

    key = bypass_key(args.env_file)
    print(f"{args.base_url} · X-Eval-Bypass {'on' if key else 'off (in-app caps apply)'}")
    preflight(args.base_url, {"X-Eval-Bypass": key} if key else {}, args.warmup)
    items = load_items()
    segments = list(SEGMENTS) if args.segment == "all" else [args.segment]
    with sync_playwright() as pw:
        results = [run_segment(pw, args, s, items, key) for s in segments]
    sys.exit(0 if all(r["good"] for r in results) else 1)


if __name__ == "__main__":
    main()
