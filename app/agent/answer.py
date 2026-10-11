"""Final answer schema (SPEC §3.7). The model fills it; the loop validates it and the page renders it.

policy_facts render as "What the policy says" (policy chips for citations, tool chips for
data_sources); recommendations as "Suggested next steps" (no chips). The eval harness reads
escalation.trigger, refusal.reason and clarification directly. `verification_note` is set by the
loop, never by the model, when facts are removed by the citation check.
"""

from __future__ import annotations

import copy
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

UNVERIFIED_NOTE = (
    "Some details couldn't be verified, so I left them out. Contact HR (hr@ridgeline.example or "
    "HR Portal > Ask HR) if you need them."
)


class Citation(BaseModel):
    doc_id: str = Field(description="Policy Document ID, e.g. RSE-PTO-01.")
    section: str = Field(description="Section number exactly as in the passage, e.g. 4.2.")
    snippet: str = Field(description="A verbatim quote copied from that passage's text.")


class DataSource(BaseModel):
    tool: str = Field(description="An hr tool that ran successfully this turn, e.g. check_pto_balance.")


class PolicyFact(BaseModel):
    text: str
    citations: list[Citation] = []
    data_sources: list[DataSource] = []

    @model_validator(mode="after")
    def _grounded(self) -> PolicyFact:
        if not self.citations and not self.data_sources:
            raise ValueError("each policy fact needs at least one citation or data_source")
        return self


class Recommendation(BaseModel):
    text: str


class Escalation(BaseModel):
    reason: str
    trigger: Literal["sensitive_matter", "needs_hr_review", "hr_handles_per_policy", "insufficient_evidence",
                     "user_requested_human"]


class Clarification(BaseModel):
    question: str


class Refusal(BaseModel):
    reason: Literal["not_covered", "not_hr", "legal_tax_immigration"]
    text: str


class FinalAnswer(BaseModel):
    lead: str = Field(description="One-line answer shown first on the card.")
    policy_facts: list[PolicyFact] = []
    recommendations: list[Recommendation] = []
    escalation: Escalation | None = None
    clarification: Clarification | None = None
    refusal: Refusal | None = None
    verification_note: str | None = None  # set by the loop only

    @model_validator(mode="after")
    def _one_note(self) -> FinalAnswer:
        if sum(x is not None for x in (self.escalation, self.clarification, self.refusal)) > 1:
            raise ValueError("at most one of escalation / clarification / refusal")
        return self


def strict_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Make a JSON schema acceptable to strict tool use / structured outputs: every object gets
    additionalProperties: false and lists all its properties as required (optional ones stay
    nullable through anyOf); titles and defaults are dropped. $defs are inlined."""
    schema = copy.deepcopy(schema)
    defs = schema.pop("$defs", {})

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                return walk(copy.deepcopy(defs[node["$ref"].split("/")[-1]]))
            node = {k: walk(v) for k, v in node.items() if k not in ("title", "default")}
            if node.get("type") == "object" and "properties" in node:
                node["additionalProperties"] = False
                node["required"] = list(node["properties"])
            return node
        if isinstance(node, list):
            return [walk(x) for x in node]
        return node

    return walk(schema)


def model_facing_schema() -> dict[str, Any]:
    """The FinalAnswer schema the model is asked to produce (without loop-only fields)."""
    schema = FinalAnswer.model_json_schema()
    schema["properties"].pop("verification_note")
    return strict_schema(schema)
