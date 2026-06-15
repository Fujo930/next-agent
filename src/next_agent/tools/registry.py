"""Unified tool registry — schema definitions + dispatch.

Tools are defined in two parts:
- TOOLS: list of OpenAI-compatible function schemas (sent to LLM)
- TOOL_MAP: dict of name → callable (dispatched at runtime)

DeepSeek optimization: keep tools ≤ 40 total. Each schema is kept flat
(no nested objects in parameters.properties) for better function calling.
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable

from . import files, shell, git, web, patch as patcher, subagent, mcp
from .patch import DeterministicPatcher


# ── Schema definitions ───────────────────────────────────────

def _make_tool(name: str, description: str, properties: dict, required: list[str] | None = None) -> dict:
    """Build an OpenAI-compatible tool schema."""
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required or [],
            },
        },
    }


# File tools
TOOL_READ_FILE = _make_tool(
    "read_file",
    "Read a text file with line numbers. Use this instead of shell 'cat'. Returns content with 1-indexed line numbers.",
    {
        "path": {"type": "string", "description": "File path (absolute or relative to workspace)"},
        "offset": {"type": "integer", "description": "Line number to start from (1-indexed, default 1)"},
        "limit": {"type": "integer", "description": "Max lines to return (default 500, max 2000)"},
    },
    ["path"],
)

TOOL_WRITE_FILE = _make_tool(
    "write_file",
    "Write content to a file, completely replacing existing content. Creates parent directories automatically.",
    {
        "path": {"type": "string", "description": "File path to write"},
        "content": {"type": "string", "description": "Complete file content"},
    },
    ["path", "content"],
)

TOOL_EDIT_FILE = _make_tool(
    "edit_file",
    "Targeted find-and-replace edit. Provide old_string and new_string. Old_string must be UNIQUE in the file — include 2-3 lines of surrounding context to ensure uniqueness.",
    {
        "path": {"type": "string", "description": "File path to edit"},
        "old_string": {"type": "string", "description": "Exact text to find and replace (must be unique in file)"},
        "new_string": {"type": "string", "description": "Replacement text"},
    },
    ["path", "old_string", "new_string"],
)

TOOL_LIST_DIR = _make_tool(
    "list_dir",
    "List files and directories. [F] = file, [D] = directory. Sorted by modification time.",
    {
        "path": {"type": "string", "description": "Directory to list (default: workspace root)"},
    },
)

TOOL_SEARCH_FILES = _make_tool(
    "search_files",
    "Search file contents with regex patterns. Use this instead of shell grep/rg.",
    {
        "pattern": {"type": "string", "description": "Regex pattern to search for"},
        "path": {"type": "string", "description": "Directory or file to search in (default: workspace root)"},
        "file_glob": {"type": "string", "description": "Filter by file pattern (e.g., '*.py')"},
    },
    ["pattern"],
)

# Shell tools
TOOL_BASH = _make_tool(
    "bash",
    "Execute a shell command and return stdout/stderr/exit_code. For complex operations, use bash_script.",
    {
        "command": {"type": "string", "description": "Shell command to execute"},
        "timeout": {"type": "integer", "description": "Max execution time in seconds (default: 60)"},
        "workdir": {"type": "string", "description": "Working directory (default: workspace root)"},
    },
    ["command"],
)

TOOL_BASH_SCRIPT = _make_tool(
    "bash_script",
    "Execute a multi-line shell script. Useful for complex sequences.",
    {
        "script": {"type": "string", "description": "Multi-line shell script"},
        "timeout": {"type": "integer", "description": "Max execution time in seconds (default: 120)"},
    },
    ["script"],
)

# Git tools
TOOL_GIT = _make_tool(
    "git",
    "Execute a git command. Allowed: status, log, diff, branch, add, commit, stash, push, pull, fetch, merge, checkout, reset. Returns output.",
    {
        "command": {"type": "string", "description": "Git command (e.g., 'status', 'log --oneline -5', 'diff')"},
    },
    ["command"],
)

# Web tools
TOOL_WEB_SEARCH = _make_tool(
    "web_search",
    "Search the web. Returns titles, URLs, and descriptions.",
    {
        "query": {"type": "string", "description": "Search query"},
        "limit": {"type": "integer", "description": "Max results (default 5)"},
    },
    ["query"],
)

TOOL_WEB_FETCH = _make_tool(
    "web_fetch",
    "Fetch content from a URL. Returns markdown text. Use for documentation, API references, etc.",
    {
        "url": {"type": "string", "description": "URL to fetch"},
    },
    ["url"],
)

# Sub-agent tools
TOOL_SPAWN_AGENT = _make_tool(
    "spawn_agent",
    "Spawn a parallel sub-agent to work on an independent task. Returns the sub-agent's result. Use for parallel code review, multi-file analysis, etc.",
    {
        "goal": {"type": "string", "description": "What the sub-agent should accomplish"},
        "context": {"type": "string", "description": "Background info: file paths, errors, constraints"},
    },
    ["goal"],
)

TOOL_THINK = _make_tool(
    "think",
    "Write down your step-by-step reasoning, analysis, and plan BEFORE taking complex actions (file edits, shell execution, git, multi-step operations). Use this to think through problems. The thought is recorded internally. Simple reads (read_file, list_dir) usually don't need this.",
    {
        "thought": {"type": "string", "description": "Your complete reasoning: current state, analysis, plan, expected outcome"},
    },
    ["thought"],
)

TOOL_PROJECT_INFO = _make_tool(
    "project_info",
    "Get project overview: file count, directory count, language breakdown.",
    {},
)

TOOL_WEB_EXTRACT = _make_tool(
    "web_extract",
    "Extract and parse content from web pages as clean markdown. Use for documentation, API references, blog posts, etc.",
    {
        "urls": {"type": "string", "description": "Comma-separated list of URLs to extract (max 5)"},
    },
    ["urls"],
)

# ── All tools ordered by category ────────────────────────────

ALL_TOOL_SCHEMAS = [
    TOOL_READ_FILE,
    TOOL_WRITE_FILE,
    TOOL_EDIT_FILE,
    TOOL_LIST_DIR,
    TOOL_SEARCH_FILES,
    TOOL_BASH,
    TOOL_BASH_SCRIPT,
    TOOL_GIT,
    TOOL_WEB_SEARCH,
    TOOL_WEB_FETCH,
    TOOL_WEB_EXTRACT,
    TOOL_SPAWN_AGENT,
    TOOL_THINK,
    TOOL_PROJECT_INFO,
]


# ── Tool dispatch ─────────────────────────────────────────────

# Shared patcher instance (one per session for caching)
_patcher: DeterministicPatcher | None = None


def _get_patcher() -> DeterministicPatcher:
    global _patcher
    if _patcher is None:
        _patcher = DeterministicPatcher()
    return _patcher


# Safety: blocked shell patterns
_BLOCKED_PATTERNS = [
    (r"rm\s+-rf\s+/", "rm -rf / (destructive)"),
    (r"mkfs\.", "mkfs (format filesystem)"),
    (r">\s*/dev/", "overwrite /dev/ device"),
    (r"dd\s+if=", "dd (raw device write)"),
    (r"chmod\s+777", "chmod 777 (insecure permissions)"),
    (r"curl.*\|.*sh", "curl pipe shell (potential RCE)"),
]

# Allowed git subcommands
_GIT_ALLOWED = {
    "status", "log", "diff", "branch", "add", "commit", "stash",
    "push", "pull", "fetch", "merge", "checkout", "reset",
    "remote", "show", "rev-parse", "tag", "blame",
}


def dispatch(name: str, arguments: dict) -> dict:
    """Dispatch a tool call to the appropriate handler.

    Returns {"ok": True, "output": ..., "exit_code": 0}
         or {"ok": False, "error": "message"}
    """
    try:
        match name:
            case "read_file":
                path = arguments.get("path", ".")
                offset = arguments.get("offset", 1)
                limit = arguments.get("limit", 500)
                return files.read_file(path, offset, limit)

            case "write_file":
                path = arguments["path"]
                content = arguments["content"]
                return files.write_file(path, content)

            case "edit_file":
                path = arguments["path"]
                old = arguments["old_string"]
                new = arguments.get("new_string", "")
                return _get_patcher().edit(path, old, new)

            case "list_dir":
                path = arguments.get("path", ".")
                return files.list_dir(path)

            case "search_files":
                pattern = arguments["pattern"]
                path = arguments.get("path", ".")
                file_glob = arguments.get("file_glob")
                return files.search_files(pattern, path, file_glob)

            case "bash":
                command = arguments["command"]
                timeout = arguments.get("timeout", 60)
                workdir = arguments.get("workdir")
                return shell.bash(command, timeout, workdir)

            case "bash_script":
                script = arguments["script"]
                timeout = arguments.get("timeout", 120)
                return shell.bash_script(script, timeout)

            case "git":
                command = arguments["command"]
                return git.run(command, _GIT_ALLOWED)

            case "web_search":
                query = arguments["query"]
                limit = arguments.get("limit", 5)
                return web.web_search(query, limit)

            case "web_fetch":
                url = arguments["url"]
                return web.web_fetch(url)

            case "web_extract":
                urls = arguments["urls"]
                return web.web_extract(urls)

            case "spawn_agent":
                goal = arguments["goal"]
                context = arguments.get("context", "")
                return subagent.spawn(goal, context)

            case "project_info":
                return files.project_info()

            case "think":
                thought = arguments.get("thought", "")
                return {"ok": True, "output": f"[Thinking: {len(thought)} chars]", "_thought": thought}

            case _:
                # Check MCP tools
                if name.startswith("mcp_"):
                    return mcp.get_mcp_manager().call_tool(name, arguments)
                return {"ok": False, "error": f"Unknown tool: {name}"}

    except Exception as e:
        return {"ok": False, "error": str(e)}


def is_safe_bash(command: str) -> tuple[bool, str]:
    """Check if a shell command is safe to execute."""
    for pattern, reason in _BLOCKED_PATTERNS:
        if re.search(pattern, command):
            return False, f"BLOCKED: {reason}"
    return True, ""


def serialized_tool_count() -> int:
    """Rough token estimate for all tool schemas (for context budget)."""
    raw = json.dumps(ALL_TOOL_SCHEMAS, ensure_ascii=False)
    return len(raw) // 4  # ~4 chars per token
