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
