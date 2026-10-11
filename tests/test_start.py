"""Start check: the app boots and /health answers with both MCP servers' tools (slices 1, 3, 4)."""

from fastapi.testclient import TestClient

from app.main import create_app


def test_health_returns_200_with_live_tool_lists(settings):
    with TestClient(create_app(settings, in_memory_mcp=True)) as client:
        r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["demo_today"] == "2026-11-02"
    assert body["llm"] == {"provider": "fake", "model": settings.llm_model}
    assert len(body["mcp"]["policy"]["tools"]) == 2
    assert len(body["mcp"]["hr"]["tools"]) == 7
    assert body["index"]["chunks"] > 100 and len(body["index"]["corpus_hash"]) == 64
    assert "uptime_s" in body and "version" in body


def test_health_is_503_when_a_server_is_down(settings):
    app = create_app(settings, in_memory_mcp=True)
    app.state.hub.targets["policy"] = "http://127.0.0.1:9/mcp/policy/"  # nothing listens there
    with TestClient(app) as client:
        r = client.get("/health")
    assert r.status_code == 503
    assert r.json()["mcp"]["policy"]["ok"] is False
    assert r.json()["mcp"]["hr"]["ok"] is True


def test_health_never_returns_a_key(settings):
    settings.llm_api_key = "sk-secret-value"
    with TestClient(create_app(settings, in_memory_mcp=True)) as client:
        assert "sk-secret-value" not in client.get("/health").text
