"""Local HTTP adapter for NextAgentGUI.

The GUI talks to this server over localhost. Agent instances stay in memory
so each GUI session preserves its conversation and prefix cache.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
import threading
import time
import uuid
from dataclasses import asdict
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .agent import Agent, AgentConfig
from .gui_state import GUIStateDB
from .llm import LLMAdapter, LLMConfig
from .memory import MemoryManager
from .setup import load_config
from .skills import SkillManager
from .workspace import build_snapshot


def app_data_dir() -> Path:
    base = Path(os.environ.get("APPDATA", Path.home()))
    return base / "NextAgent"


def credential_file() -> Path:
    return app_data_dir() / "deepseek_api_key"


def bundled_path(*parts: str) -> Path:
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return root.joinpath(*parts)


def _round_payload(round_data) -> dict[str, Any]:
    return asdict(round_data)


def _safe_provider_error(exc: Exception) -> str:
    message = str(exc)
    lowered = message.lower()
    if "401" in message or "authentication" in lowered or "api key" in lowered:
        return "DeepSeek authentication failed. Update DEEPSEEK_API_KEY or the workspace .api_key file."
    if "429" in message or "rate limit" in lowered:
        return "DeepSeek rate limit reached. Wait briefly, then try again."
    if "timeout" in lowered:
        return "The DeepSeek request timed out. Check the network and try again."
    return "NextAgent core could not complete the request. Check the core service logs."


class SessionStore:
    def __init__(self, default_workdir: str, state_path: str | Path | None = None):
        self.default_workdir = str(Path(default_workdir).resolve())
        self._sessions: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()
        default_state_path = (
            Path(default_workdir) / ".nextagent-gui-test.db"
            if os.environ.get("PYTEST_CURRENT_TEST")
            else app_data_dir() / "gui_state.db"
        )
        self.state = GUIStateDB(state_path or default_state_path)
        self.extra_state_path = self.state.path.with_name("workspace_state.json")
        self.memory = MemoryManager()
        self.skills = SkillManager()
        self._dswork_agents: dict[str, Agent] = {}
        self._restore_code_sessions()

    def _load_extra_state(self) -> dict[str, Any]:
        defaults = {
            "projects": [],
            "scheduled": [],
            "artifacts": [],
            "connectors": [],
            "plugins": [],
        }
        if not self.extra_state_path.is_file():
            return defaults
        try:
            payload = json.loads(self.extra_state_path.read_text(encoding="utf-8"))
            return {key: payload.get(key, value) for key, value in defaults.items()}
        except (OSError, json.JSONDecodeError, AttributeError):
            return defaults

    def _save_extra_state(self, payload: dict[str, Any]) -> None:
        current = self._load_extra_state()
        for key in current:
            if key in payload and isinstance(payload[key], list):
                current[key] = payload[key]
        self.extra_state_path.parent.mkdir(parents=True, exist_ok=True)
        self.extra_state_path.write_text(
            json.dumps(current, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _new_agent(self, model: str, workdir: str, effort: str = "high", auto_model: bool = True) -> Agent:
        file_config = load_config()
        config = AgentConfig(
            model=model,
            workdir=workdir,
            max_rounds=int(file_config.get("max_rounds", 25)),
            enable_cache_dash=True,
            enable_lang_router=file_config.get("language", "auto") != "en",
            stream=False,
            effort=effort,
            auto_model=auto_model,
        )
        return Agent(config=config, llm_config=self.llm_config(model, workdir))

    def _restore_code_sessions(self) -> None:
        for item in self.state.list_conversations("code"):
            self._sessions[item["id"]] = {
                **item,
                "last_response": "",
                "error": "",
                "agent": None,
                "run_lock": threading.Lock(),
            }

    def _ensure_agent(self, record: dict[str, Any]) -> Agent:
        if record["agent"] is None:
            agent = self._new_agent(record["model"], record["workdir"] or self.default_workdir, auto_model=False)
            conversation = record.get("conversation") or {}
            for turn in conversation.get("turns", []):
                title = str(turn.get("title", "")).strip()
                response = str(turn.get("response", "")).strip()
                if title:
                    agent.messages.append({"role": "user", "content": title})
                    agent.turn_count += 1
                if response and turn.get("status") != "thinking":
                    agent.messages.append({"role": "assistant", "content": response})
            record["agent"] = agent
        return record["agent"]

    def _apply_runtime(self, agent: Agent, model: str | None, workdir: str, effort: str, auto_model: bool = False) -> None:
        before_model = agent.config.model
        agent.set_runtime_options(model=model, effort=effort, auto_model=auto_model)
        if model and model != before_model:
            agent.llm = LLMAdapter(self.llm_config(model, workdir))

    def _trace(self, agent: Agent | None) -> list[dict[str, Any]]:
        return list(getattr(agent, "last_trace", []) or [])

    def llm_config(self, model: str, workdir: str) -> LLMConfig:
        config = LLMConfig.from_env(model)
        key_file = credential_file()
        if not config.api_key and key_file.is_file():
            config.api_key = key_file.read_text(encoding="utf-8").strip()
        return config

    def provider_configured(self) -> bool:
        config = LLMConfig.from_env()
        return bool(
            config.api_key
            or credential_file().is_file()
        )

    def save_api_key(self, api_key: str) -> None:
        value = api_key.strip()
        if not value:
            raise ValueError("DeepSeek API key is required")
        path = credential_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding="utf-8")

    def preflight(self) -> dict[str, Any]:
        configured = self.provider_configured()
        checks = {
            "core": True,
            "workspace": Path(self.default_workdir).is_dir(),
            "commands": bundled_path("next_agent", "commands").is_dir()
            or (Path.cwd() / "next_agent" / "commands").is_dir(),
            "provider": False,
        }
        error = ""
        if configured:
            try:
                config = self.llm_config("deepseek-v4-flash", self.default_workdir)
                adapter = LLMAdapter(config)
                adapter.client.with_options(timeout=8.0).models.list()
                checks["provider"] = True
            except Exception as exc:
                error = _safe_provider_error(exc)
        return {
            "ok": all(checks.values()),
            "provider_configured": configured,
            "checks": checks,
            "error": error,
        }

    def create(self, title: str = "Untitled code session", model: str | None = None, workdir: str | None = None) -> dict:
        file_config = load_config()
        selected_model = model or file_config.get("model", "deepseek-v4-flash")
        selected_workdir = str(Path(workdir or self.default_workdir).resolve())
        agent = self._new_agent(selected_model, selected_workdir)
        now = time.time()
        session_id = uuid.uuid4().hex[:12]
        record = {
            "id": session_id,
            "title": title,
            "model": selected_model,
            "workdir": selected_workdir,
            "created_at": now,
            "updated_at": now,
            "status": "idle",
            "last_response": "",
            "error": "",
            "conversation": None,
            "pinned": False,
            "done": False,
            "archived": False,
            "agent": agent,
            "run_lock": threading.Lock(),
        }
        with self._lock:
            self._sessions[session_id] = record
        self.state.upsert_conversation(record, "code")
        return self.public(record)

    def public(self, record: dict[str, Any]) -> dict[str, Any]:
        agent: Agent | None = record["agent"]
        return {
            "id": record["id"],
            "title": record["title"],
            "model": record["model"],
            "workdir": record["workdir"],
            "created_at": record["created_at"],
            "updated_at": record["updated_at"],
            "status": record["status"],
            "last_response": record["last_response"],
            "error": record["error"],
            "turn_count": agent.turn_count if agent else len((record.get("conversation") or {}).get("turns", [])),
            "rounds": len(agent.cache_dash.rounds) if agent else 0,
            "conversation": record.get("conversation"),
            "pinned": bool(record.get("pinned")),
            "done": bool(record.get("done")),
        }

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                self.public(record)
                for record in sorted(self._sessions.values(), key=lambda item: item["updated_at"], reverse=True)
            ]

    def get_record(self, session_id: str) -> dict[str, Any] | None:
        with self._lock:
            return self._sessions.get(session_id)

    def run_message(
        self,
        session_id: str,
        message: str,
        model: str | None = None,
        effort: str = "high",
        auto_model: bool = False,
    ) -> dict[str, Any]:
        record = self.get_record(session_id)
        if not record:
            raise KeyError("Session not found")
        if not record["run_lock"].acquire(blocking=False):
            raise RuntimeError("Session is already running")

        record["status"] = "running"
        record["error"] = ""
        record["updated_at"] = time.time()
        if record["title"].startswith("Untitled"):
            record["title"] = message.strip().splitlines()[0][:72] or record["title"]
        conversation = record.get("conversation") or {"title": record["title"], "status": "thinking", "turns": []}
        turns = list(conversation.get("turns", []))
        if not turns or turns[-1].get("title") != message or turns[-1].get("status") != "thinking":
            turns.append({"title": message, "response": "", "status": "thinking"})
        record["conversation"] = {**conversation, "title": conversation.get("title") or record["title"], "status": "thinking", "turns": turns}

        try:
            agent = self._ensure_agent(record)
            selected_model = model or record["model"]
            selected_effort = (effort or "high").lower()
            self._apply_runtime(agent, selected_model, record["workdir"] or self.default_workdir, selected_effort, auto_model=auto_model)
            record["model"] = agent.config.model
            before_rounds = len(agent.cache_dash.rounds)
            response = agent.chat(message)
            for round_data in agent.cache_dash.rounds[before_rounds:]:
                self.state.add_usage(record["id"], "code", record["model"], asdict(round_data), round_data.elapsed_ms)
            record["last_response"] = response
            record["status"] = "completed"
            trace = self._trace(agent)
            turns[-1] = {**turns[-1], "response": response, "status": "complete", "trace": trace}
            record["conversation"] = {**record["conversation"], "status": "complete", "turns": turns}
            return {"session": self.public(record), "response": response, "trace": trace, "model": agent.config.model, "effort": agent.config.effort}
        except Exception as exc:
            record["status"] = "failed"
            record["error"] = _safe_provider_error(exc)
            turns[-1] = {**turns[-1], "response": record["error"], "status": "failed"}
            record["conversation"] = {**record["conversation"], "status": "failed", "turns": turns}
            raise RuntimeError(record["error"]) from exc
        finally:
            record["updated_at"] = time.time()
            self.state.upsert_conversation(record, "code")
            record["run_lock"].release()

    def chat(self, messages: list[dict[str, str]], model: str | None = None, session_id: str | None = None, effort: str = "high", auto_model: bool = False) -> dict[str, Any]:
        """Run a DeepSeek conversation with Agent (frozen prefix + tools + compression).

        Each session_id gets a persistent Agent instance so the prefix cache
        and tool schemas are frozen once and reused across turns.
        """
        selected_model = model or "deepseek-v4-flash"
        clean_messages = [
            {"role": item.get("role", ""), "content": str(item.get("content", "")).strip()}
            for item in (messages or [])
            if item.get("role") in {"user", "assistant"} and str(item.get("content", "")).strip()
        ]
        if not clean_messages or clean_messages[-1]["role"] != "user":
            raise ValueError("A user message is required")

        # Find or create a persistent Agent for this session
        session_key = session_id or "__ephemeral"
        agent = self._dswork_agents.get(session_key)

        if agent is None:
            # New session: create Agent; all messages are history
            agent = self._new_agent(selected_model, self.default_workdir, effort=effort, auto_model=auto_model)
            # Feed all but the last user message as history
            for msg in clean_messages[:-1]:
                agent.messages.append(msg)
                if msg["role"] == "user":
                    agent.turn_count += 1
            self._dswork_agents[session_key] = agent
        else:
            # Existing session: agent.messages already has history
            # Verify the last message matches what the GUI sent (avoid drift)
            self._apply_runtime(agent, selected_model, self.default_workdir, effort, auto_model=auto_model)

        try:
            # Process the last user message through the Agent
            last_msg = clean_messages[-1]["content"]
            before_rounds = len(agent.cache_dash.rounds)
            response_text = agent.chat(last_msg)
            from dataclasses import asdict
            for round_data in agent.cache_dash.rounds[before_rounds:]:
                self.state.add_usage(
                    session_id or session_key, "dswork",
                    selected_model, asdict(round_data), round_data.elapsed_ms,
                )

            # Record conversation turns in state DB (same format as before)
            if session_id:
                turns = []
                pending = None
                for msg in clean_messages:
                    if msg["role"] == "user":
                        if pending:
                            turns.append(pending)
                        pending = {"title": msg["content"], "response": "", "status": "complete"}
                    elif pending:
                        pending["response"] = msg["content"]
                if pending:
                    pending["response"] = response_text
                    turns.append(pending)
                first_title = turns[0]["title"] if turns else "Untitled task"
                self.state.upsert_conversation({
                    "id": session_id,
                    "title": first_title,
                    "model": selected_model,
                    "status": "Complete",
                    "conversation": {"title": first_title, "status": "complete", "turns": turns},
                }, "dswork")

            return {"response": response_text, "usage": {}, "model": agent.config.model, "effort": agent.config.effort, "trace": self._trace(agent)}
        except Exception as exc:
            raise RuntimeError(_safe_provider_error(exc)) from exc

    def stats(self) -> dict[str, Any]:
        return self.state.stats()

    def gui_state(self) -> dict[str, Any]:
        return {
            "code": self.state.list_conversations("code"),
            "dswork": self.state.list_conversations("dswork"),
            "archived": self.state.list_conversations(archived=True),
            "memories": self.memory.stats(),
            **self._load_extra_state(),
        }

    def save_gui_state(self, payload: dict[str, Any]) -> dict[str, Any]:
        code_items = payload.get("code", [])
        dswork_items = payload.get("dswork", [])
        self.state.replace_mode("code", code_items)
        self.state.replace_mode("dswork", dswork_items)
        self._save_extra_state(payload)
        with self._lock:
            for item in code_items:
                record = self._sessions.get(str(item.get("id")))
                if record:
                    for key in ("title", "conversation", "pinned", "done", "status", "updated_at"):
                        if key in item:
                            record[key] = item[key]
        return self.gui_state()

    def remember_user_message(self, message: str, project: str | None = None) -> None:
        content = message.strip()
        if not content:
            return
        existing = self.memory.db.search_by_type("user", project, limit=100)
        if any(item.content.strip().lower() == content.lower() for item in existing):
            return
        self.memory.remember(content[:1000], "user", project, importance=0.55)

    def close(self) -> None:
        self.state.close()
        self.memory.close()

    def reset(self) -> None:
        self.state.reset()
        self.memory.db.conn.execute("DELETE FROM memories")
        self.memory.db.conn.commit()
        key_file = credential_file()
        if key_file.exists():
            key_file.unlink()
        if self.extra_state_path.exists():
            self.extra_state_path.unlink()
        with self._lock:
            self._sessions.clear()
            self._dswork_agents.clear()


class GUIRequestHandler(BaseHTTPRequestHandler):
    store: SessionStore
    static_dir: Path | None = None
    server_version = "NextAgentGUI/0.1"

    def log_message(self, format: str, *args) -> None:
        return

    def _send(self, status: int, payload: Any) -> None:
        body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "http://127.0.0.1:4173")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict[str, Any]:
        size = int(self.headers.get("Content-Length", "0"))
        if not size:
            return {}
        return json.loads(self.rfile.read(size).decode("utf-8"))

    def _send_file(self, path: Path) -> None:
        content = path.read_bytes()
        content_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_OPTIONS(self) -> None:
        self._send(HTTPStatus.NO_CONTENT, {})

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/health":
            self._send(HTTPStatus.OK, {
                "ok": True,
                "service": "next-agent-core",
                "version": "0.1.0",
                "provider_configured": self.store.provider_configured(),
            })
        elif path == "/api/preflight":
            self._send(HTTPStatus.OK, self.store.preflight())
        elif path == "/api/sessions":
            self._send(HTTPStatus.OK, {"sessions": self.store.list()})
        elif path == "/api/stats":
            self._send(HTTPStatus.OK, self.store.stats())
        elif path == "/api/state":
            self._send(HTTPStatus.OK, self.store.gui_state())
        elif path == "/api/memories":
            self._send(HTTPStatus.OK, {"memories": self.store.memory.list_all(limit=100), "stats": self.store.memory.stats()})
        elif path == "/api/skills":
            self._send(HTTPStatus.OK, {"skills": self.store.skills.list_skills(), "stats": self.store.skills.stats()})
        elif path == "/api/workspace":
            self._send(HTTPStatus.OK, {"workdir": self.store.default_workdir, "snapshot": build_snapshot(self.store.default_workdir)})
        elif self.static_dir:
            relative = path.lstrip("/") or "index.html"
            candidate = (self.static_dir / relative).resolve()
            if self.static_dir.resolve() in candidate.parents and candidate.is_file():
                self._send_file(candidate)
            else:
                self._send_file(self.static_dir / "index.html")
        else:
            self._send(HTTPStatus.NOT_FOUND, {"error": "Not found"})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            body = self._body()
            if path == "/api/sessions":
                session = self.store.create(body.get("title", "Untitled code session"), body.get("model"), body.get("workdir"))
                self._send(HTTPStatus.CREATED, {"session": session})
                return
            if path == "/api/config":
                self.store.save_api_key(str(body.get("api_key", "")))
                self._send(HTTPStatus.OK, {"ok": True, "provider_configured": True})
                return
            if path == "/api/chat":
                messages = body.get("messages", [])
                if messages:
                    self.store.remember_user_message(str(messages[-1].get("content", "")))
                result = self.store.chat(
                    messages, body.get("model"),
                    str(body.get("session_id") or "") or None,
                    effort=str(body.get("effort", "high")).lower(),
                    auto_model=body.get("auto_model", False),
                )
                self._send(HTTPStatus.OK, result)
                return
            if path == "/api/state":
                self._send(HTTPStatus.OK, self.store.save_gui_state(body))
                return
            if path == "/api/skills":
                name = str(body.get("name", "")).strip()
                description = str(body.get("description", "")).strip()
                content = str(body.get("content", "")).strip()
                trigger = str(body.get("trigger", "")).strip()
                if not name or not description or not content:
                    self._send(HTTPStatus.BAD_REQUEST, {"error": "Name, description, and instructions are required"})
                    return
                skill = self.store.skills.create_skill(name, description, content, trigger, created_by="user")
                self._send(HTTPStatus.CREATED, {"skill": skill.to_dict()})
                return
            if path == "/api/reset":
                self.store.reset()
                self._send(HTTPStatus.OK, {"ok": True})
                return

            parts = path.strip("/").split("/")
            if len(parts) == 4 and parts[0:2] == ["api", "sessions"] and parts[3] == "messages":
                message = str(body.get("message", "")).strip()
                if not message:
                    self._send(HTTPStatus.BAD_REQUEST, {"error": "Message is required"})
                    return
                record = self.store.get_record(parts[2])
                self.store.remember_user_message(message, record.get("workdir") if record else None)
                result = self.store.run_message(
                    parts[2],
                    message,
                    model=body.get("model"),
                    effort=str(body.get("effort", "high")).lower(),
                    auto_model=body.get("auto_model", False),
                )
                self._send(HTTPStatus.OK, result)
                return

            self._send(HTTPStatus.NOT_FOUND, {"error": "Not found"})
        except KeyError as exc:
            self._send(HTTPStatus.NOT_FOUND, {"error": str(exc)})
        except Exception as exc:
            self._send(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})


def create_server(
    host: str = "127.0.0.1",
    port: int = 8765,
    workdir: str | None = None,
    static_dir: str | Path | None = None,
) -> ThreadingHTTPServer:
    store = SessionStore(workdir or os.getcwd())
    handler = type(
        "BoundGUIRequestHandler",
        (GUIRequestHandler,),
        {"store": store, "static_dir": Path(static_dir).resolve() if static_dir else None},
    )
    return ThreadingHTTPServer((host, port), handler)


def main() -> None:
    parser = argparse.ArgumentParser(description="NextAgentGUI local API")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--workdir", default=os.getcwd())
    parser.add_argument("--static-dir")
    args = parser.parse_args()
    server = create_server(args.host, args.port, args.workdir, args.static_dir)
    print(f"NextAgentGUI API listening on http://{args.host}:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
