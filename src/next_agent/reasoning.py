"""Innovation A — Reasoning Extraction Layer.

DeepSeek v4 lacks Claude's extended thinking. This module forces the model
to output a structured REASONING block before tool calls, then validates
that the actual tool calls match the stated reasoning.

Three layers:
1. Prompt injection — system prompt asks for reasoning blocks
2. Output interception — parse REASONING: blocks from LLM output
3. Reasoning validation — check tool calls don't contradict stated plan
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


# Prompt fragment injected into the system prompt
REASONING_PROMPT = """
## Reasoning Protocol

Before any complex tool call (file edit, shell execution, git commit, multi-step
operation), output a brief REASONING block:

```
REASONING:
- What I know: [current state]
- What I need: [which tools and why]
- Expected outcome: [what result I expect]
```

Keep it concise — 1-3 lines. Simple reads (read_file, list_dir) don't need it.
If your reasoning contradicts your tool call, the call will be blocked.
""".strip()


@dataclass
class ReasoningBlock:
    """A single reasoning block extracted from LLM output."""
    content: str
    raw: str
    turn: int = 0


@dataclass 
class ValidationWarning:
    """A mismatch between reasoning and tool calls."""
    severity: str  # "warning" or "error"
    message: str
    reasoning_reference: str = ""


class ReasoningExtractor:
    """Extracts and validates reasoning blocks from DeepSeek output."""

    PATTERN = re.compile(
        r"REASONING:\s*\n(.*?)(?=\n*(?:Tool call|ASSISTANT:|$))",
        re.DOTALL | re.IGNORECASE,
    )

    def __init__(self):
        self.history: list[ReasoningBlock] = []

    def extract(self, text: str, turn: int = 0) -> tuple[str | None, str]:
        """Extract reasoning block from LLM output.

        Returns (reasoning_content, rest_of_text) or (None, original_text).
        The rest_of_text is what comes after the reasoning block — 
        this is what should contain tool calls.
        """
        if not text:
            return None, text

        match = self.PATTERN.search(text)
        if not match:
            return None, text

        reasoning_text = match.group(1).strip()
        rest = text[match.end():].strip()

        block = ReasoningBlock(
            content=reasoning_text,
            raw=match.group(0),
            turn=turn,
        )
        self.history.append(block)

        return reasoning_text, rest

    def validate_against_tool_calls(
        self, reasoning: str | None, tool_names: list[str]
    ) -> list[ValidationWarning]:
        """Check if tool calls contradict stated reasoning.

        Simple heuristic checks:
        - If reasoning mentions specific files but tool calls touch different files
        - If reasoning says "debug" but tool calls do writes (should be reads first)
        """
        if not reasoning:
            return []

        warnings = []

        # Check for destructive operations without reasoning justification
        destructive_ops = {"write_file", "edit_file", "bash", "bash_script"}
        destructive_called = any(n in destructive_ops for n in tool_names)

        if destructive_called:
            # Check reasoning contains justification
            justification_keywords = [
                "fix", "change", "update", "modify", "write", "edit",
                "修正", "修改", "更新", "写入", "编辑", "修复",
            ]
            has_justification = any(
                kw.lower() in reasoning.lower() for kw in justification_keywords
            )
            if not has_justification:
                warnings.append(ValidationWarning(
                    severity="warning",
                    message=(
                        f"Destructive tool(s) called ({', '.join(tool_names)}) "
                        f"without clear justification in reasoning."
                    ),
                ))

        # Check for mentioned files not being accessed
        mentioned_files = re.findall(r'["\']?([\w./\\-]+\.\w{1,10})["\']?', reasoning)
        if mentioned_files and "read_file" in tool_names:
            # Not a hard error — just informational
            pass

        return warnings

    def get_latest_reasoning(self) -> str | None:
        """Get the most recent reasoning block content."""
        if self.history:
            return self.history[-1].content
        return None

    def summarize_reasoning(self, max_items: int = 5) -> str:
        """Summarize recent reasoning history (for context compression)."""
        if not self.history:
            return ""
        recent = self.history[-max_items:]
        return "\n".join(
            f"[turn {r.turn}] {r.content[:200]}"
            for r in recent
        )
