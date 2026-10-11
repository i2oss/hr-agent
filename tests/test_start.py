"""Start check: the app boots and /health answers (slice 1)."""

from fastapi.testclient import TestClient

from app.main import create_app


def test_health_returns_200(settings):
    with TestClient(create_app(settings)) as client:
        r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["demo_today"] == "2026-11-02"
    assert body["llm"] == {"provider": "fake", "model": settings.llm_model}
    assert "uptime_s" in body and "version" in body


def test_health_never_returns_a_key(settings):
    settings.llm_api_key = "sk-secret-value"
    with TestClient(create_app(settings)) as client:
        assert "sk-secret-value" not in client.get("/health").text
