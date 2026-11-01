import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app import talk
from app.main import app


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(talk, "DATA", tmp_path)
    monkeypatch.setattr(talk, "AGENT_FILE", tmp_path / "agent.json")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    monkeypatch.delenv("TALK_AGENT_ID", raising=False)
    return tmp_path


def mock(calls):
    def handler(req: httpx.Request) -> httpx.Response:
        calls.append((req.method, req.url.path))
        assert req.headers["xi-api-key"] == "test-key"
        if req.url.path.endswith("/agents/create"):
            return httpx.Response(200, json={"agent_id": "agent_1"})
        if req.url.path.endswith("/get-signed-url"):
            assert req.url.params["agent_id"] == "agent_1"
            return httpx.Response(200, json={"signed_url": "wss://x.test/c?token=t"})
        return httpx.Response(200, json={})
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_creates_agent_once_then_reuses(env):
    calls = []
    c = mock(calls)
    assert talk.start_session(client=c)["signed_url"].startswith("wss://")
    talk.start_session(client=c)
    assert [m for m, p in calls if p.endswith("/create")] == ["POST"]       # created once
    assert json.loads((env / "agent.json").read_text())["agent_id"] == "agent_1"


def test_changed_prompt_patches_existing_agent(env, monkeypatch):
    calls = []
    c = mock(calls)
    talk.start_session(client=c)
    monkeypatch.setattr(talk, "PROMPT", talk.PROMPT + "\nExtra.")
    talk.start_session(client=c)
    assert ("PATCH", "/v1/convai/agents/agent_1") in calls


def test_agent_id_from_env_skips_creation(env, monkeypatch):
    monkeypatch.setenv("TALK_AGENT_ID", "mine")
    calls = []
    def handler(req):
        calls.append(req.url.path)
        return httpx.Response(200, json={"signed_url": "wss://x.test/c"})
    talk.start_session(client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert not any(p.endswith("/create") for p in calls)


def test_permission_error_is_readable(env):
    def handler(req):
        return httpx.Response(401, json={"detail": {"message": "missing the permission convai_write"}})
    with pytest.raises(RuntimeError, match="convai_write"):
        talk.start_session(client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_api_without_key(monkeypatch):
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.setattr(talk.config, "elevenlabs_key", lambda: None)
    t = TestClient(app)
    assert t.get("/api/talk/status").json()["available"] is False
    assert t.post("/api/talk/session").status_code == 503


def test_prompt_variables_are_declared():
    cfg = talk.agent_config()["conversation_config"]["agent"]
    placeholders = cfg["dynamic_variables"]["dynamic_variable_placeholders"]
    for name in ("topic", "goal", "focus"):
        assert "{{%s}}" % name in cfg["prompt"]["prompt"] and name in placeholders


def test_every_scenario_has_english_guidance():
    assert len({s["id"] for s in talk.SCENARIOS}) == len(talk.SCENARIOS)
    for s in talk.SCENARIOS:
        assert s["title"] and s["goal"] and len(s["starters"]) >= 3
