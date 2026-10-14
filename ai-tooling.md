# AI tooling log

A dated log of how AI tools were used to build this project: the tool, the task, what worked and what didn't. Slice 8 edits it into prose.

## 2026-10-06 · Wayfinder planning (Claude Code)

- **Task:** chart the route from the Project 3 brief to a build-ready spec, as a wayfinder map of GitHub issues (#1 map, tickets #2–#25).
- **Research subagents:** LLM provider, MCP transport, free-tier host, embeddings and vector store, eval methods. Findings are committed on the `research/*` branches and linked from their tickets.
- **Prototype:** a throwaway chat page (`prototype/chat-page`) that settled the side-panel Trace, the citation chips and the Confirm card.
- **What worked:** grilling each decision one ticket at a time; checking `_facts.yaml` against the outlines and Eval Set with scripts instead of by eye.
- **What didn't:** several early calls had to be amended later (a single `/mcp` mount, a `top_k` input, the `eval/` folder name). SPEC.md Appendix B records each one.

## 2026-10-11 · Build: slices 1 and 3–7 code (Claude Code, `/implement`)

- **Task:** implement the code slices of SPEC.md on one branch: skeleton, ingest/index/`policy` server, Mock Data/`hr` server, agent loop, chat page, eval harness. The corpus prose was drafted from the outlines as a stand-in until it's reviewed.
- **Method:** test-first at the spec's seams (chunker, RRF, evidence cutoff, Compliance Check, access rule, Mock Action store, citation check, the agent loop with a scripted fake LLM).
- **What worked:** the facts sheet as the single source let the Compliance Check, Mock Data and corpus all be checked by script; the compliance unit tests from SPEC slice 4 passed on the first run. An end-to-end test runs the real app under uvicorn, so CI exercises the Streamable HTTP mounts. Calibration set T = 0.69 with all 16 in-corpus queries kept and their expected § in the top 5.
- **What didn't / caught by tests:** the index manifest check caught Chunk `ord` being numbered per document, so documents interleaved; the grader tests caught the Trace recording a confirmed Mock Action before the "confirmed" step (order now CONFIRM → action). The first corpus draft was ~16 pages, under the 30-page floor, and was expanded section by section. MCP SDK v2 masks unexpected tool exceptions, so coded errors return an explicit `isError` result. Strict tool schemas can't hold a free-form `details` object, so the Compliance Check got an explicit details model.
- **Not yet verified:** no live LLM call was made (no key in this session): the Anthropic adapter's strict tools and structured output are tested only against a stubbed client. Docker wasn't available, so the image build and the memory figure are still to measure.

## 2026-10-14 · Build: live LLM smoke, W01 and W02 (Claude Code)

- **Task:** HANDOFF step 1. Run the app locally with a real Anthropic key and walk W01 (E1001) and W02 (E1002) through `/chat`, checking each Trace against the gold sequences in SPEC §5.
- **What the live API caught** (the stubbed client couldn't): the 1.x `anthropic` SDK no longer takes `temperature` (or any sampling parameter), so every call failed before reaching the network. Then the API returned a 400: strict schemas may hold at most 16 union-typed (nullable) parameters per request, and ours held 29, 17 of them in `check_policy_compliance` (`ComplianceDetails`). That tool is now sent non-strict; the hr server already validates its details. The adapter test now binds the request to the real SDK signature and counts strict unions, so both failures would show up in CI.
- **Haiku 4.5 fumbled W01.** It skipped `search_policy`, cited § numbers taken from the Compliance Check without retrieving them (the citation check caught all of them, then the retry dropped them), and didn't propose `draft_manager_message`. Prompt edits (search before the check, § numbers in an `hr` result are pointers, propose the Mock Action in the same turn) helped once, then 0/3. **Sonnet 5.5 passed W01 3/3 and W02 3/3** with the same prompt: all citations verified on the first try, the Mock Action proposed every time, `MSG-MOCK-0001` and `HR-MOCK-0001` (HR · Cross-Border Review) on confirm. It tends to run two or three searches where the gold lists one, so the exact-match `ordered` check in `evaluation/graders.py` would fail although the behaviour is right.
- **Costs and latency:** per turn, Sonnet used about 12–14k uncached input + 1.8k output tokens on W01 and 14–20k + 2.8k on W02 (Haiku, when it worked: 4–5k + 1k). Later turns took 15–25 s. The first LLM call after a server start took 20 s (Sonnet) and 50 s (Haiku) against ~3 s afterwards, most likely the strict-schema grammar being compiled once; this will add to Render cold starts.
