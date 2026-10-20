# How AI tools were used

This project was planned and built with **Claude Code** (Anthropic's coding agent, in the terminal), working with Ross, the sole developer, who made every decision and reviewed every merge. The running app uses Claude Sonnet 5.5 as its own model; this document is about the tools used to *build* it. A one-line-per-session log is in the [appendix](#appendix-session-log).

## Planning: a wayfinder map instead of a prompt

The brief was not handed to an agent with "build this". It was first charted as a **wayfinder map** on GitHub: one parent issue ([#1](https://github.com/i2oss/hr-agent/issues/1)) and one ticket per open decision (#2–#25): the LLM, the MCP transport, the host, embeddings, chunking, guardrails, the eval design, the docs, the demo. Claude Code worked each ticket in a "grilling" session: it put its recommendation to Ross as a multiple-choice question, Ross picked or overrode it, and the resolution was written into the ticket with its reasoning. The tickets are the evidence. Each has the question, the options weighed and the decision, and [docs/SPEC.md](docs/SPEC.md) compiles them into one build plan that links back to each.

That paid off later. Every build session read only SPEC §1–§3 plus its own slice, so a fresh session started with the decisions rather than re-deriving them. When an early call turned out wrong (a single `/mcp` mount, a `top_k` tool input, the `eval/` folder name), it was amended in the ticket and recorded in SPEC's Appendix B, so no session built the superseded version.

## Research subagents

Five of the decisions needed facts that change faster than a model's training data: which free hosts still exist, what the current MCP SDK looks like, rate limits and prices. For each, Claude Code sent a research subagent to read primary sources (vendor docs, the SDK source and changelog, pricing pages) and write up findings with links. The write-ups are on the `research/*` branches: `llm-provider`, `mcp-transport`, `free-tier-host`, `embeddings-vector-store` and `eval-methods`. They caught things a plan from memory would have got wrong: the MCP Python SDK had moved to v2 (`FastMCP` became `MCPServer`, with one `Client` for every transport), Chroma's docs advise against hosts with under 2 GB of RAM, and several "free" hosts now need a card or a paid plan.

## Prototype

Before any app code, Claude Code built a throwaway chat page (branch `prototype/chat-page`) to settle the UI questions that would shape the API: where the Trace goes (a side panel), how a Citation shows its snippet (chips that expand in place), how data facts differ from policy facts (tool chips, which added `data_sources` to the answer schema), and what the Confirm card shows (the exact draft). Clicking through it answered in minutes what would otherwise have been rework after slice 6.

## Code generation

Claude Code wrote the code, slice by slice, from SPEC: test first at the seams the spec names (the chunker, RRF, the evidence cutoff, the Compliance Check, the access rule, the citation check, the agent loop driven by a scripted fake LLM). It also drafted the 12 Policy Documents from the outlines and the facts sheet, the Mock Data, the Eval Set, and the deploy wizard (`scripts/setup_render.sh`) that walks a human through the Render dashboard. Ross reviewed and merged each pull request; the corpus was signed off by him before the evaluation ran.

Three habits kept the output checkable:
- **One source of facts.** Every number in the corpus, the Mock Data and the Compliance Check comes from `corpus/_facts.yaml`, and scripts in CI check all three against it. Generated prose can't quietly drift from the rules the code enforces.
- **Measured, not estimated.** Memory came from `docker stats`, the LLM budget from token counts in 33 saved Traces at live prices, latency from runs against the deployed URL.
- **Ask before anything outward-facing.** Installs, pushes, merges, issue changes and paid API calls each waited for Ross, with the cost stated first.

## Where AI output was wrong, and how it was caught

The useful record is less what the AI wrote than what was caught afterwards, and by what.

**By tests and checks in CI:**
- The index manifest check caught Chunk numbering restarting per document, which would have interleaved documents.
- The grader tests caught the Trace recording a confirmed Mock Action *before* the Confirmation step.
- The first corpus draft came to about 16 pages, under the brief's 30-page floor; `check_corpus.py` counts length, and the documents were expanded section by section.
- A strict tool schema can't hold a free-form `details` object, so the Compliance Check got an explicit model.

**By the first live API call** (the unit tests had used a stubbed client):
- The 1.x `anthropic` SDK no longer takes `temperature`, so every call failed before reaching the network.
- The API caps strict schemas at 16 union-typed parameters per request; ours had 29. `check_policy_compliance` is now sent non-strict, and a test counts the strict total.
- The planned model, Claude Haiku 4.5, fumbled W01 (no search, citations it hadn't retrieved) even after prompt fixes. Sonnet 5.5 passed 3/3 and became the default.

**By running the real graders on live Traces:**
- The graders read the last response, which after a Confirm is a short "done" message, so a correct Escalation graded as a failure. They now grade the first answer.
- `normalise` missed curly apostrophes and "11.0 days", which would have failed correct answers.
- The model repeated an `hr` call after `NOT_PERMITTED` despite a prompt line and a loop note. The guard moved into code: the loop now refuses that call itself.
- The model sent 2026-01-04 for "January 4" with a Demo Date in November 2026. A prompt line now resolves yearless dates forward.

**By the evaluation:**
- All 3 baseline tool-selection misses were the model proposing a Mock Action nobody asked for. The first prompt fix overshot: W01 and W02 stopped proposing theirs too. That run was stopped after 8 records, the line was reworded with the demo questions as examples, and the re-run passed 18/18.
- The first judge agreed with Ross's labels on 26 of 29 answers, just under the 90% bar, because it never saw the session (the Demo Date, the signed-in Requester) or `hr` errors. The second agreed on 27/29. Its remaining blind spot is written up rather than tuned away on the same labels.
- The latency harness would have hidden every cold start, because its first `/health` call absorbed the wake. It now records the wake and client time separately, and it caught a "cold" sample that had found the instance still awake.

**By a human:**
- Ross's labels for the judge, his sign-off on the corpus, and his calls on strict citation grading and on reporting the two missed targets.
- The auto-mode safety classifier blocked a probe that would have touched the API key in `.env`. It was right to.
- Twice the app returned a bare HTTP 500 in production when the API credit ran out. Rather than guess, Claude Code asked for Render's logs, which named the cause. A friendly error message is still an open follow-up.

## Writing the docs

The design document, this file and the README's grader map were drafted by Claude Code from the closed tickets, the SPEC, the code and the committed results, and every number was checked against `evaluation/results/`. The evaluation section of `design-and-evaluation.md` is generated by `evaluation/report.py` and never edited by hand, so the document can't drift from the data.

## The demo

Claude Code wrote the demo script (`docs/demo-script.md`) and the demo runner (`scripts/demo_runner.py`). The runner drives the deployed page with Playwright and grades each take with the same `evaluation/graders.py` the evals use. Ross asked whether the Playwright MCP could do the job instead. It can click a browser live, but it can't be committed, re-run or graded, so the runner stayed a script. Before any paid take, a free rehearsal ran against the app locally with the scripted fake LLM, to prove the selectors, the beats and the video. The word-for-word MCP lines in the script were written from the calls in the recorded takes, not from the plan. Looking at frames pulled from the videos caught one bug: opening a wide JSON block scrolled the Trace panel sideways, out of view. A unit test alone wouldn't have caught it. The first paid set after a wake was good on all three segments (`MSG-MOCK-0001`, `HR-MOCK-0001`, all guardrails), and the guardrails were retaken once after the fix, also good.

## Appendix: session log

| Date | Session | Outcome |
|---|---|---|
| 2026-10-06 | Wayfinder planning | Map #1 and tickets #2–#25; 5 research write-ups; the chat-page prototype; SPEC compiled |
| 2026-10-11 | Build: slices 1, 3–7 code | Skeleton, ingest and index, both MCP servers, agent loop, chat page, eval harness; corpus drafted; tests first at every seam |
| 2026-10-14 | Live LLM smoke | Two SDK/API bugs fixed; Haiku 4.5 failed W01; Sonnet 5.5 passed W01 and W02 3/3 and became the default |
| 2026-10-14 | Smoke follow-ups | Graders read the first answer; `normalise` fixed; X02 filler calls fixed with a prompt line and a loop note |
| 2026-10-14 | Docker and memory | Image built; 239 MiB peak of 512 under load; `.env` inline comments broke `--env-file` |
| 2026-10-14 | Budget, deploy wizard | Budget from 33 Traces (≈ $53 build); daily cap lowered to 100; `setup_render.sh` |
| 2026-10-15 | Deploy and live check | Live on Render via CI; two wizard bugs fixed; W01, W02, X02 verified; 43 s cold wake |
| 2026-10-15 | `NOT_PERMITTED` guard | Repeat `hr` calls on a denied subject blocked in the loop |
| 2026-10-15 | Yearless dates | Prompt line: a date without a year resolves forward from the Demo Date |
| 2026-10-15 | Corpus sign-off | Ross approved the 12 documents unchanged; index rebuilt, T unchanged at 0.69 |
| 2026-10-16 | Eval baseline | 87 records; safety 87/87; two prompt fixes, re-run 18/18 |
| 2026-10-19 | Ablations, spare, harness | k2, k10, vector, spare; R04 Refusal gap reported; cold-start timing fixed in the harness |
| 2026-10-20 | Judge validation | v2 at 27/29 (93.1%), 5/5 seeds; groundedness 80/87 |
| 2026-10-20 | Deployed latency | Warm p95 27.2 s (missed, reported); cold 43.4 s wake + ≈ 16.6 s |
| 2026-10-20 | Docs (slice 8) | `design-and-evaluation.md` written around the generated section; README grader map, `deployed.md`, this file |
| 2026-10-20 | Demo (slice 9) | `docs/demo-script.md` and `scripts/demo_runner.py`; good takes of W01, W02 and the guardrails on the deployed URL (≈ $0.52) |
