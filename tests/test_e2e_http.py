"""End-to-end W01 against the real app under uvicorn (SPEC slice 5): the agent's MCP client reaches
both servers over Streamable HTTP on 127.0.0.1, exactly as in production. Fake LLM, no key."""

import socket
import threading
import time
import uuid

import httpx
import pytest
import uvicorn

from app.agent.fake_scripts import W01
from app.agent.llm import FakeLLM
from app.main import create_app


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def base_url(settings):
    settings.port = free_port()
    server = uvicorn.Server(uvicorn.Config(create_app(settings, llm=FakeLLM()), host="127.0.0.1",
                                           port=settings.port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 30
    while not server.started:
        assert time.time() < deadline, "uvicorn didn't start"
        time.sleep(0.05)
    yield f"http://127.0.0.1:{settings.port}"
    server.should_exit = True
    thread.join(10)


def test_health_lists_nine_tools_over_http(base_url):
    body = httpx.get(f"{base_url}/health", timeout=30).json()
    assert len(body["mcp"]["policy"]["tools"]) + len(body["mcp"]["hr"]["tools"]) == 9


def test_w01_over_streamable_http(base_url):
    s = uuid.uuid4().hex
    with httpx.Client(base_url=base_url, timeout=60) as c:
        r = c.post("/chat", json={"session_id": s, "speaking_as": "E1001", "message": W01}).json()
        tools = [x["tool"] for x in r["trace"]["steps"] if x["kind"] == "tool"]
        assert tools == ["lookup_employee_profile", "check_pto_balance", "search_policy", "check_policy_compliance"]
        assert r["pending_action"]["tool"] == "draft_manager_message"
        done = c.post(f"/chat/actions/{r['pending_action']['action_id']}", json={"decision": "confirm"}).json()
    assert done["action_result"]["id"].startswith("MSG-MOCK-")


def test_mcp_mounts_reject_a_public_host(base_url):
    r = httpx.post(f"{base_url}/mcp/hr/", headers={"Host": "attacker.example", "content-type": "application/json"},
                   json={})
    assert r.status_code == 421
