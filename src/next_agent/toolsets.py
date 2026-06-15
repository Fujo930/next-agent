"""Toolset grouping — named tool groups for user-level enable/disable.

Tools are organised into groups by category. Users can enable/disable
groups via config (enabled_toolsets). Some groups are required and cannot
be disabled.

Relationship with `allowed-tools` (command-level):
- `allowed-tools` > `toolsets` — command constraints take priority
- A tool must be in an enabled toolset AND pass command filtering
"""

from __future__ import annotations

from .tools.registry import (
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
)

TOOLSETS: dict[str, dict] = {
    "core": {
        "name": "Core",
        "description": "Essential file and search operations",
        "tools": [TOOL_READ_FILE, TOOL_LIST_DIR, TOOL_SEARCH_FILES, TOOL_PROJECT_INFO],
        "default": True,
        "required": True,  # cannot be disabled
    },
    "editing": {
        "name": "Editing",
        "description": "File writing and editing",
        "tools": [TOOL_WRITE_FILE, TOOL_EDIT_FILE],
        "default": True,
    },
    "shell": {
        "name": "Shell",
        "description": "Command execution",
        "tools": [TOOL_BASH, TOOL_BASH_SCRIPT],
        "default": True,
    },
    "git": {
        "name": "Git",
        "description": "Version control operations",
        "tools": [TOOL_GIT],
        "default": True,
    },
    "web": {
        "name": "Web",
        "description": "Search and fetch web content",
        "tools": [TOOL_WEB_SEARCH, TOOL_WEB_FETCH, TOOL_WEB_EXTRACT],
        "default": True,
    },
    "subagent": {
        "name": "Sub-Agents",
        "description": "Parallel task delegation",
        "tools": [TOOL_SPAWN_AGENT],
        "default": False,  # experimental
    },
    "reasoning": {
        "name": "Reasoning",
        "description": "Think tool for planning",
        "tools": [TOOL_THINK],
        "default": True,
        "required": True,  # always on
    },
}


def get_enabled_tools(enabled_toolsets: set[str] | None = None) -> list[dict]:
    """Get tool schemas for currently enabled toolsets.

    Args:
        enabled_toolsets: Set of toolset names to enable. If None or empty,
                          uses default-enabled toolsets.

    Returns:
        List of tool schemas (OpenAI-compatible function definitions).
    """
    if enabled_toolsets is None:
        enabled_toolsets = set()

    enabled: list[dict] = []
    seen: set[str] = set()

    for toolset_name, toolset in TOOLSETS.items():
        is_required = toolset.get("required", False)
        is_default = toolset.get("default", True)
        is_enabled = toolset_name in enabled_toolsets

        # Include if: required, or explicitly enabled, or (default and no explicit config)
        if is_required or is_enabled or (is_default and not enabled_toolsets):
            for tool in toolset["tools"]:
                fn_name = tool.get("function", tool).get("name", "")
                if fn_name not in seen:
                    enabled.append(tool)
                    seen.add(fn_name)

    return enabled


def get_tool_names_for_toolset(toolset_name: str) -> list[str]:
    """Get the list of tool names in a toolset."""
    toolset = TOOLSETS.get(toolset_name)
    if not toolset:
        return []
    return [
        tool.get("function", tool).get("name", "")
        for tool in toolset["tools"]
    ]
