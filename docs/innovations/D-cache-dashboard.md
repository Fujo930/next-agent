# D — Cache 仪表盘 (Cache Dashboard)

## 解决的问题

DeepSeek 的自动 prefix cache 是最大的成本优势，但 Reasonix 和 CodeWhale 都没有给用户**可见的 cache 指标**。用户不知道自己省了多少钱，也不知道为什么 cache miss。

## 方案

在每个 agent 回合结束后显示 cache 统计。DeepSeek API 已经返回了所有需要的数据：

```json
{
  "usage": {
    "prompt_tokens": 1500,
    "completion_tokens": 200,
    "prompt_cache_hit_tokens": 1200,
    "prompt_cache_miss_tokens": 300
  }
}
```

### 三层指标

```
Layer 1 — 即时反馈（每轮结束后）
  
  ┌─────────────────────────────────────────────┐
  │  ✓ Done (2.3s)                               │
  │  输入: 1,500 tokens  |  输出: 200 tokens      │
  │  Cache命中: 1,200 (80%)  |  节省: $0.0017     │
  │  累计节省: $0.023  |  本会话 Cache 效率: 84%   │
  └─────────────────────────────────────────────┘

Layer 2 — 会话统计（/stats 命令）

  本会话:
    总 tokens: 45,200
    缓存命中: 38,400 (84.9%)
    实际花费: $0.052
    如果不缓存: $0.213
    节省: $0.161 (75.6%)

Layer 3 — Cache Miss 诊断

  最近 3 次 Cache Miss 原因:
    1. 切换模型: flash → pro (12:03:45)
    2. 新增工具定义 (12:05:22)
    3. 系统提示修改 (12:08:01)
```

### 实现

```python
class CacheDashboard:
    """Tracks and displays DeepSeek prefix-cache metrics."""

    def __init__(self):
        self.session_stats = CacheStats()
        self.round_history: list[CacheRound] = []

    def record_round(self, usage: dict, response_time: float) -> CacheRound:
        prompt_tokens = usage.get("prompt_tokens", 0)
        hit_tokens = usage.get("prompt_cache_hit_tokens", 0)
        miss_tokens = usage.get("prompt_cache_miss_tokens", 0)
        
        hit_rate = hit_tokens / prompt_tokens if prompt_tokens else 0
        saved_cost = self._calc_savings(hit_tokens, miss_tokens)

        round = CacheRound(
            prompt_tokens=prompt_tokens,
            cache_hit=hit_tokens,
            cache_miss=miss_tokens,
            hit_rate=hit_rate,
            saved=saved_cost,
            response_time=response_time,
        )
        self.session_stats += round
        self.round_history.append(round)
        return round

    def detect_miss_cause(self, round: CacheRound) -> str | None:
        """Heuristic to guess why cache missed."""
        prev = self.round_history[-2] if len(self.round_history) > 1 else None
        if not prev:
            return "first round"
        if round.cache_miss > prev.cache_miss * 2:
            # Sudden spike → prefix probably changed
            return "possible prefix modification"
        return None

    def format_round(self, round: CacheRound) -> str:
        bar = "█" * int(round.hit_rate * 10) + "░" * (10 - int(round.hit_rate * 10))
        return (
            f"  命中: {round.cache_hit:,} / {round.prompt_tokens:,} "
            f"[{bar}] {round.hit_rate:.0%}\n"
            f"  节省: ${round.saved:.4f}  |  "
            f"累计节省: ${self.session_stats.total_saved:.4f}"
        )

    @staticmethod
    def _calc_savings(hit: int, miss: int) -> float:
        # DeepSeek pricing: cache hit ≈ 10% of full price
        # flash: $0.15/M input, cache hit: ~$0.01/M
        RATE_FULL = 0.15 / 1_000_000    # $0.15 per 1M tokens
        RATE_CACHED = 0.01 / 1_000_000  # ~$0.01 per 1M cached tokens
        full_cost = miss * RATE_FULL
        cached_cost = hit * RATE_CACHED
        return full_cost - cached_cost  # amount saved
```

## 优势

- 用户可以看到 cache 的价值 → 更愿意保持会话不切换 → 更高的 cache 命中率
- Cache miss 诊断帮助用户理解什么操作破坏了缓存
- 零额外 API 调用——数据来自 `usage` 字段

## 与 I (成本调度) 的关系

Cache 统计为成本调度提供数据依据：
- 如果 pro 模型的 cache 命中率 90%+ → 不值得切换到 flash
- 如果 flash 的 cache 命中率降到 30% → 说明频繁切换破坏了缓存，需要调整策略
