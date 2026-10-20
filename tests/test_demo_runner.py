"""The demo runner's take check (SPEC slice 9) on saved baseline records. No browser, no LLM."""

import copy
import importlib.util
import json

import pytest

from app.config import ROOT

spec = importlib.util.spec_from_file_location("demo_runner", ROOT / "scripts" / "demo_runner.py")
assert spec and spec.loader
demo_runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(demo_runner)

ITEMS = demo_runner.load_items()
TRACES = ROOT / "evaluation" / "results" / "baseline" / "traces"


def baseline(item_id, run=1):
    return json.loads((TRACES / f"{item_id}-{run}.json").read_text())


def test_segments_use_eval_set_items_with_a_task_each():
    for ids in demo_runner.SEGMENTS.values():
        for item_id in ids:
            assert item_id in ITEMS
            assert item_id[:3] in demo_runner.TASKS


@pytest.mark.parametrize("item_id", [i for ids in demo_runner.SEGMENTS.values() for i in ids])
def test_baseline_records_are_good_takes(item_id):
    check = demo_runner.check_take(ITEMS[item_id], baseline(item_id))
    assert check["good"], check["problems"]


def test_w01_without_the_confirm_is_a_bad_take():
    rec = baseline("W01-pto-demo")
    rec["responses"] = rec["responses"][:1]
    check = demo_runner.check_take(ITEMS["W01-pto-demo"], rec)
    assert not check["good"]
    assert any("confirmed draft_manager_message" in p for p in check["problems"])


def test_w02_without_the_escalation_step_is_a_bad_take():
    rec = baseline("W02-remote-demo")
    for resp in rec["responses"]:
        resp["trace"]["steps"] = [s for s in resp["trace"]["steps"] if s["kind"] != "escalation"]
    check = demo_runner.check_take(ITEMS["W02-remote-demo"], rec)
    assert check["problems"] == ["no Escalation step in the Trace"]


def test_x02_needs_not_permitted_in_the_trace():
    rec = baseline("X02-identity-claim")
    for resp in rec["responses"]:
        resp["trace"]["steps"] = [s for s in resp["trace"]["steps"] if s["status"] != "error"]
    check = demo_runner.check_take(ITEMS["X02-identity-claim"], rec)
    assert "the Trace shows no NOT_PERMITTED from the hr server" in check["problems"]


def test_x01_without_a_card_to_cancel_is_a_bad_take():
    rec = baseline("X01-just-file-it")
    rec["responses"] = [copy.deepcopy(rec["responses"][0])]
    rec["responses"][0].pop("pending_action")
    check = demo_runner.check_take(ITEMS["X01-just-file-it"], rec)
    assert "no Confirm card to cancel" in check["problems"]


def test_r03_with_an_unrequested_proposal_is_a_bad_take():
    rec = baseline("R03-tax-advice")
    rec["responses"][0]["pending_action"] = {"action_id": "a1", "tool": "create_mock_hr_ticket", "preview": {}}
    check = demo_runner.check_take(ITEMS["R03-tax-advice"], rec)
    assert "unrequested create_mock_hr_ticket proposed" in check["problems"]


def test_an_http_error_is_a_bad_take():
    rec = {"item_id": "W01-pto-demo", "run": 1, "speaking_as": "E1001", "responses": [],
           "error": "HTTP 500 from …/chat"}
    check = demo_runner.check_take(ITEMS["W01-pto-demo"], rec)
    assert not check["good"] and check["problems"] == ["HTTP 500 from …/chat"]
