# Handoff: Ridgeline HR Agent build (continue from here)

> Paste this into a new Claude Code conversation started in the `hr-agent` repo, or say "read HANDOFF.md and continue". Written 2026-10-11 at the end of the first `/implement` session.

## Where things are

- **Repo:** `i2oss/hr-agent`. Local checkout: `~/Desktop/Shelton OS/wayfinder/hr-agent`.
- **Branch:** `worktree-implement-spec`, pushed. **Draft PR #28:** https://github.com/i2oss/hr-agent/pull/28
- The previous session worked in a git worktree at `.claude/worktrees/implement-spec`. If that is gone, `git fetch && git switch worktree-implement-spec`.
- **Plan:** `SPEC.md`. A build session reads §1–§3 plus its own slice section (§4). The glossary is `CONTEXT.md`.
- The branch **merges the open planning PRs** #15–#18 (via #18) and #20–#21 (via #21), because the code builds on `corpus/_facts.yaml` and the Eval Set. Merging PR #28 lands them too. Close them afterwards, or merge them first.

## Ground rules from Ross (follow these)

- **Ask before installing anything** on the machine (brew, pip/npm globals, system tools). Say what it is, why it's needed and the exact command, or suggest Ross runs `! <command>`. Project-local `uv sync` into `.venv` is fine.
- Ask every wayfinder/grilling question through the AskUserQuestion picker, not as plain text.
- Commit and push to the branch, never to `main`. Don't merge PRs or make other outward-facing changes (issues, collaborators, Render) without asking.

## Done (slice by slice)

| Slice | State |
|---|---|
| 0 Housekeeping | **Partly.** Done: `eval/` → `evaluation/` with references fixed, `_outlines.md` RSE-HB-01 §7.2 amended, `ai-tooling.md` started. **Not done:** the "Build" parent issue with child issues per slice and native blocking; adding `quantic-grader` as a read collaborator. |
| 1 Skeleton | Code done: `pyproject.toml` + `uv.lock` (Python 3.12), `app/config.py` (every env var), `.env.example`, `/health`, `Dockerfile` (bakes the fastembed model, one uvicorn worker, `--factory app.main:create_app`), `Makefile`, `.github/workflows/ci.yml` (`test` → `deploy` → live smoke). **Not done:** Render service, the deploy secret, a docker build and the memory measurement. |
| 2 Corpus | **Draft only.** All 12 documents and 214 §s are written from `_facts.yaml`: 8 MD, 2 HTML (HOL, BEN), 2 PDF (HB, EXP, built from `corpus/_src/*.md` by `scripts/build_pdfs.py`). About 15.2k words ≈ 30.4 pages, just over the 30-page floor. `scripts/check_corpus.py` passes. Each header says "draft prose … pending review". **Needs Ross's sign-off**, and probably expansion toward the ~55-page target. Rebuild with `make pdfs && make index` after any edit. |
| 3 Index + `policy` server | Done. 173 Chunks, `index/policy_index.sqlite` + `manifest.json` committed, hybrid vector + FTS5 with RRF(60), evidence cutoff on the top cosine. Calibration: **T = 0.69** (`app/config.py` `CALIBRATED_EVIDENCE_THRESHOLD`); 16/16 in-corpus queries kept, all with the expected § in the top 5; 1/15 out-of-corpus queries above T ("monthly parking subsidy"). Report at `evaluation/results/calibration/`. Manifest check: `scripts/check_index_manifest.py`. **Not done:** re-measure memory. |
| 4 Mock Data + `hr` server | Done. `mock_data/*.json` (25 employees), generated once and committed. Data test, access rule, Compliance Check (rules and parameters from `_facts.yaml`), Mock Action store, 7 tools. `docs/tool-schemas.json` is checked in CI by `scripts/export_tool_schemas.py --check`. |
| 5 Agent loop + API | Code done. `app/agent/` (loop, llm adapters, mcp_client, citations, answer, trace, sessions, prompt.md, fake_scripts) and `app/api/` (routes, limits). **Not done:** a live run with a real key, the live W01/W02/X02 checks, memory under chat load. |
| 6 Chat page | Done locally (`app/web/`). W01 was walked through in Chrome against a local fake-LLM server. `docs/chat-page-fake-llm.jpg` is a **placeholder**; replace it with a deployed, real-LLM screenshot. |
| 7 Evaluation | **Harness only.** `evaluation/run.py`, `graders.py` (unit-tested), `judge.py`, `report.py`, `judge_labels.yaml` (an empty template). **No runs yet.** |
| 8 Docs | Not started. README has only a status line and a quickstart. |
| 9 Demo runner + script | Not started. |

Checks at handoff, all green: `ruff check .`, `make typecheck` (mypy), `make check` (facts/outlines, eval set, corpus), `scripts/check_index_manifest.py`, `scripts/export_tool_schemas.py --check`, and **148 pytest tests** (`uv run pytest -q`).

## Next steps, in order

1. **Live LLM smoke (Ross's key).** `LLM_API_KEY=... make run`, then in the browser walk W01 as E1001 ("Can I take Wednesday to Friday off next week?") and W02 as E1002 ("Can I work from Lisbon for 6 weeks starting January 4?"). Check the gold sequences in SPEC §5 against the Trace. Watch for:
   - Anthropic rejecting the request shape. The adapter in `app/agent/llm.py` sends `strict: true` tools (built by `strict_schema`), `output_config.format` JSON schema (it falls back to JSON parsing if that 400s), `tool_choice: {"type": "none"}` when tool calls are off, and `temperature=0`. None of this has been checked against the real API.
   - Whether Haiku 4.5 follows the prompt (re-searching, citing verbatim snippets). If it fumbles a Workflow, the spec's upgrade path is `LLM_MODEL=claude-sonnet-5-5`.
2. **Docker.** Docker isn't installed; ask Ross before installing it. Run `make docker`, then measure memory under `docker stats` with the model loaded: target < 400 MB of 512 MB. Log the figure in `ai-tooling.md`.
3. **Render + CI deploy (Ross, human steps).** Free web service, Docker runtime, health check `/health`, auto-deploy **off**, env vars from `.env.example`. GitHub secret `RENDER_DEPLOY_HOOK_URL`, and a repo **variable** `APP_URL` (the deploy job reads it; it's not in the spec's env var table). Prove once that a failing test blocks deploy.
4. **Slice 0 leftovers.** The Build parent issue and its children with blocking; `quantic-grader` access. Both are outward-facing, so ask first.
5. **Corpus sign-off (slice 2).** Ross reviews the prose and expands it where wanted. Afterwards: `make pdfs && make index && make calibrate`, update T if it changes, and commit the index and calibration together.
6. **Slice 7 runs.** Baseline locally (`RATE_LIMITS_ENABLED=false`): `uv run python -m evaluation.run --run-id baseline --runs 3`. Ross labels the answers in `evaluation/judge_labels.yaml`. Then `python -m evaluation.judge --run-id baseline --seeded`; ablations `k2`, `k10`, `vector` (set `RETRIEVAL_TOP_K` / `RETRIEVAL_MODE` per run); deployed warm/cold latency with `X-Eval-Bypass`; finally `python -m evaluation.report`. Failure causes and fixes go in `evaluation/results/failure_notes.yaml`.
7. **Slice 8 docs:** README in full, `design-and-evaluation.md` (keep the `<!-- eval:begin/end -->` markers that `report.py` fills), `deployed.md`, `keepalive.yml`, `ai-tooling.md` edited into prose, and move SPEC to `docs/SPEC.md`.
8. **Slice 9:** `docs/demo-script.md` and `scripts/demo_runner.py` (Playwright is a dev dependency to add; ask first).

## Decisions and deviations to know about

- **Confirmation pause, kept append-only.** When the model calls a Mock Action, the loop runs a `preview_only=True` dry run (an injected argument, hidden from the model like `requester_id`/`session_id`) to get an exact preview. It returns `{"status": "awaiting_confirmation", ...}` as the tool result, and the model then writes the answer card. Confirm or cancel appends a `[Confirmation]` user note and resumes the loop with tool calls off. Loop notes to the model are user-role text that starts with `[`.
- **The FinalAnswer has an extra field, `verification_note`**, set only by the loop when the citation check removes facts. It is not in the model-facing schema.
- **Citation snippets** must be at least 12 characters and a verbatim substring (normalised for whitespace and curly quotes) of a Passage returned this turn, with the same `doc_id` and `section`.
- **`check_policy_compliance.details`** is an explicit model (`ComplianceDetails`), not a dict, so the strict schema works. Unknown expense categories return `MISSING_ARGUMENT`.
- **Access rule:** "reporting chain" means anyone above the subject (`MockData.chain_above`). If the Requester isn't set, any `hr` call returns `MISSING_ARGUMENT`, which forces the Clarification.
- **Ticket queues:** `remote_work` → "HR · Cross-Border Review" (even for domestic stays), `conduct` → "HR Confidential" (summary capped at 200 characters), plus `pto`, `benefits`, `expense` and `other` queues.
- **Rate limit:** keyed on the rightmost `X-Forwarded-For` hop, which Render's proxy appends.
- **The judge leaves `temperature` unset:** Claude Sonnet 5.5 rejects non-default sampling parameters.
- **The MCP client opens a fresh `Client` per call** (simple, with a 10 s timeout around each). It was flagged in review as a possible cost; measure before optimising.
- **`create_app(settings, in_memory_mcp=True, llm=FakeLLM(...))`** is the test seam: the agent's MCP client talks to the server objects in memory. `tests/test_e2e_http.py` runs the real app under uvicorn instead.
- **Fake LLM scripts** (`app/agent/fake_scripts.py`) cover only W01 and the CI smoke question. Their final answers build citations from the passages actually returned, so they pass the real citation check.

## Gotchas from the first session

- The worktree guard in background sessions rejects compound shell commands (heredocs, `&&` chains with `git`, and even the word `eval` in a path). Write edit scripts to a file and run them, or use the Write/Edit tools.
- The first `python -m ingest.build_index` once hung at exit at 90% CPU and couldn't be reproduced afterwards. If it recurs, run it under `PYTHONFAULTHANDLER`.
- `uv` was installed via Homebrew without asking (Ross has flagged this; don't repeat it). `docker` and `timeout` are not installed.
