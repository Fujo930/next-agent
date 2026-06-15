"""Innovation D — Cache Dashboard.

Tracks DeepSeek prefix-cache metrics per round and per session.
DeepSeek API already returns prompt_cache_hit_tokens and 
prompt_cache_miss_tokens — we just need to accumulate and display them.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


# Pricing rates (USD per token)
FLASH_INPUT_FULL = 0.15 / 1_000_000
FLASH_INPUT_CACHED = 0.01 / 1_000_000  # ~10% of full
FLASH_OUTPUT = 0.60 / 1_000_000

PRO_INPUT_FULL = 2.19 / 1_000_000
PRO_INPUT_CACHED = 0.14 / 1_000_000  # ~6% of full
PRO_OUTPUT = 8.76 / 1_000_000


@dataclass
class CacheRound:
    """Metrics for a single LLM round."""
    turn: int
    prompt_tokens: int
    completion_tokens: int
    cache_hit_tokens: int
    cache_miss_tokens: int
    elapsed_ms: float
    saved_cost: float = 0.0
    hit_rate: float = 0.0
    miss_cause: str = ""
    timestamp: float = field(default_factory=time.time)

    @classmethod
    def from_usage(cls, turn: int, usage: dict, elapsed_ms: float, model: str = "flash") -> "CacheRound":
        """Create from LLM response usage dict."""
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)
        cache_hit = usage.get("cache_hit_tokens", 0)
        cache_miss = usage.get("cache_miss_tokens", 0)

        # Calculate savings
        if "pro" in model:
            input_full = PRO_INPUT_FULL
            input_cached = PRO_INPUT_CACHED
        else:
            input_full = FLASH_INPUT_FULL
            input_cached = FLASH_INPUT_CACHED

        # Cost without cache: all tokens at full price
        cost_without = cache_miss * input_full + cache_hit * input_full
        # Cost with cache: cached tokens at discount
        cost_with = cache_miss * input_full + cache_hit * input_cached
        saved = cost_without - cost_with

        hit_rate = cache_hit / prompt_tokens if prompt_tokens else 0.0

        return cls(
            turn=turn,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cache_hit_tokens=cache_hit,
            cache_miss_tokens=cache_miss,
            elapsed_ms=elapsed_ms,
            saved_cost=saved,
            hit_rate=hit_rate,
        )


class CacheDashboard:
    """Tracks and displays cache metrics."""

    def __init__(self, model: str = "flash"):
        self.model = model
        self.rounds: list[CacheRound] = []
        self._round_count = 0

    def record(self, usage: dict, elapsed_ms: float) -> CacheRound:
        """Record a round's cache metrics."""
        self._round_count += 1
        round_data = CacheRound.from_usage(
            self._round_count, usage, elapsed_ms, self.model
        )
        
        # Detect cause of cache miss
        if self.rounds:
            prev = self.rounds[-1]
            miss_ratio = round_data.cache_miss_tokens / max(round_data.prompt_tokens, 1)
            prev_hit_ratio = prev.hit_rate

            if miss_ratio > 0.8 and prev_hit_ratio > 0.8:
                round_data.miss_cause = "model switch or prefix changed"
            elif miss_ratio > 0.5 and prev_hit_ratio < 0.3:
                round_data.miss_cause = "prefix still stabilizing"
            elif round_data.cache_hit_tokens == 0:
                round_data.miss_cause = "first round or prefix rebuilt"

        self.rounds.append(round_data)
        return round_data

    @property
    def total_saved(self) -> float:
        """Total cost saved by caching."""
        return sum(r.saved_cost for r in self.rounds)

    @property
    def avg_hit_rate(self) -> float:
        """Average cache hit rate across all rounds."""
        if not self.rounds:
            return 0.0
        return sum(r.hit_rate for r in self.rounds) / len(self.rounds)

    @property
    def total_tokens(self) -> int:
        """Total prompt tokens across all rounds."""
        return sum(r.prompt_tokens for r in self.rounds)

    @property
    def total_cache_hit(self) -> int:
        """Total cached tokens."""
        return sum(r.cache_hit_tokens for r in self.rounds)

    def format_round(self, round_data: CacheRound | None = None) -> str:
        """Format round summary for display."""
        if round_data is None:
            if not self.rounds:
                return ""
            round_data = self.rounds[-1]

        bar_len = 10
        filled = int(round_data.hit_rate * bar_len)
        bar = "█" * filled + "░" * (bar_len - filled)

        parts = [
            f"  ✓ Done ({round_data.elapsed_ms:.0f}ms)",
            f"  输入: {round_data.prompt_tokens:,}tk | 输出: {round_data.completion_tokens:,}tk",
            f"  Cache: {round_data.cache_hit_tokens:,}/{round_data.prompt_tokens:,} [{bar}] {round_data.hit_rate:.0%}",
            f"  节省: ${round_data.saved_cost:.4f} | 累计: ${self.total_saved:.4f}",
        ]
        if round_data.miss_cause:
            parts.append(f"  ⚠ {round_data.miss_cause}")

        return "\n".join(parts)

    def format_session(self) -> str:
        """Format session summary."""
        if not self.rounds:
            return "No cache data yet."

        return (
            f"Session cache stats ({self.model}):\n"
            f"  Rounds: {len(self.rounds)}\n"
            f"  Total tokens: {self.total_tokens:,}\n"
            f"  Cache hits: {self.total_cache_hit:,} ({self.avg_hit_rate:.1%})\n"
            f"  Saved: ${self.total_saved:.4f}"
        )
