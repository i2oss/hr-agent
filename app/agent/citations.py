"""Citation check (SPEC §3.6 step 6).

Every Policy Fact citation must match a Passage returned this turn (same doc_id and section), and
its snippet must be a verbatim substring of that Passage's text, whitespace-normalised. Every
data_sources[].tool must have run successfully this turn. A fact with any failing citation or data
source fails; after one retry, failing facts are removed and the answer gets the "not verified" note.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass, field

from app.agent.answer import UNVERIFIED_NOTE, FinalAnswer, PolicyFact
from mcp_servers.common.models import Passage

MIN_SNIPPET_CHARS = 12  # an empty or one-word "quote" would match any passage
_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"'})


def normalise(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text).translate(_QUOTES)).strip()


@dataclass
class CheckResult:
    failed: dict[int, list[str]] = field(default_factory=dict)  # fact index -> problems
    facts: list[PolicyFact] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failed

    @property
    def problems(self) -> list[str]:
        return [p for ps in self.failed.values() for p in ps]

    def removed_texts(self) -> list[str]:
        return [self.facts[i].text for i in sorted(self.failed)]

    def remove_failures(self, answer: FinalAnswer) -> FinalAnswer:
        if self.ok:
            return answer
        kept = [f for i, f in enumerate(answer.policy_facts) if i not in self.failed]
        return answer.model_copy(update={"policy_facts": kept, "verification_note": UNVERIFIED_NOTE})


def check_answer(answer: FinalAnswer, passages: Iterable[Passage], tools_ok: set[str]) -> CheckResult:
    by_section: dict[tuple[str, str], list[str]] = {}
    for p in passages:
        by_section.setdefault((p.doc_id, p.section), []).append(normalise(p.text))
    result = CheckResult(facts=list(answer.policy_facts))
    for i, f in enumerate(answer.policy_facts):
        problems: list[str] = []
        for c in f.citations:
            texts = by_section.get((c.doc_id, c.section))
            if texts is None:
                problems.append(f"Fact {i + 1}: {c.doc_id} §{c.section} wasn't returned by a policy tool this turn.")
            elif len(normalise(c.snippet)) < MIN_SNIPPET_CHARS:
                problems.append(f"Fact {i + 1}: the snippet for {c.doc_id} §{c.section} is too short to verify; "
                                "quote a full phrase.")
            elif not any(normalise(c.snippet) in t for t in texts):
                problems.append(f"Fact {i + 1}: the snippet for {c.doc_id} §{c.section} is not a verbatim quote "
                                f"from that passage: {c.snippet!r}.")
        for d in f.data_sources:
            if d.tool not in tools_ok:
                problems.append(f"Fact {i + 1}: data source {d.tool} did not run successfully this turn.")
        if problems:
            result.failed[i] = problems
    return result
