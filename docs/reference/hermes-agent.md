# Hermes Agent 参考分析

> 来源: [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent) — Nous Research 旗舰 agent 平台
> 语言: Python (核心) + TypeScript (GUI)
> 分发: 桌面 GUI 应用 (Windows/macOS/Linux), `pip install hermes-agent`

## 概述

Hermes Agent 是 Nous Research 打造的完整 agent 平台——由一个统一的 agent loop 驱动，通过桌面 GUI、Web、API Gateway 等多前端交互。它是 agent 生态中最"全家桶"的方案：从底层 LLM 适配到顶层项目管理，从语音交互到定时任务，一应俱全。

Hermes 的设计哲学是"一切在 agent 内"——用户不需要离开 Hermes 就能完成 coding、项目管理、知识管理、任务编排等全部工作流。

## 核心架构

```
~/.hermes/
├── profiles/<name>/       # 多实例隔离
│   ├── config.yaml
│   ├── skills/            # 自学习 skill 文件
│   ├── memories/          # 持久记忆
│   ├── cron/              # 定时任务
│   └── plugins/           # 插件扩展
├── gateway/               # API 网关
└── curator/               # Skill 策展
```

### 一个 Agent Loop，多个前端

```
                    ┌─────────────────┐
                    │   Agent Loop    │
                    │  (统一核心)      │
                    └────────┬────────┘
           ┌─────────────────┼─────────────────┐
           ▼                 ▼                  ▼
    ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
    │  Desktop GUI  │  │   Web UI     │  │  API Gateway │
    │  (Electron)   │  │  (React)     │  │  (REST/SSE)  │
    └──────────────┘  └──────────────┘  └──────────────┘
```

## 关键功能

### 1. Skill 系统 (Skills)

Agent 在执行任务中学到的模式、发现的 bug 类型、验证过的工作流，会自动保存为 markdown skill 文件。通过 `skill_view(name='skill-name')` 在 session 中动态加载。Skill 存储在 `~/.hermes/skills/` 和 profile 各自的 skills 目录下。

### 2. 跨会话记忆 (Persistent Memory)

可插拔的持久记忆系统——记住用户偏好、环境细节、经验教训。默认内置 FTS5 全文搜索引擎，可切换到 Honcho、Mem0 等外部后端。记忆存储在 `~/.hermes/memories/`。

### 3. Profiles 多实例

完全隔离的 agent 实例——各自有独立的配置、skills、记忆、cron 任务、插件。支持同时运行多个 profile，通过 profile 名称切换。Profile 存储在 `~/.hermes/profiles/<name>/`。

### 4. API Gateway

Hermes Gateway 将 agent 能力暴露为 REST API 和 SSE 流。外部应用可以通过 HTTP 调用 agent、查询状态、接收实时事件。Gateway 支持多 provider 统一接入。

### 5. Cron 定时任务

完整的 cron 子系统——定时触发 agent 执行任务、支持 delivery 到多平台（邮件、Slack、Discord）、script 前置数据收集、`context_from` 任务链依赖。

### 6. Curator (Skill 策展)

Skill 生命周期管理——自动发现重复/过时 skill、合并相似 skill、评分排序、Hub 分享。Curator 是 Hermes skill 生态的"编辑"，确保 skill 库质量。

### 7. Kanban 项目管理

内置看板系统——agent 可以将复杂任务拆分为卡片、跟踪进度、自动移动卡片状态。适合长期项目的可视化管理。

### 8. Voice 语音交互

语音输入/输出——用户可以直接对 Hermes 说话，agent 通过 TTS 回应。支持多种语音引擎。

### 9. Secret Redaction

`security.redact_secrets` 默认开启——所有工具输出（terminal stdout、read_file、web content、subagent summaries）在被注入对话上下文前，扫描并脱敏密钥模式。

### 10. Toolset 分组

将 30+ 工具分成 25 个命名 toolset（web、terminal、file、vision、browser...），用户可以按平台/场景开启或关闭。

### 11. Message Role 交替强制

Agent loop 强制 message role 交替——永远不会出现连续两个 `assistant` 或连续两个 `user` 消息，防止 API 400 错误。

### 12. ACP (Agent Communication Protocol)

Agent 间通信协议——允许多个 Hermes agent 实例协作，共享上下文和任务状态。

---

## 我们借鉴的设计 (J–R)

从 Hermes 的 12+ 功能中，我们选择了 **9 个** (J–R) 直接借鉴并适配到 Next Agent 的 DeepSeek-first 架构中：

### J — 多 Provider 支持

**借鉴来源**: Hermes 支持 20+ providers，通过 `config.yaml` 声明式配置。切换 provider 不改变 agent 行为。

**我们怎么做的**: `LLMAdapter` 从硬编码 DeepSeek 扩展为支持 DeepSeek、OpenAI、Anthropic（via gateway）、OpenRouter、本地模型（LM Studio / Ollama / vLLM）。Provider 切换通过 `--provider` flag 或 GUI 下拉框。

**为什么借鉴**: 单 provider 锁定是最大风险——DeepSeek 服务中断 = Next Agent 完全不可用。多 provider 是必要的生存策略。

### K — Secret Redaction (密钥自动脱敏)

**借鉴来源**: Hermes 的 `security.redact_secrets` 在所有工具输出进入 context 前扫描脱敏。

**我们怎么做的**: `SecretRedactor` 匹配 7 种模式（API keys、GitHub tokens、AWS keys、JWTs、credential pairs、private key markers），在每个 tool result 返回前自动脱敏。红action 耗时 <1ms，不影响 prefix cache。

**为什么借鉴**: 安全是底线。Agent 读 `.env`、shell 输出、web 内容时泄露密钥是不可接受的。Hermes 的系统级方案比文件过滤更彻底。

### L — Message Role 交替强制

**借鉴来源**: Hermes 的 agent loop 强制 message role 交替——`user` → `assistant` → `tool` → `assistant`，从不违反。

**我们怎么做的**: `_append_message()` 替换所有 `messages.append()` 裸调用。检测到违规时自动注入 synthetic assistant acknowledgment。防止 API 400 错误。

**为什么借鉴**: 子代理结果合并、压缩后消息重排、手动构造消息列表都可能导致 role 违规。单点检查是零成本的防御。

### M — Skill 系统

**借鉴来源**: Hermes 最核心的能力——agent 在任务中学到的模式自动保存为 skill，在未来的 session 中加载。

**我们怎么做的**: Markdown + YAML frontmatter skill 文件，存储在 `~/.nextagent/skills/`。与 Hermes 的关键差异：
- **自动触发**（根据 trigger 条件匹配），非手动 `/skill` 加载
- **可执行 Python hook**，不只是文本提示
- **自动清理**（use_count=0 且 7 天未用 → 归档），不需要 curator

**为什么借鉴**: Skill 是 agent 持续进化的核心机制。一个 agent 不能每次都从零开始。但我们改进了触发方式——Hermes 的 curator/manual 加载模式在 GUI-first 场景下太慢。

### N — 跨会话记忆

**借鉴来源**: Hermes 的可插拔持久记忆系统——SQLite+FTS5，记住用户偏好、环境细节、经验教训。

**我们怎么做的**: 三层记忆（Global / Project / Session-relevant），FTS5 全文搜索，衰减权重排序（importance × log(access_count+1)），top 5 注入 frozen prefix。

**为什么借鉴**: 无记忆的 agent 是"金鱼脑"——每次新 session 都像第一次见用户。Hermes 的记忆系统成熟且可插拔，直接借鉴架构，简化后端（只用 SQLite）。

### O — Goal 持久目标

**借鉴来源**: Hermes 的 `/goal` 系统——agent 记住跨回合的持久目标，每轮自动继续。

**我们怎么做的**: `GoalManager` 跟踪目标文本、进度、累计 token/时间，每轮注入 system context。GUI 顶部状态栏显示进度条。

**为什么借鉴**: 长时间任务（如"重构认证模块"）跨越多个 session，agent 需要记住"做到哪了"。Goal 系统解决了 session 间的连续性。

### P — Profiles 多实例

**借鉴来源**: Hermes 的 profiles 系统——多个完全隔离的 agent 实例，各自有独立的配置、skills、记忆。

**我们怎么做的**: `~/.nextagent/profiles/<name>/` 目录隔离。每个 profile 独立选择 provider、model、语言、项目路径。CLI: `next-agent --profile work-python`。

**为什么借鉴**: 一个 coding agent 在不同项目中的需求截然不同——工作项目用 pro 模型 + 中文，开源项目用 flash 省钱 + 英文。Profiles 让切换零摩擦。

### Q — Cron 定时任务

**借鉴来源**: Hermes 的 cron 子系统——定时触发 agent、多平台 delivery、任务链依赖。

**我们怎么做的**: 轻量版 scheduler——daemon 线程每 30s 轮询，支持 cron 表达式和人类可读语法（`"30m"`, `"0 9 * * *"`），结果存 SQLite + JSON。GUI 面板管理。

**为什么借鉴**: Coding agent 的自动化场景丰富——周报、依赖检查、CI 监控。但 Hermes 的 cron 太重（multi-delivery, task chains），我们取了核心 scheduler 模式，砍掉了 delivery 层和任务链。

### R — Toolset 分组

**借鉴来源**: Hermes 将 30+ 工具分成 25 个命名 toolset，用户可按场景开关。

**我们怎么做的**: 14 个工具分 7 组（Core, Editing, Shell, Git, Web, Sub-Agent, Reasoning）。`required` 组不可关闭，`allowed-tools`（命令级）优先级 > toolsets（会话级）。

**为什么借鉴**: 工具数量增长后，用户需要按场景控制 agent 的能力范围。但 Hermes 的 25 组对我们 14 个工具来说过度细分——7 组刚好。

---

## 我们没有借鉴的

Hermes 有 12+ 功能，我们只借鉴了 9 个 (J–R)。以下是未借鉴的功能及原因：

### Gateway (API Gateway)

**Hermes 做什么**: 将 agent 能力暴露为 REST API + SSE 流。外部应用通过 HTTP 调用 agent、查询状态、接收实时事件。

**为什么不借鉴**: Next Agent v0.2 的目标是 GUI + CLI，不是 headless API 服务。GUI 通过 pywebview 内嵌 Python 后端直连，不需要 HTTP 中间层。如果未来需要 headless 模式，可以再加——但这增加了攻击面和维护成本，当前不需要。

**替代方案**: GUI 通过函数调用直连 agent core，CLI 通过 stdin/stdout。外部集成通过 MCP 协议（已在规划中）。

### Kanban (项目管理看板)

**Hermes 做什么**: 内置看板系统，agent 拆分任务为卡片、跟踪进度、自动移动状态。

**为什么不借鉴**: 这是应用层功能，不是 agent 核心能力。Next Agent 定位为 coding agent——用户用外部项目管理工具（Linear、GitHub Projects、Notion），agent 专注于写代码。在 agent 内建看板会模糊定位，增加不必要的复杂度。

**替代方案**: Agent 通过斜杠命令或 web 工具与外部项目管理工具交互（如 `/github issue create`），而不是在 agent 内维护自己的看板。

### Curator (Skill 策展系统)

**Hermes 做什么**: 自动发现重复/过时 skill、合并相似 skill、评分排序、Hub 分享。

**为什么不借鉴**: Curator 解决的是 skill 生态规模问题——当你有数百个 skill 时需要策展。Next Agent 的 skill 系统采用**自动清理**策略（7 天未用自动归档），在 skill 数量达到需要 curator 的阈值之前，简单的 TTL 清理就够了。

**设计选择**: 用自动过期替代策展——更快、更简单、零维护。如果未来 skill 数量超过 100，再考虑 curator。

### Voice (语音交互)

**Hermes 做什么**: 语音输入（STT）和语音输出（TTS），支持多种语音引擎。

**为什么不借鉴**: Voice 对 coding agent 几乎没有价值——程序员写代码时不会对着屏幕说话。Voice 是通用 AI 助手的功能，不是 coding agent 的功能。加入 voice 只会增加依赖和打包体积，对核心用户场景零增益。

**设计选择**: 专注键盘和文本交互——coding agent 的最佳界面是终端和文本编辑器。

### ACP (Agent Communication Protocol)

**Hermes 做什么**: Agent 间通信协议——多个 Hermes agent 实例协作，共享上下文和任务状态。

**为什么不借鉴**: ACP 是 multi-agent 场景的协议。Next Agent 当前的子代理（spawn_agent）通信通过函数调用和消息传递即可——不需要独立的通信协议。引入 ACP 是过度设计。

**未来可能**: 如果 Next Agent 发展到需要跨机器、跨进程的 agent 协作，MCP (Model Context Protocol) 是更通用的选择——它已被生态广泛采用，不需要自己造协议。

---

## 核心差异 vs Next Agent

| | Hermes Agent | Next Agent |
|---|-------------|------------|
| 定位 | 全能 agent 平台 | 专注 DeepSeek coding agent |
| 界面 | 桌面 GUI + Web + API | GUI + CLI (先 CLI 后 GUI) |
| 模型策略 | 通用多 provider | DeepSeek-first，多 provider 为 fallback |
| Prefix cache | 不特殊优化 | **架构北极星**，所有设计围绕 cache |
| Skill 加载 | 手动 `/skill` + curator | **自动触发** + TTL 归档 |
| 项目管理 | 内置 Kanban | 不内置，通过工具对接外部 |
| 分发 | 桌面应用安装包 | `pip install` + 可选 GUI EXE |
| 复杂度 | 12+ 功能全家桶 | 精选 9 个 + 自建 8 个创新 |
| 语音 | ✅ 内置 | ❌ 不适用 coding 场景 |
| 开放程度 | 核心闭源，部分开源 | 全开源 MIT |
