"""Git operations with allow-listed subcommands."""

from __future__ import annotations

import subprocess


_ALLOWED = {
    "status", "log", "diff", "branch", "add", "commit", "stash",
    "push", "pull", "fetch", "merge", "checkout", "reset",
    "remote", "show", "rev-parse", "tag", "blame",
}

_ALLOW_MULTI_WORD = {
    "log --oneline", "log -p", "diff --stat", "diff --staged",
    "branch -a", "branch -r", "remote -v", "stash list",
    "stash pop", "status --short", "tag -l", "checkout -b",
    "reset --soft", "reset --hard", "add -A", "add .",
}


def _is_allowed(command: str) -> bool:
    """Check if a git command is in the allow list."""
    cmd = command.strip()
    if cmd in _ALLOW_MULTI_WORD:
        return True
    # Check first word
    first_word = cmd.split()[0] if cmd else ""
    return first_word in _ALLOWED


def run(command: str, extra_allowed: set[str] | None = None) -> dict:
    """Execute a git command (allow-listed)."""
    allowed = _ALLOWED | (extra_allowed or set())
    first_word = command.strip().split()[0] if command.strip() else ""

    if first_word not in allowed and command.strip() not in _ALLOW_MULTI_WORD:
        return {
            "ok": False,
            "error": f"Git command '{command}' not allowed. Allowed: {', '.join(sorted(allowed))}",
        }

    try:
        result = subprocess.run(
            f"git {command}",
            shell=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Git command timed out after 30s"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

    output = result.stdout + result.stderr
    return {"ok": True, "output": output.strip() or "(no output)", "exit_code": result.returncode}
