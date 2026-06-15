"""Shell execution with safety filtering."""

from __future__ import annotations

import subprocess
import re

# Blocked patterns (destructive commands)
_BLOCKED = [
    (r"rm\s+-rf\s+/", "rm -rf / (destructive)"),
    (r"mkfs\.", "mkfs (format filesystem)"),
    (r">\s*/dev/sd", "overwrite block device"),
    (r"dd\s+if=.*of=/dev", "dd raw device write"),
    (r"curl.*\|.*sh", "curl pipe shell (potential RCE)"),
    (r"wget.*-O-.*\|.*sh", "wget pipe shell"),
]


def bash(command: str, timeout: int = 60, workdir: str | None = None) -> dict:
    """Execute a shell command with safety checks.

    Returns {"ok": True, "output": "combined stdout+stderr", "exit_code": int}
    """
    # Safety check
    for pattern, reason in _BLOCKED:
        if re.search(pattern, command):
            return {"ok": False, "error": f"BLOCKED: {reason}"}

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=workdir,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"Command timed out after {timeout}s"}
    except FileNotFoundError as e:
        return {"ok": False, "error": f"Command not found: {e}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

    output = result.stdout
    if result.stderr:
        output += "\n[stderr]\n" + result.stderr

    return {"ok": True, "output": output.strip() or "(no output)", "exit_code": result.returncode}


def bash_script(script: str, timeout: int = 120) -> dict:
    """Execute a multi-line shell script."""
    return bash(script, timeout=timeout)
