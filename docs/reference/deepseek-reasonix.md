# DeepSeek-Reasonix 参考分析

> 来源: [esengine/DeepSeek-Reasonix](https://github.com/esengine/DeepSeek-Reasonix) — 22k ⭐
> 语言: Go 68.6%, TypeScript 21.8% (v2 从 TS 重写为 Go)
> 1000+ commits, 活跃开发中

## 核心架构

### 1. Cache-First 设计 (最具启发性)

**这是 Reasonix 最精华的部分。** 它的整个架构围绕 DeepSeek 的 prefix cache 设计:

```go
// REASONIX.md 中的核心原则：
// "Cache-first: the system-prompt prefix must stay byte-stable
//  across turns so DeepSeek's automatic prefix cache stays warm."
```

**实现**: `control.Controller` + `control.Compose`
- system prompt 在 session 开始时构建一次
- 所有后续轮次只 append user/tool 消息
- 前缀永不变动 → cache 命中率接近 100% → 几乎免费的 context

### 2. 配置驱动 (reasonix.toml)

```toml
default_model = "deepseek-flash"

[[providers]]
name        = "deepseek-flash"
kind        = "openai"
base_url    = "https://api.deepseek.com"
model       = "deepseek-v4-flash"
api_key_env = "DEEPSEEK_API_KEY"
```

- 声明式配置，无需修改代码
- 密钥通过环境变量注入，不写配置文件
- 支持多 provider，但 focus 在 DeepSeek

### 3. 双模型协作 (Executor + Planner)

```
┌─ Planner (pro, 只读) ──┐    ┌─ Executor (flash, 读写) ─┐
│ 分析任务                  │    │ 执行工具调用               │
│ 制定计划                  │    │ 读取文件                   │
│ 对比执行结果               │    │ 编辑代码                   │
│ 不直接操作文件             │    │ 不参与规划                 │
└──────────────────────────┘    └──────────────────────────┘
            ↑ 独立 session, 独立 cache ↑
```

### 4. 插件系统 (MCP-compatible)

- 外部工具通过 stdio JSON-RPC (MCP 协议)
- 内置工具在编译时注册 (Go plugin 模式)
- 插件是独立进程，语言无关

### 5. 内部包结构 (46 个包)

```
internal/
├── agent/        # 核心 agent loop
├── control/      # 传输无关的 controller (TUI/HTTP/Desktop)
├── tool/         # 工具注册和分发
├── checkpoint/   # 快照和回滚
├── history/      # 会话历史
├── memory/       # REASONIX.md + MEMORY.md 记忆系统
├── provider/     # LLM provider 抽象
├── command/      # 斜杠命令系统
├── skill/        # 技能系统
├── hook/         # 钩子系统
├── permission/   # 权限控制
├── sandbox/      # 执行沙箱
├── lsp/          # 语言服务器协议诊断
├── diff/         # diff 生成
├── plugin/       # 插件管理
├── serve/        # HTTP/SSE 服务
├── bot/          # Feishu/Lark/WeChat 机器人
└── desktop/      # Wails 桌面应用
```

## 我们借鉴的设计

### ✅ 必须借鉴

| 设计 | 借鉴程度 | 原因 |
|------|---------|------|
| Prefix-cache 稳定 | **全盘借鉴** | DeepSeek 的核心优势，不改 prefix → 成本降 10x |
| 配置驱动 | 借鉴 | `.toml` 或 `.json`，用 env 注入密钥 |
| 双模型协作 | 改进后借鉴 | 我们做 session 级路由，不需要同时跑两个 |
| Checkpoint 系统 | 借鉴 | 快照 + 回滚，保护用户代码 |
| Control.Controller | 借鉴 | 一个核心 loop 后端多个前端 (CLI 先) |

### ❌ 不需要借鉴

| 设计 | 原因 |
|------|------|
| Go 重写 | Python 足够，开发速度快 5x |
| Go plugin 模式 | Python 的 import 更简单 |
| Feishu/WX 机器人 | Narrow use case，先专注 CLI |

## Reasonix 的已知问题 (从 Issues)

1. **Sub-agent 参数泄漏** (#4317) — 子代理的 tool call 参数会泄漏到用户对话中
2. **MCP stdio 挂起** (#4299) — 服务器响应慢时 agent 无限等待
3. **Planner 不尊重 max_steps** (#4166) — 配置 bug
4. **Windows 用户名空格** (#4011) — 路径处理问题
5. **MCP 进程重复** (#3818) — 每个 tab 开一个新 MCP 进程

这些都是 Next Agent 可以避免的。
