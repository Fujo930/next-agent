"""Goal Manager — persistent cross-turn goals.

Inspired by Hermes /goal system. Goals persist across turns and
are automatically injected into the system prompt each round.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class AgentGoal:
    """A persistent goal that the agent works toward across turns."""
    text: str
    status: str = "active"  # active | paused | completed
    progress: str = ""
    created_at: float = field(default_factory=time.time)
    tokens_used: int = 0
    time_spent: float = 0.0


class GoalManager:
    """Manages cross-turn goals."""

    def __init__(self):
        self._goal: AgentGoal | None = None
        self._completed_goals: list[AgentGoal] = []

    def set(self, goal_text: str) -> AgentGoal:
        """Set a new goal. Replaces any existing active goal."""
        if self._goal and self._goal.status == "active":
            self._goal.status = "paused"
            self._completed_goals.append(self._goal)

        self._goal = AgentGoal(text=goal_text)
        return self._goal

    def update_progress(self, detail: str, tokens: int = 0, time_s: float = 0.0) -> None:
        """Called by agent loop each turn when goal is active."""
        if not self._goal or self._goal.status != "active":
            return
        self._goal.progress = detail
        self._goal.tokens_used += tokens
        self._goal.time_spent += time_s

    def complete(self) -> None:
        """Mark the current goal as completed."""
        if self._goal:
            self._goal.status = "completed"
            self._completed_goals.append(self._goal)
            self._goal = None

    def pause(self) -> None:
        """Pause the current goal."""
        if self._goal:
            self._goal.status = "paused"

    def resume(self) -> None:
        """Resume a paused goal."""
        if self._goal and self._goal.status == "paused":
            self._goal.status = "active"

    @property
    def current(self) -> AgentGoal | None:
        return self._goal

    @property
    def is_active(self) -> bool:
        return self._goal is not None and self._goal.status == "active"

    def to_prompt(self) -> str:
        """Generate prompt extension for the system context."""
        if not self._goal:
            return ""

        if self._goal.status != "active":
            return ""

        lines = [
            "## Active Goal",
            f"Goal: {self._goal.text}",
        ]
        if self._goal.progress:
            lines.append(f"Progress: {self._goal.progress}")
        if self._goal.tokens_used or self._goal.time_spent:
            lines.append(
                f"Spent: {self._goal.tokens_used:,} tokens, "
                f"{self._goal.time_spent:.0f}s"
            )
        lines.append(
            "Continue working on this goal. Do not switch to unrelated tasks "
            "until the goal is complete."
        )
        return "\n".join(lines)

    def get_state(self) -> dict:
        """Return serializable state for the GUI."""
        if not self._goal:
            return {"status": "no_goal"}
        return {
            "text": self._goal.text,
            "status": self._goal.status,
            "progress": self._goal.progress,
            "tokens_used": self._goal.tokens_used,
            "time_spent": self._goal.time_spent,
        }
