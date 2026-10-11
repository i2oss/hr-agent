"""App factory: FastAPI web app, with the two MCP servers mounted inside it (SPEC §3.4)."""

from __future__ import annotations

import time
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    started = time.monotonic()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield

    app = FastAPI(title="Ridgeline HR Agent (FICTIONAL)", lifespan=lifespan)
    app.state.settings = settings

    @app.get("/health")
    async def health():
        return {
            "status": "ok",
            "version": settings.render_git_commit or "dev",
            "uptime_s": round(time.monotonic() - started, 1),
            "llm": {"provider": settings.llm_provider, "model": settings.llm_model},
            "demo_today": settings.demo_today.isoformat(),
        }

    return app
