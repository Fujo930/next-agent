"""Cross-session memory manager.

MemoryManager wraps MemoryDB with high-level operations:
- remember(): save a memory
- load_for_session(): query FTS5 + type filters, return prompt extension
- search(): full-text search
- Auto-save patterns (detect lessons from repeated errors)

Loaded at session start only (in _build_prefix) — never changes mid-session,
preserving the DeepSeek prefix cache.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .memory_db import MemoryDB, Memory


# ── Memory types ──────────────────────────────────────────────

MEMORY_TYPES = {
    "user":        "User profile / identity / name / preferences",
    "project":     "Project-specific knowledge (tools, structure, conventions)",
    "preference":  "User preferences (UI, language, style)",
    "lesson":      "Lessons learned (bugs, fixes, patterns)",
    "convention":  "Code conventions, commit style, naming",
    "env":         "Environment details (OS, Python version, quirks)",
}

VALID_TYPES = set(MEMORY_TYPES.keys())


# ── Prompt extension template ─────────────────────────────────

MEMORY_PROMPT_TEMPLATE = """## Agent Memory (Cross-Session)

The following memories persist across sessions. Use them to avoid repeating past mistakes and to respect user preferences.

{entries}

---

*Memories are automatically saved when the agent discovers patterns or the user corrects behavior.*"""


# ── MemoryManager ─────────────────────────────────────────────

class MemoryManager:
    """Cross-session memory manager for Next Agent.

    Usage:
        m = MemoryManager()
        m.remember("User prefers Chinese responses", "preference")
        results = m.search("Chinese")
        prompt_ext = m.load_for_session(project="myproject", user_input="fix the bug")
    """

    def __init__(self, db_path: str | Path | None = None):
        self.db = MemoryDB(db_path)

    # ── Core operations ─────────────────────────────────────

    def remember(
        self,
        content: str,
        mem_type: str = "lesson",
        project: str | None = None,
        importance: float = 0.5,
    ) -> int:
        """Save a new memory. Returns the memory id.

        Args:
            content: The memory text.
            mem_type: One of: user, project, preference, lesson, convention, env.
            project: Optional project name/identifier. None = global.
            importance: 0.0 - 1.0, higher = more important.

        Raises:
            ValueError: if mem_type is invalid.
        """
        if mem_type not in VALID_TYPES:
            raise ValueError(
                f"Invalid memory type '{mem_type}'. "
                f"Valid types: {', '.join(sorted(VALID_TYPES))}"
            )
        return self.db.insert(content, mem_type, project, importance)

    def search(
        self,
        query: str,
        mem_type: str | None = None,
        project: str | None = None,
        limit: int = 10,
    ) -> list[dict]:
        """Full-text search across memories.

        Args:
            query: Text to search for (FTS5).
            mem_type: Optional filter by memory type.
            project: Optional filter by project.
            limit: Max results.

        Returns:
            List of memory dicts.
        """
        results = self.db.search_fts(query, mem_type, project, limit)
        return [m.to_dict() for m in results]

    def load_for_session(
        self,
        project: str | None = None,
        user_input: str = "",
    ) -> str:
        """Load relevant memories as a prompt extension for this session.

        Called ONCE at session start. The result is frozen into the prefix.

        Strategy:
        1. Global memories (user profile, preferences) — top 5 by importance
        2. Project-specific memories — top 5 by importance
        3. Memories matching user_input via FTS5 — top 5

        Returns:
            A markdown string to inject into the system prompt, or "" if no memories.
        """
        all_memories: list[Memory] = []

        # 1. Global memories (no project filter, high importance)
        global_mems = self.db.search_by_type(
            mem_type=None, project=None, limit=5
        )
        all_memories.extend(global_mems)

        # 2. Project-specific memories
        if project:
            proj_mems = self.db.search_by_type(
                mem_type=None, project=project, limit=5
            )
            # Avoid duplicates already from global
            global_ids = {m.id for m in all_memories}
            for m in proj_mems:
                if m.id not in global_ids:
                    all_memories.append(m)

        # 3. FTS5 match against user_input
        if user_input:
            fts_mems = self.db.search_fts(
                query=user_input, mem_type=None, project=project, limit=5
            )
            existing_ids = {m.id for m in all_memories}
            for m in fts_mems:
                if m.id not in existing_ids:
                    all_memories.append(m)

        if not all_memories:
            return ""

        # Sort by importance * log(access_count + 1) descendant
        import math
        all_memories.sort(
            key=lambda m: m.importance * math.log(m.access_count + 1 + m.importance),
            reverse=True,
        )

        # Take top 10
        all_memories = all_memories[:10]

        # Touch accessed memories
        for m in all_memories:
            self.db.touch(m.id)

        # Format entries
        entries = []
        for m in all_memories:
            entries.append(f"- [{m.type}] {m.content}")

        return MEMORY_PROMPT_TEMPLATE.format(entries="\n".join(entries))

    # ── Auto-save helpers ───────────────────────────────────

    def auto_save_lesson(
        self,
        lesson: str,
        project: str | None = None,
    ) -> int:
        """Auto-save a lesson learned. Called when agent discovers patterns.

        Checks for duplicates before saving (case-insensitive content match).
        """
        # Check for near-duplicates
        existing = self.db.search_by_type("lesson", project, limit=100)
        for mem in existing:
            if lesson.strip().lower() in mem.content.lower():
                # Already saved — bump importance and return
                self.db.touch(mem.id)
                self.db.update_importance(mem.id, min(1.0, mem.importance + 0.1))
                return mem.id

        return self.db.insert(lesson, "lesson", project, importance=0.7)

    def auto_save_env(
        self,
        detail: str,
        project: str | None = None,
    ) -> int:
        """Save an environment quirk discovered during execution."""
        return self.db.insert(detail, "env", project, importance=0.8)

    # ── Management ──────────────────────────────────────────

    def delete(self, memory_id: int) -> bool:
        """Delete a memory by id."""
        return self.db.delete(memory_id)

    def list_all(self, mem_type: str | None = None, limit: int = 50) -> list[dict]:
        """List all memories, optionally filtered by type."""
        results = self.db.search_by_type(mem_type, project=None, limit=limit)
        # Also get project-scoped ones
        if not mem_type:
            results += self.db.search_by_type(None, project=None, limit=limit)
        # Dedup
        seen = set()
        unique = []
        for m in results:
            if m.id not in seen:
                seen.add(m.id)
                unique.append(m)
        return [m.to_dict() for m in unique[:limit]]

    def stats(self) -> dict:
        """Get memory statistics."""
        c = self.db.conn
        total = self.db.count()
        by_type = {}
        rows = c.execute(
            "SELECT type, COUNT(*) as cnt FROM memories GROUP BY type"
        ).fetchall()
        for row in rows:
            by_type[row["type"]] = row["cnt"]

        return {
            "total": total,
            "by_type": by_type,
        }

    def close(self) -> None:
        """Close the database."""
        self.db.close()
