# MCP transport and process topology (one free-tier service)

Ticket: [#3](https://github.com/i2oss/hr-agent/issues/3) · Researched 2026-10-06 against MCP Python SDK **v2.3.0** (PyPI, 2026-10-02) and MCP spec revision **2026-07-28**.

## TL;DR

- **Recommend: mount the MCP server inside the FastAPI app** (Streamable HTTP at `/mcp`), and have the agent loop call it as a real MCP client over `http://127.0.0.1:$PORT/mcp`. One process, one port, one deploy, one health check.
- **Tests:** use the SDK's in-memory client (`Client(mcp)`) for fast tool tests in CI, plus one end-to-end test that goes over real HTTP.
- **Fallback:** stdio subprocess (the agent launches the MCP server as a child process). Still one service, but more memory and more lifecycle code.
- **Don't** deploy MCP as a separate service: double the cold starts, a second URL to secure, more free-tier hours, nothing gained for the rubric.

## What changed in 2026 (important for the SPEC)

- SDK v2 is current. `FastMCP` is renamed **`MCPServer`** (`from mcp.server import MCPServer`); old v1 tutorials won't import. v1.x is maintenance-only. ([What's new in v2](https://py.sdk.modelcontextprotocol.io/whats-new/))
- One **`Client`** object replaces v1's `stdio_client` + `ClientSession` + `initialize()` layering. It picks the transport from its argument: a URL → Streamable HTTP, `StdioServerParameters` → subprocess, the server object → in-memory. ([Client transports](https://py.sdk.modelcontextprotocol.io/client/transports/))
- Spec 2026-07-28 drops the `initialize` handshake and HTTP sessions (`Mcp-Session-Id`): every request stands alone. The SDK still serves older 2025-era clients automatically. ([What's new](https://py.sdk.modelcontextprotocol.io/whats-new/), [Deploy & scale](https://py.sdk.modelcontextprotocol.io/run/deploy/))
- Spec transports remain **stdio** and **Streamable HTTP**; old HTTP+SSE is superseded — don't build on it. ([Spec: transports](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports), [SDK README](https://github.com/modelcontextprotocol/python-sdk))
- Pin: `mcp>=2.3,<3`. Python 3.10+.

## The options

### A. In-process Streamable HTTP, mounted on FastAPI (recommended)

How it works:
- `mcp.streamable_http_app()` returns a Starlette (ASGI) app; FastAPI mounts it. ([Add to an existing app](https://py.sdk.modelcontextprotocol.io/run/asgi/))
- The agent loop opens `Client("http://127.0.0.1:{PORT}/mcp")`, calls `list_tools()` to discover tools (names, descriptions, JSON schemas → handed to the LLM), then `call_tool(name, args)` for each tool the LLM picks.
- Every tool call is a genuine MCP JSON-RPC request over a real transport — easy to show in the Trace and defend against "a direct function call is not a Tool call" (see CONTEXT.md).

Sketch:
```python
mcp = MCPServer("hr-tools")          # tools defined with @mcp.tool()
mcp_app = mcp.streamable_http_app(streamable_http_path="/")

@asynccontextmanager
async def lifespan(app):
    async with mcp.session_manager.run():   # REQUIRED when mounted
        yield

app = FastAPI(lifespan=lifespan)
# ... /api/chat, /health, static chat page routes ...
app.mount("/mcp", mcp_app)                  # endpoint: /mcp/
```

Startup / health:
- One uvicorn process; the platform health check hits FastAPI's `/health`. Can optionally do a self-`list_tools()` in a `/ready` check to prove MCP is up.
- Startup cost ≈ zero extra: no second interpreter.

Testing in CI:
- Fast unit tests: `async with Client(mcp, raise_exceptions=True) as c:` — no port, no subprocess, still the full MCP protocol layer. ([Testing](https://py.sdk.modelcontextprotocol.io/get-started/testing/))
- One integration test: start uvicorn on a free port in a pytest fixture and run the agent loop against `http://127.0.0.1:<port>/mcp/` (LLM stubbed).

Gotchas:
- **Lifespan:** a mounted app's own lifespan never runs. Forget `mcp.session_manager.run()` in FastAPI's lifespan and the first call fails with `RuntimeError: Task group is not initialized`. ([ASGI page](https://py.sdk.modelcontextprotocol.io/run/asgi/))
- **Host allowlist (421 errors):** by default the MCP app accepts only `Host: localhost/127.0.0.1`. Because our agent calls it via `127.0.0.1`, the default is exactly right — and it means outsiders hitting `https://<app>.onrender.com/mcp/` get rejected for free. Only if we ever want public MCP access do we add `transport_security=TransportSecuritySettings(allowed_hosts=[...])`. ([Deploy & scale](https://py.sdk.modelcontextprotocol.io/run/deploy/))
- **Async only:** the chat endpoint must be `async def` and await the client. A blocking (sync) call to our own server from inside the same single worker could deadlock it.
- **Route order:** if mounted at `/`, it swallows every later route. Mounting at `/mcp` avoids that. Trailing-slash redirect `/mcp` → `/mcp/` is followed by the client, but configure `/mcp/` exactly.
- **Workers:** keep one uvicorn worker (free tier anyway). If ever scaled, multi-round-trip tools need a shared `RequestStateSecurity` key — not relevant if Confirmation is handled by our agent loop rather than MCP elicitation.
- **Elicitation:** on 2026-07-28 there is no server→client push (`ctx.elicit()` fails). Do HITL Confirmation in the agent loop / chat UI, not inside MCP tools. (Fits the existing Mock Action design.)

### B. stdio subprocess (fallback)

How it works:
- The FastAPI app starts the MCP server as a child process: `Client(StdioServerParameters(command="python", args=["-m", "hr_agent.mcp_server"], env={...}))`. JSON-RPC flows over stdin/stdout. ([Client transports: stdio](https://py.sdk.modelcontextprotocol.io/client/transports/))
- Same `list_tools()` / `call_tool()` calls as Option A.

Pros: the textbook MCP picture (client launches server), very clear separation, no network/Host config.

Cons / gotchas:
- **Memory:** a second Python interpreter + its imports. If tools load the vector index or data files, that's loaded twice. Risky on a 512 MB free instance.
- **Lifecycle:** spawning per chat request is slow (process start each time); keeping one long-lived child means opening the `Client` in FastAPI's lifespan and handling crashes/restarts yourself.
- **Env vars:** the child gets only a minimal allow-list (`HOME`, `PATH`, …). Secrets/paths must be passed via `env=` explicitly.
- **stdout is sacred:** any `print()` in server code corrupts the protocol; log to stderr only.
- Testing: same in-memory `Client(mcp)` unit tests; integration test spawns the subprocess (works fine in GitHub Actions).

### C. Localhost HTTP as a second process in the same container

- Run uvicorn twice (FastAPI on `$PORT`, MCP on e.g. 8001) under a process manager or a shell script.
- Combines the downsides: two interpreters (memory), a supervisor to keep both alive, health check only sees the main one. No advantage over A. **Not recommended.**

### D. Separate deployed service

- Two free services (app + MCP), agent calls `https://hr-mcp.onrender.com/mcp/`.
- Costs: two cold starts on the demo (each free instance sleeps when idle), two sets of env vars/deploys, a public MCP endpoint that needs a Host allowlist and ideally auth (spec: servers SHOULD authenticate), TLS-proxy config (`--proxy-headers`, else redirect-downgrade errors), CORS not needed but still more surface. ([Deploy & scale](https://py.sdk.modelcontextprotocol.io/run/deploy/), [Spec security warning](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports#security-warning))
- Upside: could be "real microservices" talking point. Not worth it for the rubric; mention it as a future-scale note in the design doc instead.

## Comparison

| | A. Mounted HTTP | B. stdio child | C. 2nd local HTTP proc | D. Separate service |
|---|---|---|---|---|
| Processes | 1 | 2 | 2 | 2 services |
| Extra memory | none | 2nd interpreter | 2nd interpreter | separate instance |
| Real MCP transport | yes (HTTP) | yes (stdio) | yes (HTTP) | yes (HTTP) |
| Health check | one `/health` | must watch child | must watch both | two checks |
| Cold start on demo | 1 | 1 (+ spawn) | 1 (+ spawn) | 2 |
| Security config | none (localhost default) | none | none | allowlist + auth |
| CI testing | easy | easy | awkward | awkward |

## Recommendation for SPEC.md

1. **Topology:** one FastAPI service; MCP server (`MCPServer`, SDK `mcp>=2.3,<3`) mounted at `/mcp`; FastAPI lifespan enters `mcp.session_manager.run()`; one uvicorn worker.
2. **Agent client:** one long-lived `Client("http://127.0.0.1:{PORT}/mcp/")` opened in the lifespan (or per chat turn — cheap, since 2026-07-28 has no handshake); `list_tools()` once at startup → LLM tool schemas; `call_tool()` per step; every call logged into the Trace.
3. **Security:** keep the default localhost-only Host check, so `/mcp` is not publicly usable.
4. **HITL:** Confirmation lives in the agent loop/UI, not MCP elicitation.
5. **CI:** in-memory `Client(mcp)` tests per tool + one uvicorn-backed end-to-end test with a stubbed LLM.
6. **Fallback:** if mounting misbehaves on the host platform, switch to stdio child (Option B) — the agent code changes only the `Client(...)` argument.

## Sources

- MCP Python SDK repo/README: https://github.com/modelcontextprotocol/python-sdk
- PyPI `mcp` (v2.3.0): https://pypi.org/project/mcp/
- SDK docs — What's new in v2: https://py.sdk.modelcontextprotocol.io/whats-new/
- SDK docs — Add to an existing app (ASGI mounting): https://py.sdk.modelcontextprotocol.io/run/asgi/
- SDK docs — Deploy & scale: https://py.sdk.modelcontextprotocol.io/run/deploy/
- SDK docs — Client transports: https://py.sdk.modelcontextprotocol.io/client/transports/
- SDK docs — Testing: https://py.sdk.modelcontextprotocol.io/get-started/testing/
- MCP spec — Transports: https://modelcontextprotocol.io/specification/2025-06-18/basic/transports (2026-07-28 revision also published: https://modelcontextprotocol.io/specification/2026-07-28/basic/transports)
