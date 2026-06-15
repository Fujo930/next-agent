"""Persistent GUI sessions, conversations, and usage accounting."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any


class GUIStateDB:
    """Small SQLite store used by the desktop GUI across restarts."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            self.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    mode TEXT NOT NULL,
                    title TEXT NOT NULL,
                    model TEXT NOT NULL,
                    workdir TEXT,
                    status TEXT NOT NULL,
                    conversation_json TEXT,
                    pinned INTEGER NOT NULL DEFAULT 0,
                    done INTEGER NOT NULL DEFAULT 0,
                    archived INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS usage_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT,
                    mode TEXT NOT NULL,
                    model TEXT NOT NULL,
                    prompt_tokens INTEGER NOT NULL DEFAULT 0,
                    completion_tokens INTEGER NOT NULL DEFAULT 0,
                    cache_hit_tokens INTEGER NOT NULL DEFAULT 0,
                    cache_miss_tokens INTEGER NOT NULL DEFAULT 0,
                    elapsed_ms REAL NOT NULL DEFAULT 0,
                    saved_cost REAL NOT NULL DEFAULT 0,
                    hit_rate REAL NOT NULL DEFAULT 0,
                    timestamp REAL NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_conversations_mode_updated
                ON conversations(mode, updated_at DESC);

                CREATE INDEX IF NOT EXISTS idx_usage_timestamp
                ON usage_events(timestamp);
                """
            )
            self.conn.commit()

    @staticmethod
    def _conversation(row: sqlite3.Row) -> dict[str, Any]:
        try:
            conversation = json.loads(row["conversation_json"]) if row["conversation_json"] else None
        except json.JSONDecodeError:
            conversation = None
        return {
            "id": row["id"],
            "mode": row["mode"],
            "title": row["title"],
            "model": row["model"],
            "workdir": row["workdir"],
            "status": row["status"],
            "conversation": conversation,
            "pinned": bool(row["pinned"]),
            "done": bool(row["done"]),
            "archived": bool(row["archived"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def upsert_conversation(self, item: dict[str, Any], mode: str) -> None:
        now = time.time()
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO conversations (
                    id, mode, title, model, workdir, status, conversation_json,
                    pinned, done, archived, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    mode=excluded.mode, title=excluded.title, model=excluded.model,
                    workdir=excluded.workdir, status=excluded.status,
                    conversation_json=excluded.conversation_json,
                    pinned=excluded.pinned, done=excluded.done,
                    archived=excluded.archived, updated_at=excluded.updated_at
                """,
                (
                    str(item["id"]),
                    mode,
                    str(item.get("title") or "Untitled"),
                    str(item.get("model") or "deepseek-v4-flash"),
                    item.get("workdir"),
                    str(item.get("status") or item.get("meta") or "idle"),
                    json.dumps(item.get("conversation"), ensure_ascii=False),
                    int(bool(item.get("pinned"))),
                    int(bool(item.get("done"))),
                    int(bool(item.get("archived"))),
                    float(item.get("created_at") or now),
                    float(item.get("updated_at") or now),
                ),
            )
            self.conn.commit()

    def replace_mode(self, mode: str, items: list[dict[str, Any]]) -> None:
        ids = {str(item["id"]) for item in items if item.get("id") is not None}
        with self._lock:
            rows = self.conn.execute(
                "SELECT id FROM conversations WHERE mode = ? AND archived = 0", (mode,)
            ).fetchall()
            for row in rows:
                if row["id"] not in ids:
                    self.conn.execute(
                        "UPDATE conversations SET archived = 1, updated_at = ? WHERE id = ?",
                        (time.time(), row["id"]),
                    )
            self.conn.commit()
        for item in items:
            self.upsert_conversation(item, mode)

    def list_conversations(self, mode: str | None = None, archived: bool = False) -> list[dict[str, Any]]:
        query = "SELECT * FROM conversations WHERE archived = ?"
        params: list[Any] = [int(archived)]
        if mode:
            query += " AND mode = ?"
            params.append(mode)
        query += " ORDER BY pinned DESC, updated_at DESC"
        with self._lock:
            rows = self.conn.execute(query, params).fetchall()
        return [self._conversation(row) for row in rows]

    def add_usage(
        self,
        session_id: str | None,
        mode: str,
        model: str,
        usage: dict[str, Any],
        elapsed_ms: float = 0,
    ) -> None:
        prompt = int(usage.get("prompt_tokens", 0) or 0)
        completion = int(usage.get("completion_tokens", 0) or 0)
        cache_hit = int(usage.get("cache_hit_tokens", 0) or 0)
        cache_miss = int(usage.get("cache_miss_tokens", 0) or 0)
        hit_rate = cache_hit / prompt if prompt else 0
        input_full = 2.19 / 1_000_000 if "pro" in model else 0.15 / 1_000_000
        input_cached = 0.14 / 1_000_000 if "pro" in model else 0.01 / 1_000_000
        saved = cache_hit * (input_full - input_cached)
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO usage_events (
                    session_id, mode, model, prompt_tokens, completion_tokens,
                    cache_hit_tokens, cache_miss_tokens, elapsed_ms, saved_cost,
                    hit_rate, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id, mode, model, prompt, completion, cache_hit, cache_miss,
                    float(elapsed_ms or 0), saved, hit_rate, time.time(),
                ),
            )
            self.conn.commit()

    def stats(self) -> dict[str, Any]:
        with self._lock:
            totals = self.conn.execute(
                """
                SELECT COUNT(*) AS rounds, COALESCE(SUM(prompt_tokens), 0) AS prompt,
                    COALESCE(SUM(completion_tokens), 0) AS completion,
                    COALESCE(SUM(cache_hit_tokens), 0) AS cache_hit,
                    COALESCE(SUM(cache_miss_tokens), 0) AS cache_miss,
                    COALESCE(SUM(saved_cost), 0) AS saved,
                    COALESCE(AVG(hit_rate), 0) AS avg_hit
                FROM usage_events
                """
            ).fetchone()
            rows = self.conn.execute(
                "SELECT * FROM usage_events ORDER BY timestamp DESC LIMIT 366"
            ).fetchall()
            models = self.conn.execute(
                "SELECT model, SUM(prompt_tokens + completion_tokens) AS tokens FROM usage_events GROUP BY model"
            ).fetchall()
            sessions = self.conn.execute(
                "SELECT COUNT(*) FROM conversations WHERE archived = 0"
            ).fetchone()[0]
            messages = self.conn.execute(
                "SELECT conversation_json FROM conversations WHERE archived = 0"
            ).fetchall()
        message_count = 0
        for row in messages:
            try:
                conversation = json.loads(row["conversation_json"]) if row["conversation_json"] else {}
                message_count += len(conversation.get("turns", []))
            except (json.JSONDecodeError, AttributeError):
                pass
        rounds = [
            {
                "turn": index + 1,
                "prompt_tokens": row["prompt_tokens"],
                "completion_tokens": row["completion_tokens"],
                "cache_hit_tokens": row["cache_hit_tokens"],
                "cache_miss_tokens": row["cache_miss_tokens"],
                "elapsed_ms": row["elapsed_ms"],
                "saved_cost": row["saved_cost"],
                "hit_rate": row["hit_rate"],
                "miss_cause": "",
                "timestamp": row["timestamp"],
            }
            for index, row in enumerate(reversed(rows))
        ]
        return {
            "sessions": sessions,
            "messages": message_count,
            "total_tokens": totals["prompt"] + totals["completion"],
            "prompt_tokens": totals["prompt"],
            "completion_tokens": totals["completion"],
            "cache_hit_tokens": totals["cache_hit"],
            "cache_miss_tokens": totals["cache_miss"],
            "saved_cost": totals["saved"],
            "avg_hit_rate": totals["avg_hit"],
            "models": [row["model"] for row in models],
            "model_usage": {row["model"]: row["tokens"] for row in models},
            "rounds": rounds,
        }

    def close(self) -> None:
        with self._lock:
            self.conn.close()

    def reset(self) -> None:
        with self._lock:
            self.conn.execute("DELETE FROM usage_events")
            self.conn.execute("DELETE FROM conversations")
            self.conn.commit()
