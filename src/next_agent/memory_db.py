"""SQLite + FTS5 memory engine for cross-session persistent memory.

Stores typed memories with full-text search.
Database is created on first use at ~/.nextagent/memory.db.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional


# ── Memory data model ─────────────────────────────────────────

@dataclass
class Memory:
    """A single persistent memory entry."""
    id: int
    type: str           # user, project, preference, lesson, convention, env
    content: str
    project: str | None = None  # None = global
    created_at: float = 0.0
    last_accessed: float = 0.0
    access_count: int = 0
    importance: float = 0.5

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type,
            "content": self.content,
            "project": self.project,
            "created_at": self.created_at,
            "last_accessed": self.last_accessed,
            "access_count": self.access_count,
            "importance": self.importance,
        }


# ── Database engine ───────────────────────────────────────────

class MemoryDB:
    """SQLite + FTS5 engine for the cross-session memory system.

    Creates/opens the database at ~/.nextagent/memory.db on first use.
    """

    def __init__(self, db_path: str | Path | None = None):
        if db_path is None:
            db_path = Path.home() / ".nextagent" / "memory.db"
        self.db_path = Path(db_path)
        self._conn: sqlite3.Connection | None = None

    @property
    def conn(self) -> sqlite3.Connection:
        """Lazy-initialize the database connection."""
        if self._conn is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._init_schema()
        return self._conn

    def _init_schema(self) -> None:
        """Create tables and FTS5 index if they don't exist."""
        c = self.conn

        c.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT NOT NULL,
                content TEXT NOT NULL,
                project TEXT,
                created_at REAL NOT NULL,
                last_accessed REAL NOT NULL,
                access_count INTEGER DEFAULT 0,
                importance REAL DEFAULT 0.5
            )
        """)

        # FTS5 virtual table for full-text search
        c.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
                content,
                type,
                project,
                content='memories',
                content_rowid='id'
            )
        """)

        # Triggers to keep FTS in sync
        c.execute("""
            CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
                INSERT INTO memories_fts(rowid, content, type, project)
                VALUES (new.id, new.content, new.type, new.project);
            END
        """)

        c.execute("""
            CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
                INSERT INTO memories_fts(memories_fts, rowid, content, type, project)
                VALUES ('delete', old.id, old.content, old.type, old.project);
            END
        """)

        c.execute("""
            CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
                INSERT INTO memories_fts(memories_fts, rowid, content, type, project)
                VALUES ('delete', old.id, old.content, old.type, old.project);
                INSERT INTO memories_fts(rowid, content, type, project)
                VALUES (new.id, new.content, new.type, new.project);
            END
        """)

        # Index on type + project for fast filtered queries
        c.execute("""
            CREATE INDEX IF NOT EXISTS idx_memories_type_project
            ON memories(type, project)
        """)

        self._conn.commit()

    # ── Public API ──────────────────────────────────────────

    def insert(
        self,
        content: str,
        mem_type: str,
        project: str | None = None,
        importance: float = 0.5,
    ) -> int:
        """Insert a new memory. Returns the row id."""
        now = time.time()
        c = self.conn
        cur = c.execute(
            """INSERT INTO memories (type, content, project, created_at, last_accessed, access_count, importance)
               VALUES (?, ?, ?, ?, ?, 0, ?)""",
            (mem_type, content, project, now, now, importance),
        )
        self._conn.commit()
        return cur.lastrowid

    def search_fts(
        self,
        query: str,
        mem_type: str | None = None,
        project: str | None = None,
        limit: int = 10,
    ) -> list[Memory]:
        """Full-text search over memories with optional type/project filters.

        Uses FTS5 for text matching, then joins to main table for metadata.
        """
        c = self.conn

        # Build FTS5 query - sanitize to avoid syntax errors
        clean_query = query.replace('"', '').replace("'", "")
        where_clauses = [f"memories_fts MATCH '{clean_query}'"]
        params: list = []

        if mem_type:
            where_clauses.append("memories_fts.type = ?")
            params.append(mem_type)
        if project:
            where_clauses.append("memories_fts.project = ?")
            params.append(project)

        where = " AND ".join(where_clauses)

        try:
            rows = c.execute(
                f"""SELECT m.* FROM memories m
                    JOIN memories_fts fts ON m.id = fts.rowid
                    WHERE {where}
                    ORDER BY rank
                    LIMIT ?""",
                (*params, limit),
            ).fetchall()
        except sqlite3.OperationalError:
            # FTS5 match might fail on weird queries
            return []

        return [self._row_to_memory(row) for row in rows]

    def search_by_type(
        self,
        mem_type: str | None = None,
        project: str | None = None,
        limit: int = 20,
    ) -> list[Memory]:
        """Query memories by type and/or project (no text search)."""
        c = self.conn
        conditions = []
        params = []

        if mem_type:
            conditions.append("type = ?")
            params.append(mem_type)
        if project:
            conditions.append("project = ?")
            params.append(project)
        elif project is None:
            # When project is explicitly None, get global memories only
            conditions.append("project IS NULL")

        where = " AND ".join(conditions) if conditions else "1=1"

        rows = c.execute(
            f"""SELECT * FROM memories
                WHERE {where}
                ORDER BY importance * (access_count + 1) DESC, last_accessed DESC
                LIMIT ?""",
            (*params, limit),
        ).fetchall()

        return [self._row_to_memory(row) for row in rows]

    def touch(self, memory_id: int) -> None:
        """Update last_accessed and increment access_count."""
        now = time.time()
        self.conn.execute(
            "UPDATE memories SET last_accessed = ?, access_count = access_count + 1 WHERE id = ?",
            (now, memory_id),
        )
        self._conn.commit()

    def delete(self, memory_id: int) -> bool:
        """Delete a memory by id. Returns True if deleted."""
        c = self.conn
        cur = c.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        self._conn.commit()
        return cur.rowcount > 0

    def update_importance(self, memory_id: int, new_importance: float) -> None:
        """Update the importance score of a memory."""
        self.conn.execute(
            "UPDATE memories SET importance = ? WHERE id = ?",
            (new_importance, memory_id),
        )
        self._conn.commit()

    def count(self) -> int:
        """Total number of memories stored."""
        return self.conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

    # ── Internal helpers ────────────────────────────────────

    def _row_to_memory(self, row: sqlite3.Row) -> Memory:
        return Memory(
            id=row["id"],
            type=row["type"],
            content=row["content"],
            project=row["project"],
            created_at=row["created_at"],
            last_accessed=row["last_accessed"],
            access_count=row["access_count"],
            importance=row["importance"],
        )
