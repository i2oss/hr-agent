# Deployed: ops card

The Ridgeline HR Agent runs as one Docker container on a **Render free web service**. Everything is fictional: the Company, its people and its policies.

| | |
|---|---|
| **App** | _pending the first deploy_ (the `APP_URL` repo variable; set by `scripts/setup_render.sh`) |
| **Health** | `<APP_URL>/health` |
| **Config** | `<APP_URL>/config` (Demo Date, model, Personas) |
| **Host** | Render free: 512 MB RAM, 0.1 CPU, Docker runtime, one uvicorn worker, health check path `/health` |
| **Deploys** | Only from CI: a push to `main` runs `test`, then the `deploy` job POSTs the Render deploy hook, waits for `/health` to report the new git SHA and sends one real question as a smoke check. Auto-deploy is off. |

## `/health`

Returns 200 with `{status, version, uptime_s, index, mcp, llm, demo_today}`, or 503 if either MCP server lists no tools. `version` is the deployed git SHA (Render's `RENDER_GIT_COMMIT`). `mcp` holds a **live** `list_tools()` from each server: 2 `policy` tools and 7 `hr` tools. It never calls the LLM and never returns a key.

## Environment variables

Names only; the values live in Render's dashboard. `.env.example` lists every one with its default, and `app/config.py` is the only code that reads them.

| Name | Notes |
|---|---|
| `LLM_PROVIDER`, `LLM_MODEL`, `LLM_API_KEY` (secret), `LLM_BASE_URL` | `anthropic` / `claude-sonnet-5-5` in production. `LLM_BASE_URL` is for `openai_compat` only. |
| `JUDGE_MODEL` | Used by the evals, not the app. |
| `EMBEDDINGS_PROVIDER`, `VOYAGE_API_KEY` (secret) | `local` (fastembed, baked into the image). |
| `RETRIEVAL_TOP_K`, `RETRIEVAL_MODE`, `EVIDENCE_THRESHOLD` | `5`, `hybrid`, and the calibrated default when unset. |
| `DEMO_TODAY` | `2026-11-02`, the Demo Date. |
| `MCP_POLICY_URL`, `MCP_HR_URL` | Unset: the agent reaches the in-process mounts over Streamable HTTP on localhost. |
| `RATE_LIMITS_ENABLED`, `RATE_LIMIT_PER_IP`, `MAX_MESSAGE_CHARS`, `MAX_TURNS_PER_SESSION`, `DAILY_MESSAGE_CAP` | The in-app caps below. |
| `EVAL_BYPASS_KEY` (secret) | A request with the header `X-Eval-Bypass: <key>` skips the caps (latency runs, demo runner). |
| `PORT` | Set by Render. |

GitHub holds one secret, `RENDER_DEPLOY_HOOK_URL`, and two variables: `APP_URL` (read by the deploy and keep-alive jobs) and `KEEPALIVE`. CI itself uses no LLM key.

## Cold start

The free service **sleeps after 15 minutes idle**. The next request wakes it, which takes **roughly 30–60 s** before the page loads. The first chat after a wake can take ~20 s more, while the API prepares the strict tool schemas once. Measured cold and warm latencies are in `design-and-evaluation.md` (Evaluation).

**Keep-alive (opt-in):** `.github/workflows/keepalive.yml` pings `/health` every 10 minutes while the repo variable `KEEPALIVE` is `on`. It's **off by default**. Switch it on for the grading window with `gh variable set KEEPALIVE --body on`, and off afterwards with `--body off`. A ping costs no LLM tokens, but an always-awake service uses Render's monthly free instance hours, so check the allowance on the Render billing page before leaving it on for long.

## In-app caps

Every cap returns HTTP 429 with "Demo limit reached, please try again later."

| Cap | Default |
|---|---|
| Messages per IP | 20 per 10 minutes (keyed on the address Render's proxy appends) |
| Message length | 2,000 characters |
| Turns per conversation | 30 |
| Site-wide messages | **100 per UTC day** |

They protect the LLM budget (`docs/SPEC.md` §3.2, LLM budget). The Anthropic console also has a monthly spend limit as a hard stop.

## State resets on restart

Chat sessions, the Trace and the **Mock Action store** (drafted manager messages, created HR tickets) live **in memory** in the one worker. A cold start, a restart or a deploy clears them, so IDs start again at `MSG-MOCK-0001` and `HR-MOCK-0001`. The seed Mock Data (`mock_data/*.json`) and the policy index are read-only and baked into the image. Nothing is ever really sent or filed.

## The Demo Date

The Company's "today" is fixed at **Monday 2026-11-02** (`DEMO_TODAY`), whatever the real calendar says. PTO balances "as of", tenure, notice periods and phrases like "next week" are all reckoned from it. So W01's "Wednesday to Friday next week" means 2026-11-11 to 2026-11-13. The chat page header shows the Demo Date.
