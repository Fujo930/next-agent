# Next Agent — Architecture

## 目标

给每一个人最好的 DeepSeek agent 体验。

不是一个"Claude Code clone for DeepSeek"。而是从第一天起就围绕 DeepSeek 的特性（和缺陷）设计——
发挥 prefix cache 的成本优势，弥补 function calling 的可靠性差距，弥补 128K 上下文的限制，弥补缺少 thinking 的推理盲区。

## 核心创新

| ID | 创新 | 位置 | 优先级 |
|----|------|------|--------|
| A | 推理提取层 | `src/next_agent/reasoning.py` | P0 |
| B | 工具预验证 | `src/next_agent/validate.py` | P0 |
| C | 跨文件一致性 | `src/next_agent/cross_file.py` | P1 |
| D | Cache 仪表盘 | `src/next_agent/cache_dash.py` | P0 |
| E | 中英路由 | `src/next_agent/lang_router.py` | P1 |
| G | 渐进压缩 | `src/next_agent/compress.py` | P1 |
| H | 确定性补丁 | `src/next_agent/tools/patch.py` | P0 |
| I | 成本调度 | `src/next_agent/turbo.py` | P1 |
| J | 多 Provider 支持 | `src/next_agent/llm.py` (LLMConfig) | P0 |
| K | Secret Redaction | `src/next_agent/redact.py` | P0 |
| L | Message Role 强制 | `src/next_agent/agent.py` (_append_message) | P0 |
| M | Skill 系统 | `src/next_agent/skills.py` | P0 |
| N | 跨会话记忆 | `src/next_agent/memory.py` + `memory_db.py` | P0 |
| O | Goal 持久目标 | `src/next_agent/goal.py` | P1 |
| P | Profiles 多实例 | `src/next_agent/profiles.py` | P1 |
| Q | Cron 定时任务 | `src/next_agent/cron_jobs.py` | P1 |
| R | Toolset 分组 | `src/next_agent/toolsets.py` | P2 |
| — | 子代理并行 | `src/next_agent/tools/subagent.py` | P1 |
| — | MCP 协议 | `src/next_agent/tools/mcp.py` | P1 |

## 项目结构

```
next-agent/
├── pyproject.toml                    # [tool.poetry] + console_scripts
├── next_agent/
│   ├── commands/                     # 斜杠命令 (*.md)
│   │   ├── review.md
│   │   ├── commit.md
│   │   ├── pr.md
│   │   └── deploy.md
│   ├── constitution.json             # agent 行为宪法
│   ├── README.md
│   └── LICENSE
│
├── src/next_agent/
│   ├── __init__.py
│   ├── main.py                       # CLI 入口 (readline loop)
│   ├── agent.py                      # 核心 agent loop
│   ├── llm.py                        # 多 Provider LLM 适配器 (J)
│   ├── workspace.py                  # 项目快照构建
│   ├── prefix.py                     # byte-stable prefix 管理器
│   ├── turbo.py                      # 成本感知模型路由 (I)
│   ├── reasoning.py                  # 推理提取 (A)
│   ├── validate.py                   # 工具预验证 (B)
│   ├── cross_file.py                 # 跨文件守卫 (C)
│   ├── cache_dash.py                 # Cache 统计 (D)
│   ├── lang_router.py                # 中英路由 (E)
│   ├── compress.py                   # 渐进压缩 (G)
│   ├── constitution.py               # 宪法加载和 enforcement
│   ├── command.py                    # 命令系统 (Claude Code 模式)
│   ├── snapshot.py                   # Side-git 快照 (CodeWhale 模式)
│   │
│   ├── redact.py                     # Secret 自动脱敏 (K)
│   ├── skills.py                     # Self-improving Skill 系统 (M)
│   ├── memory.py                     # 跨会话记忆管理器 (N)
│   ├── memory_db.py                  # SQLite+FTS5 记忆引擎 (N)
│   ├── goal.py                       # 持久目标系统 (O)
│   ├── profiles.py                   # 多实例 Profile 管理 (P)
│   ├── cron_jobs.py                  # Cron 定时任务调度 (Q)
│   ├── toolsets.py                   # 用户级工具集分组 (R)
│   │
│   └── tools/
│       ├── __init__.py
│       ├── registry.py               # 统一注册 + 分发
│       ├── patch.py                  # 确定性补丁引擎 (H)
│       ├── files.py                  # read/write/edit/list/search
│       ├── shell.py                  # bash 执行 + 安全过滤
│       ├── git.py                    # git 操作白名单
│       ├── web.py                    # web_search + web_fetch
│       ├── subagent.py               # 并行子代理
│       └── mcp.py                    # MCP 协议支持
│
├── docs/
│   ├── architecture.md               # 本文件
│   ├── innovations/                  # 所有创新文档
│   │   ├── A-reasoning-extraction.md
│   │   ├── B-tool-call-prevalidation.md
│   │   ├── C-cross-file-consistency.md
│   │   ├── D-cache-dashboard.md
│   │   ├── E-cn-en-routing.md
│   │   ├── F-skipped-speculative-execution.md
│   │   ├── G-progressive-compression.md
│   │   ├── H-deterministic-patch.md
│   │   └── I-cost-aware-scheduling.md
│   └── reference/                    # 参考项目分析
│       ├── claude-code.md
│       ├── deepseek-reasonix.md
│       └── codewhale.md
│
└── tests/
    ├── test_agent.py
    ├── test_tools.py
    └── ...
```

## 核心 Agent Loop

```
┌─────────────────────────────────────────────────────────────┐
│                   Next Agent Loop (v0.2)                     │
│                                                              │
│  User Input ──────────────────────────────────────────────► │
│                                                              │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ 1. COMMAND LOADER                                     │   │
│  │    Is input a slash command? (/commit, /review...)    │   │
│  │    → Load .md + inject !`shell` results               │   │
│  │    → Apply allowed-tools constraint                   │   │
│  └─────────────────────────────────────────────────────┘   │
│         │                                                    │
│         ▼                                                    │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ 2. LANGUAGE ROUTER (E)                                │   │
│  │    检测用户语言 + 任务类型                              │   │
│  │    → 中文推理 / 英文代码 / 双语混合                     │   │
│  └─────────────────────────────────────────────────────┘   │
│         │                                                    │
│         ▼                                                    │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ 3. TURBO ROUTER (I)                                   │   │
│  │    New session → flash or pro?                        │   │
│  │    Existing → keep same model (preserve cache)         │   │
│  └─────────────────────────────────────────────────────┘   │
│         │                                                    │
│         ▼                                                    │
│  ┌────────────────────────────────────────────────────────┐ │
│  │ 4. PREFIX BUILD (first turn only, frozen thereafter)   │ │
│  │    system = constitution + reasoning prompt             │ │
│  │    + skills (M, auto-loaded by trigger)                 │ │
│  │    + memory (N, FTS5 search for relevant items)         │ │
│  │    + goal (O, if active: inject progress + directive)  │ │
│  │    + project snapshot + MCP tools                       │ │
│  │    tools  = enabled toolsets (R) + MCP tools            │ │
│  │    → LOCKED to preserve DeepSeek prefix cache           │ │
│  └────────────────────────────────────────────────────────┘ │
│         │                                                    │
│         ▼                                                    │
│  ┌────────────────────────────────────────────────────────┐ │
│  │ 5. LLM CALL + MESSAGE ROLE ENFORCEMENT (L)              │ │
│  │    POST /v1/chat/completions (multi-provider via J)    │ │
│  │    messages = frozen prefix + conversation               │ │
│  │    → _append_message() enforces role alternation        │ │
│  └────────────────────────────────────────────────────────┘ │
│         │                                                    │
│         ▼                                                    │
│  ┌────────────────────────────────────────────────────────┐ │
│  │ 6. REASONING EXTRACTOR (A)                              │ │
│  │    LLM output: "REASONING: ..." → extract + store      │ │
│  │    LLM output: tool_calls → validate against reasoning  │ │
│  │    think tool results → captured as reasoning blocks    │ │
│  └────────────────────────────────────────────────────────┘ │
│         │                                                    │
│         ▼                                                    │
│  ┌───────────── 7. TOOL CALL LOOP ───────────────┐         │
│  │                                                  │         │
│  │  ┌───────────────────────────────────────┐      │         │
│  │  │ 7a. PRE-VALIDATION (B)                 │      │         │
│  │  │     JSON parse, schema check, required │      │         │
│  │  │     type check, safety check, dedup    │      │         │
│  │  └──────────────┬────────────────────────┘      │         │
│  │                 │ ✅ PASS                         │         │
│  │                 ▼                                │         │
│  │  ┌───────────────────────────────────────┐      │         │
│  │  │ 7b. PRE-EDIT SNAPSHOT (C)             │      │         │
│  │  │     If edit/write → snapshot files     │      │         │
│  │  │     Build dependency graph            │      │         │
│  │  └──────────────┬────────────────────────┘      │         │
│  │                 │                                │         │
│  │                 ▼                                │         │
│  │  ┌───────────────────────────────────────┐      │         │
│  │  │ 7c. EXECUTE (H)                       │      │         │
│  │  │     Deterministic patch engine        │      │         │
│  │  │     Sub-agent spawn (parallel tasks)  │      │         │
│  │  │     MCP tool dispatch                 │      │         │
│  │  │     Other tool dispatch               │      │         │
│  │  └──────────────┬────────────────────────┘      │         │
│  │                 │                                │         │
│  │                 ▼                                │         │
│  │  ┌───────────────────────────────────────┐      │         │
│  │  │ 7d. SECRET REDACTION (K)              │      │         │
│  │  │     Scan tool output for secrets       │      │         │
│  │  │     Regex-based redaction (keys, JWT)  │      │         │
│  │  └──────────────┬────────────────────────┘      │         │
│  │                 │                                │         │
│  │                 ▼                                │         │
│  │  ┌───────────────────────────────────────┐      │         │
│  │  │ 7e. POST-EDIT VALIDATION (C)          │      │         │
│  │  │     Cross-file import consistency     │      │         │
│  │  │     Symbol resolution check           │      │         │
│  │  │     Syntax check                       │      │         │
│  │  └───────────────────────────────────────┘      │         │
│  │                                                  │         │
│  └──────────────────────────────────────────────────┘         │
│         │                                                    │
│         ▼                                                    │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ 8. COMPRESSION CHECK (G)                              │   │
│  │    Context > 50%? → Level 1 compress old turns       │   │
│  │    Context > 65%? → Level 2 facts-only               │   │
│  │    Context > 85%? → Checkpoint + resume new session   │   │
│  └─────────────────────────────────────────────────────┘   │
│         │                                                    │
│         ▼                                                    │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ 9. CACHE DASHBOARD (D)                                │   │
│  │    Record usage metrics (hit rate, saved cost)        │   │
│  │    Detect cache miss causes                           │   │
│  │    Display round summary                              │   │
│  └─────────────────────────────────────────────────────┘   │
│         │                                                    │
│         ▼                                                    │
│  Response to User ────────────────────────────────────────► │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

## 关键设计决策

### 1. Prefix Cache 是架构的北极星

所有设计围绕一个原则：**system prompt 在 session 内永不变动**。

- `prefix.py` 负责构建并锁定 prefix
- 工具定义在第一轮之后永不修改
- 项目上下文在第一轮注入后不变
- 记忆在第一轮注入后不变
- 后续轮次只 append user/tool 消息

### 2. 单 Session 单模型

不学 Reasonix 的 executor+planner 并行模式。原因：
- 双模型 → 双 prefix → 双 cache → 浪费
- 单模型 + 稳定 prefix → cache 命中率 80%+
- 子代理可以独立选择模型（不影响主 session cache）

### 3. 防御优先 (v0.1 → v0.2 五层)

```
Layer 1 (B): 预验证 — 阻止不安全的工具调用
Layer 2 (H): 执行验证 — 确保编辑正确应用
Layer 3 (K): Secret Redaction — 工具输出脱敏 [v0.2]
Layer 4 (C): 后验证 — 确保跨文件一致性
Layer 5 (A): 推理验证 — 确保工具调用匹配计划
```

每一层都可以独立工作，但组合起来提供 5 层安全网。

### 4. 信息密度 > 上下文数量

DeepSeek 128K 不是短板——如果把关键信息保留、冗余信息压缩。G (渐进压缩) 确保 context 中永远是最高价值的信息，不是最近的信息。

### 5. Agent 自我进化 (M + N) [v0.2]

v0.2 引入两个自我改进机制：
- **Skill 系统 (M)**: Agent 在执行任务中学到的模式、发现的 bug 类型、验证过的工作流，自动保存为 skill 文件（markdown + YAML frontmatter）。下次 session 开始时自动匹配 trigger 并注入 prefix。
- **跨会话记忆 (N)**: SQLite + FTS5 全文搜索驱动。六种记忆类型（user/project/preference/lesson/convention/env），按重要性排序注入。agent 通过 `remember` 工具自动或手动保存。
- 两者都在 prefix build 时一次性注入，不影响 mid-session cache。

### 6. 多 Provider + 多实例 (J + P) [v0.2]

- **多 Provider (J)**: `LLMConfig.from_provider("openai")` 一行切换。支持 DeepSeek / OpenAI / Anthropic (via gateway) / OpenRouter / 本地模型。切换 provider 重建 prefix cache。
- **Profiles (P)**: `~/.nextagent/profiles/<name>/` 目录隔离——各自独立的 config, skills, memory, snapshots。`--profile work-python` 切换上下文。GUI 可以通过 API 切换 profile。

### 7. 子代理并行与 MCP [v0.1→v0.2]

- **子代理并行**: `spawn_agent` 工具派生独立 agent 实例处理子任务（code review, multi-file analysis, parallel investigation）。子代理可独立选择模型，不影响主 session cache。
- **MCP 协议**: `MCPManager` 管理 stdio JSON-RPC 连接的 MCP server 子进程。MCP tools 自动发现并注册为 `mcp_<server>_<tool>` 格式，在 prefix build 时与内置工具合并。

### 8. 自动化 (Q + R) [v0.2]

- **Cron 定时任务 (Q)**: 后台线程每 30 秒检查到期 job，自动执行任务（周报、依赖检查、CI 监控）。Schedule 支持 "30m", "2h", "0 9 * * *", ISO 时间戳。
- **Toolset 分组 (R)**: 7 个预定义工具组（core/editing/shell/git/web/subagent/reasoning），用户可按组开关。`required` 组不可禁用，命令级 `allowed-tools` 优先级高于 toolsets。

## 安装和使用

```bash
# 安装
pip install next-agent

# 配置
next-agent setup
# → 输入 API key（可选多 provider）
# → 选择默认 provider 和 model
# → 生成 ~/.nextagent/config.json

# 使用
cd your-project
next-agent                                    # 交互模式
next-agent "fix the auth bug"                 # 单任务模式
next-agent --provider openai "review code"    # 指定 provider
next-agent --profile work-python "refactor"   # 指定 profile
next-agent run --model pro "review security"  # 指定模型
```

## 环境变量

| 变量 | 用途 |
|------|------|
| `NEXT_API_KEY` | DeepSeek API key（默认 provider） |
| `DEEPSEEK_API_KEY` | DeepSeek API key（provider-specific） |
| `OPENAI_API_KEY` | OpenAI API key（provider-specific） |
| `ANTHROPIC_API_KEY` | Anthropic API key（provider-specific） |
| `OPENROUTER_API_KEY` | OpenRouter API key（provider-specific） |
| `NEXT_PROVIDER` | 默认 provider (deepseek/openai/anthropic/openrouter/local) |
| `NEXT_MODEL` | 默认模型 (flash/pro/gpt-4o 等) |
| `NEXT_PROFILE` | 默认 profile 名称 |
| `NEXT_WORKDIR` | 默认工作目录 |
| `NEXT_MAX_ROUNDS` | 每任务最大轮次 (默认 25) |
| `NEXT_CACHE_REPORT` | 是否显示 cache 统计 (默认 on) |
| `NEXT_LANG` | 语言偏好 (auto/zh/en) |
| `NEXT_REDACTION` | Secret redaction 开关 (默认 on) |

## 与 Moss Agent 的关系

Next Agent 是 Moss Agent 的 spiritual successor，但从架构上是全新的：
- Moss Agent: Tauri + Python 后端 + 桌面 GUI — 聊天助手
- Next Agent: 纯 Python CLI — 终端编码 agent
- 共同点: 都专注 DeepSeek, 都防重复修补, 都用 multi-layer defense
