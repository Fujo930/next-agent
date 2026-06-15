"""Sub-agent orchestration with parallel execution.

Sub-agents run in separate LLM calls with isolated contexts and
a minimal toolset. Multiple sub-agents can run concurrently using
ThreadPoolExecutor.

Used for: code review (parallel review agents), multi-file analysis,
parallel investigation of different hypotheses.
"""

from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any

# Minimal toolset for sub-agents (no write/edit/bash_script for safety)
SUB_AGENT_TOOLS = ["read_file", "search_files", "list_dir", "bash", "git", "project_info"]

_subagent_count = 0
_lock = threading.Lock()


@dataclass
class SubAgentResult:
    """Result from a sub-agent invocation."""
    goal: str
    ok: bool
    output: str = ""
    error: str = ""
    tool_calls_made: int = 0
    model: str = ""


class SubAgentRunner:
    """Manages sub-agent lifecycle and parallel execution."""

    def __init__(self, llm_adapter, tool_registry, prefix_manager=None):
        self.llm = llm_adapter
        self.registry = tool_registry
        self.prefix = prefix_manager

    def run(self, goal: str, context: str = "", max_turns: int = 5) -> SubAgentResult:
        """Run a single sub-agent synchronously.

        Args:
            goal: What the sub-agent should accomplish
            context: Background information (file paths, errors, constraints)
            max_turns: Max tool-call rounds (conservative — sub-agents should be brief)
        """
        global _subagent_count
        with _lock:
            _subagent_count += 1
            agent_id = _subagent_count

        # Build system prompt
        system = (
            "You are a focused sub-agent. Complete this single task "
            "concisely. Do NOT edit files, run destructive commands, "
            "or spawn other agents. Return a clear result.\n\n"
        )

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": f"Goal: {goal}\n\nContext: {context}" if context else f"Goal: {goal}"},
        ]

        # Filter tools to sub-agent safe subset
        tools = self._get_sub_agent_tools()
        tool_count = 0

        for turn in range(max_turns):
            try:
                resp = self.llm.chat(
                    messages=messages,
                    tools=tools,
                    tool_choice="auto",
                    max_tokens=2000,  # sub-agents should be concise
                )
            except Exception as e:
                return SubAgentResult(
                    goal=goal, ok=False,
                    error=f"LLM call failed: {e}",
                    tool_calls_made=tool_count,
                )

            if resp.tool_calls:
                # Build assistant message
                tool_calls_msg = []
                for tc in resp.tool_calls:
                    tool_count += 1
                    tool_calls_msg.append({
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments, ensure_ascii=False, default=str),
                        },
                    })

                messages.append({
                    "role": "assistant",
                    "content": resp.content or "",
                    "tool_calls": tool_calls_msg,
                })

                # Execute tools
                for tc in resp.tool_calls:
                    # Safety: block writes and destructive ops in sub-agents
                    if tc.name in ("write_file", "edit_file", "bash_script"):
                        result = {"ok": False, "error": f"Tool '{tc.name}' not available in sub-agent"}
                    else:
                        try:
                            result = self.registry.dispatch(tc.name, tc.arguments)
                        except Exception as e:
                            result = {"ok": False, "error": str(e)}

                    # Truncate long results
                    output = result.get("output", "")
                    if isinstance(output, str) and len(output) > 3000:
                        result["output"] = output[:3000] + "... [truncated]"

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps(result, ensure_ascii=False, default=str),
                    })
            else:
                # Done — return the response
                return SubAgentResult(
                    goal=goal,
                    ok=True,
                    output=resp.content or "",
                    tool_calls_made=tool_count,
                    model=resp.model,
                )

        # Max turns reached
        return SubAgentResult(
            goal=goal,
            ok=True,
            output=f"[Sub-agent reached max {max_turns} turns] " + (resp.content or ""),
            tool_calls_made=tool_count,
        )

    def run_parallel(
        self, tasks: list[dict], max_workers: int = 4
    ) -> list[SubAgentResult]:
        """Run multiple sub-agents in parallel.

        Args:
            tasks: List of {"goal": str, "context": str} dicts
            max_workers: Max concurrent sub-agents

        Returns:
            List of results in the same order as tasks.
        """
        results: dict[int, SubAgentResult] = {}

        with ThreadPoolExecutor(max_workers=min(max_workers, len(tasks))) as executor:
            future_to_idx = {}
            for i, task in enumerate(tasks):
                future = executor.submit(
                    self.run,
                    task["goal"],
                    task.get("context", ""),
                    task.get("max_turns", 5),
                )
                future_to_idx[future] = i

            for future in as_completed(future_to_idx):
                idx = future_to_idx[future]
                try:
                    results[idx] = future.result()
                except Exception as e:
                    results[idx] = SubAgentResult(
                        goal=tasks[idx]["goal"],
                        ok=False,
                        error=f"Sub-agent failed: {e}",
                    )

        return [results[i] for i in sorted(results)]

    def _get_sub_agent_tools(self) -> list[dict]:
        """Get filtered tool schemas safe for sub-agents."""
        all_tools = self.registry.ALL_TOOL_SCHEMAS if hasattr(self.registry, "ALL_TOOL_SCHEMAS") else []
        return [
            t for t in all_tools
            if t.get("function", {}).get("name", "") in SUB_AGENT_TOOLS
        ]


# ── Global runner (set by agent.py at init) ──

_runner: SubAgentRunner | None = None


def set_runner(runner: SubAgentRunner) -> None:
    """Set the global sub-agent runner (called by Agent.__init__)."""
    global _runner
    _runner = runner


def spawn(goal: str, context: str = "") -> dict:
    """Spawn a sub-agent. Must call set_runner() first."""
    global _runner
    if _runner is None:
        return {"ok": False, "error": "Sub-agent runner not initialized"}

    result = _runner.run(goal, context)
    return {
        "ok": result.ok,
        "output": result.output if result.ok else result.error,
        "tool_calls_made": result.tool_calls_made,
    }


def spawn_parallel(tasks: list[dict]) -> list[dict]:
    """Spawn multiple sub-agents in parallel."""
    global _runner
    if _runner is None:
        return [{"ok": False, "error": "Sub-agent runner not initialized"}]

    results = _runner.run_parallel(tasks)
    return [
        {
            "ok": r.ok,
            "output": r.output if r.ok else r.error,
            "tool_calls_made": r.tool_calls_made,
        }
        for r in results
    ]
