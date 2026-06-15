"""Slash command system — inspired by Claude Code's .claude/commands/.

Commands are markdown files in next_agent/commands/<name>.md with
YAML frontmatter:

    ---
    allowed-tools: read_file, search_files, bash(git:*)
    description: Review a pull request
    ---

Features:
- allowed-tools: restricts which tools the command can use
- !`shell`: injects shell output into the prompt at load time
- Multi-tool enforcement: "MUST do all in a single message"
"""

from __future__ import annotations

import re
import os
import subprocess
from pathlib import Path


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Parse YAML frontmatter from markdown.

    Returns (frontmatter_dict, body_text).
    """
    # Match ---\n...\n---
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    if not match:
        return {}, text

    frontmatter_text = match.group(1)
    body = text[match.end():]

    # Simple YAML parser (avoid pyyaml dependency; just key: value)
    fm = {}
    for line in frontmatter_text.splitlines():
        line = line.strip()
        if ":" in line:
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip()
            fm[key] = value

    return fm, body


def _expand_shell_injections(body: str, workdir: str = ".") -> str:
    """Expand !`command` shell injections in the prompt body.

    Each !`cmd` is executed and its output replaces the placeholder.
    """
    pattern = re.compile(r"!`([^`]+)`")

    def _replace(match: re.Match) -> str:
        cmd = match.group(1)
        try:
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True,
                timeout=10, cwd=workdir,
            )
            output = (result.stdout + result.stderr).strip()
            if not output:
                output = "(no output)"
            return output
        except subprocess.TimeoutExpired:
            return f"(timeout: {cmd})"
        except Exception as e:
            return f"(error: {e})"

    return pattern.sub(_replace, body)


class CommandManager:
    """Manages slash commands for the agent."""

    def __init__(self, commands_dir: str | None = None):
        if commands_dir is None:
            # Search paths
            candidates = [
                Path(os.environ["NEXT_BUNDLED_COMMANDS"]) if os.environ.get("NEXT_BUNDLED_COMMANDS") else None,
                Path.cwd() / "next_agent" / "commands",
                Path.home() / ".nextagent" / "commands",
            ]
            for c in candidates:
                if c and c.exists() and c.is_dir():
                    commands_dir = str(c)
                    break

        self.commands_dir = Path(commands_dir) if commands_dir else None
        self._commands: dict[str, dict] = {}

    def load(self) -> list[str]:
        """Load all commands from the commands directory.

        Returns list of command names.
        """
        if not self.commands_dir or not self.commands_dir.exists():
            return []

        self._commands.clear()
        for fp in sorted(self.commands_dir.glob("*.md")):
            name = fp.stem
            try:
                text = fp.read_text(encoding="utf-8")
                fm, body = _parse_frontmatter(text)
                self._commands[name] = {
                    "name": name,
                    "description": fm.get("description", ""),
                    "allowed_tools": fm.get("allowed-tools", ""),
                    "body": body,
                    "source": str(fp),
                }
            except Exception:
                continue

        return list(self._commands.keys())

    def get(self, name: str) -> dict | None:
        """Get a command by name."""
        return self._commands.get(name)

    def resolve(self, input_text: str) -> tuple[dict | None, str]:
        """Check if input is a slash command, and if so resolve it.

        Returns (command_dict, processed_prompt) or (None, original_input).
        """
        if not input_text.startswith("/"):
            return None, input_text

        # Extract command name (everything after / until space or end)
        parts = input_text[1:].split(maxsplit=1)
        cmd_name = parts[0]
        extra_args = parts[1] if len(parts) > 1 else ""

        cmd = self.get(cmd_name)
        if not cmd:
            return None, input_text

        # Build the full prompt
        body = cmd["body"]

        # Expand shell injections
        body = _expand_shell_injections(body)

        # Append user args if any
        if extra_args:
            body = f"{body}\n\n## Additional context\n{extra_args}"

        return cmd, body

    def list_commands(self) -> list[str]:
        """List available commands with descriptions."""
        result = []
        for name, cmd in sorted(self._commands.items()):
            desc = cmd.get("description", "")
            result.append(f"  /{name}  — {desc}" if desc else f"  /{name}")

        return result
