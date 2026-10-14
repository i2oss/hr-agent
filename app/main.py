"""App factory: the FastAPI web app, with the two MCP servers mounted inside it (SPEC §3.4).

`policy` is served at /mcp/policy and `hr` at /mcp/hr over Streamable HTTP. The lifespan enters
both session managers. The agent reaches them only through its MCP client, at MCP_POLICY_URL and
MCP_HR_URL (by default these in-process mounts on 127.0.0.1). The SDK's default localhost-only
Host check keeps /mcp/* closed to the public.
"""

from __future__ import annotations

import time
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.agent.llm import LLM, make_llm
from app.agent.loop import AgentLoop
from app.agent.mcp_client import McpHub, ServerName
from app.agent.sessions import SessionStore
from app.api.limits import Limits
from app.api.routes import build_router
from app.config import ROOT, Settings, get_settings
from mcp_servers.hr.models import load_mock_data
from mcp_servers.hr.server import build_hr_server
from mcp_servers.hr.store import MockActionStore
from mcp_servers.policy.embeddings import make_embedder
from mcp_servers.policy.retrieval import PolicyIndex
from mcp_servers.policy.server import build_policy_server


def create_app(settings: Settings | None = None, *, in_memory_mcp: bool = False, llm: LLM | None = None) -> FastAPI:
    """`in_memory_mcp` (tests only) points the agent's MCP client at the server objects instead of
    the HTTP mounts, because FastAPI's TestClient can't reach its own app over a socket. `llm`
    (tests only) injects a scripted FakeLLM."""
    settings = settings or get_settings()
    started = time.monotonic()

    embedder = make_embedder(settings)
    index = PolicyIndex.load(settings.index_path, embedder)
    store = MockActionStore()
    policy = build_policy_server(index, settings)
    hr = build_hr_server(settings, store)
    policy_app = policy.streamable_http_app(streamable_http_path="/")
    hr_app = hr.streamable_http_app(streamable_http_path="/")

    targets: dict[ServerName, Any] = (
        {"policy": policy, "hr": hr} if in_memory_mcp else {"policy": settings.policy_url, "hr": settings.hr_url}
    )
    hub = McpHub(targets)
    loop = AgentLoop(hub, llm or make_llm(settings), settings)
    sessions = SessionStore()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with AsyncExitStack() as stack:
            await stack.enter_async_context(policy.session_manager.run())
            await stack.enter_async_context(hr.session_manager.run())
            embedder.embed_query("warm up")  # load the embedding model before the first request
            yield

    app = FastAPI(title="Ridgeline HR Agent (FICTIONAL)", lifespan=lifespan)
    app.state.settings = settings
    app.state.hub = hub
    app.state.store = store
    app.state.loop = loop
    app.state.sessions = sessions
    app.include_router(build_router(loop, sessions, Limits(settings), load_mock_data(settings.mock_data_dir)))
    app.mount("/mcp/policy", policy_app)
    app.mount("/mcp/hr", hr_app)

    @app.get("/health")
    async def health() -> JSONResponse:
        mcp = await hub.health()
        ok = all(s["ok"] for s in mcp.values())
        body = {
            "status": "ok" if ok else "degraded",
            "version": settings.render_git_commit or "dev",
            "uptime_s": round(time.monotonic() - started, 1),
            "index": {"chunks": index.chunk_count, "corpus_hash": index.corpus_hash},
            "mcp": mcp,
            "llm": {"provider": settings.llm_provider, "model": settings.llm_model},
            "demo_today": settings.demo_today.isoformat(),
        }
        return JSONResponse(body, status_code=200 if ok else 503)

    web = ROOT / "app" / "web"
    if web.is_dir():
        app.mount("/", StaticFiles(directory=web, html=True), name="web")  # last: the chat page
    return app
