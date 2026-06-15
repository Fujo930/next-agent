# R — Toolset 分组 (Named Tool Groups)

## 借鉴 Hermes

Hermes 将 30+ 工具分成 25 个 toolset（web、terminal、file、vision、browser...），用户可以按平台/场景开启或关闭。

## 当前状态

Next Agent v0.1 是 14 个工具的扁平列表。`allowed-tools` 按命令限制，但没有用户级的工具组开关。

## 方案

按场景分组的工具集，GUI 高级设置面板中开关。

### 分组设计

```python
TOOLSETS = {
    "core": {
        "name": "Core",
        "description": "Essential file and search operations",
        "tools": ["read_file", "list_dir", "search_files", "project_info"],
        "default": True,
        "required": True,  # cannot be disabled
    },
    "editing": {
        "name": "Editing",
        "description": "File writing and editing",
        "tools": ["write_file", "edit_file"],
        "default": True,
    },
    "shell": {
        "name": "Shell",
        "description": "Command execution",
        "tools": ["bash", "bash_script"],
        "default": True,
    },
    "git": {
        "name": "Git",
        "description": "Version control operations",
        "tools": ["git"],
        "default": True,
    },
    "web": {
        "name": "Web",
        "description": "Search and fetch web content",
        "tools": ["web_search", "web_fetch", "web_extract"],
        "default": True,
    },
    "subagent": {
        "name": "Sub-Agents",
        "description": "Parallel task delegation",
        "tools": ["spawn_agent"],
        "default": False,  # experimental
    },
    "reasoning": {
        "name": "Reasoning",
        "description": "Think tool for planning",
        "tools": ["think"],
        "default": True,
        "required": True,  # always on
    },
}
```

### 工具过滤

Agent 初始化时根据 enabled toolsets 过滤工具列表：

```python
def get_enabled_tools(config: AgentConfig) -> list[dict]:
    enabled = []
    for toolset_name, toolset in TOOLSETS.items():
        if toolset.get("required") or config.is_toolset_enabled(toolset_name):
            for tool_name in toolset["tools"]:
                schema = find_schema(tool_name)
                if schema:
                    enabled.append(schema)
    return enabled
```

### GUI 对接

```
GET  /toolsets        → [{id, name, description, enabled, required, tools}]
POST /toolsets/toggle → body: {"name": "web", "enabled": false}
```

### 与 allowed-tools 的关系

- `allowed-tools`（命令级约束）> `toolsets`（会话级开关）
- 命令设置 `allowed-tools: bash, read_file` → 即使 toolsets 里 git 开了也看不到
- 用户关闭 web toolset → 所有命令的 web 工具都不可用

### 改动文件

- `src/next_agent/toolsets.py` — 分组定义
- `src/next_agent/agent.py` — 初始化时过滤
- `src/next_agent/main.py` — --toolsets flag
- `~/.nextagent/config.json` — enabled_toolsets 字段
