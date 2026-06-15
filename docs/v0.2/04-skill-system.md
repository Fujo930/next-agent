# M — Skill 系统 (Self-Improving Agent Skills)

## 借鉴 Hermes

Hermes 最核心的能力——agent 在执行任务中学到的模式、发现的 bug 类型、验证过的工作流，会自动保存为 skill 文件，在未来的 session 中自动加载。

## 方案

```
~/.nextagent/skills/
├── index.json                  # 技能索引
├── python-import-check.md       # skill 文件
├── git-commit-convention.md
└── react-component-pattern.md
```

### Skill 文件格式

与 Hermes 兼容的 markdown + YAML frontmatter：

```markdown
---
name: python-import-check
description: Before editing Python files, verify imports resolve
trigger: editing .py files in any project
created_by: agent
created_at: 2026-06-14
use_count: 5
---

## Pattern

When editing Python files that change imports (add/remove/rename):

1. Read the target file first
2. Check all imports with `python -c "import ast; ast.parse(open('file').read())"`
3. If imports changed, read the imported module to verify the symbol exists

## Why

DeepSeek sometimes adds imports for symbols that don't exist in the target module.
This skill prevents that by enforcing a pre-edit import check.
```

### 自动创建

当 agent 发现以下情况时，自动提议保存为 skill：

```python
TRIGGERS = [
    "same_error_3x",        # 同一类错误出现 3 次以上
    "user_correction",      # 用户纠正了 agent 的行为
    "successful_pattern",   # 一个复杂工作流成功执行
    "new_workflow",         # agent 发现了一个新的有效做法
]
```

### 加载

Session 开始时，`SkillManager` 扫描所有 skill 文件的 frontmatter，将 `trigger` 匹配当前上下文的 skill 注入 system prompt。

### 与 Hermes 的关键差异

| Hermes Skill | Next Agent Skill |
|-------------|-----------------|
| 手动 `/skill name` 加载 | **自动触发**（根据 trigger 条件） |
| 纯 markdown | markdown + **可执行 Python hook** |
| 需要 curator 管理 | **自动清理**（use_count=0 且 7天未用 → 归档） |
| 通过 hub 分享 | 本地优先 |

### GUI 对接

```
GET  /skills        → [{name, description, use_count, trigger}]
POST /skills/load   → body: {"name": "python-import-check"}
GET  /skills/stats  → {total, active, stale, by_category}
```

### 改动文件

- `src/next_agent/skills.py` — SkillManager 核心
- `src/next_agent/agent.py` — 集成加载
- `~/.nextagent/skills/` — 存储目录
- `next_agent/skills/` — 内置 skill 目录
