"""Answer schema and citation check (SPEC §3.6 step 6, §3.7)."""

import pytest
from pydantic import ValidationError

from app.agent.answer import FinalAnswer, model_facing_schema, strict_schema
from app.agent.citations import check_answer, normalise
from mcp_servers.common.models import Passage

P42 = Passage(doc_id="RSE-PTO-01", title="Paid Time Off Policy", section="4.2", section_heading="Notice",
              text="Requests for more than 3 PTO days need at least 14 calendar days' notice (two weeks)\n"
                   "before the first day off.", score=0.03)


def answer(**facts):
    return FinalAnswer.model_validate({"lead": "Yes.", **facts})


def fact(snippet, section="4.2", doc="RSE-PTO-01", data_sources=()):
    cites = [{"doc_id": doc, "section": section, "snippet": snippet}] if snippet else []
    return {"text": "x", "citations": cites, "data_sources": [{"tool": t} for t in data_sources]}


def test_fact_needs_a_citation_or_data_source():
    with pytest.raises(ValidationError):
        answer(policy_facts=[{"text": "x"}])


def test_at_most_one_of_escalation_clarification_refusal():
    with pytest.raises(ValidationError):
        answer(clarification={"question": "Which dates?"},
               refusal={"reason": "not_hr", "text": "I only do HR."})


def test_verbatim_snippet_passes_with_whitespace_normalised():
    r = check_answer(answer(policy_facts=[fact("14 calendar days' notice (two weeks) before the first day")]),
                     [P42], set())
    assert r.ok and r.problems == []


def test_curly_quotes_are_normalised():
    assert normalise("days’ notice") == normalise("days' notice")


def test_non_verbatim_snippet_fails():
    r = check_answer(answer(policy_facts=[fact("two weeks' notice is required")]), [P42], set())
    assert not r.ok
    assert "not a verbatim quote" in r.problems[0]


def test_citation_to_a_passage_not_returned_this_turn_fails():
    r = check_answer(answer(policy_facts=[fact("before the first day off", section="4.3")]), [P42], set())
    assert "wasn't returned" in r.problems[0]


def test_data_source_must_have_run_this_turn():
    a = answer(policy_facts=[fact(None, data_sources=["check_pto_balance"])])
    assert not check_answer(a, [], set()).ok
    assert check_answer(a, [], {"check_pto_balance"}).ok


def test_remove_failures_keeps_good_facts_and_records_removed_text():
    a = answer(policy_facts=[fact("before the first day off"), {**fact("made up"), "text": "Invented."}])
    r = check_answer(a, [P42], set())
    cleaned = r.remove_failures(a)
    assert [f.text for f in cleaned.policy_facts] == ["x"]
    assert cleaned.verification_note.startswith("Some details couldn't be verified")
    assert r.removed_texts() == ["Invented."]


def test_strict_schema_sets_additional_properties_and_required_everywhere():
    s = model_facing_schema()
    assert "verification_note" not in s["properties"]

    def objects(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                yield node
            for v in node.values():
                yield from objects(v)
        elif isinstance(node, list):
            for v in node:
                yield from objects(v)

    objs = list(objects(s))
    assert objs and all(o["additionalProperties"] is False and set(o["required"]) == set(o["properties"])
                        for o in objs)
    assert "$defs" not in s and "$ref" not in str(s)


def test_strict_schema_drops_defaults():
    s = strict_schema({"type": "object", "properties": {"a": {"type": "string", "default": "x", "title": "A"}}})
    assert s == {"type": "object", "properties": {"a": {"type": "string"}}, "additionalProperties": False,
                 "required": ["a"]}
