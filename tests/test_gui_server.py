"""Tests for the localhost GUI adapter."""

import json
import threading
from urllib.request import Request, urlopen

from next_agent.gui_server import SessionStore, create_server, credential_file
from next_agent.gui_server import _safe_provider_error


def test_session_store_creates_public_session(tmp_path):
    store = SessionStore(str(tmp_path))
    session = store.create()
    assert session["title"] == "Untitled code session"
    assert session["workdir"] == str(tmp_path.resolve())
    assert session["status"] == "idle"
    assert "agent" not in session


def test_empty_stats(tmp_path):
    store = SessionStore(str(tmp_path))
    stats = store.stats()
    assert stats["sessions"] == 0
    assert stats["total_tokens"] == 0
    assert stats["rounds"] == []


def test_session_runs_message_and_updates_stats(tmp_path):
    store = SessionStore(str(tmp_path))
    session = store.create()
    record = store.get_record(session["id"])
    record["agent"].chat = lambda message: f"received: {message}"

    result = store.run_message(session["id"], "Inspect the workspace")

    assert result["response"] == "received: Inspect the workspace"
    assert result["session"]["status"] == "completed"
    assert result["session"]["title"] == "Inspect the workspace"
    assert store.stats()["messages"] == 1


def test_dswork_chat_uses_isolated_agent_without_code_session(tmp_path, monkeypatch):
    store = SessionStore(str(tmp_path))
    monkeypatch.setattr("next_agent.gui_server.Agent.chat", lambda self, message: "agent response")
    result = store.chat([{"role": "user", "content": "hello"}])

    assert result["response"] == "agent response"
    assert store.list() == []


def test_reset_clears_gui_state_memory_and_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    store = SessionStore(str(tmp_path), state_path=tmp_path / "state.db")
    store.create()
    store.memory.remember("Remember me", "user")
    store.state.add_usage(None, "dswork", "deepseek-v4-flash", {"prompt_tokens": 3})
    store.save_api_key("sk-reset")

    store.reset()

    assert store.list() == []
    assert store.gui_state()["dswork"] == []
    assert store.stats()["total_tokens"] == 0
    assert store.memory.stats()["total"] == 0
    assert not credential_file().exists()


def test_sessions_conversations_and_usage_survive_restart(tmp_path):
    state_path = tmp_path / "gui-state.db"
    store = SessionStore(str(tmp_path), state_path=state_path)
    session = store.create()
    store.save_gui_state({
        "code": [{
            **session,
            "title": "Remember this session",
            "conversation": {
                "title": "Remember this session",
                "status": "complete",
                "turns": [{"title": "Remember this session", "response": "Remembered.", "status": "complete"}],
            },
            "pinned": True,
        }],
        "dswork": [{
            "id": "ds-persisted",
            "title": "Plain chat",
            "model": "deepseek-v4-flash",
            "meta": "Complete",
            "conversation": {
                "title": "Plain chat",
                "status": "complete",
                "turns": [{"title": "Plain chat", "response": "Hello.", "status": "complete"}],
            },
        }],
    })
    store.state.add_usage(session["id"], "code", "deepseek-v4-flash", {
        "prompt_tokens": 12,
        "completion_tokens": 3,
        "cache_hit_tokens": 8,
        "cache_miss_tokens": 4,
    })

    restored = SessionStore(str(tmp_path), state_path=state_path)

    assert restored.list()[0]["title"] == "Remember this session"
    assert restored.list()[0]["conversation"]["turns"][0]["response"] == "Remembered."
    assert restored.gui_state()["dswork"][0]["id"] == "ds-persisted"
    assert restored.stats()["total_tokens"] == 15


def test_workspace_features_survive_restart(tmp_path):
    state_path = tmp_path / "gui-state.db"
    store = SessionStore(str(tmp_path), state_path=state_path)
    store.save_gui_state({
        "code": [],
        "dswork": [],
        "projects": [{"id": "project-1", "name": "Docs", "path": str(tmp_path)}],
        "scheduled": [{"id": "schedule-1", "name": "Daily brief", "enabled": True}],
        "artifacts": [{"id": "artifact-1", "name": "Status board", "html": "<h1>Status</h1>"}],
        "connectors": [{"id": "connector-1", "name": "GitHub", "url": "https://github.com"}],
        "plugins": [{"id": "plugin-1", "name": "Release notes", "installed": True}],
    })

    restored = SessionStore(str(tmp_path), state_path=state_path).gui_state()

    assert restored["projects"][0]["name"] == "Docs"
    assert restored["scheduled"][0]["enabled"]
    assert restored["artifacts"][0]["html"] == "<h1>Status</h1>"
    assert restored["connectors"][0]["name"] == "GitHub"
    assert restored["plugins"][0]["installed"]


def test_provider_errors_are_sanitized():
    error = ValueError("401 invalid api key: secret-value")
    assert _safe_provider_error(error) == (
        "DeepSeek authentication failed. Update DEEPSEEK_API_KEY or the workspace .api_key file."
    )


def test_save_api_key_uses_user_app_data(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    store = SessionStore(str(tmp_path))
    store.save_api_key("sk-test")
    assert credential_file().read_text(encoding="utf-8") == "sk-test"
    assert store.provider_configured()


def test_config_http_endpoint(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    server = create_server(port=0, workdir=str(tmp_path))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        request = Request(
            f"http://127.0.0.1:{server.server_port}/api/config",
            data=json.dumps({"api_key": "sk-http-test"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request) as response:
            payload = json.loads(response.read())
        assert payload["provider_configured"]
        assert credential_file().read_text(encoding="utf-8") == "sk-http-test"
    finally:
        server.shutdown()
        server.server_close()


def test_preflight_reports_missing_provider(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    store = SessionStore(str(tmp_path))
    result = store.preflight()
    assert not result["ok"]
    assert not result["provider_configured"]
    assert not result["checks"]["provider"]
