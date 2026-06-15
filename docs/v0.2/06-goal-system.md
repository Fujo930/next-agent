# O — Goal 持久目标 (Persistent Goal System)

## 借鉴 Hermes

Hermes 的 `/goal` 系统让 agent 记住一个跨回合的持久目标。Agent 每轮开始时会检查当前 goal 的进度，自动继续未完成的部分。

## 方案

Goal 是 session-scoped 的持久状态。存储在 session state 中，每轮注入 prefix。

### 实现

```python
@dataclass
class AgentGoal:
    text: str              # "完成 JWT 认证模块的重构"
    status: str            # "active" | "paused" | "completed"
    progress: str          # "已修改 auth.py, 待写测试"
    created_at: float
    tokens_used: int       # 累计 token 消耗
    time_spent: float      # 累计时间

class GoalManager:
    def set(self, goal_text: str) -> AgentGoal:
        """Set a new goal. Replaces any existing active goal."""
        ...
    
    def update_progress(self, detail: str, tokens: int, time: float) -> None:
        """Called by agent loop each turn when goal is active."""
        ...
    
    def complete(self) -> None:
        """Mark goal as completed."""
        ...
    
    def to_prompt(self) -> str:
        """Generate prompt extension for system context."""
        if not self._goal or self._goal.status != "active":
            return ""
        return (
            f"## Active Goal\n"
            f"Goal: {self._goal.text}\n"
            f"Progress: {self._goal.progress}\n"
            f"Tokens used: {self._goal.tokens_used:,} | "
            f"Time: {self._goal.time_spent:.0f}s\n"
            f"Continue working on this goal. Do not switch to unrelated tasks."
        )
```

### Agent Loop 集成

```python
# In _run_loop, after prefix build:
goal_prompt = self.goal.to_prompt()
if goal_prompt:
    self.messages.append({"role": "system", "content": goal_prompt})

# After each turn:
self.goal.update_progress(
    detail=f"Completed: {self._last_action_summary}",
    tokens=response.usage.get("total_tokens", 0),
    time=response.elapsed_ms / 1000,
)
```

### GUI 对接

```
GET  /goal              → {text, status, progress, tokens_used, time_spent}
POST /goal              → body: {"text": "重构认证模块"}
POST /goal/pause        → 暂停
POST /goal/complete     → 标记完成
```

顶部状态栏显示当前 goal 和进度条。

### 改动文件

- `src/next_agent/goal.py` — GoalManager
- `src/next_agent/agent.py` — 集成
