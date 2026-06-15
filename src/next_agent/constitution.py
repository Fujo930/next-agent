"""Constitution loader — reads and enforces agent behavior rules.

Inspired by CodeWhale's constitution.json. The constitution defines:
- authority: priority ordering when instructions conflict
- protected_invariants: rules the agent must never violate
- verification_policy: what the agent must verify before claiming done
- escalate_when: when to escalate to the user

The constitution is loaded from:
1. Project-local: <workdir>/next_agent/constitution.json
2. User-global: ~/.nextagent/constitution.json
3. Built-in default (this module)
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Constitution:
    """Agent behavior constitution."""
    authority: list[str] = field(default_factory=lambda: [
        "current user request",
        "live code and tests",
        "project constitution",
        "memory",
        "previous session context",
    ])
    protected_invariants: list[str] = field(default_factory=lambda: [
        "Keep the system prompt prefix byte-stable across turns (DeepSeek cache).",
        "Verify edits by reading files back before claiming success.",
        "Never modify the constitution.",
    ])
    verification_policy: list[str] = field(default_factory=lambda: [
        "Read changed files back to confirm the edit landed as intended.",
        "Run syntax checks after editing code files.",
        "Never claim verification you did not perform.",
    ])
    escalate_when: list[str] = field(default_factory=lambda: [
        "An action is destructive or hard to reverse.",
        "Deleting or overwriting files you did not create.",
        "Changing provider, auth, or configuration.",
    ])

    @classmethod
    def load(cls, workdir: str = ".") -> "Constitution":
        """Load constitution from the most specific source available."""
        constitution = cls()

        # 1. Try project-local
        local_path = Path(workdir) / "next_agent" / "constitution.json"
        if local_path.exists():
            return cls._merge(constitution, cls._read(local_path))

        # 2. Try user-global
        global_path = Path.home() / ".nextagent" / "constitution.json"
        if global_path.exists():
            return cls._merge(constitution, cls._read(global_path))

        return constitution

    @staticmethod
    def _read(path: Path) -> dict:
        """Read and parse a constitution file."""
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    @classmethod
    def _merge(cls, base: "Constitution", overrides: dict) -> "Constitution":
        """Merge overrides into the base constitution."""
        for key in ("authority", "protected_invariants", "verification_policy", "escalate_when"):
            if key in overrides:
                setattr(base, key, overrides[key])
        return base

    def to_prompt_extension(self) -> str:
        """Convert to a prompt extension for the system message."""
        lines = ["\n## Agent Constitution"]

        if self.authority:
            lines.append("\n### Authority (priority order)")
            for i, item in enumerate(self.authority, 1):
                lines.append(f"{i}. {item}")

        if self.protected_invariants:
            lines.append("\n### Protected Invariants (NEVER violate)")
            for item in self.protected_invariants:
                lines.append(f"- {item}")

        if self.verification_policy:
            lines.append("\n### Verification Policy")
            for item in self.verification_policy:
                lines.append(f"- {item}")

        if self.escalate_when:
            lines.append("\n### Escalate When")
            for item in self.escalate_when:
                lines.append(f"- {item}")

        return "\n".join(lines)
