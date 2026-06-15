# CodeWhale 参考分析

> 来源: [Hmbown/CodeWhale](https://github.com/Hmbown/CodeWhale) — 38k ⭐
> 语言: Rust 94.2%, TypeScript 2.6%, JavaScript 1.6%
> 前身: deepseek-tui (DeepSeek 专属 TUI agent)

## 核心架构

### 1. Constitution 系统 (最有价值的设计)

`.codewhale/constitution.json` — 硬编码 agent 行为准则:

```json
{
  "schema_version": 1,
  "authority": [
    "current user request",
    "live code and tests",
    "GitHub issue/PR details",
    "AGENTS.md and project CLAUDE.md",
    "memory",
    "previous-session handoffs"
  ],
  "protected_invariants": [
    "Keep the active first-turn tool-catalog head byte-stable"
  ],
  "verification_policy": {
    "before_claiming_done": [
      "run the focused tests for the changed crate",
      "read changed files back to confirm the edit landed as intended",
      "never claim verification you did not perform"
    ]
  },
  "escalate_when": [
    "an action is destructive or hard to reverse",
    "changing provider/auth/config"
  ]
}
```

**核心思想**：
- **权限层级**: 当前用户请求 > 代码和测试 > issue 描述 > 项目文档 > 记忆 > 历史
- **不可违背的约束**: 工具定义不能变（cache），只用稳定 Rust
- **验证策略**: 声称完成前必须做什么验证
- **升级条件**: 什么情况下升级到用户确认

### 2. Side-Git 快照系统

```
每轮对话后:
  → 自动 git add .codewhale/snapshots/
  → 不碰 repo 的 .git (用户的项目 git 不受影响)
  
用户输入 /restore:
  → 回滚到上一个快照
  → 撤销 AI 的所有修改
```

这是**非侵入式**的撤销系统——不需要初始化 git repo。

### 3. 多模型路由

```
/provider → 切换 Provider (DeepSeek, GLM, Kimi, OpenRouter...)
/model    → 在 Provider 内切换模型 (flash, pro)
/provider deepseek /model v4-flash
```

亮点：不是硬编码模型列表，而是动态查询 provider 能力。

### 4. Rust Crate 架构 (16 个 crate)

```
crates/
├── agent/       # 核心 agent loop
├── core/        # Runtime — JobManager, ThreadManager
├── cli/         # 命令行入口
├── tui/         # 终端 UI
├── tui-core/    # TUI 逻辑
├── tools/       # 工具注册和执行
├── hooks/       # 钩子系统
├── mcp/         # MCP 协议
├── whaleflow/   # 声明式工作流
├── config/      # 配置管理
├── state/       # StateStore 持久化
├── execpolicy/  # 执行策略
├── protocol/    # 通信协议
├── secrets/     # 密钥管理
├── app-server/  # HTTP/SSE 服务
└── release/     # 发布工具
```

### 5. Agent 行为准则 (6 条宪法)

```
1. The agent has an address. 每个 agent 实例有明确的工作目录和终端
2. Evidence outranks narration. 工具输出 > 模型的猜测
3. User intent stays sovereign. 当前请求 > 过时的指导/记忆
4. Local law is explicit. repos 可以定义 .codewhale/constitution.json
5. Runtime policy is enforced. 模式/批准/沙箱/回滚都是代码
6. Constitution is binding. agent 不能修改或忽略宪法
```

### 6. 上下文预算服务 (正在开发)

Issue #3086 描述了 CodeWhale 的架构演进方向:
- 统一的 `ContextBudgetService` — 一个 API 回答所有上下文相关问题
- 模型上下文窗口大小、max output tokens、compaction 阈值
- UI pressure 指示器 (safe/warm/hot/critical)
- 这个思路 → 我们的 G (渐进压缩) + D (cache 仪表盘)

## 我们借鉴的设计

### ✅ 必须借鉴

| 设计 | 借鉴程度 | 原因 |
|------|---------|------|
| Constitution | **全盘借鉴** | agent 行为约束是系统级的，不能靠 prompt 提示 |
| Side-git 快照 | 借鉴（简化版） | 非侵入式撤销，不需要项目是 git repo |
| 权限层级 (authority) | 借鉴 | 用户 > 代码 > 文档 > 记忆 |
| 多模型路由 | 借鉴 | `/provider` + `/model` 动态切换 |
| JobManager | 借鉴 | 指数退避重试、状态机管理后台任务 |
| 上下文预算 | 借鉴（改进） | 我们做渐进压缩，比简单的预算更智能 |

### 💡 改进后的版本

CodeWhale 的 constitution 中对每个模型都硬编码了 "You are DeepSeek V4"
(这是 Issue #3025)。我们的 constitution 会自动参数化模型信息。

## CodeWhale 的已知问题 (从 Issues)

1. **Constitution 硬编码 DeepSeek V4 事实** (#3025) — 切换模型时 agent 得到错误的自我认知
2. **上下文预算分散** (#3086) — 多模块各自判断，不一致
3. **Codex/Responses 可靠性** (#3019) — function calling 错误处理不足
4. **Reasoning 完整性** (#3016) — 思考链有 4 个已知 bug
5. **DeepSeek V4 over Anthropic API** (#2963) — 跨 API 集成问题

## 与 Next Agent 的关键差异

| | CodeWhale | Next Agent |
|---|-----------|------------|
| 语言 | Rust | Python |
| 目标 | 所有模型的一流 harness | DeepSeek 的第一流 agent |
| 推出时间 | 先做 DeepSeek TUI 再扩展 | 从第一天就专注 DeepSeek |
| 复杂度 | 16 个 crate，高编译成本 | 纯 Python，快速迭代 |
| 分发 | `cargo install` | `pip install` |
