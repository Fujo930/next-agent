# I — 成本感知调度 (Cost-Aware Scheduling)

## 解决的问题

DeepSeek v4 提供 flash 和 pro 两个模型，价格差 14 倍：
- flash: $0.15/M input tokens
- pro: $2.19/M input tokens

但现有 agent 要么只用一个模型，要么让用户手动切换。没有人做**自动的、基于任务复杂度的模型选择**。

**核心挑战**：模型切换会清空 prefix cache。所以不能频繁切换。

## 方案：Session 级别的模型选择

不在单轮任务内切换，而是在**新 session 启动时**选择最优模型。

```
用户启动 Next Agent
    ↓
[模型路由器] — 分析项目上下文 + 任务类型
    ↓
  flash (默认)           pro (复杂项目/任务)
    ↓                       ↓
  ┌─────────────────┐   ┌─────────────────┐
  │ Session: flash  │   │ Session: pro    │
  │ prefix cache    │   │ prefix cache    │
  │ 保持稳定         │   │ 保持稳定         │
  └─────────────────┘   └─────────────────┘
```

### 路由决策树

```python
class ModelRouter:
    """Session-level model selection based on project complexity."""

    # Tasks that ALWAYS need pro
    PRO_TASKS = {
        "architecture": ["design", "architecture", "refactor",
                         "migrate", "schema", "restructure"],
        "security": ["security", "vulnerability", "audit",
                     "penetration", "injection"],
        "analysis": ["root cause", "why", "complex", "investigate",
                     "race condition", "deadlock"],
    }

    # Project signals that suggest pro
    PRO_PROJECT_SIGNALS = {
        "size_mb": 50,           # codebase > 50MB
        "file_count": 500,       # > 500 files
        "language_count": 3,     # multi-language project
    }

    def select_model(
        self,
        user_request: str,
        project_context: ProjectContext,
        cost_budget: float | None = None,  # monthly budget
    ) -> ModelSelection:
        """Choose flash or pro for this session."""

        # 1. Explicit user preference (from flag or config)
        # 2. Task complexity signals
        # 3. Project complexity signals
        # 4. Budget constraints

        reasons = []

        # Task-based routing
        task_score = self._score_task_complexity(user_request)
        if task_score > 0.7:
            reasons.append(f"complex task (score={task_score:.2f})")

        # Project-based routing
        project_score = self._score_project_complexity(project_context)
        if project_score > 0.7:
            reasons.append(f"complex project (score={project_score:.2f})")

        # Budget constraint
        if cost_budget and not reasons:
            # Keep using flash if budget is tight
            reasons.append("budget optimization")

        # Decision
        if reasons:
            model = "deepseek-v4-pro"
        else:
            model = "deepseek-v4-flash"

        return ModelSelection(model=model, reasons=reasons)

    def _score_task_complexity(self, text: str) -> float:
        """Heuristic scoring: how likely this task needs pro."""
        text_lower = text.lower()
        score = 0.0

        for category, keywords in self.PRO_TASKS.items():
            for kw in keywords:
                if kw in text_lower:
                    score += 0.25  # each keyword adds 0.25
                    if score > 1.0:
                        return 1.0

        # Natural language complexity signals
        long_question = len(text.split()) > 50
        multiple_files = len(re.findall(r'[\w./-]+\.\w+', text)) > 3
        
        if long_question:
            score += 0.1
        if multiple_files:
            score += 0.15

        return min(score, 1.0)

    def _score_project_complexity(self, ctx: ProjectContext) -> float:
        """Score how complex the codebase is."""
        score = 0.0
        
        if ctx.total_size_mb > self.PRO_PROJECT_SIGNALS["size_mb"]:
            score += 0.4
        if ctx.file_count > self.PRO_PROJECT_SIGNALS["file_count"]:
            score += 0.3
        if ctx.language_count >= self.PRO_PROJECT_SIGNALS["language_count"]:
            score += 0.3
            
        return min(score, 1.0)
```

## Session 内特殊路由：子代理

虽然主 session 不能切换模型（会破坏 cache），但**子代理可以**：

```
用户: "审查这个 PR"
    ↓
Main Agent (flash): 规划审查策略
    ↓
  Sub-agent 1 (flash): 检查 CLUADE.md 合规性    ← 便宜的
  Sub-agent 2 (flash): 检查代码格式               ← 便宜的
  Sub-agent 3 (pro):   深度安全检查               ← 只有这个需要 pro
  Sub-agent 4 (pro):   逻辑错误审查               ← 只有这个需要 pro
    ↓
Main Agent (flash): 汇总结果
```

子代理是独立 session → 各自有独立的 cache → 可以为每个子代理选择最合适的模型。

## 成本估算

```python
class CostEstimator:
    """Estimate session cost before starting."""

    FLASH_INPUT = 0.15 / 1_000_000    # $0.15/M
    FLASH_OUTPUT = 0.60 / 1_000_000   # $0.60/M
    PRO_INPUT = 2.19 / 1_000_000      # $2.19/M
    PRO_OUTPUT = 8.76 / 1_000_000     # $8.76/M

    def estimate_session(self, selection: ModelSelection, 
                         estimated_turns: int = 20) -> CostEstimate:
        """Rough cost estimate before the session starts."""
        avg_input_per_turn = 5_000   # typical: system + context + user
        avg_output_per_turn = 800    # typical: reasoning + tool calls + text

        if "flash" in selection.model:
            input_rate = self.FLASH_INPUT
            output_rate = self.FLASH_OUTPUT
        else:
            input_rate = self.PRO_INPUT
            output_rate = self.PRO_OUTPUT

        # With cache (assuming 80% hit rate after first few turns)
        cached_ratio = 0.6  # 60% of input tokens cached
        input_cost = (
            estimated_turns * avg_input_per_turn * input_rate
            * (1 - cached_ratio)  # only pay for uncached
        )
        output_cost = estimated_turns * avg_output_per_turn * output_rate

        total = input_cost + output_cost
        return CostEstimate(
            model=selection.model,
            turns=estimated_turns,
            estimated_cost=total,
            with_cache=cached_ratio > 0,
        )
```

## 优势

- 用户不需要理解 flash vs pro 的区别
- Session 级别选择 → prefix cache 不受影响
- 子代理可以混合模型 → 审查任务中最省成本
- 预算保护 → 用户可以设置月限额

## 风险

- 关键词匹配不完美 → 可能高估或低估任务复杂度
- 随着 DeepSeek 模型变化，价值判断需要更新
