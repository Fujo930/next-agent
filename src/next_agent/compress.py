"""Innovation G — Progressive Context Compression.

DeepSeek has 128K context (36% smaller than Claude's 200K). This module
provides multi-level compression that preserves critical information while
dropping redundant data.

Four levels:
Level 0: Full fidelity — last 5 turns unchanged
Level 1: Summarized — tool results compressed to key facts (~500 chars each)
Level 2: Facts only — "what was done → what was the result"
Level 3: Session summary — whole conversation compressed, then checkpoint

Thresholds:
- > 50% full → Level 1 compression on oldest turns
- > 65% full → Level 2 compression
- > 85% full → Checkpoint + resume new session
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class CompressionLevel(Enum):
    NONE = 0
    LEVEL1 = 1
    LEVEL2 = 2
    CHECKPOINT = 3


class ProgressiveCompressor:
    """Multi-level context compression for DeepSeek's 128K window.

    Max usable tokens: ~120K (128K * 0.94 after overhead).
    """

    THRESHOLD_LEVEL1 = 0.50
    THRESHOLD_LEVEL2 = 0.65
    THRESHOLD_CHECKPOINT = 0.85

    def __init__(self, max_tokens: int = 120_000):
        self.max_tokens = max_tokens

    def check(self, current_tokens: int) -> CompressionLevel:
        """Determine compression action based on current token usage."""
        ratio = current_tokens / self.max_tokens
        if ratio < self.THRESHOLD_LEVEL1:
            return CompressionLevel.NONE
        elif ratio < self.THRESHOLD_LEVEL2:
            return CompressionLevel.LEVEL1
        elif ratio < self.THRESHOLD_CHECKPOINT:
            return CompressionLevel.LEVEL2
        else:
            return CompressionLevel.CHECKPOINT

    def compress_tool_result(self, content: str, level: CompressionLevel) -> str:
        """Compress a tool result based on compression level."""
        if level == CompressionLevel.NONE or len(content) < 300:
            return content
        if level == CompressionLevel.LEVEL1:
            return self._compress_level1(content)
        elif level == CompressionLevel.LEVEL2:
            return self._compress_level2(content)
        return content

    def compress_messages(
        self, messages: list[dict], current_tokens: int
    ) -> tuple[list[dict], int]:
        """Compress oldest messages to make room. Keeps system + recent intact."""
        level = self.check(current_tokens)
        if level in (CompressionLevel.NONE, CompressionLevel.CHECKPOINT):
            return messages, current_tokens

        system_idx = next(
            (i for i, m in enumerate(messages) if m.get("role") == "system"), 0
        )
        num_messages = len(messages)
        keep_tail = max(0, min(10, num_messages - system_idx - 1))
        compress_zone = messages[system_idx + 1 : num_messages - keep_tail]
        keep_zone = messages[num_messages - keep_tail:]

        compressed = []
        for msg in compress_zone:
            if msg.get("role") == "tool":
                content = msg.get("content", "")
                compressed.append(
                    {**msg, "content": self.compress_tool_result(content, level)}
                )
            else:
                compressed.append(msg)

        # Preserve messages before system_idx + system + compressed + keep
        result = messages[:system_idx] + [messages[system_idx]] + compressed + keep_zone
        token_saved = len(compress_zone) * 200
        return result, max(0, current_tokens - token_saved)

    def generate_checkpoint(self, session_summary: str) -> dict:
        """Generate a checkpoint message to start a new session."""
        return {
            "role": "system",
            "content": (
                f"[Checkpoint — continuing previous session]\n"
                f"Previous session summary:\n{session_summary}\n\n"
                f"Continue from where you left off."
            ),
        }

    @staticmethod
    def _compress_level1(content: str) -> str:
        """Compress to ~500 chars preserving key facts."""
        facts = []
        paths = re.findall(r'["\']?([/\w.-]+\.\w{1,6})["\']?', content)
        if paths:
            facts.append(f"files: {', '.join(paths[:5])}")
        errors = re.findall(r'(Error|Exception|Traceback|error):\s*(.+?)(?:\n|$)', content)
        if errors:
            facts.append(f"errors: {'; '.join(f'{t}: {m[:60]}' for t, m in errors[:3])}")
        counts = re.findall(r'(\d+)\s*(lines?|files?|entries?|matches?)', content)
        if counts:
            facts.append(f"counts: {', '.join(f'{n} {u}' for n, u in counts[:3])}")
        exit_match = re.search(r'exit.code.*?(\d+)', content, re.IGNORECASE)
        if exit_match:
            facts.append(f"exit_code: {exit_match.group(1)}")
        if facts:
            return f"[压缩] {' | '.join(facts)}"
        return f"[压缩] {content[:500]}"

    @staticmethod
    def _compress_level2(content: str) -> str:
        """Ultra-compressed: just the key outcome."""
        if '"ok": true' in content or '"ok":true' in content:
            output_match = re.search(r'"output":\s*"([^"]{1,200})"', content)
            return f"[OK] {output_match.group(1)}" if output_match else "[OK] ok"
        if '"ok": false' in content or '"ok":false' in content:
            error_match = re.search(r'"error":\s*"([^"]{1,200})"', content)
            return f"[FAIL] {error_match.group(1)}" if error_match else "[FAIL] failed"
        short = re.sub(r'\s+', ' ', content)[:200]
        return f"[·] {short}"
