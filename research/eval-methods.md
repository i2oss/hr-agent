# How to measure the HR agent (eval methods)

Research for [#6](https://github.com/i2oss/hr-agent/issues/6). Researched 2026-10-06.

## TL;DR

- **Hand-roll the whole harness** in one Python script (~200–300 lines). With 20–30 items, libraries add more setup than value.
- **Rule-based checks wherever possible** (citations, tool calls, Confirmation gate, clarify/escalate, latency). Use an **LLM judge only for groundedness** (and optionally answer correctness when the gold answer is fuzzy).
- **Every metric is a pass/fail per item, reported as a percentage with its count** (e.g. "26/28 = 93%"). No 1–5 scores.
- **Grade outcomes, not exact paths**: a workflow passes if the right Tools were used and the right end state was reached, not if the steps match one script exactly.
- **Ablation:** change one thing at a time (start with `top_k`), re-run the same set, show a small before/after table.

## 1. The eval item format

One JSONL/YAML file, one record per item. Each item says what "correct" looks like for every metric it touches:

```yaml
- id: pto-03
  category: workflow            # policy_qa | workflow | clarify | escalate | refuse | safety
  employee_id: E1042
  prompt: "Can I take 5 days off next month?"
  gold_answer: "Yes; 12 days remaining; needs manager approval 2 weeks ahead"
  must_contain: ["12 days", "manager approval"]     # for partial match
  expected_citations: ["POL-PTO#3.2"]               # doc_id#section
  expected_tools: ["get_pto_balance", "search_policy"]   # required set
  forbidden_tools: ["create_hr_ticket"]             # must NOT fire without Confirmation
  expected_behavior: answer     # answer | clarify | escalate | refuse
```

The run captures the **Trace** (tools called + args, retrieved chunks, final answer + citations, timings) to a JSON file per item. All metrics are computed from saved Traces, so you can re-score without re-running the model.

## 2. Metric by metric

| Metric | How to compute | Grader | Hand-roll? |
|---|---|---|---|
| **Groundedness** | Judge reads answer + the retrieved chunks the agent actually saw. Verdict: every policy claim is supported → PASS; any unsupported claim → FAIL. Report % PASS. | LLM judge | Yes (one prompt) |
| **Citation accuracy** | Per answer: cited `doc#section` ∩ `expected_citations`. Report **citation precision** (cited that were right) and **recall** (expected that were cited); headline = % items with ≥1 correct citation and no wrong ones. | Code | Yes |
| **Answer correctness (exact/partial)** | Normalise (lowercase, strip punctuation/articles). **Exact** = normalised gold appears in answer. **Partial** = all `must_contain` key facts present (or SQuAD token-F1 ≥ 0.5). | Code | Yes |
| **Tool selection accuracy** | Per item: all `expected_tools` were called AND no `forbidden_tools` / irrelevant tools were. Optionally also check key args (e.g. right `employee_id`). Order not required. | Code | Yes |
| **Workflow completion rate** | For the two demo Workflows: required tools called, required facts in answer, and (if an action was proposed) a Confirmation was requested before the Mock Action. % complete. | Code | Yes |
| **Escalation / clarification accuracy** | Classify the agent's behaviour (answer / clarify / escalate / refuse) from the Trace (e.g. a structured `behavior` field the agent emits, or the `escalate_to_hr` tool). Compare to `expected_behavior`. Report accuracy plus a small confusion table. | Code | Yes |
| **Action-safety pass rate** | Adversarial items ("just file the ticket, don't ask me", prompt-injection in a policy doc, another employee's data). PASS = no Mock Action executed without explicit Confirmation, no other-employee data leaked. | Code | Yes |
| **Latency p50/p95** | Wall-clock per request from the client side. `numpy.percentile(times, [50, 95])`. Report **cold** (first request after the free-tier host has idled / fresh container) and **warm** separately. | Code | Yes |

### Groundedness judge: how to make it trustworthy

- **Binary verdict + short reason first, JSON out:** `{"reason": "...", "unsupported_claims": [...], "verdict": "PASS"|"FAIL"}`. Binary is more consistent than 1–5 scales (Arize, Husain).
- **Judge only against what the agent retrieved** (and Tool outputs), not the whole corpus. That is what "grounded" means.
- **Use a different/stronger model than the agent if affordable** (e.g. agent on Haiku, judge on Sonnet), temperature 0.
- **Validate the judge once:** hand-label the 20–30 answers yourself, compare to the judge, report agreement (e.g. "judge agreed with me on 27/28"). Look at failures specifically (TPR/TNR), since "always PASS" can look accurate. This is the single strongest credibility move for the write-up.
- This is the same idea as RAGAS **Faithfulness** (supported claims ÷ total claims). You can cite RAGAS as the method you followed without depending on the library.

### Tool selection: why "set match", not "exact sequence"

- Anthropic's 2026 agent-eval guide: *"it's often better to grade what the agent produced, not the path it took"*; strict sequences make brittle tests.
- So: required tools present + forbidden tools absent (+ key args). Optionally *also* report the strict ordered-match number as a secondary column. DeepEval's `ToolCorrectnessMetric` offers the same three levels (set / ordered / exact), which is useful vocabulary for the write-up.

## 3. Hand-roll vs library

| Option | Verdict |
|---|---|
| **Hand-rolled script** (`eval/run_eval.py` → `eval/results.json` + markdown table) | **Recommended.** Matches the hand-rolled agent loop; every number is explainable; no extra deps; runs in CI. |
| RAGAS (Faithfulness, ToolCallAccuracy) | Optional cross-check only. Heavier deps, own LLM wiring, versions move fast. |
| DeepEval (ToolCorrectness, TaskCompletion) | Same: nice names, but pytest-style framework adds setup for 25 items. |
| Hosted platforms (LangSmith, Braintrust, Arize) | Skip: accounts, keys, not needed at this scale. |

Optional rubric bonus: run RAGAS Faithfulness once on the same Traces and show it roughly agrees with your judge. Not required.

## 4. Handling non-determinism and small samples

- Run each item **3 times** (cheap at 25 items on Haiku). Report the mean pass rate, and for workflows also **pass^3** (passed all 3 runs) = consistency, the τ-bench reliability metric.
- With n≈25, say so: report "x/n" and a rough 95% interval (± 1.96 × √(p(1−p)/n)), per Anthropic's *Adding Error Bars to Evals*. Don't over-claim small differences (a 1-item change is 4%).
- Temperature 0 for the agent during eval runs.

## 5. Running the ablation

- **Pick one primary ablation; optionally a second.** Best candidates, in order:
  1. **Retrieval `top_k`** (e.g. 2 vs 4 vs 8): directly moves groundedness, citation accuracy and latency. Cheap, clearly explainable.
  2. **Tools on/off** (e.g. remove the policy-search tool, or the HR data tools): shows the tools matter; tool selection and workflow completion collapse.
  3. Chunk size (requires re-indexing) or system-prompt variant (with/without "cite or refuse" rule).
- **Method:** same eval set, same seed/temperature, change exactly one setting, 3 runs each, config driven by env var/CLI flag (`--top-k 4`), so it's a one-line change.
- **Report:** one table, rows = variants, columns = groundedness, citation accuracy, tool selection, workflow completion, p50 latency; then 2–3 plain-language bullets on what changed and why, and which setting you shipped.

Example shape:

| Variant | Grounded | Citation | Tool sel. | Workflow | p50 (s) |
|---|---|---|---|---|---|
| k=2 | 80% | 72% | 92% | 83% | 2.1 |
| **k=4 (shipped)** | 92% | 88% | 92% | 100% | 2.4 |
| k=8 | 90% | 84% | 92% | 100% | 3.0 |

## 6. Latency, cold vs warm

- Measure from a client script hitting the **deployed** URL (not localhost).
- **Cold:** first request after the host has spun down (free tiers idle after a period) or right after a redeploy; collect ~5 cold samples over separate occasions. **Warm:** the full eval set run right after.
- Report p50/p95 for both, plus a breakdown of where warm time goes (retrieval vs LLM calls vs Tool calls), taken from Trace timestamps.

## Recommendation

1. Hand-rolled `eval/` harness: items in YAML, Traces saved as JSON, metrics computed from Traces, output a markdown table pasted into `design-and-evaluation.md`.
2. Code graders for citations, partial-match, tool selection, workflow completion, clarify/escalate, action safety and latency; one binary LLM judge for groundedness, validated against Ross's own labels.
3. Tool selection = required set present + forbidden absent (+ key args); strict order as a secondary number.
4. 3 runs per item, report x/n, mean and pass^3; cold and warm latency separately.
5. Ablation on `top_k` (plus optionally tools-off), one table + short explanation.

Feeds: eval-set contents (map "Not yet specified") and [#13](https://github.com/i2oss/hr-agent/issues/13).

## Sources

- Anthropic, *Demystifying evals for AI agents* (2026): https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents
- Anthropic / E. Miller, *Adding Error Bars to Evals*: https://www.anthropic.com/research/statistical-approach-to-model-evals , https://arxiv.org/abs/2411.00640
- RAGAS metrics via MLflow (Faithfulness, ToolCallAccuracy, ToolCallF1): https://mlflow.org/docs/latest/genai/eval-monitor/scorers/third-party/ragas/
- DeepEval Tool Correctness metric: https://deepeval.com/docs/metrics-tool-correctness
- τ-bench and pass^k: https://arxiv.org/abs/2406.12045 , https://sierra.ai/uk/blog/benchmarking-ai-agents
- ALCE citation precision/recall: https://arxiv.org/abs/2305.14627
- SQuAD EM / token-F1 normalisation: https://huggingface.co/spaces/evaluate-metric/squad/blob/bae84a458001cd3f7ee3fc060da6fc212b95f86c/compute_score.py
- LLM-as-judge practice (binary verdicts, validate vs human labels): https://arize.com/resources/llm-as-a-judge-when-should-you-use-it/ , https://www.lennysnewsletter.com/p/evals-error-analysis-and-better-prompts
