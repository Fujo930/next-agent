"""Innovation E — Chinese-English dynamic routing.

Detects user language and task type, then injects language-tuning
instructions into the system prompt. DeepSeek is strong in both CN and EN —
this unlocks the bilingual advantage.

Strategy:
- Chinese user + analysis/design task → reasoning in Chinese
- Chinese user + code task → code in English, explanation in Chinese
- English user → all English (no changes to default behavior)
- Mixed input → auto-detect and follow user's lead
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class LanguageDecision:
    """Result of language routing."""
    user_language: str  # "zh" or "en"
    prompt_extension: str  # appended to system prompt
    should_translate_output: bool = False


class LanguageRouter:
    """Routes prompt language based on user language and task type."""

    CHINESE_CHARS = re.compile(r'[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]')

    # Tasks that benefit from Chinese reasoning
    CN_REASONING_KEYWORDS = [
        "为什么", "如何", "设计", "架构", "重构", "建议",
        "怎么", "原因", "分析", "解释", "比较", "选择",
        "优化", "最佳实践", "方案", "思路", "实现", "流程",
    ]

    # Tasks that should use English (code-heavy)
    EN_CODE_KEYWORDS = [
        "def ", "class ", "import ", "async ", "await ",
        "function", "const ", "let ", "var ",
    ]

    @classmethod
    def detect(cls, text: str) -> str:
        """Detect the user's primary language from input text.

        Uses character ratio: if > 30% Chinese characters, treat as Chinese.
        """
        if not text:
            return "en"

        chinese_count = len(cls.CHINESE_CHARS.findall(text))
        # Remove whitespace and punctuation for ratio calculation
        clean = re.sub(r'\s+', '', text)
        clean = re.sub(r'[^\w\u4e00-\u9fff]', '', clean)
        total = len(clean)

        if total > 0 and chinese_count / total > 0.3:
            return "zh"
        return "en"

    @classmethod
    def route(cls, user_input: str, task_type: str = "auto") -> LanguageDecision:
        """Determine language strategy for this turn.

        Args:
            user_input: The user's message
            task_type: "auto", "code", "analysis", "chat"
        """
        lang = cls.detect(user_input)

        if lang == "en":
            # English user — no special handling needed
            return LanguageDecision(
                user_language="en",
                prompt_extension="",
            )

        # Chinese user — determine strategy based on task
        if task_type == "auto":
            task_type = cls._infer_task_type(user_input)

        if task_type == "code":
            extension = (
                "\n## Language\n"
                "A Chinese-speaking user is interacting with you in Chinese. "
                "Write code, variable names, function names, and code comments in English. "
                "Provide explanations and guidance in Chinese. "
                "When debugging, reason about the problem in Chinese for clarity."
            )
        elif task_type == "analysis":
            extension = (
                "\n## Language\n"
                "A Chinese-speaking user is interacting with you in Chinese. "
                "Use Chinese for reasoning, analysis, and explanations — "
                "this leads to more accurate analysis for Chinese-speaking users. "
                "Keep technical terms and code snippets in English."
            )
        else:  # chat
            extension = (
                "\n## Language\n"
                "A Chinese-speaking user is interacting with you in Chinese. "
                "Respond in Chinese. Keep code and technical terms in English."
            )

        return LanguageDecision(
            user_language="zh",
            prompt_extension=extension,
        )

    @classmethod
    def _infer_task_type(cls, text: str) -> str:
        """Infer whether this is a code task, analysis task, or chat."""
        text_lower = text.lower()

        # Code task signals
        code_signals = [
            "fix", "bug", "error", "implement", "write", "create",
            "test", "deploy", "commit", "refactor", "add", "remove",
            "修复", "实现", "写", "创建", "测试", "部署", "提交", "重构",
            "添加", "删除", "修改",
        ]
        code_score = sum(1 for s in code_signals if s in text_lower)

        # Analysis signals
        analysis_signals = [
            "why", "how", "explain", "analyze", "design", "architecture",
            "review", "understand", "compare", "what is",
            "为什么", "如何", "解释", "分析", "设计", "架构",
            "审查", "理解", "比较", "什么是",
        ]
        analysis_score = sum(1 for s in analysis_signals if s in text_lower)

        # Check for embedded code
        has_code = any(kw in text for kw in cls.EN_CODE_KEYWORDS)

        if has_code and code_score > analysis_score:
            return "code"
        elif analysis_score > code_score:
            return "analysis"
        elif code_score > 0:
            return "code"
        return "chat"
