# Claude Code 参考分析

> 来源: [anthropics/claude-code](https://github.com/anthropics/claude-code) — 132k ⭐
> 核心闭源（npm 二进制），插件/命令系统开源
> 语言: Python 79.7%, Shell 13.7%, TypeScript 5%

## 我们借鉴的设计

### 1. 命令系统 (最重要)

```
.claude/commands/<name>.md

---
allowed-tools: Bash(git checkout --branch:*), Bash(git add:*), Bash(git status:*)
description: Commit, push, and open a PR
---

## Context
- Current git status: !`git status`
- Current git diff: !`git diff HEAD`
- Current branch: !`git branch --show-current`

## Your task
1. Create a new branch if on main
2. Create a single commit with an appropriate message
3. Push the branch to origin
4. Create a pull request using `gh pr create`
5. You MUST do all in a single message. Do not use other tools.
```

**关键设计**:
- `allowed-tools` — 限制命令能用的工具，防止 LLM 跑偏
- `!` 前缀 — shell 注入：`!`git status`` 在加载时执行
- `You MUST do all in a single message` — 强制并行工具调用
- 每个命令是完全自包含的 prompt

### 2. 插件架构

```
plugins/<name>/
├── .claude-plugin/
│   └── claude-plugin.json     # 插件元数据
├── commands/                   # 自定义命令 (*.md)
├── SKILL.md                    # 插件技能
└── README.md
```

13 个官方插件:
- development: agent-sdk-dev, feature-dev, frontend-design, plugin-dev, ralph-wiggum
- productivity: code-review, commit-commands, hookify, pr-review-toolkit
- learning: explanatory-output-style, learning-output-style
- security: security-guidance

### 3. 代码审查插件 (最值得学习的模式)

```
Step 1: Haiku agent → 快速预检查 (PR 是否已关闭/已审)
Step 2: Haiku agent → 获取 CLAUDE.md 项目配置
Step 3: Sonnet agent → PR 摘要
Step 4: 4 个并行 agent → 同时审查不同维度
          Agent 1,2: CLAUDE.md 合规性
          Agent 3:   Bug 扫描 (diff only)
          Agent 4:   安全/逻辑错误
Step 5: 并行验证 → 每个 issue 再验证一次 (去假阳性)
Step 6: 过滤 → 只保留高置信度 issue
Step 7: 输出 → 只列问题，不废话
```

**核心原则**:
- 便宜模型做快速决策，贵模型做深度分析
- 并行审查避免单点偏见
- 置信度评分过滤假阳性
- 每个 agent 有明确的、不重叠的角色

### 4. Marketplace 系统

`.claude-plugin/marketplace.json` — 声明式插件注册:
```json
{
  "$schema": "...",
  "plugins": [
    {
      "name": "code-review",
      "version": "1.0.0",
      "source": "./plugins/code-review",
      "description": "..."
    }
  ]
}
```

## 我们不需要借鉴的

- **核心 agent loop** — 闭源的，看不到
- **混模型策略** (Haiku/Sonnet/Opus 分级) — DeepSeek 只有 flash/pro 两级
- **Extended thinking** — DeepSeek 没有，我们用 A (推理提取) 替代
- **桌面 app / Web / IDE 扩展** — Next Agent 先专注 CLI

## 核心差异 vs Next Agent

| Claude Code | Next Agent |
|-------------|------------|
| 闭源核心 | 全开源 |
| 3 级模型 (Haiku/Sonnet/Opus) | 2 级 (flash/pro) |
| Extended thinking 原生 | 自建推理提取 (A) |
| 200K 上下文 | 128K 上下文 + 压缩 (G) |
| 目标: 最好 | 目标: DeepSeek 最好 |
