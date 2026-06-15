# v0.2 — 9 项从 Hermes 借鉴的新功能

> 全部针对 GUI-first coding agent 场景优化

## 功能清单

| # | 功能 | 借鉴源 | 优先级 | 难度 |
|---|------|--------|--------|------|
| 1 | 多 Provider 支持 | Hermes 20+ providers | P0 | ⭐ 极低 |
| 2 | Secret redaction | Hermes security.redact_secrets | P0 | ⭐ 低 |
| 3 | Message role 强制 | Hermes role alternation | P0 | ⭐ 极低 |
| 4 | Skill 系统 | Hermes skills | P0 | ⭐⭐ 中 |
| 5 | 跨会话记忆 | Hermes persistent memory | P0 | ⭐⭐ 中 |
| 6 | Goal 持久目标 | Hermes /goal | P1 | ⭐ 低 |
| 7 | Profiles 多实例 | Hermes profiles | P1 | ⭐ 低 |
| 8 | Cron 定时任务 | Hermes cron | P1 | ⭐⭐⭐ 高 |
| 9 | Toolset 分组 | Hermes toolsets | P2 | ⭐ 低 |

## 实现顺序

```
Phase 1 (立即): 1→2→3  (极低难度，消除已知风险)
Phase 2 (本周): 4→5     (核心差异化能力)
Phase 3 (本周): 6→7     (体验增强)
Phase 4 (下周): 8→9     (自动化)
```

## 架构原则

1. **不破坏 prefix cache** — 新增功能只在 session 边界生效
2. **GUI-first** — 每个功能暴露 HTTP endpoint 供 GUI 消费
3. **向后兼容** — v0.1 的 CLI 和 API 全部保持
4. **防御优先** — 安全功能（secret redaction、message role）在执行前拦截
