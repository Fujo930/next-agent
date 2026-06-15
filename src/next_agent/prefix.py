"""Byte-stable prefix manager — the heart of DeepSeek cost optimization.

DeepSeek's automatic prefix caching means the system prompt (tool definitions
+ project context + memory) must stay byte-identical across turns. Any change,
even one byte, invalidates the cache and costs 100% of prefix tokens.

This module:
1. Builds the frozen prefix once per session
2. Ensures it never changes mid-session
3. Composes turn messages by appending to the frozen prefix
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field


@dataclass
class PrefixManager:
    """Manages the byte-stable system prompt prefix."""

    system_prompt: str = ""
    tool_schemas: list[dict] = field(default_factory=list)
    project_context: str = ""
    memory: str = ""

    # Internal state
    _prefix_hash: str = ""
    _is_frozen: bool = False
    _build_count: int = 0

    def build(
        self,
        system_prompt: str,
        tool_schemas: list[dict],
        project_context: str = "",
        memory: str = "",
    ) -> str:
        """Build the prefix. Must be called ONCE per session.

        After this call, the prefix is frozen — any subsequent build() calls
        are ignored (the cache must stay stable).
        """
        if self._is_frozen:
            return self._assembled

        self.system_prompt = system_prompt
        self.tool_schemas = tool_schemas
        self.project_context = project_context
        self.memory = memory
        self._build_count += 1
        self._is_frozen = True

        # Assemble the prefix
        self._assembled = self._assemble()
        self._prefix_hash = hashlib.sha256(
            self._assembled.encode()
        ).hexdigest()[:16]
        
        return self._assembled

    def compose(self, user_messages: list[dict]) -> list[dict]:
        """Compose full message list: frozen prefix + new user/tool messages.

        The prefix (system message with tools) stays at the front.
        User and tool messages are appended after it.

        Args:
            user_messages: The conversation messages to append AFTER the prefix.
                          Should NOT include the system prompt or tool definitions.

        Returns:
            Complete message list for the API call.
        """
        if not self._is_frozen:
            raise RuntimeError(
                "Prefix not built yet. Call prefix.build() before compose()."
            )

        return [self._system_message] + user_messages

    @property
    def prefix_hash(self) -> str:
        """Get the hash of the frozen prefix (for cache miss detection)."""
        return self._prefix_hash

    @property
    def is_frozen(self) -> bool:
        """Whether the prefix has been built and frozen."""
        return self._is_frozen

    @property
    def estimated_tokens(self) -> int:
        """Rough token count of the prefix (for context budget tracking)."""
        if not self._assembled:
            return 0
        # Rough: 1 token ≈ 4 chars for English
        return len(self._assembled) // 4

    def _assemble(self) -> str:
        """Assemble the complete system prompt prefix."""
        parts = [self.system_prompt]

        if self.project_context:
            parts.append(f"\n\n## Project Context\n{self.project_context}")

        if self.memory:
            parts.append(f"\n\n## Memory\n{self.memory}")

        return "\n".join(parts)

    @property
    def _system_message(self) -> dict:
        """The single system message with prefix + tool definitions."""
        if not self._is_frozen:
            raise RuntimeError("Prefix not built yet.")

        # Tool definitions are passed separately to the API,
        # NOT embedded in the system message.
        return {
            "role": "system",
            "content": self._assembled,
        }

    def get_tool_schemas(self) -> list[dict]:
        """Get the frozen tool schemas for API calls."""
        return self.tool_schemas
