# Which LLM gives reliable tool-calling within a small budget?

Research for [#2](https://github.com/i2oss/hr-agent/issues/2). Sources checked 2026-10-06.

## Recommendation (short version)

- **Use Claude Haiku 4.5 (`claude-haiku-4-5`) as the default model**, called through Anthropic's own Python SDK (`anthropic`).
- **Expected total cost: about $25-$60** for development + 5 full eval runs + demo. Buy $25 of credit to start; set a $50 spend limit in the Console.
- **Keep a free-tier fallback** (Groq `openai/gpt-oss-120b` or `qwen/qwen3.8-27b`) behind the same env var, for cheap smoke tests only, not for graded eval runs or the recorded demo.
- **Keep the provider swappable with a tiny adapter in our own code** (two classes, ~100 lines total), not with an OpenAI-compatible shim in front of Claude.
- **Upgrade path:** if Haiku fumbles a Workflow in the eval, switch `LLM_MODEL=claude-sonnet-5-5` (about 2x the cost, still under ~$120 total). No code change.

## The options compared

| Option | Price | Limits that matter | Tool-calling in multi-step loops | Fit |
|---|---|---|---|---|
| **Claude Haiku 4.5** (paid) | $1 in / $5 out per 1M tokens | Start tier: 1,000 requests/min, 2M input tokens/min. Brand-new accounts may begin in a lower "Evaluation" tier that rises automatically | Native tool use, `strict: true` schema-valid arguments, parallel tool calls. Strong and well documented | **Best.** Reliable, cheap, no daily cap to trip on |
| Claude Sonnet 5.5 (paid) | $2 in / $10 out | Same tier limits | Stronger reasoning; thinking always on (can't be switched fully off) | Backup if Haiku is not good enough |
| Groq free tier (`gpt-oss-120b`, `qwen3.8-27b`) | $0 | 30 req/min, **1,000 req/day, 8K tokens/min, 200K tokens/day** | Fast, but community reports of tool-calling failures on gpt-oss (ignored tools, invented tool names, null replies). Qwen/Kimi reported more stable | A full eval run (~30 questions x ~3-4 calls x ~6K tokens) is ~600K tokens: **3x the daily token cap**. 8K tokens/min means 1 agent call per minute at our prompt size |
| OpenRouter `:free` models | $0 | 20 req/min; **50 req/day** (1,000/day only after a $10 credit purchase) | Varies by model and by whichever host serves it; free variants can be pulled without notice | 50/day breaks an eval run. Not demo-safe |
| Google Gemini Flash free tier | $0 | Google no longer publishes free limits (per project, in AI Studio); cut in Dec 2025 to roughly 5 RPM / 20 requests/day on 2.5 Flash | Decent tool calling | Too few requests/day; **free-tier prompts may be used to improve Google products and read by human reviewers** |
| Local (Ollama, e.g. Qwen 3 8B) | $0 | Your laptop's speed | Small local models are the weakest at multi-step tool use | Fine for offline dev; **cannot run on a free-tier web host** (no GPU, ~512 MB RAM), so the deployed app can't use it |

## Cost estimate (Haiku 4.5)

Assumptions, per user question (one agent run):

- ~3 model calls per run (choose tool, read result, maybe a second tool, then answer).
- ~6K input tokens per call on average (system prompt + tool definitions ~3K, retrieved policy chunks ~2K, growing conversation) and ~350 output tokens per call.
- So **~18K input + ~1K output per question = about $0.023**.

| Activity | Runs | Cost |
|---|---|---|
| Development and manual testing | ~1,500 questions | ~$35 |
| 5 full eval runs (30 questions each, plus an LLM-as-judge pass of similar size) | 5 x 60 | ~$7 |
| Demo rehearsals + recording | ~100 questions | ~$2.50 |
| **Total** | | **~$45 (range $25-$60)** |

Notes:

- Prompt caching could cut input cost further (cache reads are ~10% of the input price and don't count toward the per-minute limit), but Haiku 4.5 only caches prompts above a minimum length; our ~3K static prefix may be below it. Treat caching as a bonus, not part of the budget.
- Sonnet 5.5 roughly doubles every line above (~$90 total).
- Anthropic Start tier has a $500/month spend cap; you can set your own lower limit (recommend $50) so a runaway loop can't surprise you.

## Rate limits vs. the demo and eval

- **Eval run:** 30 questions x ~3 calls = ~90 requests and ~600K input tokens, spread over a few minutes. Haiku's Start tier (1,000 RPM, 2M input tokens/min) handles this with room to spare. Groq free (8K tokens/min, 200K/day) and OpenRouter free (50/day) do not.
- **Live demo:** only a handful of requests; any provider survives this *unless* a daily cap was already used up by testing that day. Paid Haiku removes that risk.
- **Latency:** Haiku is a fast tier; expect roughly 1-3 s per model call, so ~3-8 s per agent run with 2-3 calls. Groq is faster per call but the speed doesn't help if requests are rate-limited or tool calls fail. (Estimate, not measured; measure in the eval and report it in `design-and-evaluation.md`.)

## Keeping the provider swappable (hand-rolled loop)

Two ways to do it:

1. **One OpenAI-compatible client for everything** (`openai` SDK + `base_url`). Groq, OpenRouter, Gemini and Ollama all speak this format, and Anthropic has a compatibility endpoint too. **But** Anthropic says that endpoint is for testing, "not considered a long-term or production-ready solution"; it **ignores `strict`** (tool arguments not guaranteed to match the schema), **does not support prompt caching**, and drops native citations and thinking. That throws away the reasons we picked Claude.
2. **A thin adapter in our own code (recommended).** Define one small interface the agent loop calls, e.g. `llm.chat(messages, tools) -> {text, tool_calls, usage}`, with two implementations:
   - `AnthropicLLM` using the native `anthropic` SDK (tool use, `strict: true`, caching, usage numbers for the Trace).
   - `OpenAICompatLLM` using the `openai` SDK with a configurable `base_url` (covers Groq, OpenRouter, Gemini, Ollama).

   The loop keeps its own neutral message list (user / assistant / tool-call / tool-result) and each adapter translates to its provider's format. The loop, the MCP Tools and the Trace never know which provider is in use.

Suggested env vars:

```
LLM_PROVIDER=anthropic        # or: openai_compat
LLM_MODEL=claude-haiku-4-5    # or e.g. openai/gpt-oss-120b
LLM_API_KEY=...
LLM_BASE_URL=                 # only for openai_compat, e.g. https://api.groq.com/openai/v1
```

Why this helps the rubric: "provider swappable via env var" is a visible, explainable design choice, and keeping the agent loop hand-rolled means the adapter is the only provider-specific code.

## Sources

- Claude model ids and prices: Anthropic `claude-api` skill model table (cached 2026-09-25); [Claude pricing](https://platform.claude.com/docs/en/about-claude/pricing)
- Claude rate limits, tiers, spend caps, cache-aware limits: https://platform.claude.com/docs/en/api/rate-limits
- Anthropic OpenAI-compatibility limitations: https://platform.claude.com/docs/en/api/openai-sdk
- Groq free-tier limits: https://console.groq.com/docs/rate-limits
- Groq gpt-oss tool-calling reports: https://community.groq.com/t/tool-calling-errors-on-both-gpt-oss-models/406 , https://community.groq.com/t/gpt-oss-120b-ignoring-tools/385 , https://community.groq.com/t/groq-gpt-oss-120b-returns-null-response/1180
- OpenRouter free-model limits: https://openrouter.ai/docs/api-reference/limits
- Gemini free tier (limits per project; data use): https://ai.google.dev/gemini-api/docs/rate-limits , https://agentdeals.dev/gemini-api-pricing-changes
- Berkeley Function Calling Leaderboard (last updated 2026-04-12; useful for the write-up): https://gorilla.cs.berkeley.edu/leaderboard.html
